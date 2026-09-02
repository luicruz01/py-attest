"""Provider-boundary redaction that preserves patch structure (ADR-004 SS2(c), ported from
Seed B's ``quality_gate/redaction.py`` unchanged except for the import path).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----.*?"
    r"(?:-----END (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|\Z)",
    re.DOTALL,
)
_BEARER = re.compile(r"(?i)(\bBearer[ \t]+)[A-Za-z0-9._~+/=-]+")
_KNOWN_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b")
_CLOUD_TOKEN = re.compile(
    r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_DATE = re.compile(r"(?<![A-Za-z0-9-])(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2}(?![A-Za-z0-9-])")
_SECRET_VALUE = re.compile(
    r"(?i)(\b(?:api_?key|access_?token|auth_?token|secret|password)\b\s*[:=]\s*['\"]?)([^'\"\s,}]+)"
)
_PII_VALUE = re.compile(
    r"(?i)(\b(?:full_name|email|birthdate)\b\s*[:=]\s*['\"]?)([^'\"\s\n,}][^'\"\n,}]*)"
)


@dataclass(frozen=True)
class RedactionResult:
    text: str
    counts: dict[str, int]

    @property
    def redacted(self) -> bool:
        return any(self.counts.values())


def redact(text: str) -> RedactionResult:
    counts = {"secret": 0, "pii": 0, "private_key": 0}

    def replace(pattern: re.Pattern[str], value: str, category: str, source: str) -> str:
        def sub(match: re.Match[str]) -> str:
            counts[category] += 1
            if match.lastindex:
                return f"{match.group(1)}{value}"
            return value

        return pattern.sub(sub, source)

    result = replace(_PRIVATE_KEY_BLOCK, "[REDACTED_SECRET]", "private_key", text)
    result = replace(_BEARER, "[REDACTED_SECRET]", "secret", result)
    result = replace(_KNOWN_TOKEN, "[REDACTED_SECRET]", "secret", result)
    result = replace(_CLOUD_TOKEN, "[REDACTED_SECRET]", "secret", result)
    result = replace(_JWT, "[REDACTED_SECRET]", "secret", result)
    result = replace(_SECRET_VALUE, "[REDACTED_SECRET]", "secret", result)
    result = replace(_PII_VALUE, "[REDACTED_PII]", "pii", result)
    result = replace(_EMAIL, "[REDACTED_PII]", "pii", result)
    result = replace(_DATE, "[REDACTED_PII]", "pii", result)
    return RedactionResult(result, counts)


def contains_sensitive_text(text: str) -> bool:
    text = text.replace("[REDACTED_SECRET]", "").replace("[REDACTED_PII]", "")
    return any(
        pattern.search(text)
        for pattern in (
            _EMAIL,
            _PRIVATE_KEY_BLOCK,
            _BEARER,
            _KNOWN_TOKEN,
            _CLOUD_TOKEN,
            _JWT,
            _DATE,
            _SECRET_VALUE,
            _PII_VALUE,
        )
    )
