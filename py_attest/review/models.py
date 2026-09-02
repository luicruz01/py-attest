"""Structured output schema and validation for LLM review results."""

from typing import Any

CONFIDENCE_LEVELS = ("high", "medium", "low")
SIDES = ("old", "new")

FINDING_PROPERTIES: dict[str, Any] = {
    "rule_id": {"type": "string"},
    "path": {"type": "string"},
    "side": {"type": "string", "enum": list(SIDES)},
    "line_start": {"type": "integer"},
    "line_end": {"type": "integer"},
    "title": {"type": "string"},
    "evidence": {"type": "string"},
    "explanation": {"type": "string"},
    "suggested_fix": {"type": "string"},
    "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": FINDING_PROPERTIES,
                "required": list(FINDING_PROPERTIES),
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["findings", "summary"],
    "additionalProperties": False,
}


class SchemaValidationError(ValueError):
    """Raised when a review result does not match ``REVIEW_SCHEMA``."""


def validate_review_result(value: object) -> dict[str, Any]:
    """Validate a decoded model response without adding a runtime dependency."""
    if not isinstance(value, dict):
        raise SchemaValidationError("review result must be an object")
    if set(value) != {"findings", "summary"}:
        raise SchemaValidationError("review result must contain only findings and summary")
    if not isinstance(value["summary"], str):
        raise SchemaValidationError("summary must be a string")
    if not isinstance(value["findings"], list):
        raise SchemaValidationError("findings must be an array")

    required = set(FINDING_PROPERTIES)
    for index, finding in enumerate(value["findings"]):
        if not isinstance(finding, dict):
            raise SchemaValidationError(f"finding {index} must be an object")
        if set(finding) != required:
            raise SchemaValidationError(f"finding {index} has missing or unexpected fields")
        _validate_finding(finding, index)
    return value


def _validate_finding(finding: dict[str, Any], index: int) -> None:
    string_fields = {
        "rule_id",
        "path",
        "side",
        "title",
        "evidence",
        "explanation",
        "suggested_fix",
        "confidence",
    }
    if any(not isinstance(finding[field], str) for field in string_fields):
        raise SchemaValidationError(f"finding {index} contains a non-string text field")
    if finding["side"] not in SIDES:
        raise SchemaValidationError(f"finding {index} has an invalid side")
    if finding["confidence"] not in CONFIDENCE_LEVELS:
        raise SchemaValidationError(f"finding {index} has an invalid confidence")
    for bound in ("line_start", "line_end"):
        value = finding[bound]
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise SchemaValidationError(f"finding {index} {bound} must be a positive integer")
    if finding["line_end"] < finding["line_start"]:
        raise SchemaValidationError(f"finding {index} line_end must be >= line_start")
