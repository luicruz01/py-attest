from pathlib import Path

import click
import pytest

from py_attest.config import load_config
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext
from py_attest.doctor.runner import ALL_CHECKS, run_doctor


class _AlwaysPass(Check):
    id = "always_pass"
    severity = "S3"

    def run(self, _ctx: DoctorContext) -> CheckResult:
        return CheckResult(status=CheckStatus.PASS, message="ok")


class _AlwaysFailS1(Check):
    id = "always_fail_s1"
    severity = "S1"

    def run(self, _ctx: DoctorContext) -> CheckResult:
        return CheckResult(status=CheckStatus.FAIL, message="broken", remedy="fix it")


class _AlwaysFailS2(Check):
    id = "always_fail_s2"
    severity = "S2"

    def run(self, _ctx: DoctorContext) -> CheckResult:
        return CheckResult(status=CheckStatus.FAIL, message="drifted")


class _CompatOne(Check):
    id = "compat_one"
    severity = "S1"

    def run(self, _ctx: DoctorContext) -> CheckResult:
        return CheckResult(status=CheckStatus.PASS, message="ok")


def _ctx(tmp_path: Path) -> DoctorContext:
    return DoctorContext(repo_root=tmp_path, offline=False, config=load_config(tmp_path))


def test_all_checks_is_the_four_registered_checks() -> None:
    ids = {check_cls.id for check_cls in ALL_CHECKS}

    assert ids == {
        "standards_valid",
        "standards_in_sync",
        "compat_engine_range",
        "compat_pin_consistent",
    }


def test_run_doctor_runs_every_registered_check_by_default(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path), checks=[_AlwaysPass, _AlwaysFailS1], only=None, compat=False
    )

    ran_ids = [check.id for check, _result in report.results]

    assert ran_ids == ["always_pass", "always_fail_s1"]


def test_run_doctor_with_only_filters_to_the_named_ids(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysPass, _AlwaysFailS1],
        only={"always_pass"},
        compat=False,
    )

    ran_ids = [check.id for check, _result in report.results]

    assert ran_ids == ["always_pass"]


def test_run_doctor_with_unknown_only_id_is_a_usage_error(tmp_path: Path) -> None:
    with pytest.raises(click.UsageError):
        run_doctor(
            _ctx(tmp_path),
            checks=[_AlwaysPass],
            only={"does_not_exist"},
            compat=False,
        )


def test_run_doctor_with_compat_restricts_to_compat_prefixed_checks(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysPass, _CompatOne],
        only=None,
        compat=True,
    )

    ran_ids = [check.id for check, _result in report.results]

    assert ran_ids == ["compat_one"]


def test_run_doctor_only_takes_precedence_over_compat(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysPass, _CompatOne],
        only={"always_pass"},
        compat=True,
    )

    ran_ids = [check.id for check, _result in report.results]

    assert ran_ids == ["always_pass"]


def test_run_doctor_has_block_true_when_strict_and_an_s1_check_fails(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysFailS1],
        only=None,
        compat=False,
        strict=True,
    )

    assert report.blocked is True


def test_run_doctor_not_blocked_when_strict_but_only_s2_fails(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysFailS2],
        only=None,
        compat=False,
        strict=True,
    )

    assert report.blocked is False


def test_run_doctor_not_blocked_when_s1_fails_but_strict_is_off(tmp_path: Path) -> None:
    report = run_doctor(
        _ctx(tmp_path),
        checks=[_AlwaysFailS1],
        only=None,
        compat=False,
        strict=False,
    )

    assert report.blocked is False
