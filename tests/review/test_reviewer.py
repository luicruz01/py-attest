import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import click
import pytest

from py_attest.config import Config
from py_attest.errors import InconclusiveError
from py_attest.llm.types import ProviderFailure, ProviderRequest, ProviderResponse, Usage
from py_attest.review import context_pack as context_pack_module
from py_attest.review import reviewer as review_module
from py_attest.review.diff import DiffError
from py_attest.review.egress import raw as raw_egress_module
from py_attest.review.report import render_markdown
from py_attest.review.reviewer import FIREWALL_SKIP_NOTE, run_review
from py_attest.review.secrets_gate import SecretsGateError

FIXTURES = Path(__file__).parent / "fixtures"


def finding(*, rule_id: str, confidence: str) -> dict[str, object]:
    return {
        "rule_id": rule_id,
        "path": "app/main.py",
        "side": "new",
        "line_start": 7,
        "line_end": 7,
        "title": "Review policy violation",
        "evidence": "changed value",
        "explanation": "The changed code violates a team standard.",
        "suggested_fix": "Change the implementation to follow the standard.",
        "confidence": confidence,
    }


def fake_call_provider(
    review: dict[str, object], *, metadata: dict[str, object] | None = None
) -> Any:
    """Build a `review_module._call_provider` replacement returning a fixed response."""

    def _fake(
        *,
        provider_name: str,
        config: Config,
        fake_response: str | None,
        egress_result: Any,
        prompt_version: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del provider_name, config, fake_response, egress_result, prompt_version
        return review, metadata or {"temperature_applied": "model-default"}

    return _fake


def test_markdown_explicitly_approves_zero_findings() -> None:
    markdown = render_markdown(
        "feature/sound-change",
        {
            "findings": [],
            "summary": "No standards violations found.",
            "filtered_out": [],
            "verdict": "APPROVE",
            "meta": {
                "prompt_version": "v3",
                "model": "gpt-5-mini",
                "temperature": "model-default",
                "gate_commit": "c8ca0e9",
            },
        },
    )

    assert markdown.splitlines()[1] == (
        "Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate c8ca0e9"
    )
    assert "APPROVED — no findings" in markdown
    assert "No standards violations found." in markdown


def test_markdown_renders_contextual_severity_not_the_literal_none() -> None:
    contextual_finding = {
        **finding(rule_id="retention-1", confidence="high"),
        "severity": None,
        "requires_human_classification": True,
    }

    markdown = render_markdown(
        "feature/sound-change",
        {
            "findings": [contextual_finding],
            "summary": "One contextual finding.",
            "filtered_out": [],
            "verdict": "COMMENT",
            "meta": {
                "prompt_version": "v3",
                "model": "gpt-5-mini",
                "temperature": "model-default",
                "gate_commit": "c8ca0e9",
            },
        },
    )

    assert "[None]" not in markdown
    assert "| None |" not in markdown
    assert "[contextual]" in markdown
    assert "human severity classification required" in markdown


@pytest.mark.parametrize(
    ("model_finding", "expected_severity", "expected_verdict", "expected_exit"),
    [
        pytest.param(finding(rule_id="pii-1", confidence="low"), "S1", "COMMENT", 0, id="low-S1"),
        pytest.param(
            finding(rule_id="testing-2", confidence="medium"), "S2", "BLOCK", 2, id="medium-S2"
        ),
    ],
)
def test_run_review_computes_and_publishes_verdict_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    model_finding: dict[str, object],
    expected_severity: str,
    expected_verdict: str,
    expected_exit: int,
) -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -7,0 +7 @@\n"
        "+changed value\n"
    )
    output_dir = tmp_path / "reports"
    model_review = {"findings": [model_finding], "summary": "One violation found."}
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    calls: list[str] = []

    def spy_call_provider(
        *,
        provider_name: str,
        config: Config,
        fake_response: str | None,
        egress_result: Any,
        prompt_version: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del provider_name, fake_response, egress_result
        calls.append(prompt_version)
        calls.append(config.model)
        return model_review, {"temperature_applied": "model-default", "attempts": 1, "usage": None}

    monkeypatch.setattr(review_module, "_call_provider", spy_call_provider)

    outcome = run_review(
        diff=diff,
        source_name="change.patch",
        repo_root=tmp_path,
        config=Config(model="gpt-5-mini"),
        out_dir=output_dir,
    )

    assert outcome.exit_code == expected_exit
    assert calls == ["v3", "gpt-5-mini"]
    json_report = json.loads((output_dir / "change.patch.json").read_text(encoding="utf-8"))
    assert json_report["schema_version"] == 3
    assert json_report["verdict"] == expected_verdict
    assert json_report["exit_code"] == expected_exit
    assert json_report["stage"] == "review"
    assert json_report["layers"] == {
        "deterministic": "ran",
        "secrets": "pass",
        "llm": "ran",
    }
    assert json_report["summary"] == model_review["summary"]
    assert json_report["filtered_out"] == []
    [reported_finding] = json_report["findings"]
    assert reported_finding["rule_id"] == model_finding["rule_id"]
    assert reported_finding["severity"] == expected_severity
    assert reported_finding["confidence"] == model_finding["confidence"]
    assert reported_finding["path"] == model_finding["path"]
    assert reported_finding["side"] == model_finding["side"]
    assert reported_finding["line_start"] == model_finding["line_start"]
    assert reported_finding["line_end"] == model_finding["line_end"]
    assert reported_finding["evidence_verified"] is True
    assert json_report["meta"]["prompt_version"] == "v3"
    assert json_report["meta"]["model"] == "gpt-5-mini"
    assert json_report["meta"]["temperature_applied"] == "model-default"
    assert json_report["meta"]["attempts"] == 1
    assert json_report["meta"]["gate_commit"] == "c8ca0e9"

    markdown = (output_dir / "change.patch.md").read_text(encoding="utf-8")
    assert markdown.splitlines()[1] == (
        "Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate c8ca0e9"
    )
    assert f"VERDICT: {expected_verdict}" in markdown
    assert "| Severity | Rule | File:line | Title | Confidence |" in markdown
    assert "Suggested fix: Change the implementation to follow the standard." in markdown
    assert "Evidence: changed value" in markdown
    assert f"Verdict: {expected_verdict}" in capsys.readouterr().out

    if model_finding["confidence"] == "low":
        assert "HUMAN REVIEW REQUESTED" in markdown


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_secret_diff_blocks_before_any_provider_is_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_build_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a provider must not be built when the diff has a secret")

    monkeypatch.setattr(review_module, "_build_provider", fail_build_provider)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    diff = (FIXTURES / "secret.patch").read_text(encoding="utf-8")
    secret_value = "AKIAABCDEFGHIJKLMNOP"  # noqa: S105 - fake AWS key fixture, not a real secret
    assert secret_value in diff
    output_dir = tmp_path / "reports"

    outcome = run_review(
        diff=diff,
        source_name="secret.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=output_dir,
    )

    assert outcome.exit_code == 2
    json_text = (output_dir / "secret.patch.json").read_text(encoding="utf-8")
    markdown = (output_dir / "secret.patch.md").read_text(encoding="utf-8")
    report = json.loads(json_text)
    assert report["verdict"] == "BLOCK"
    assert report["layers"]["llm"] == "skipped:secret_detected"
    assert report["layers"]["secrets"] == "fail"
    assert report["layers"]["deterministic"] == "ran"
    assert report["note"] == FIREWALL_SKIP_NOTE
    assert report["filtered_out"] == []
    # Same literal secret is a valid AWS access-key shape, so both the deterministic
    # layer's own regex and gitleaks independently catch it on the same line -- both
    # now cite rule_id "secrets-1", so merge_findings collapses them into ONE finding
    # (not a dedup bug: "one id per violation type, regardless of detection mechanism").
    assert [f["rule_id"] for f in report["findings"]] == ["secrets-1"]
    assert all(
        finding["severity"] == "S1" and finding["confidence"] == "high"
        for finding in report["findings"]
    )
    captured = capsys.readouterr()
    all_output = json_text + markdown + captured.out + captured.err
    assert FIREWALL_SKIP_NOTE in markdown
    assert secret_value not in all_output
    assert "redacted" in all_output.lower()


def test_default_report_directory_is_gitignored() -> None:
    git_executable = shutil.which("git")
    assert git_executable is not None
    result = subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
        [git_executable, "check-ignore", "--quiet", "reports/probe.json"],
        cwd=Path.cwd(),
        check=False,
    )
    assert result.returncode == 0


