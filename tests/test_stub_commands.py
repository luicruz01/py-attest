from pathlib import Path

import pytest
from click.testing import CliRunner

from py_attest.cli.main import cli


@pytest.mark.parametrize(
    "args",
    [
        ["check"],
        ["new"],
        ["upgrade"],
        ["calibrate"],
        ["standards", "build"],
        ["standards", "lint"],
        ["standards", "new-rule"],
    ],
)
def test_stub_command_prints_not_implemented_and_exits_zero(
    args: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, args)

    assert result.exit_code == 0
    assert "not implemented yet" in result.output


def test_review_with_branch_flag_prints_not_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["review", "--branch", "feature/x"])

    assert result.exit_code == 0
    assert "not implemented yet" in result.output


def test_gate_with_branch_flag_prints_not_implemented(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["gate", "--branch", "feature/x"])

    assert result.exit_code == 0
    assert "not implemented yet" in result.output
