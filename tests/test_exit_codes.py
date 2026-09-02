from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from py_attest.cli.main import AttestGroup, cli, exit_code_for
from py_attest.errors import BlockedError, IncompatibleError, InconclusiveError


def test_exit_code_for_usage_error_is_64() -> None:
    assert exit_code_for(click.UsageError("bad usage")) == 64


def test_exit_code_for_blocked_error_is_2() -> None:
    assert exit_code_for(BlockedError("blocked")) == 2


def test_exit_code_for_incompatible_error_is_3() -> None:
    assert exit_code_for(IncompatibleError("incompatible")) == 3


def test_exit_code_for_inconclusive_error_is_4() -> None:
    assert exit_code_for(InconclusiveError("inconclusive")) == 4


def test_exit_code_for_unexpected_exception_is_4() -> None:
    assert exit_code_for(ValueError("unexpected")) == 4


def test_unexpected_exception_in_dispatch_exits_4() -> None:
    """An uncaught, non-AttestError exception from a command must fail closed (never approve)."""

    @click.command()
    def _boom() -> None:
        raise ValueError("boom")

    group = AttestGroup(name="test-group", commands={"boom": _boom})
    runner = CliRunner()

    result = runner.invoke(group, ["boom"])

    assert result.exit_code == 4


@pytest.mark.parametrize(
    ("error", "expected_exit_code"),
    [
        (BlockedError("blocked"), 2),
        (IncompatibleError("incompatible"), 3),
        (InconclusiveError("inconclusive"), 4),
    ],
)
def test_attest_error_in_dispatch_exits_with_its_mapped_code(
    error: Exception, expected_exit_code: int
) -> None:
    """Exercises AttestGroup.main()'s except-AttestError branch, not just exit_code_for()."""

    @click.command()
    def _boom() -> None:
        raise error

    group = AttestGroup(name="test-group", commands={"boom": _boom})
    runner = CliRunner()

    result = runner.invoke(group, ["boom"])

    assert result.exit_code == expected_exit_code


def test_doctor_exits_zero_on_a_repo_with_no_applicable_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 0
    assert "compat_engine_range" in result.output


def test_gate_without_branch_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["gate"])

    assert result.exit_code == 64


def test_review_without_source_flag_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["review"])

    assert result.exit_code == 64


def test_unknown_config_key_makes_any_command_exit_64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.attest]\nnot_a_real_key = 1\n")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor"])

    assert result.exit_code == 64
    assert "not_a_real_key" in result.output
