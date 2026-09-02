import copy

import pytest

from tools.quality_gate.schema import SchemaValidationError, validate_review_result


def valid_review() -> dict:
    return {
        "findings": [
            {
                "rule": "3-PII-logging",
                "severity": "S1",
                "file": "app/main.py",
                "line": 42,
                "title": "PII is logged",
                "evidence": 'logger.info("%s", student.email)',
                "explanation": "The changed line logs an email address.",
                "suggested_fix": "Pass the payload through redact().",
                "confidence": "high",
            }
        ],
        "summary": "One standards violation found.",
    }


def test_valid_example_passes() -> None:
    review = valid_review()

    assert validate_review_result(review) is review


@pytest.mark.parametrize("mutation", ["severity", "verdict"])
def test_invalid_severity_and_verdict_smuggling_fail(mutation: str) -> None:
    review = copy.deepcopy(valid_review())
    if mutation == "severity":
        review["findings"][0]["severity"] = "critical"
    else:
        review["verdict"] = "block"

    with pytest.raises(SchemaValidationError):
        validate_review_result(review)


def test_evidence_is_required_for_every_finding() -> None:
    review = valid_review()
    del review["findings"][0]["evidence"]

    with pytest.raises(SchemaValidationError):
        validate_review_result(review)
