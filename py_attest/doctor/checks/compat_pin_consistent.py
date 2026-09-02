from py_attest.doctor import _compat
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext


class CompatPinConsistentCheck(Check):
    """ADR-003 §3, row 2: pyproject.toml's pin vs. .copier-answers.yml's attest_engine_range."""

    id = "compat_pin_consistent"
    severity = "S2"

    def run(self, ctx: DoctorContext) -> CheckResult:
        try:
            answers = _compat.load_copier_answers(ctx.repo_root)
            if answers is None:
                return CheckResult(
                    status=CheckStatus.SKIP,
                    message=f"not a py-attest-template repo (no {_compat.ANSWERS_FILENAME})",
                )
            answers_range = _compat.engine_range_from_answers(answers)
            pyproject_range = _compat.engine_range_from_pyproject(ctx.repo_root)
        except _compat.CompatDataError as exc:
            return CheckResult(status=CheckStatus.ERROR, message=str(exc))

        if pyproject_range.specifier == answers_range.specifier:
            return CheckResult(
                status=CheckStatus.PASS,
                message=f"pyproject.toml pin matches attest_engine_range {answers_range}",
            )
        return CheckResult(
            status=CheckStatus.FAIL,
            message=(
                f"pyproject.toml pins py-attest{pyproject_range}, but "
                f".copier-answers.yml's attest_engine_range is {answers_range}"
            ),
            remedy="run `attest upgrade` to re-render the pin, or reconcile it by hand",
        )
