"""Discover and run doctor checks, producing a DoctorReport."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import click

from py_attest.doctor.check import Check, CheckResult, CheckStatus, DoctorContext
from py_attest.doctor.checks.compat_engine_range import CompatEngineRangeCheck
from py_attest.doctor.checks.compat_pin_consistent import CompatPinConsistentCheck
from py_attest.doctor.checks.standards_in_sync import StandardsInSyncCheck
from py_attest.doctor.checks.standards_valid import StandardsValidCheck

ALL_CHECKS: tuple[type[Check], ...] = (
    StandardsValidCheck,
    StandardsInSyncCheck,
    CompatEngineRangeCheck,
    CompatPinConsistentCheck,
)


@dataclass(frozen=True)
class DoctorReport:
    target: Path
    strict: bool
    compat: bool
    results: list[tuple[Check, CheckResult]]

    @property
    def blocked(self) -> bool:
        if not self.strict:
            return False
        return any(
            check.severity == "S1" and result.status in (CheckStatus.FAIL, CheckStatus.ERROR)
            for check, result in self.results
        )


def run_doctor(
    ctx: DoctorContext,
    *,
    checks: tuple[type[Check], ...] = ALL_CHECKS,
    only: set[str] | None = None,
    compat: bool = False,
    strict: bool = False,
) -> DoctorReport:
    """Run the selected checks against ``ctx`` and return their results."""
    selected = _select(checks, only=only, compat=compat)
    results = [(check, check.run(ctx)) for check in selected]
    return DoctorReport(target=ctx.repo_root, strict=strict, compat=compat, results=results)


def _select(checks: tuple[type[Check], ...], *, only: set[str] | None, compat: bool) -> list[Check]:
    if only is not None:
        known_ids = {check_cls.id for check_cls in checks}
        unknown = only - known_ids
        if unknown:
            raise click.UsageError(f"--only: unknown check id(s): {', '.join(sorted(unknown))}")
        return [check_cls() for check_cls in checks if check_cls.id in only]
    if compat:
        return [check_cls() for check_cls in checks if check_cls.id.startswith("compat_")]
    return [check_cls() for check_cls in checks]
