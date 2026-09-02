import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from py_attest.cli.main import cli

FIXTURES = Path(__file__).parent / "doctor" / "fixtures"


def test_doctor_on_empty_repo_exits_zero_and_reports_no_applicable_checks(
    tmp_path: Path,
) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor", str(tmp_path)])

    assert result.exit_code == 0
    assert "compat_engine_range" in result.output
    assert "skip" in result.output


def test_doctor_compat_on_engine_range_pass_fixture_exits_zero() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli, ["doctor", "--compat", str(FIXTURES / "compat_engine_range" / "pass")]
    )

    assert result.exit_code == 0
    assert "compat_engine_range" in result.output
    assert "pass" in result.output


def test_doctor_compat_on_engine_range_fail_fixture_exits_zero_and_prints_remedy() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli, ["doctor", "--compat", str(FIXTURES / "compat_engine_range" / "fail")]
    )

    assert result.exit_code == 0
    assert "compat_engine_range" in result.output
    assert 'pip install -U "py-attest>=97,<98"' in result.output


def test_doctor_compat_strict_on_engine_range_fail_fixture_exits_2() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli,
        ["doctor", "--compat", "--strict", str(FIXTURES / "compat_engine_range" / "fail")],
    )

    assert result.exit_code == 2


def test_doctor_compat_only_runs_compat_checks() -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli, ["doctor", "--compat", "--json", str(FIXTURES / "compat_engine_range" / "fail")]
    )

    payload = json.loads(result.output)
    ids = {row["id"] for row in payload["checks"]}

    assert ids == {"compat_engine_range", "compat_pin_consistent"}


def test_doctor_json_flag_prints_valid_json_matching_the_schema(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor", "--json", str(tmp_path)])

    payload = json.loads(result.output)

    assert payload["schema_version"] == 1
    assert payload["target"] == str(tmp_path)
    assert "checks" in payload
    assert "summary" in payload
    assert "meta" in payload


def test_doctor_only_with_unknown_check_id_is_a_usage_error(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor", "--only", "does_not_exist", str(tmp_path)])

    assert result.exit_code == 64


def test_doctor_only_restricts_to_the_named_check(tmp_path: Path) -> None:
    runner = CliRunner()

    result = runner.invoke(
        cli, ["doctor", "--only", "compat_engine_range", "--json", str(tmp_path)]
    )

    payload = json.loads(result.output)
    ids = {row["id"] for row in payload["checks"]}

    assert ids == {"compat_engine_range"}


def test_doctor_defaults_to_cwd_when_no_path_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli, ["doctor", "--json"])

    payload = json.loads(result.output)
    assert payload["target"] == str(tmp_path)


def test_doctor_offline_flag_is_accepted_and_has_no_effect_on_these_checks(
    tmp_path: Path,
) -> None:
    runner = CliRunner()

    result = runner.invoke(cli, ["doctor", "--offline", str(tmp_path)])

    assert result.exit_code == 0
