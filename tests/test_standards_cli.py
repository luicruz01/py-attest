# tests/test_standards_cli.py
from pathlib import Path

from click.testing import CliRunner

from py_attest.cli.main import cli

DEFAULTS = Path(__file__).parent.parent / "py_attest" / "standards" / "defaults"


def _write_standards(tmp_path: Path) -> None:
    (tmp_path / "core.standards.yml").write_text(
        (DEFAULTS / "core.standards.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tmp_path / "domain.standards.yml").write_text(
        (DEFAULTS / "domain.standards.yml").read_text(encoding="utf-8"), encoding="utf-8"
    )


def test_standards_lint_passes_on_valid_standards(tmp_path: Path, monkeypatch) -> None:
    _write_standards(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["standards", "lint"])

    assert result.exit_code == 0


def test_standards_lint_exits_64_on_a_schema_violation(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "core.standards.yml").write_text("not: [valid", encoding="utf-8")
    (tmp_path / "domain.standards.yml").write_text("version: 1\nsections: []\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["standards", "lint"])

    assert result.exit_code == 64


def test_standards_build_writes_team_standards_md(tmp_path: Path, monkeypatch) -> None:
    _write_standards(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["standards", "build"])

    assert result.exit_code == 0
    assert (tmp_path / "TEAM-STANDARDS.md").is_file()


def test_standards_build_check_passes_when_up_to_date(tmp_path: Path, monkeypatch) -> None:
    _write_standards(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    runner.invoke(cli, ["standards", "build"])

    result = runner.invoke(cli, ["standards", "build", "--check"])

    assert result.exit_code == 0


def test_standards_build_check_exits_2_on_drift(tmp_path: Path, monkeypatch) -> None:
    _write_standards(tmp_path)
    (tmp_path / "TEAM-STANDARDS.md").write_text("stale\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(cli, ["standards", "build", "--check"])

    assert result.exit_code == 2
