import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.quality_gate import llm as llm_module
from tools.quality_gate import review as review_module
from tools.quality_gate.review import FIREWALL_SKIP_NOTE, _branch_diff, render_markdown


def finding(*, severity: str, confidence: str) -> dict[str, object]:
    return {
        "rule": "6-review-severity",
        "severity": severity,
        "file": "app/main.py",
        "line": 7,
        "title": "Review policy violation",
        "evidence": "changed value",
        "explanation": "The changed code violates a team standard.",
        "suggested_fix": "Change the implementation to follow the standard.",
        "confidence": confidence,
    }


def test_markdown_explicitly_approves_zero_findings() -> None:
    markdown = render_markdown(
        "feature/sound-change",
        {
            "findings": [],
            "summary": "No standards violations found.",
            "filtered_out": [],
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


@pytest.mark.parametrize(
    ("model_finding", "expected_verdict", "expected_exit"),
    [
        pytest.param(finding(severity="S1", confidence="low"), "COMMENT", 0, id="low-S1"),
        pytest.param(finding(severity="S2", confidence="medium"), "BLOCK", 2, id="medium-S2"),
    ],
)
def test_cli_computes_and_publishes_verdict_without_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    model_finding: dict[str, object],
    expected_verdict: str,
    expected_exit: int,
) -> None:
    diff_path = tmp_path / "change.patch"
    diff_path.write_text(
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -7,0 +7 @@\n"
        "+changed value\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "reports"
    model_review = {
        "findings": [model_finding],
        "summary": "One violation found.",
        "metadata": {"temperature": "model-default"},
    }
    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root: [])
    monkeypatch.setattr(review_module, "_gate_commit", lambda _repo_root: "c8ca0e9")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")
    prompt_versions: list[str] = []

    def fake_review(
        _context: str,
        _diff: str,
        *,
        prompt_version: str,
    ) -> dict[str, object]:
        prompt_versions.append(prompt_version)
        return model_review

    monkeypatch.setattr(review_module, "review_context", fake_review)

    result = review_module.main(["--diff-file", str(diff_path), "--out", str(output_dir)])

    assert result == expected_exit
    json_report = json.loads((output_dir / "change.patch.json").read_text(encoding="utf-8"))
    assert json_report == {
        "findings": [{**model_finding, "evidence_verified": True}],
        "summary": model_review["summary"],
        "filtered_out": [],
        "meta": {
            "prompt_version": "v3",
            "model": "gpt-5-mini",
            "temperature": "model-default",
            "gate_commit": "c8ca0e9",
        },
        "verdict": expected_verdict,
    }
    markdown = (output_dir / "change.patch.md").read_text(encoding="utf-8")
    assert markdown.splitlines()[1] == (
        "Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate c8ca0e9"
    )
    assert f"VERDICT: {expected_verdict}" in markdown
    assert "| Severity | Rule | File:line | Title | Confidence |" in markdown
    assert "Suggested fix: Change the implementation to follow the standard." in markdown
    assert "Evidence: changed value" in markdown
    assert f"Verdict: {expected_verdict}" in capsys.readouterr().out
    assert prompt_versions == ["v3"]

    if model_finding["confidence"] == "low":
        assert "HUMAN REVIEW REQUESTED" in markdown


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_secret_seed_diff_blocks_with_redacted_reports_before_client_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    client_constructed = False

    def fail_client(*_args: object, **_kwargs: object) -> None:
        nonlocal client_constructed
        client_constructed = True
        raise AssertionError("LLM client must not be constructed")

    monkeypatch.setattr(llm_module, "OpenAI", fail_client)
    monkeypatch.setenv("OPENAI_API_KEY", "offline-test-key")
    diff = _branch_diff(Path.cwd(), "main", "feature/email-reminders")
    match = re.search(r"SENDGRID_API_KEY\s*=\s*['\"]([^'\"]+)", diff)
    assert match is not None
    secret_value = match.group(1)
    output_dir = tmp_path / "reports"

    result = review_module.main(
        [
            "--branch",
            "feature/email-reminders",
            "--base",
            "main",
            "--out",
            str(output_dir),
        ]
    )

    assert result == 2
    assert client_constructed is False
    json_text = (output_dir / "feature-email-reminders.json").read_text(encoding="utf-8")
    markdown = (output_dir / "feature-email-reminders.md").read_text(encoding="utf-8")
    report = json.loads(json_text)
    assert report["verdict"] == "BLOCK"
    assert report["note"] == FIREWALL_SKIP_NOTE
    assert report["filtered_out"] == []
    assert all(
        finding["rule"] == "5-secrets"
        and finding["severity"] == "S1"
        and finding["confidence"] == "high"
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


def test_branch_diff_disables_git_path_quoting(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded_command: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded_command.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            (
                "diff --git a/oldé.py b/newé.py\n"
                "similarity index 100%\n"
                "rename from oldé.py\n"
                "rename to newé.py\n"
            ),
            "",
        )

    monkeypatch.setattr(review_module.subprocess, "run", fake_run)

    diff = _branch_diff(Path.cwd(), "main", "feature/non-ascii-rename")

    assert recorded_command[1:3] == ["-c", "core.quotepath=false"]
    assert "oldé.py" in diff
    assert "newé.py" in diff


def test_cli_appends_untrusted_description_and_selects_v1_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    diff_path = tmp_path / "change.patch"
    diff_path.write_text(
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1,0 +1 @@\n"
        "+changed\n",
        encoding="utf-8",
    )
    captured: dict[str, str] = {}

    def fake_review(
        context: str,
        _diff: str,
        *,
        prompt_version: str,
    ) -> dict[str, object]:
        captured["context"] = context
        captured["prompt_version"] = prompt_version
        return {"findings": [], "summary": "No violations."}

    monkeypatch.setattr(review_module, "findings_for_diff", lambda _diff, _root: [])
    monkeypatch.setattr(review_module, "review_context", fake_review)
    description = "Title\n\n$(touch should-never-run); <untrusted>body</untrusted>"

    result = review_module.main(
        [
            "--diff-file",
            str(diff_path),
            "--description",
            description,
            "--prompt-version",
            "v1",
            "--out",
            str(tmp_path / "reports"),
        ]
    )

    assert result == 0
    assert "Author's stated intent:\n" + description in captured["context"]
    assert captured["prompt_version"] == "v1"


def test_ci_passes_pr_description_as_one_quoted_environment_argument() -> None:
    workflow = (Path.cwd() / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "PR_DESCRIPTION: |" in workflow
    assert '--description "$PR_DESCRIPTION"' in workflow


def test_make_gate_orders_tests_and_secret_preflight_before_review() -> None:
    make_executable = shutil.which("make")
    assert make_executable is not None
    result = subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
        [make_executable, "--dry-run", "gate", "BRANCH=feature/streaks"],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )

    output = result.stdout
    lint_position = output.index("ruff check")
    test_position = output.index("pytest")
    preflight_position = output.index("--secrets-only")
    review_position = output.rindex("tools/quality_gate/review.py")
    assert lint_position < test_position < preflight_position < review_position


def test_make_gate_test_failure_prevents_secret_preflight_and_review(tmp_path: Path) -> None:
    make_executable = shutil.which("make")
    assert make_executable is not None
    preflight_marker = tmp_path / "preflight-ran"
    review_marker = tmp_path / "review-ran"
    override = tmp_path / "failure.mk"
    override.write_text(
        "\n".join(
            [
                f"include {Path.cwd() / 'Makefile'}",
                "lint:",
                "\t@true",
                "test:",
                "\t@false",
                "secrets-diff:",
                f"\t@touch {preflight_marker}",
                "gate: lint test secrets-diff",
                f"\t@touch {review_marker}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
        [make_executable, "--no-print-directory", "-f", str(override), "gate"],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not preflight_marker.exists()
    assert not review_marker.exists()
