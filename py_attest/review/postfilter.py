"""Deduplicate findings after they've been validated (review/validation.py)."""

import shlex
from collections.abc import Mapping
from typing import Any

CONFIDENCE_LEVELS = ("high", "medium", "low")
_SEVERITIES = ("S1", "S2", "S3")
_SEVERITY_STRENGTH = {
    severity: len(_SEVERITIES) - index for index, severity in enumerate(_SEVERITIES)
}
_CONFIDENCE_STRENGTH = {
    confidence: len(CONFIDENCE_LEVELS) - index for index, confidence in enumerate(CONFIDENCE_LEVELS)
}


def files_in_diff(diff: str) -> set[str]:
    """Extract old and new repository-relative paths from unified diff headers."""
    files: set[str] = set()
    lines = diff.splitlines()
    for index, line in enumerate(lines):
        if not line.startswith("diff --git "):
            if line.startswith("--- ") and index + 1 < len(lines):
                next_line = lines[index + 1]
                if next_line.startswith("+++ "):
                    files.update(_header_paths(line[4:], next_line[4:]))
            continue
        try:
            parts = shlex.split(line)
        except ValueError:
            continue
        if len(parts) < 4:
            continue
        for path in parts[2:4]:
            normalized = _normalize_path(path)
            if normalized is not None:
                files.add(normalized)
    return files


def _header_paths(old_header: str, new_header: str) -> set[str]:
    paths: set[str] = set()
    for header in (old_header, new_header):
        path = header.split("\t", maxsplit=1)[0]
        normalized = _normalize_path(path)
        if normalized is not None:
            paths.add(normalized)
    return paths


def _normalize_path(path: str) -> str | None:
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def merge_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedup by (rule_id, path, side, line_start, line_end); on a tie, first-seen wins.

    Callers that need "deterministic findings always beat an LLM duplicate" (review/
    deterministic.py, once F0.3 wires it in per spec §5.3) get that behavior for free
    by placing deterministic findings first in the input list.
    """
    kept: list[dict[str, Any]] = []
    seen: dict[tuple[object, ...], int] = {}

    for finding in findings:
        identity = (
            finding.get("rule_id"),
            finding.get("path"),
            finding.get("side"),
            finding.get("line_start"),
            finding.get("line_end"),
        )
        if identity in seen:
            kept_index = seen[identity]
            if _strength(finding) > _strength(kept[kept_index]):
                kept[kept_index] = finding
            continue
        seen[identity] = len(kept)
        kept.append(finding)

    return kept


def _strength(finding: Mapping[str, Any]) -> tuple[int, int]:
    return (
        _SEVERITY_STRENGTH.get(finding.get("severity"), -1),
        _CONFIDENCE_STRENGTH.get(finding.get("confidence"), -1),
    )
