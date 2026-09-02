from py_attest.doctor import _compat
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext


class CompatEngineRangeCheck(Check):
    """ADR-003 §3, row 1: installed py-attest vs. the template's attest_engine_range."""

    id = "compat_engine_range"
    severity = "S1"

    def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            answers = _compat.load_copier_answers(ctx.repo_root)
            if answers is None:
                return CheckResult(
                    status=CheckStatus.SKIP,
                    message=f"not a py-attest-template repo (no {_compat.ANSWERS_FILENAME})",
                )
            engine_range = _compat.engine_range_from_answers(answers)
            installed = _compat.installed_engine_version()
        except _compat.CompatDataError as exc:
            return CheckResult(status=CheckStatus.ERROR, message=str(exc))

        if installed in engine_range:
            return CheckResult(
                status=CheckStatus.PASS,
                message=f"installed py-attest {installed} satisfies {engine_range}",
            )
        return CheckResult(
            status=CheckStatus.FAIL,
            message=(
                f"installed py-attest {installed} is outside attest_engine_range {engine_range}"
            ),
            remedy=f'pip install -U "py-attest{engine_range}"',
        )
