from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext
from py_attest.standards.lint import lint


class StandardsValidCheck(Check):
    """ADR-001: core.standards.yml + domain.standards.yml validate against the schema
    and every deterministic rule's `check` references a known check id (lint.py)."""

    id = "standards_valid"
    severity = "S1"

    def run(self, ctx: DoctorContext) -> CheckResult:
        core_path = ctx.repo_root / ctx.config.standards.core
        domain_path = ctx.repo_root / ctx.config.standards.domain
        if not core_path.is_file() and not domain_path.is_file():
            return CheckResult(
                status=CheckStatus.SKIP,
                message=(
                    f"no standards.yml configured ({ctx.config.standards.core}/"
                    f"{ctx.config.standards.domain} not found)"
                ),
            )

        errors = lint(core_path, domain_path)
        if errors:
            return CheckResult(
                status=CheckStatus.FAIL,
                message="; ".join(error.message for error in errors),
                remedy="run `attest standards lint` for the full list of problems",
            )
        return CheckResult(status=CheckStatus.PASS, message="core/domain standards.yml are valid")
