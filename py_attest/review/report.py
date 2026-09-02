"""Render review reports: Markdown (Seed A rendering, unchanged) and JSON (schema v3, TRD §4.3)."""

import hashlib
from datetime import UTC, datetime
from typing import Any

from py_attest import __version__
from py_attest.review.policy import verdict


def render_markdown(source_name: str, review: dict[str, Any]) -> str:
    """Render a report using the deterministic verdict derived from its findings."""
    findings = review["findings"]
    verdict_name, _exit_code = verdict(findings)
    meta = review["meta"]
    provenance = (
        f"Reviewed with prompt {meta['prompt_version']} · {meta['model']} · "
        f"temp {meta['temperature']} · gate {meta['gate_commit']}"
    )
    lines = [f"# AI Quality Review: {source_name}", provenance, ""]
    note = review.get("note")
    if note:
        lines.extend([f"> **{note}**", ""])

    if not findings:
        lines.extend(["> **APPROVED — no findings**", "", "## Summary", "", review["summary"]])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([f"> **VERDICT: {verdict_name}**", ""])
    if any(
        finding["severity"] in {"S1", "S2"} and finding["confidence"] == "low"
        for finding in findings
    ):
        lines.extend(
            [
                "> **HUMAN REVIEW REQUESTED:** Low-confidence S1/S2 finding; merge is not blocked.",
                "",
            ]
        )

    lines.extend(
        [
            "## Findings",
            "",
            "| Severity | Rule | File:line | Title | Confidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for finding in findings:
        location = _finding_location(finding)
        cells = (
            finding["severity"],
            finding["rule_id"],
            location,
            finding["title"],
            finding["confidence"],
        )
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")

    lines.extend(["", "## Details", ""])
    for index, finding in enumerate(findings, start=1):
        location = _finding_location(finding)
        lines.extend(
            [
                f"### {index}. [{finding['severity']}] {finding['title']}",
                "",
                f"- Rule: `{finding['rule_id']}`",
                f"- Location: `{location}`",
                f"- Confidence: {finding['confidence']}",
                f"- Evidence: {_markdown_cell(finding['evidence'])}",
                "",
                finding["explanation"],
                "",
                f"Suggested fix: {finding['suggested_fix']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", review["summary"]])
    return "\n".join(lines).rstrip() + "\n"


def _finding_location(finding: dict[str, Any]) -> str:
    location = str(finding["path"])
    if finding.get("line_start") is not None:
        location += f":{finding['line_start']}"
    return location


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def _fingerprint(finding: dict[str, Any]) -> str:
    identity = "|".join(
        str(finding.get(key)) for key in ("rule_id", "path", "side", "line_start", "title")
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _finding_v3(finding: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_id": finding["rule_id"],
        "severity": finding.get("severity"),
        "requires_human_classification": finding.get("requires_human_classification", False),
        "confidence": finding["confidence"],
        "evidence_verified": finding.get("evidence_verified", False),
        "path": finding["path"],
        "side": finding.get("side"),
        "line_start": finding.get("line_start"),
        "line_end": finding.get("line_end"),
        "title": finding["title"],
        "evidence": finding["evidence"],
        "explanation": finding["explanation"],
        "suggested_fix": finding["suggested_fix"],
        "fingerprint": _fingerprint(finding),
    }


def build_json_report(
    *,
    review: dict[str, Any],
    stage: str,
    layers: dict[str, str],
    egress: dict[str, Any],
    source: dict[str, Any],
    review_complete: bool,
    meta_extra: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the schema_version 3 JSON report (TRD §4.3) from an internal review result."""
    verdict_name, exit_code = verdict(review["findings"], review_complete=review_complete)
    report = {
        "schema_version": 3,
        "verdict": verdict_name,
        "exit_code": exit_code,
        "stage": stage,
        "source": source,
        "review_complete": review_complete,
        "layers": layers,
        "egress": egress,
        "findings": [_finding_v3(finding) for finding in review["findings"]],
        "filtered_out": review.get("filtered_out", []),
        "summary": review.get("summary", ""),
        "meta": {
            "engine_version": __version__,
            "generated_at": datetime.now(UTC).isoformat(),
            **meta_extra,
        },
    }
    if "note" in review:
        report["note"] = review["note"]
    return report
