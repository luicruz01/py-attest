"""Ported from Seed B's tests/quality_gate/test_controls.py (redaction.py cases)."""

from py_attest.review.redaction import contains_sensitive_text, redact


def test_redacts_secret_pii_email_bearer_and_private_key() -> None:
    token = "g" + "hp_" + "a" * 24
    private = "-----BEGIN " + "PRIVATE KEY-----\nsynthetic\n-----END " + "PRIVATE KEY-----"
    source = "\n".join(
        [
            "Authorization: Bearer " + "b" * 20,
            "api_key='" + token + "'",
            "full_name='Example Student'",
            "contact=student@example.test",
            private,
        ]
    )

    result = redact(source)

    assert result.redacted is True
    assert token not in result.text
    assert "Example Student" not in result.text
    assert "student@example.test" not in result.text
    assert "synthetic" not in result.text
    assert contains_sensitive_text(result.text) is False


def test_unclosed_private_key_is_redacted_through_end_of_input() -> None:
    result = redact("prefix\n-----BEGIN " + "PRIVATE KEY-----\nprivate material")

    assert "private material" not in result.text
    assert result.counts["private_key"] == 1
