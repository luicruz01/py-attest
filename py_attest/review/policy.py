"""Deterministic trust-policy verdicts for reviewed findings."""

from collections.abc import Iterable, Mapping
from typing import Literal

Verdict = Literal["APPROVE", "COMMENT", "BLOCK"]
VerdictResult = tuple[Verdict, int]

APPROVE_RESULT: VerdictResult = ("APPROVE", 0)

# Trust Policy v1. This table is the tunable policy surface for the eval phase.
TRUST_POLICY_V1: dict[tuple[str, str], VerdictResult] = {
    ("S1", "high"): ("BLOCK", 2),
    ("S1", "medium"): ("BLOCK", 2),
    ("S1", "low"): ("COMMENT", 0),
    ("S2", "high"): ("BLOCK", 2),
    ("S2", "medium"): ("BLOCK", 2),
    ("S2", "low"): ("COMMENT", 0),
    ("S3", "high"): ("COMMENT", 0),
    ("S3", "medium"): ("COMMENT", 0),
    ("S3", "low"): ("COMMENT", 0),
}


def verdict(findings: Iterable[Mapping[str, object]]) -> VerdictResult:
    """Return the strongest policy outcome for validated, post-filtered findings."""
    outcomes = (
        TRUST_POLICY_V1[(str(finding["severity"]), str(finding["confidence"]))]
        for finding in findings
    )
    return max(outcomes, key=lambda outcome: outcome[1], default=APPROVE_RESULT)
