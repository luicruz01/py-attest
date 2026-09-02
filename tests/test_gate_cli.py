"""CLI-level tests for `attest gate`.

Ports the invariant Seed A's `make gate` Makefile chain (lint -> test -> secrets-diff ->
review) used to guarantee: check runs before review, and a failing/blocked check
short-circuits review (no secrets-gate call, no LLM spend). The mechanism moved from
Makefile prerequisites to Python orchestration in gate() (py_attest/cli/main.py); the
guarantee itself is unchanged.
"""

import json

import pytest
from click.testing import CliRunner

from py_attest.check import runner as check_runner
from py_attest.cli.main import cli
from py_attest.review import reviewer as review_module
from py_attest.review.diff import DiffError


def test_gate_runs_check_before_review(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def fake_run_check(**_kwargs: object) -> dict[str, object]:
        calls.append("check")
        return {"findings": [], "verdict": "APPROVE", "exit_code": 0}

    def fake_run_review(**_kwargs: object) -> review_module.ReviewOutcome:
        calls.append("review")
        return review_module.ReviewOutcome(exit_code=0, json_report={"schema_version": 3})

    monkeypatch.setattr("py_attest.cli.main.run_check", fake_run_check)
    monkeypatch.setattr("py_attest.cli.main.run_review", fake_run_review)
    monkeypatch.setattr(
        "py_attest.cli.main._branch_diff", lambda *_args, **_kwargs: "diff --git a b\n"
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x"])

    assert result.exit_code == 0
    assert calls == ["check", "review"]


def test_gate_blocked_check_short_circuits_review(monkeypatch: pytest.MonkeyPatch) -> None:
    review_called = False

    def fake_run_check(**_kwargs: object) -> dict[str, object]:
        return {
            "findings": [
                {
                    "rule": "testing-1",
                    "severity": "S2",
                    "confidence": "high",
                    "file": "<pytest>",
                    "line": None,
                    "title": "pytest failed",
                    "evidence": "",
                    "explanation": "",
                    "suggested_fix": "",
                }
            ],
            "verdict": "BLOCK",
            "exit_code": 2,
        }

    def fake_run_review(**_kwargs: object) -> review_module.ReviewOutcome:
        nonlocal review_called
        review_called = True
        raise AssertionError("review must not run when check is blocked")

    monkeypatch.setattr("py_attest.cli.main.run_check", fake_run_check)
    monkeypatch.setattr("py_attest.cli.main.run_review", fake_run_review)
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x"])

    assert result.exit_code == 2
    assert review_called is False
    assert "skipping review" in result.output


def test_gate_execution_failure_in_check_short_circuits_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review_called = False

    def fake_run_check(**_kwargs: object) -> dict[str, object]:
        raise check_runner.CheckExecutionError("gitleaks executable not found")

    def fake_run_review(**_kwargs: object) -> review_module.ReviewOutcome:
        nonlocal review_called
        review_called = True
        raise AssertionError("review must not run when check fails to execute")

    monkeypatch.setattr("py_attest.cli.main.run_check", fake_run_check)
    monkeypatch.setattr("py_attest.cli.main.run_review", fake_run_review)
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x"])

    assert result.exit_code == 4
    assert review_called is False


def test_gate_json_flag_prints_the_combined_report_when_review_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "py_attest.cli.main.run_check",
        lambda **_kwargs: {"findings": [], "verdict": "APPROVE", "exit_code": 0},
    )
    monkeypatch.setattr(
        "py_attest.cli.main.run_review",
        lambda **_kwargs: review_module.ReviewOutcome(
            exit_code=0, json_report={"schema_version": 3, "verdict": "APPROVE"}
        ),
    )
    monkeypatch.setattr(
        "py_attest.cli.main._branch_diff", lambda *_args, **_kwargs: "diff --git a b\n"
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x", "--json"])

    payload = json.loads(result.output)
    assert payload["stage"] == "gate"
    assert payload["exit_code"] == 0
    assert payload["review"] == {"schema_version": 3, "verdict": "APPROVE"}


def test_gate_json_flag_prints_a_check_only_report_when_short_circuited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "py_attest.cli.main.run_check",
        lambda **_kwargs: {"findings": [], "verdict": "BLOCK", "exit_code": 2},
    )
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x", "--json"])

    payload = json.loads(result.output)
    assert payload["stage"] == "gate"
    assert payload["exit_code"] == 2
    assert payload["review"] is None


def test_gate_maps_branch_diff_failure_to_exit_4(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "py_attest.cli.main.run_check",
        lambda **_kwargs: {"findings": [], "verdict": "APPROVE", "exit_code": 0},
    )

    def fail(*_args: object, **_kwargs: object) -> str:
        raise DiffError("cannot diff main...feature/x: fatal: bad revision")

    monkeypatch.setattr("py_attest.cli.main._branch_diff", fail)
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x"])

    assert result.exit_code == 4