def test_run_review_appends_untrusted_description_and_selects_v1_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1,0 +1 @@\n"
        "+changed\n"
    )
    captured: dict[str, str] = {}

    def spy_call_provider(
        *,
        provider_name: str,
        config: Config,
        fake_response: str | None,
        egress_result: Any,
        prompt_version: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del provider_name, config, fake_response
        captured["context"] = egress_result.user_content
        captured["prompt_version"] = prompt_version
        return {"findings": [], "summary": "No violations."}, {}

    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_call_provider", spy_call_provider)
    description = "Title\n\n$(touch should-never-run); <untrusted>body</untrusted>"

    outcome = run_review(
        diff=diff,
        source_name="change.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
        description=description,
        prompt_version="v1",
    )

    assert outcome.exit_code == 0
    assert "Author's stated intent:\n" + description in captured["context"]
    assert captured["prompt_version"] == "v1"


def test_run_review_falls_back_to_packaged_defaults_when_repo_has_no_standards_yml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """repo_root here has no core.standards.yml/domain.standards.yml -- confirms the
    fallback documented in spec SS5.3 rather than a hard failure.
    """
    diff = "diff --git a/app/main.py b/app/main.py\n--- a/app/main.py\n+++ b/app/main.py\n+x\n"
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    monkeypatch.setattr(
        review_module, "_call_provider", fake_call_provider({"findings": [], "summary": ""})
    )

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(),
        out_dir=tmp_path / "reports",
    )

    assert outcome.exit_code == 0


