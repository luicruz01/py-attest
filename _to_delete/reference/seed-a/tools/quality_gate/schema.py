"""Structured output schema and validation for LLM review results."""

from typing import Any

SEVERITIES = ("S1", "S2", "S3")
CONFIDENCE_LEVELS = ("high", "medium", "low")

FINDING_PROPERTIES: dict[str, Any] = {
    "rule": {"type": "string"},
    "severity": {"type": "string", "enum": list(SEVERITIES)},
    "file": {"type": "string"},
    "line": {"type": ["integer", "null"]},
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
        "rule",
        "severity",
        "file",
        "title",
        "evidence",
        "explanation",
        "suggested_fix",
        "confidence",
    }
    if any(not isinstance(finding[field], str) for field in string_fields):
        raise SchemaValidationError(f"finding {index} contains a non-string text field")
    if finding["severity"] not in SEVERITIES:
        raise SchemaValidationError(f"finding {index} has an invalid severity")
    if finding["confidence"] not in CONFIDENCE_LEVELS:
        raise SchemaValidationError(f"finding {index} has an invalid confidence")
    line = finding["line"]
    if line is not None and (not isinstance(line, int) or isinstance(line, bool)):
        raise SchemaValidationError(f"finding {index} line must be an integer or null")
