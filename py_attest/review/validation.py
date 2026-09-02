"""Resolve LLM findings against the standards Registry: rule_id membership, severity
resolution, and the range-in-changed-lines-by-side check that replaces postfilter.py's
prose-evidence re-anchoring for LLM-origin findings.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, NamedTuple

from py_attest.standards.registry import Registry

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


class ValidationResult(NamedTuple):
    findings: list[dict[str, Any]]
    filtered_out: list[dict[str, Any]]
    review_complete: bool
    invalid_count: int = 0
    total_count: int = 0
    invalidated_reasons: frozenset[str] = frozenset()


def _normalize_path(header: str) -> str | None:
    path = header.split("\t", maxsplit=1)[0]
    if path == "/dev/null":
        return None
    if path.startswith(("a/", "b/")):
        return path[2:]
    return path


def changed_line_index(diff: str) -> dict[str, dict[str, set[int]]]:
    """Map each side ("old"/"new") to {path: {changed line numbers}}.

    Hunk-count-aware: `--- `/`+++ ` are only recognized as file-header lines when no
    hunk is currently active. A hunk body line can legitimately start with `--- ` or
    `+++ ` -- e.g. a removed line whose own content starts with `-- ` becomes, once
    diff-prefixed, `--- <that content>` -- and must be classified by its leading
    `+`/`-`/` ` diff marker like any other body line, never by prefix-matching against
    header syntax regardless of position.
    """
    index: dict[str, dict[str, set[int]]] = {"old": {}, "new": {}}
    old_file: str | None = None
    new_file: str | None = None
    old_line: int | None = None
    new_line: int | None = None
    old_remaining = 0
    new_remaining = 0

    for text in diff.splitlines():
        in_hunk = old_remaining > 0 or new_remaining > 0
        if text.startswith("diff --git "):
            old_file = new_file = old_line = new_line = None
            old_remaining = new_remaining = 0
            continue
        if not in_hunk and text.startswith("--- "):
            old_file = _normalize_path(text[4:])
            continue
        if not in_hunk and text.startswith("+++ "):
            new_file = _normalize_path(text[4:])
            continue
        match = _HUNK_HEADER.match(text)
        if match:
            old_start, old_count, new_start, new_count = match.groups()
            old_line, new_line = int(old_start), int(new_start)
            old_remaining = int(old_count) if old_count is not None else 1
            new_remaining = int(new_count) if new_count is not None else 1
            continue
        if old_line is None or new_line is None:
            continue
        if text.startswith("+"):
            if new_file is not None:
                index["new"].setdefault(new_file, set()).add(new_line)
            new_line += 1
            new_remaining = max(new_remaining - 1, 0)
        elif text.startswith("-"):
            if old_file is not None:
                index["old"].setdefault(old_file, set()).add(old_line)
            old_line += 1
            old_remaining = max(old_remaining - 1, 0)
        elif not text.startswith("\\"):
            old_line += 1
            new_line += 1
            old_remaining = max(old_remaining - 1, 0)
            new_remaining = max(new_remaining - 1, 0)
    return index


def _invalid_reason(
    raw: Mapping[str, Any], registry: Registry, line_index: dict[str, dict[str, set[int]]]
) -> str | None:
    rule_id = raw["rule_id"]
    # Citable rule_ids are exactly what render_rules_block(registry.llm_rules()) put in
    # the model's <review-rules> context -- mode == "llm" only. A deterministic-mode
    # rule_id (e.g. secrets-1, code-quality-1/2/5, testing-1) is a real registry member
    # but was never shown to the model, so a finding citing one is just as unverifiable
    # as an id the model invented outright; both are "not a citable rule" from here.
    if rule_id not in registry or registry.rule(rule_id).mode != "llm":
        return "unknown_rule_id"
    changed = line_index.get(raw["side"], {}).get(raw["path"], set())
    declared = set(range(raw["line_start"], raw["line_end"] + 1))
    if not declared <= changed:
        return "range_not_in_changed_lines"
    return None


def _resolve(raw: Mapping[str, Any], registry: Registry) -> dict[str, Any]:
    rule_id = raw["rule_id"]
    contextual = registry.is_contextual(rule_id)
    return {
        **raw,
        "severity": None if contextual else registry.fixed_severity(rule_id),
        "requires_human_classification": contextual,
        # `evidence_verified` here certifies only that the finding's *location*
        # (rule_id is llm-citable, and its line range sits inside the changed lines for
        # its declared side) was verified -- NOT that the quoted `evidence` text was
        # located in the diff. The old evidence-fragment re-anchoring mechanism this
        # field name comes from (postfilter.py, removed in Task 9) is gone; nothing
        # here compares `evidence` against the diff's content at all.
        "evidence_verified": True,
    }


def validate_findings(
    findings: list[dict[str, Any]],
    *,
    registry: Registry,
    diff: str,
    evidence_policy: str,
) -> ValidationResult:
    line_index = changed_line_index(diff)
    kept: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []

    for raw in findings:
        reason = _invalid_reason(raw, registry, line_index)
        if reason is None:
            kept.append(_resolve(raw, registry))
        else:
            invalid.append({"finding": dict(raw), "reason": reason})

    if not invalid:
        return ValidationResult(findings=kept, filtered_out=[], review_complete=True)

    if evidence_policy == "fail_closed":
        return ValidationResult(
            findings=[],
            filtered_out=[],
            review_complete=False,
            invalid_count=len(invalid),
            total_count=len(findings),
            invalidated_reasons=frozenset(item["reason"] for item in invalid),
        )

    return ValidationResult(findings=kept, filtered_out=invalid, review_complete=True)
