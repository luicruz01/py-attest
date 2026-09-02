import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from py_attest.check import runner


def _ok(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(command, 0, "", "")


def test_run_check_with_all_layers_clean_approves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", _ok)

    result = runner.run_check(path=tmp_path)

    assert result == {"findings": [], "verdict": "APPROVE", "exit_code": 0}


def test_ruff_check_violations_produce_a_comment_never_a_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    violations = [
        {
            "filename": "app/main.py",
            "code": "F401",
            "message": "`os` imported but unused",
            "location": {"row": 1, "column": 1},
        }
    ]

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:2] == ["check"]:
            return subprocess.CompletedProcess(command, 1, json.dumps(violations), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert [f["rule"] for f in result["findings"]] == ["code-quality-1"]
    assert result["findings"][0]["severity"] == "S3"
    assert result["findings"][0]["evidence"] == "1 violation(s) reported by ruff"
    # The raw source snippet ruff would otherwise echo must never land in the report.
    assert "F401" not in json.dumps(result)
    assert "app/main.py" not in json.dumps(result)
    assert result["verdict"] == "COMMENT"
    assert result["exit_code"] == 0


def test_ruff_check_with_unparseable_output_still_reports_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:2] == ["check"]:
            return subprocess.CompletedProcess(command, 1, "not json", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert result["findings"][0]["evidence"] == "ruff reported violations (unparseable output)"
    assert result["verdict"] == "COMMENT"


def test_ruff_check_with_a_non_list_json_payload_still_reports_a_finding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:2] == ["check"]:
            return subprocess.CompletedProcess(command, 1, json.dumps({"not": "a list"}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert result["findings"][0]["evidence"] == "ruff reported violations (unparseable output)"


def test_ruff_format_check_violations_are_reported_separately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if command[1:3] == ["format", "--check"]:
            return subprocess.CompletedProcess(command, 1, "Would reformat: app/main.py\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert [f["rule"] for f in result["findings"]] == ["code-quality-2"]
    assert result["verdict"] == "COMMENT"


def test_pytest_failure_blocks_with_testing_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.coverage.report]\nfail_under = 95\n", encoding="utf-8"
    )

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "pytest" in command:
            return subprocess.CompletedProcess(command, 1, "1 failed, coverage 80%\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert [f["rule"] for f in result["findings"]] == ["testing-1"]
    assert result["findings"][0]["severity"] == "S2"
    assert "fail_under=95" in result["findings"][0]["explanation"]
    assert result["verdict"] == "BLOCK"
    assert result["exit_code"] == 2


def test_gitleaks_tree_detection_blocks_with_secrets_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaks = [{"RuleID": "generic-api-key", "File": "app/config.py", "StartLine": 3}]

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 1, json.dumps(leaks), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    [finding] = result["findings"]
    assert finding["rule"] == "secrets-1"
    assert finding["severity"] == "S1"
    assert finding["file"] == "app/config.py"
    assert finding["line"] == 3
    assert "generic-api-key" in finding["title"]
    assert finding["evidence"] == "<redacted secret evidence>"
    assert result["verdict"] == "BLOCK"
    assert result["exit_code"] == 2


def test_no_tests_and_no_lint_skip_those_layers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_check(path=tmp_path, no_tests=True, no_lint=True)

    assert not any("ruff" in call[0] or "pytest" in call for call in calls if call)
    assert any("gitleaks" in call[0] for call in calls)


def test_missing_gitleaks_binary_raises_check_execution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(name: str) -> str | None:
        return None if name == "gitleaks" else "/usr/bin/tool"

    monkeypatch.setattr(runner.shutil, "which", which)
    monkeypatch.setattr(runner.subprocess, "run", _ok)

    with pytest.raises(runner.CheckExecutionError, match="gitleaks"):
        runner.run_check(path=tmp_path)


def test_missing_ruff_binary_raises_check_execution_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def which(name: str) -> str | None:
        return None if name == "ruff" else "/usr/bin/tool"

    monkeypatch.setattr(runner.shutil, "which", which)
    monkeypatch.setattr(runner.subprocess, "run", _ok)

    with pytest.raises(runner.CheckExecutionError, match="ruff"):
        runner.run_check(path=tmp_path)


def test_coverage_fail_under_missing_pyproject_is_none(tmp_path: Path) -> None:
    assert runner._coverage_fail_under(tmp_path) is None


def test_coverage_fail_under_with_unparseable_toml_is_none(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not [ valid toml", encoding="utf-8")

    assert runner._coverage_fail_under(tmp_path) is None


def test_missing_ruff_binary_for_format_check_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"count": 0}

    def which(name: str) -> str | None:
        if name != "ruff":
            return "/usr/bin/tool"
        calls["count"] += 1
        return "/usr/bin/ruff" if calls["count"] == 1 else None

    monkeypatch.setattr(runner.shutil, "which", which)
    monkeypatch.setattr(runner.subprocess, "run", _ok)

    with pytest.raises(runner.CheckExecutionError, match="ruff"):
        runner.run_check(path=tmp_path)


def test_gitleaks_tree_scan_raises_on_unexpected_return_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 2, "", "boom")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.CheckExecutionError, match="exit code 2"):
        runner.run_check(path=tmp_path)


def test_gitleaks_tree_scan_raises_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 1, "{not json", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.CheckExecutionError, match="invalid JSON report"):
        runner.run_check(path=tmp_path)


