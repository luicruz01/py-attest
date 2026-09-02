"""High-precision, code-only checks that run before the secrets firewall and before any
provider call (ADR-004 SS2(d)/TRD SS5 row 2, ported from Seed B's
``quality_gate/deterministic.py``).

Findings are ground truth, not model output, and are built directly in the canonical
shape (review/report.py's ``_finding_v3`` passes them through unchanged) rather than
going through review/validation.py: that module validates *untrusted* LLM output and
rejects any rule_id whose registry ``mode`` isn't "llm" -- a deterministic finding would
be discarded there. ``confidence`` is always "high", ``evidence_verified`` is always
True, ``requires_human_classification`` is always False, and ``severity`` is resolved
from the standards registry (``registry.fixed_severity(rule_id)``), never a local
constant, per ADR-001.

The secrets-in-added-lines detector below cites rule_id ``secrets-1`` -- the same id
gitleaks (secrets_gate.py) cites -- since both are the same violation type, just
different detection mechanisms; review/reviewer.py's ``merge_findings`` call collapses a
duplicate hit from both into one finding when they land on the same location.

A COMMITTED_SECRET-shaped finding here does NOT by itself skip the gitleaks firewall
step that runs next -- CLAUDE.md is explicit that gitleaks "runs before any LLM call"
and a missing binary is "never a silent skip", so it always runs regardless of what this
layer already found.
"""

from __future__ import annotations

import re
from typing import Any

from py_attest.review.diff import ChangedFile
from py_attest.standards.registry import Registry

_TODO = re.compile(r"\bTODO\b", re.IGNORECASE)
_TICKET = re.compile(r"(?:https?://\S+|#\d+\b|\b[A-Z][A-Z0-9]+-\d+\b)")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
_BEARER = re.compile(r"\bAuthorization\b\s*[:=]\s*['\"]?Bearer\s+\S+", re.IGNORECASE)
_KNOWN_TOKEN = re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b")
_CLOUD_TOKEN = re.compile(
    r"\b(?:AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,})\b"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_SENSITIVE_ASSIGNMENT = re.compile(
    r"\b(?:api_?key|access_?token|auth_?token|secret|password)\b\s*[:=]\s*['\"][^'\"\s]{8,}['\"]",
    re.IGNORECASE,
)

_SECRETS_RULE_ID = "secrets-1"
_TODO_RULE_ID = "code-quality-5"


def _finding(
    registry: Registry,
    rule_id: str,
    path: str,
    line: int,
    title: str,
    evidence: str,
    explanation: str,
    fix: str,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "path": path,
        "side": "new",
        "line_start": line,
        "line_end": line,
        "title": title,
        "evidence": evidence,
        "explanation": explanation,
        "suggested_fix": fix,
        "confidence": "high",
        "severity": registry.fixed_severity(rule_id),
        "requires_human_classification": False,
        "evidence_verified": True,
    }


def run_checks(files: tuple[ChangedFile, ...], registry: Registry) -> tuple[dict[str, Any], ...]:
    findings: list[dict[str, Any]] = []
    for changed in files:
        for added in changed.added_lines:
            content = added.content
            if any(
                pattern.search(content)
                for pattern in (
                    _PRIVATE_KEY,
                    _BEARER,
                    _KNOWN_TOKEN,
                    _CLOUD_TOKEN,
                    _JWT,
                    _SENSITIVE_ASSIGNMENT,
                )
            ):
                findings.append(
                    _finding(
                        registry,
                        _SECRETS_RULE_ID,
                        changed.path,
                        added.number,
                        "Credential material committed",
                        "Added line contains [REDACTED_SECRET].",
                        "Committed credentials are a security incident.",
                        "Remove and rotate the credential; load secrets from environment "
                        "variables. Gitleaks runs as an additional, independent control.",
                    )
                )
            if _TODO.search(content) and not _TICKET.search(content):
                findings.append(
                    _finding(
                        registry,
                        _TODO_RULE_ID,
                        changed.path,
                        added.number,
                        "TODO has no ticket reference",
                        "Added TODO lacks an issue URL, #number, or ticket key.",
                        "Untracked follow-up work can become permanent dead code.",
                        "Link the TODO to a tracked issue or remove it.",
                    )
                )
    return tuple(findings)
