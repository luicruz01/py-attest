from py_attest.doctor import _standards_adapter
from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext


class StandardsInSyncCheck(Check):
    """ADR-001: TEAM-STANDARDS.md matches what `attest standards build` would regenerate."""

    id = "standards_in_sync"
    severity = "S2"

    def run(self, ctx: DoctorContext) -> CheckResult:  # noqa: ARG002 - used once F0.4 lands
        if not _standards_adapter.is_available():
            return CheckResult(
                status=CheckStatus.SKIP, message=_standards_adapter.F0_4_PENDING_MESSAGE
            )
        raise NotImplementedError
