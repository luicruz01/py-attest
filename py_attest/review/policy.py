"""Deterministic trust-policy verdicts for reviewed findings."""

from collections.abc import Iterable, Mapping
from typing import Literal

Verdict = Literal["APPROVE", "COMMENT", "BLOCK", "INCONCLUSIVE"]
VerdictResult = tuple[Verdict, int]

APPROVE_RESULT: VerdictResult = ("APPROVE", 0)
INCONCLUSIVE_RESULT: VerdictResult = ("INCONCLUSIVE", 4)

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


def verdict(
    findings: Iterable[Mapping[str, object]], review_complete: bool = True
) -> VerdictResult:
    """Return the strongest policy outcome for validated, post-filtered findings.

    Contract this relies on (review/validation.py): whenever a caller passes
    review_complete=False, `findings` must contain zero untrusted (LLM-origin)
    findings -- fail_closed empties the LLM contribution entirely when it invalidates
    a response, so a BLOCK reaching this function alongside review_complete=False can
    only be deterministic-origin (secrets_gate.py / review/deterministic.py), never an
    untrusted model claim. That is what makes "BLOCK wins over INCONCLUSIVE" safe
    without this function needing a provenance field on findings.
    """
    outcomes = (
        ("COMMENT", 0)
        if finding.get("requires_human_classification")
        else TRUST_POLICY_V1[(str(finding["severity"]), str(finding["confidence"]))]
        for finding in findings
    )
    best = max(outcomes, key=lambda outcome: outcome[1], default=APPROVE_RESULT)
    if best[0] == "BLOCK":
        return best
    if not review_complete:
        return INCONCLUSIVE_RESULT
    return best
