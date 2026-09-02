from click.testing import CliRunner

from py_attest import __version__
from py_attest.cli.main import cli


def test_version_flag_prints_version_and_exits_zero() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])

    assert result.exit_code == 0
    assert __version__ in result.output


def test_bare_invocation_shows_usage_and_exits_with_usage_error() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, [])

    assert result.exit_code == 2
    assert "Usage" in result.output
