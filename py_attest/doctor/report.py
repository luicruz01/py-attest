"""Render a DoctorReport as JSON (schema_version 1) or Markdown."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from py_attest import __version__
from py_attest.doctor.check import CheckStatus

if TYPE_CHECKING:
    from py_attest.doctor.runner import DoctorReport

SCHEMA_VERSION = 1


def to_json(report: DoctorReport) -> dict[str, Any]:
    checks = [
        {
            "id": check.id,
            "severity": check.severity,
            "status": result.status.value,
            "message": result.message,
            "remedy": result.remedy,
            "rule_id": result.rule_id,
        }
        for check, result in report.results
    ]
    summary = {status.value: 0 for status in CheckStatus}
    for _check, result in report.results:
        summary[result.status.value] += 1

    return {
        "schema_version": SCHEMA_VERSION,
        "target": str(report.target),
        "strict": report.strict,
        "compat": report.compat,
        "checks": checks,
        "summary": summary,
        "meta": {
            "engine_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
        },
    }


def to_markdown(report: DoctorReport) -> str:
    if not report.results:
        return "# attest doctor\n\nno checks ran.\n"

    lines = [
        "# attest doctor",
        "",
        "| id | severity | status | message | remedy |",
        "|---|---|---|---|---|",
    ]
    for check, result in report.results:
        remedy = result.remedy or ""
        lines.append(
            f"| {check.id} | {check.severity} | {result.status.value} | "
            f"{result.message} | {remedy} |"
        )
    return "\n".join(lines) + "\n"
