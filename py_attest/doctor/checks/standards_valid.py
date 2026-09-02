from py_attest.doctor import _standards_adapter
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext


class StandardsValidCheck(Check):
    """ADR-001: core.standards.yml + domain.standards.yml validate against the schema."""

    id = "standards_valid"
    severity = "S1"

    def run(self, ctx: DoctorContext) -> CheckResult:  # noqa: ARG002 - used once F0.4 lands
        if not _standards_adapter.is_available():
            return CheckResult(
                status=CheckStatus.SKIP, message=_standards_adapter.F0_4_PENDING_MESSAGE
            )
        raise NotImplementedError
