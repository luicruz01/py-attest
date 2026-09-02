from pathlib import Path

from py_attest.config import load_config
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext


def test_check_result_defaults_remedy_and_rule_id_to_none() -> None:
    result = CheckResult(status=CheckStatus.PASS, message="all good")

    assert result.remedy is None
    assert result.rule_id is None


def test_check_result_is_frozen() -> None:
    result = CheckResult(status=CheckStatus.PASS, message="all good")

    with_error = False
    try:
        result.message = "changed"  # type: ignore[misc]
    except AttributeError:
        with_error = True

    assert with_error


def test_a_check_subclass_declares_id_and_severity_and_runs(tmp_path: Path) -> None:
    class _AlwaysPass(Check):
        id = "always_pass"
        severity = "S3"

        def run(self, _ctx: DoctorContext) -> CheckResult:
            return CheckResult(status=CheckStatus.PASS, message="ok")

    ctx = DoctorContext(repo_root=tmp_path, offline=False, config=load_config(tmp_path))
    check = _AlwaysPass()

    result = check.run(ctx)

    assert check.id == "always_pass"
    assert check.severity == "S3"
    assert result.status == CheckStatus.PASS
