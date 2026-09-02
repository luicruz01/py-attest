import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from py_attest.cli.main import cli


def _fake_result(
    verdict: str, exit_code: int, findings: list[dict[str, object]]
) -> dict[str, object]:
    return {"findings": findings, "verdict": verdict, "exit_code": exit_code}


def test_check_clean_repo_prints_verdict_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "py_attest.cli.main.run_check", lambda **_kwargs: _fake_result("APPROVE", 0, [])
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["check", str(tmp_path)])

    assert result.exit_code == 0
    assert "Verdict: APPROVE" in result.output


def test_check_with_findings_lists_each_one_and_exits_with_the_verdict_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    findings = [
        {
            "rule": "secrets-1",
            "severity": "S1",
            "title": "Secret detected in working tree",
        }
    ]
    monkeypatch.setattr(
        "py_attest.cli.main.run_check", lambda **_kwargs: _fake_result("BLOCK", 2, findings)
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["check"])

    assert result.exit_code == 2
    assert "- [S1] secrets-1: Secret detected in working tree" in result.output


def test_check_json_flag_prints_the_raw_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "py_attest.cli.main.run_check", lambda **_kwargs: _fake_result("APPROVE", 0, [])
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["check", "--json"])

    assert json.loads(result.output) == {"findings": [], "verdict": "APPROVE", "exit_code": 0}


def test_check_execution_failure_maps_to_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    from py_attest.check.runner import CheckExecutionError

    def fail(**_kwargs: object) -> None:
        raise CheckExecutionError("gitleaks executable not found")

    monkeypatch.setattr("py_attest.cli.main.run_check", fail)
    runner = CliRunner()

    result = runner.invoke(cli, ["check"])

    assert result.exit_code == 4