def test_run_review_raises_inconclusive_when_standards_yml_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "core.standards.yml").write_text("not: [valid, standards", encoding="utf-8")
    (tmp_path / "domain.standards.yml").write_text("version: 1\nsections: []\n", encoding="utf-8")
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])

    with pytest.raises(InconclusiveError):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
            no_llm=True,
        )


def test_run_review_fail_closed_invalidates_the_response_on_an_invalid_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -7,0 +7 @@\n"
        "+changed value\n"
    )
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    bad_finding = finding(rule_id="does-not-exist-1", confidence="high")
    monkeypatch.setattr(
        review_module,
        "_call_provider",
        fake_call_provider({"findings": [bad_finding], "summary": "One violation."}),
    )

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(evidence_policy="fail_closed"),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["verdict"] == "INCONCLUSIVE"
    assert outcome.exit_code == 4
    assert outcome.json_report["findings"] == []
    assert "fail_closed" in outcome.json_report["note"]
    assert "1 of 1" in outcome.json_report["note"]


def test_run_review_fail_closed_markdown_never_says_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test for `render_markdown` recomputing its own verdict from (empty)
    findings instead of consuming the already-authoritative `review["verdict"]` --
    that bug rendered a fail_closed-invalidated (INCONCLUSIVE) review as "APPROVED —
    no findings" in the Markdown report, contradicting CLAUDE.md's fail-closed rule.
    """
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -7,0 +7 @@\n"
        "+changed value\n"
    )
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    bad_finding = finding(rule_id="does-not-exist-1", confidence="high")
    monkeypatch.setattr(
        review_module,
        "_call_provider",
        fake_call_provider({"findings": [bad_finding], "summary": "One violation."}),
    )
    out_dir = tmp_path / "reports"

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(evidence_policy="fail_closed"),
        out_dir=out_dir,
    )

    assert outcome.exit_code == 4
    markdown = (out_dir / "f.patch.md").read_text(encoding="utf-8")
    assert "APPROVED" not in markdown
    assert "VERDICT: INCONCLUSIVE" in markdown
    assert "fail_closed" in markdown


@pytest.mark.xfail(
    reason=(
        "tests py-attest-template's generated workflow (PR_DESCRIPTION -> --description); "
        "the template is a separate repo created after v1.0.0 (CLAUDE.md, ADR-003)"
    ),
    strict=True,
)
def test_ci_passes_pr_description_as_one_quoted_environment_argument() -> None:
    workflow = (Path.cwd() / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "PR_DESCRIPTION: |" in workflow
    assert '--description "$PR_DESCRIPTION"' in workflow


def test_run_review_raises_inconclusive_when_the_secrets_gate_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_diff: str, _root: Path, **_kw: object) -> list[dict[str, object]]:
        raise SecretsGateError("gitleaks executable not found")

    monkeypatch.setattr(review_module, "findings_for_diff", fail)

    with pytest.raises(InconclusiveError, match="gitleaks executable not found"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
        )


def test_run_review_skips_gracefully_with_no_provider_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    # py-attest's own repo root has no .env (gitignored, none committed), so no real key
    # can be picked up here -- and OpenAIProvider never reads .env anyway (test_openai_provider.py).
    diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n+x\n"

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["layers"]["llm"] == "skipped:no_provider_key"
    assert outcome.json_report["findings"] == []
    assert outcome.json_report["verdict"] == "APPROVE"
    assert outcome.exit_code == 0


def test_run_review_verdict_comes_from_deterministic_findings_without_a_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DONE WHEN: without a key, layers.llm = skipped:no_provider_key and the verdict
    comes from the deterministic layers (here: a TODO with no ticket, code-quality-5,
    S3 -> COMMENT/0).
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+# TODO improve this\n"

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["layers"]["llm"] == "skipped:no_provider_key"
    assert outcome.exit_code == 0
    [reported_finding] = outcome.json_report["findings"]
    assert reported_finding["rule_id"] == "code-quality-5"
    assert reported_finding["severity"] == "S3"
    assert reported_finding["requires_human_classification"] is False
    assert reported_finding["evidence_verified"] is True


def test_run_review_deterministic_finding_survives_a_no_llm_run(tmp_path: Path) -> None:
    """The --no-llm branch also merges in deterministic findings (not just the LLM
    branch) -- a TODO with no ticket must still surface and drive the verdict.
    """
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+# TODO improve this\n"

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
        no_llm=True,
    )

    assert outcome.json_report["layers"]["llm"] == "skipped:--no-llm"
    [reported_finding] = outcome.json_report["findings"]
    assert reported_finding["rule_id"] == "code-quality-5"


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_run_review_deterministic_todo_survives_a_diff_level_secret_block(
    tmp_path: Path,
) -> None:
    """A non-blocking deterministic finding (TODO) in the same diff as a blocking secret
    must still surface in the report -- the secrets-block branch also merges in
    deterministic findings, not just the LLM branch.
    """
    diff = (
        "diff --git a/app/config.py b/app/config.py\n"
        "--- a/app/config.py\n"
        "+++ b/app/config.py\n"
        "@@ -1 +1,3 @@\n"
        " EXISTING = 1\n"
        '+AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"\n'
        "+# TODO improve this\n"
    )

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
    )

    assert outcome.exit_code == 2
    rule_ids = {f["rule_id"] for f in outcome.json_report["findings"]}
    assert "code-quality-5" in rule_ids
    assert "secrets-1" in rule_ids


def test_run_review_raises_inconclusive_when_context_pack_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_diff: str, _root: Path, _files: object, _rules_block: object = None) -> str:
        raise context_pack_module.ContextPackError("required context file missing: x")

    monkeypatch.setattr(raw_egress_module, "build_context", fail)

    with pytest.raises(InconclusiveError, match="required context file missing"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="f.patch",
            repo_root=Path.cwd(),
            config=Config(),
            out_dir=tmp_path / "reports",
        )


def test_run_review_raises_inconclusive_when_the_llm_call_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingProvider:
        name = "openai"

        def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
            del request
            raise ProviderFailure("rejected", "diff too large: 999999 bytes")

    monkeypatch.setattr(review_module, "_build_provider", lambda *_a, **_kw: FailingProvider())

    with pytest.raises(InconclusiveError, match="diff too large"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="f.patch",
            repo_root=Path.cwd(),
            config=Config(),
            out_dir=tmp_path / "reports",
        )


def test_run_review_raises_inconclusive_when_gate_commit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])

    def fail(_root: Path) -> str:
        raise DiffError("git executable not found")

    monkeypatch.setattr(review_module, "_gate_commit", fail)

    with pytest.raises(InconclusiveError, match="git executable not found"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
            no_llm=True,
        )


def test_run_review_resolves_source_shas_when_branch_source_is_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])

    outcome = run_review(
        diff="diff --git a/f b/f\n+x\n",
        source_name="feature/x",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
        no_llm=True,
        branch_source=("HEAD", "HEAD"),
    )

    source = outcome.json_report["source"]
    assert source["base_sha"] == source["head_sha"] == source["merge_base_sha"]
    assert len(source["base_sha"]) == 40


def test_run_review_raises_inconclusive_when_source_sha_resolution_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])

    def fail(_root: Path, _ref: str) -> str:
        raise DiffError("cannot resolve HEAD")

    monkeypatch.setattr(review_module, "_resolve_sha", fail)

    with pytest.raises(InconclusiveError, match="cannot resolve HEAD"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="feature/x",
            repo_root=Path.cwd(),
            config=Config(),
            out_dir=tmp_path / "reports",
            no_llm=True,
            branch_source=("HEAD", "HEAD"),
        )


def test_run_review_rejects_an_unknown_egress_mode(tmp_path: Path) -> None:
    with pytest.raises(click.UsageError, match="egress='bogus' is not implemented"):
        run_review(
            diff="diff --git a/f b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(egress="bogus"),
            out_dir=tmp_path / "reports",
        )


def test_run_review_egress_minimized_produces_a_minimized_report_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root, **_kw: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    captured: dict[str, Any] = {}

    def spy_call_provider(
        *,
        provider_name: str,
        config: Config,
        fake_response: str | None,
        egress_result: Any,
        prompt_version: str,
    ) -> tuple[dict[str, object], dict[str, object]]:
        del provider_name, config, fake_response, prompt_version
        captured["user_content"] = egress_result.user_content
        return {"findings": [], "summary": "ok"}, {}

    monkeypatch.setattr(review_module, "_call_provider", spy_call_provider)

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(egress="minimized"),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["egress"] == {
        "mode": "minimized",
        "payload_version": "MINIMIZED_PATCH_V2",
    }
    assert "MINIMIZED_PATCH_V2" in captured["user_content"]
    assert "<review-rules>" in captured["user_content"]
    assert "f.py" not in captured["user_content"]


def test_run_review_scans_context_files_for_secrets_before_transmitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A secret living in a `context_files` entry -- not the diff -- must still block
    before any provider call. The diff-only firewall would miss this entirely; regression
    test for a gap found in review: context_files/--description bypassed the firewall.
    """
    (tmp_path / "TEAM-STANDARDS.md").write_text(
        'AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8"
    )
    diff = "diff --git a/app/main.py b/app/main.py\n--- a/app/main.py\n+++ b/app/main.py\n+x\n"
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")

    def fail_call_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_call_provider must not be called when context has a secret")

    monkeypatch.setattr(review_module, "_call_provider", fail_call_provider)

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(context_files=("TEAM-STANDARDS.md",)),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["layers"]["llm"] == "skipped:secret_detected"
    assert outcome.json_report["verdict"] == "BLOCK"
    assert "AKIAABCDEFGHIJKLMNOP" not in json.dumps(outcome.json_report)