def test_gitleaks_tree_scan_raises_when_report_is_not_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 1, json.dumps({}), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.CheckExecutionError, match="invalid JSON report"):
        runner.run_check(path=tmp_path)


def test_gitleaks_tree_scan_raises_when_a_leak_entry_is_not_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 1, json.dumps(["oops"]), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    with pytest.raises(runner.CheckExecutionError, match="invalid leak entry"):
        runner.run_check(path=tmp_path)


def test_gitleaks_finding_without_a_start_line_has_no_line_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    leaks = [{"RuleID": "generic-api-key", "File": "app/config.py"}]

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            return subprocess.CompletedProcess(command, 1, json.dumps(leaks), "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_check(path=tmp_path)

    assert result["findings"][0]["line"] is None


def test_gitleaks_tree_passes_the_shipped_default_excludes_when_repo_has_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, "[]", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_check(path=tmp_path)

    assert "--config" in captured["command"]
    config_path = captured["command"][captured["command"].index("--config") + 1]
    assert config_path == str(runner._DEFAULT_GITLEAKS_EXCLUDES)


def test_gitleaks_tree_respects_the_repos_own_gitleaks_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".gitleaks.toml").write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
    captured: dict[str, list[str]] = {}

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        if "detect" in command:
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, "[]", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(runner.shutil, "which", lambda name: f"/usr/bin/{name}" if name else None)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    runner.run_check(path=tmp_path)

    assert "--config" not in captured["command"]


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_run_check_ignores_secrets_in_regenerated_build_caches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--no-git` scans every file on disk, ignored or not: a __pycache__ .pyc embedding
    the same string constants as the source that produced it must not BLOCK a clean tree.
    Regression test for a false positive found in review while running the real CLI.
    """
    gitleaks_path = shutil.which("gitleaks")
    monkeypatch.setattr(
        runner.shutil, "which", lambda name: gitleaks_path if name == "gitleaks" else None
    )
    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "mod.cpython-313.pyc").write_text(
        'AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"\n', encoding="utf-8"
    )

    result = runner.run_check(path=tmp_path, no_tests=True, no_lint=True)

    assert result == {"findings": [], "verdict": "APPROVE", "exit_code": 0}


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_pytest_failure_evidence_never_leaks_the_exception_message(tmp_path: Path) -> None:
    """Regression test for a leak found in review: pytest's default short test summary
    prints "FAILED test::name - <exception repr>" per failure, and an assertion or
    exception message can itself embed a reviewed-repo runtime value (a token, a
    compared secret). That must never reach the shared report artifact (TRD Sec4.3/Sec8).
    """
    (tmp_path / "test_boom.py").write_text(
        'def test_boom():\n    raise RuntimeError("do-not-leak-this-runtime-value")\n',
        encoding="utf-8",
    )

    result = runner.run_check(path=tmp_path, no_lint=True)

    [finding] = result["findings"]
    assert finding["rule"] == "testing-1"
    assert "do-not-leak-this-runtime-value" not in json.dumps(result)
    assert "1 failed" in finding["evidence"]
