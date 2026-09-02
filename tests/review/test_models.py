import copy

import pytest

from py_attest.review.models import SchemaValidationError, validate_review_result


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


def test_review_result_must_be_an_object() -> None:
    with pytest.raises(SchemaValidationError, match="must be an object"):
        validate_review_result(["not", "a", "dict"])


def test_summary_must_be_a_string() -> None:
    review = valid_review()
    review["summary"] = 123

    with pytest.raises(SchemaValidationError, match="summary must be a string"):
        validate_review_result(review)


def test_findings_must_be_an_array() -> None:
    review = valid_review()
    review["findings"] = "not-a-list"

    with pytest.raises(SchemaValidationError, match="findings must be an array"):
        validate_review_result(review)


def test_each_finding_must_be_an_object() -> None:
    review = valid_review()
    review["findings"] = ["not-a-dict"]

    with pytest.raises(SchemaValidationError, match="must be an object"):
        validate_review_result(review)


def test_finding_text_fields_must_be_strings() -> None:
    review = valid_review()
    review["findings"][0]["title"] = 123

    with pytest.raises(SchemaValidationError, match="non-string text field"):
        validate_review_result(review)


def test_finding_confidence_must_be_valid() -> None:
    review = valid_review()
    review["findings"][0]["confidence"] = "certain"

    with pytest.raises(SchemaValidationError, match="invalid confidence"):
        validate_review_result(review)


def test_finding_line_must_be_an_integer_or_null() -> None:
    review = valid_review()
    review["findings"][0]["line"] = "42"

    with pytest.raises(SchemaValidationError, match="line must be an integer or null"):
        validate_review_result(review)


def test_finding_line_may_be_null() -> None:
    review = valid_review()
    review["findings"][0]["line"] = None

    assert validate_review_result(review) is review