def test_run_review_scans_description_for_secrets_before_transmitting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1,0 +1 @@\n"
        "+x\n"
    )
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")

    def fail_call_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_call_provider must not be called when the description has a secret")

    monkeypatch.setattr(review_module, "_call_provider", fail_call_provider)

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(),
        out_dir=tmp_path / "reports",
        description='See AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP" in the changelog',
    )

    assert outcome.json_report["layers"]["llm"] == "skipped:secret_detected"
    assert outcome.json_report["verdict"] == "BLOCK"


def test_run_review_raises_inconclusive_when_the_context_scan_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The diff-scan and context-scan are two separate findings_for_diff calls; the
    second one (over the assembled context) can fail independently of the first.
    """
    calls = {"count": 0}

    def flaky_scan(_text: str, _root: Path, **_kw: object) -> list[dict[str, object]]:
        calls["count"] += 1
        if calls["count"] == 1:
            return []
        raise SecretsGateError("gitleaks executable not found")

    monkeypatch.setattr(review_module, "findings_for_diff", flaky_scan)

    with pytest.raises(InconclusiveError, match="gitleaks executable not found"):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
        )


def test_run_review_rejects_a_context_too_large_for_the_configured_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The size guard on the raw diff (top of run_review) only bounds `diff`; the payload
    actually sent to the provider is `context` (rules block + diff + context_files +
    --description), which was otherwise unbounded -- a huge --description could step
    around the one size guard in the pipeline entirely. Regression test for a gap found
    in review.
    """
    from py_attest.config import Limits

    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")

    def fail_call_provider(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("_call_provider must not be called when context is too large")

    monkeypatch.setattr(review_module, "_call_provider", fail_call_provider)

    with pytest.raises(InconclusiveError, match="review context too large"):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(limits=Limits(max_patch_bytes=100)),
            out_dir=tmp_path / "reports",
            description="x" * 1000,
        )


