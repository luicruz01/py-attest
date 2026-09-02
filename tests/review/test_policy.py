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
