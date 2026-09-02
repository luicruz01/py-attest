import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from py_attest.cli.main import cli

FIXTURES = Path(__file__).parent / "review" / "fixtures"


def test_review_branch_flag_diffs_against_base_and_writes_a_report(tmp_path: Path) -> None:
    # HEAD...HEAD is always a valid, empty diff in any git repo (this one included),
    # so this exercises the --branch acquisition path without depending on a fixture branch.
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["review", "--branch", "HEAD", "--base", "HEAD", "--no-llm", "--out", str(out_dir)],
    )

    assert result.exit_code == 0
    report = json.loads((out_dir / "HEAD.json").read_text(encoding="utf-8"))
    assert report["source"]["base_sha"] == report["source"]["head_sha"]


def test_review_branch_flag_maps_git_failure_to_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    from py_attest.review.diff import DiffError

    def fail(*_args: object, **_kwargs: object) -> str:
        raise DiffError("cannot diff main...feature/x: fatal: bad revision")

    monkeypatch.setattr("py_attest.cli.main._branch_diff", fail)
    runner = CliRunner()

    result = runner.invoke(cli, ["review", "--branch", "feature/x"])

    assert result.exit_code == 4


def test_review_diff_file_no_llm_approves_a_clean_patch(tmp_path: Path) -> None:
    # Runs with the real py-attest repo as cwd (needed for `git rev-parse HEAD`
    # in the report's gate_commit); only the fixture diff and --out are isolated.
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "streaks.patch"),
            "--no-llm",
            "--out",
            str(out_dir),
        ],
    )

    # streaks.patch is a plain code diff with no secrets; --no-llm means the verdict
    # comes only from the secrets firewall, so this must deterministically approve.
    assert result.exit_code == 0
    report = json.loads((out_dir / "streaks.patch.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 3
    assert report["verdict"] == "APPROVE"
    assert report["layers"]["llm"] == "skipped:--no-llm"
    assert report["exit_code"] == result.exit_code


def test_review_head_flag_diffs_against_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["review", "--head", "HEAD", "--base", "HEAD", "--no-llm", "--out", str(out_dir)],
    )

    assert result.exit_code == 0
    report = json.loads((out_dir / "HEAD.json").read_text(encoding="utf-8"))
    assert report["source"]["base_sha"] == report["source"]["head_sha"]


@pytest.mark.parametrize("egress", ["raw", "minimized"])
def test_review_fake_provider_produces_a_schema_v3_report_in_both_egress_modes(
    tmp_path: Path, egress: str
) -> None:
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "streaks.patch"),
            "--provider",
            "fake",
            "--fake-response",
            str(FIXTURES / "clean.json"),
            "--egress",
            egress,
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 0, result.output
    report = json.loads((out_dir / "streaks.patch.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == 3
    assert report["verdict"] == "APPROVE"
    assert report["layers"]["llm"] == "ran"
    assert report["egress"]["mode"] == egress
    if egress == "raw":
        assert report["egress"] == {"mode": "raw", "context_files": []}
    else:
        assert report["egress"] == {"mode": "minimized", "payload_version": "MINIMIZED_PATCH_V2"}


def test_review_fake_provider_without_fake_response_is_a_usage_error() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["review", "--diff-file", str(FIXTURES / "streaks.patch"), "--provider", "fake"],
    )

    assert result.exit_code == 64


@pytest.mark.parametrize("egress", ["raw", "minimized"])
def test_review_secret_diff_blocks_with_zero_provider_calls_in_both_egress_modes(
    egress: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DONE WHEN: a diff with a secret yields BLOCK and zero provider calls in both
    modes. `--provider fake` still gets picked (validated), but never invoked -- if it
    were, `--fake-response` isn't given and `_build_provider` would raise UsageError
    (exit 64), not the exit-2 BLOCK asserted below.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "secret.patch"),
            "--provider",
            "fake",
            "--egress",
            egress,
        ],
    )

    assert result.exit_code == 2, result.output


def test_review_diff_over_the_patch_byte_limit_is_inconclusive_without_a_provider_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DONE WHEN: a diff over limits.max_patch_bytes yields INCONCLUSIVE (4) without a
    provider call. `--provider fake` with no `--fake-response` would surface as exit 64
    (UsageError) instead if the provider were ever reached -- exit 4 proves it wasn't:
    the byte-limit check runs before deterministic/firewall/egress/provider (TRD SS5 row 1).
    """
    (tmp_path / "pyproject.toml").write_text(
        "[tool.attest.limits]\nmax_patch_bytes = 10\n", encoding="utf-8"
    )
    oversized = tmp_path / "oversized.patch"
    oversized.write_text(
        "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["review", "--diff-file", str(oversized), "--provider", "fake"])

    assert result.exit_code == 4, result.output


def test_review_evidence_policy_flag_does_not_collide_with_no_llm(tmp_path: Path) -> None:
    # Renamed from test_review_evidence_policy_flag_overrides_config (final whole-branch
    # review): with --no-llm, run_review's `no_llm` branch returns before
    # resolved_evidence_policy is ever consulted, so this exercises no override behavior
    # at all -- it only confirms --evidence-policy is accepted as a flag and doesn't
    # break --no-llm's own short-circuit path. See
    # test_review_evidence_policy_flag_actually_overrides_the_config_default below for
    # a test that exercises the real override.
    #
    # Runs with the real py-attest repo as cwd (as in
    # test_review_diff_file_no_llm_approves_a_clean_patch above): gate_commit's
    # `git rev-parse HEAD` needs an actual git repo, which a bare tmp_path isn't.
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "streaks.patch"),
            "--no-llm",
            "--evidence-policy",
            "fail_closed",
            "--out",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code == 0


def test_review_evidence_policy_flag_actually_overrides_the_config_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regression test for a final whole-branch review finding: no test anywhere
    # exercised --evidence-policy actually overriding Config.evidence_policy (the
    # "degrade" default) through the CLI -- the only fail_closed coverage went through
    # Config(evidence_policy=...) directly, never the flag. This drives the LLM call
    # (via a monkeypatched _call_provider, as in tests/review/test_reviewer.py's
    # fail_closed test) with an invalid finding and asserts the flag alone flips the
    # verdict to INCONCLUSIVE, proving the override reaches run_review.
    from py_attest.review import reviewer as review_module

    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    bad_finding = {
        "rule_id": "does-not-exist-1",
        "path": "app/main.py",
        "side": "new",
        "line_start": 1,
        "line_end": 1,
        "title": "Review policy violation",
        "evidence": "changed value",
        "explanation": "The changed code violates a team standard.",
        "suggested_fix": "Change the implementation to follow the standard.",
        "confidence": "high",
    }

    def fake_call_provider(**_kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
        return {"findings": [bad_finding], "summary": "One violation."}, {}

    monkeypatch.setattr(review_module, "_call_provider", fake_call_provider)
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "streaks.patch"),
            "--evidence-policy",
            "fail_closed",
            "--out",
            str(out_dir),
        ],
    )

    assert result.exit_code == 4
    report = json.loads((out_dir / "streaks.patch.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "INCONCLUSIVE"


def test_review_json_flag_prints_the_schema_v3_report(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    runner = CliRunner()

    result = runner.invoke(
        cli,
        [
            "review",
            "--diff-file",
            str(FIXTURES / "streaks.patch"),
            "--no-llm",
            "--out",
            str(out_dir),
            "--json",
        ],
    )

    payload = json.loads(result.output)
    assert payload["schema_version"] == 3