def test_run_review_reports_an_honest_location_for_context_level_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """findings_for_diff parses its input as a unified diff to locate a secret; run over
    the assembled `context` it can latch onto the diff embedded inside it and report a
    fabricated file:line for a secret that was actually in --description. Regression test
    for a report-accuracy gap found in review.
    """
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1,0 +1 @@\n"
        "+x\n"
    )
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")

    outcome = run_review(
        diff=diff,
        source_name="f.patch",
        repo_root=tmp_path,
        config=Config(),
        out_dir=tmp_path / "reports",
        description='See AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP" in the changelog',
    )

    [reported_finding] = outcome.json_report["findings"]
    assert reported_finding["path"] == "<review context: context_files or --description>"
    assert reported_finding["side"] is None
    assert reported_finding["line_start"] is None
    assert reported_finding["line_end"] is None
    assert "app/main.py" not in outcome.json_report["note"]
    assert "assembled review context" in outcome.json_report["note"]
    assert outcome.json_report["note"] != review_module.FIREWALL_SKIP_NOTE


def test_run_review_rejects_an_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(click.UsageError, match="unknown provider"):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
            provider="made-up",
        )


def test_run_review_raises_inconclusive_for_an_unknown_prompt_version(tmp_path: Path) -> None:
    with pytest.raises(InconclusiveError, match="unknown prompt version"):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
            provider="fake",
            fake_response=str(FIXTURES / "clean.json"),
            prompt_version="v99",
        )


