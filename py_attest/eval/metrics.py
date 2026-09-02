"""Measure reviewer verdicts and findings against the golden set (F0.5).

Matching follows Seed B's SCORING-POLICY.md "One-to-one finding matching": same
rule_id, same path, overlapping [line_start, line_end] range. No finding text
(title/evidence/explanation) affects matching -- only rule_id/path/line identify a
finding, matching the schema_version 3 report shape (TRD SS4.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EvaluationError(ValueError):
    """Raised when evaluation inputs do not have the expected structure."""


@dataclass(frozen=True)
class FindingRecord:
    """A finding together with its source branch."""

    branch: str
    finding: dict[str, Any]


@dataclass(frozen=True)
class FindingMatch:
    """A one-to-one match between a golden and predicted finding."""

    expected: FindingRecord
    predicted: FindingRecord


@dataclass
class FindingResults:
    """Finding-level results for one reading (strict / adjudicated / severity_exact)."""

    true_positives: list[Any] = field(default_factory=list)
    false_positives: list[Any] = field(default_factory=list)
    false_negatives: list[Any] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denominator = len(self.true_positives) + len(self.false_positives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def recall(self) -> float:
        denominator = len(self.true_positives) + len(self.false_negatives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def f1(self) -> float:
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)


def _ranges_overlap(a_start: int, a_end: int, b_start: int | None, b_end: int | None) -> bool:
    if b_start is None or b_end is None:
        return False
    return a_start <= b_end and b_start <= a_end


def findings_match(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    """Match findings by exact rule_id, exact path, and overlapping line range."""
    return (
        expected.get("rule_id") is not None
        and expected.get("rule_id") == predicted.get("rule_id")
        and expected.get("path") == predicted.get("path")
        and _ranges_overlap(
            expected["line_start"],
            expected["line_end"],
            predicted.get("line_start"),
            predicted.get("line_end"),
        )
    )


def match_findings(
    branch: str,
    expected: list[dict[str, Any]],
    predicted: list[dict[str, Any]],
) -> FindingResults:
    """Perform deterministic one-to-one finding matching for one branch (the `strict`
    reading). llm_reachable: false findings are excluded entirely -- they sit behind the
    secrets firewall and no LLM-graded reviewer can be scored on them (TRD SS9)."""
    reachable = [finding for finding in expected if finding.get("llm_reachable", True)]
    remaining_predictions = list(predicted)
    true_positives: list[FindingMatch] = []
    false_negatives: list[FindingRecord] = []

    for expected_finding in reachable:
        match_index = _first_match(expected_finding, remaining_predictions)
        expected_record = FindingRecord(branch, expected_finding)
        if match_index is None:
            false_negatives.append(expected_record)
            continue
        predicted_finding = remaining_predictions.pop(match_index)
        true_positives.append(
            FindingMatch(expected_record, FindingRecord(branch, predicted_finding))
        )

    return FindingResults(
        true_positives=true_positives,
        false_positives=[FindingRecord(branch, finding) for finding in remaining_predictions],
        false_negatives=false_negatives,
    )


def _first_match(expected: dict[str, Any], predicted: list[dict[str, Any]]) -> int | None:
    return next(
        (
            index
            for index, predicted_finding in enumerate(predicted)
            if findings_match(expected, predicted_finding)
        ),
        None,
    )


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
