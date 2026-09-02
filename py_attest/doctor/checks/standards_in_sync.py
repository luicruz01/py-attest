from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext
from py_attest.errors import StandardsDriftError
from py_attest.standards.build import build
from py_attest.standards.registry import RegistryError


class StandardsInSyncCheck(Check):
    """ADR-001: TEAM-STANDARDS.md matches what `attest standards build` would regenerate."""

    id = "standards_in_sync"
    severity = "S2"

    def run(self, ctx: DoctorContext) -> CheckResult:
        core_path = ctx.repo_root / ctx.config.standards.core
        domain_path = ctx.repo_root / ctx.config.standards.domain
        output_path = ctx.repo_root / ctx.config.standards.output
        if not core_path.is_file() and not domain_path.is_file():
            return CheckResult(
                status=CheckStatus.SKIP,
                message=(
                    f"no standards.yml configured ({ctx.config.standards.core}/"
                    f"{ctx.config.standards.domain} not found)"
                ),
            )

        try:
            build(core_path, domain_path, output_path, check=True)
        except StandardsDriftError as exc:
            return CheckResult(
                status=CheckStatus.FAIL,
                message=str(exc),
                remedy="run `attest standards build` to regenerate " + ctx.config.standards.output,
            )
        except RegistryError as exc:
            return CheckResult(status=CheckStatus.ERROR, message=str(exc))
        return CheckResult(
            status=CheckStatus.PASS, message=f"{ctx.config.standards.output} is in sync"
        )