def test_run_review_raises_inconclusive_when_the_provider_output_fails_schema_validation(
    tmp_path: Path,
) -> None:
    """FakeProvider only validates that its fixture is *syntactically* valid JSON
    (ProviderFailure); a fixture that parses fine but doesn't match REVIEW_SCHEMA must
    still be caught -- by the engine's one schema validation (ADR-002: providers never
    validate the schema themselves).
    """
    wrong_shape = tmp_path / "wrong_shape.json"
    wrong_shape.write_text(json.dumps({"unexpected": "shape"}), encoding="utf-8")

    with pytest.raises(InconclusiveError, match="invalid structured review"):
        run_review(
            diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
            source_name="f.patch",
            repo_root=tmp_path,
            config=Config(),
            out_dir=tmp_path / "reports",
            provider="fake",
            fake_response=str(wrong_shape),
        )


def test_run_review_publishes_usage_from_the_provider_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class UsageReportingProvider:
        name = "fake"

        def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
            del request
            return ProviderResponse(
                raw_json=json.dumps({"findings": [], "summary": "ok"}),
                model="fake-model",
                temperature_applied="0",
                usage=Usage(
                    input_tokens=10, cached_input_tokens=2, output_tokens=5, reasoning_tokens=1
                ),
            )

    monkeypatch.setattr(
        review_module, "_build_provider", lambda *_a, **_kw: UsageReportingProvider()
    )

    outcome = run_review(
        diff="diff --git a/f b/f\n--- a/f\n+++ b/f\n+x\n",
        source_name="f.patch",
        repo_root=Path.cwd(),
        config=Config(),
        out_dir=tmp_path / "reports",
    )

    assert outcome.json_report["meta"]["usage"] == {
        "input_tokens": 10,
        "cached_input_tokens": 2,
        "output_tokens": 5,
        "reasoning_tokens": 1,
    }
