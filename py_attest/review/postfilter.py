"""Deterministic filtering for model-generated findings."""

import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from py_attest.review.models import CONFIDENCE_LEVELS, SEVERITIES

_SEVERITY_STRENGTH = {
    severity: len(SEVERITIES) - index for index, severity in enumerate(SEVERITIES)
}
_CONFIDENCE_STRENGTH = {
    confidence: len(CONFIDENCE_LEVELS) - index for index, confidence in enumerate(CONFIDENCE_LEVELS)
}
_HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_EVIDENCE_SEPARATOR = re.compile(r"\.\.\.|\r?\n")
_MIN_EVIDENCE_FRAGMENT_LENGTH = 8


@dataclass(frozen=True)
class _AddedLine:
    file: str
    line: int
    text: str


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


def _added_lines(diff: str) -> list[_AddedLine]:
    added: list[_AddedLine] = []
    new_file: str | None = None
    new_line: int | None = None

    for text in diff.splitlines():
        if text.startswith("diff --git "):
            new_file = None
            new_line = None
            continue
        if text.startswith("+++ "):
            header = text[4:].split("\t", maxsplit=1)[0]
            new_file = _normalize_path(header)
            continue
        match = _HUNK_HEADER.match(text)
        if match:
            new_line = int(match.group(1))
            continue
        if new_file is None or new_line is None:
            continue
        if text.startswith("+"):
            added.append(_AddedLine(new_file, new_line, text[1:]))
            new_line += 1
        elif text.startswith("-"):
            continue
        elif not text.startswith("\\"):
            new_line += 1

    return added


def filter_findings(review: Mapping[str, Any], diff: str) -> dict[str, Any]:
    """Drop structural failures, degrade unverified evidence, and merge duplicates."""
    diff_files = files_in_diff(diff)
    added_lines = _added_lines(diff)
    kept: list[dict[str, Any]] = []
    filtered_out: list[dict[str, Any]] = []
    seen: dict[tuple[object, ...], int] = {}

    for finding_value in review.get("findings", []):
        finding = dict(finding_value)
        file_name = finding.get("file")
        was_file_level = finding.get("line") is None
        if file_name not in diff_files:
            filtered_out.append({"finding": finding, "reason": "file_not_in_diff"})
            continue
        if finding.get("severity") not in SEVERITIES:
            filtered_out.append({"finding": finding, "reason": "invalid_severity"})
            continue
        evidence_line = _evidence_line(finding, added_lines)
        if evidence_line is None:
            evidence_line = _trusted_short_evidence_line(finding, added_lines)
        finding["evidence_verified"] = evidence_line is not None
        if evidence_line is None:
            finding["confidence"] = "low"
        elif finding.get("line") != evidence_line:
            finding["line"] = evidence_line
            finding["re_anchored"] = True
        line = finding.get("line")
        identity = (file_name, line, finding.get("rule"))
        if was_file_level:
            identity += (finding.get("title"),)
        if identity in seen:
            kept_index = seen[identity]
            previous = kept[kept_index]
            if _strength(finding) > _strength(previous):
                kept[kept_index] = finding
                merged_away = previous
            else:
                merged_away = finding
            filtered_out.append({"finding": merged_away, "reason": "merged_duplicate"})
            continue
        seen[identity] = len(kept)
        kept.append(finding)

    filtered_review = {
        "findings": kept,
        "summary": review.get("summary", ""),
        "filtered_out": filtered_out,
    }
    if "metadata" in review:
        filtered_review["metadata"] = review["metadata"]
    return filtered_review


def _evidence_line(
    finding: Mapping[str, Any],
    added_lines: list[_AddedLine],
) -> int | None:
    evidence = finding.get("evidence")
    if not isinstance(evidence, str):
        return None
    fragments = [
        normalized
        for fragment in _EVIDENCE_SEPARATOR.split(evidence)
        if len(normalized := _normalize_whitespace(fragment)) >= _MIN_EVIDENCE_FRAGMENT_LENGTH
    ]
    if not fragments:
        return None

    fragment_matches: list[list[_AddedLine]] = []
    for fragment in fragments:
        matches = [
            added_line
            for added_line in added_lines
            if fragment in _normalize_whitespace(added_line.text)
        ]
        if not matches:
            return None
        fragment_matches.append(matches)

    claimed_line = finding.get("line")
    finding_file = finding.get("file")
    first_matches = fragment_matches[0]
    if any(match.file == finding_file and match.line == claimed_line for match in first_matches):
        return claimed_line
    same_file_match = next((match for match in first_matches if match.file == finding_file), None)
    return (same_file_match or first_matches[0]).line


def _trusted_short_evidence_line(
    finding: Mapping[str, Any],
    added_lines: list[_AddedLine],
) -> int | None:
    """Preserve deterministic secret findings whose redacted anchor must be short."""
    if finding.get("rule") != "5-secrets":
        return None
    evidence = finding.get("evidence")
    if not isinstance(evidence, str):
        return None
    normalized_evidence = _normalize_whitespace(evidence)
    if not normalized_evidence:
        return None
    matches = [
        added_line
        for added_line in added_lines
        if added_line.file == finding.get("file")
        and normalized_evidence in _normalize_whitespace(added_line.text)
    ]
    claimed_line = finding.get("line")
    if any(match.line == claimed_line for match in matches):
        return claimed_line
    return matches[0].line if matches else None


def _normalize_whitespace(value: str) -> str:
    return " ".join(value.split())


def _strength(finding: Mapping[str, Any]) -> tuple[int, int]:
    return (
        _SEVERITY_STRENGTH.get(finding.get("severity"), -1),
        _CONFIDENCE_STRENGTH.get(finding.get("confidence"), -1),
    )
