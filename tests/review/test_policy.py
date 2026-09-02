import pytest

from py_attest.review.policy import TRUST_POLICY_V1, verdict


@pytest.mark.parametrize(
    ("severity", "confidence", "expected"),
    [
        pytest.param(severity, confidence, expected, id=f"{severity}-{confidence}-{expected[0]}")
        for (severity, confidence), expected in TRUST_POLICY_V1.items()
    ],
)
def test_trust_policy_table_drives_each_finding_outcome(
    severity: str, confidence: str, expected: tuple[str, int]
) -> None:
    findings = [{"severity": severity, "confidence": confidence}]

    assert verdict(findings) == expected


def test_zero_findings_approves() -> None:
    assert verdict([]) == ("APPROVE", 0)


def test_any_blocking_finding_dominates_comments() -> None:
    findings = [
        {"severity": "S3", "confidence": "high"},
        {"severity": "S1", "confidence": "low"},
        {"severity": "S2", "confidence": "medium"},
    ]

    assert verdict(findings) == ("BLOCK", 2)


def test_review_incomplete_without_a_blocking_finding_is_inconclusive() -> None:
    findings = [{"severity": "S3", "confidence": "high"}]

    assert verdict(findings, review_complete=False) == ("INCONCLUSIVE", 4)


def test_review_incomplete_with_no_findings_is_inconclusive() -> None:
    assert verdict([], review_complete=False) == ("INCONCLUSIVE", 4)


def test_a_trusted_blocking_finding_wins_over_an_incomplete_review() -> None:
    findings = [{"severity": "S1", "confidence": "high"}]

    assert verdict(findings, review_complete=False) == ("BLOCK", 2)


def test_contextual_finding_is_always_comment_never_block() -> None:
    findings = [{"requires_human_classification": True}]

    assert verdict(findings) == ("COMMENT", 0)


def test_contextual_finding_does_not_suppress_a_real_blocking_finding() -> None:
    findings = [
        {"requires_human_classification": True},
        {"severity": "S1", "confidence": "high"},
    ]

    assert verdict(findings) == ("BLOCK", 2)
