"""Provider contract (ADR-002): request/response shape, usage, and error taxonomy.

Field names and dataclass shape follow ADR-002's decision text (system_prompt,
user_content, output_schema, model, temperature / raw_json, temperature_applied, usage,
attempts) -- the generic "send a prompt, get back schema-validated JSON" contract that
`review/reviewer.py` already assembles today via context_pack + REVIEW_SCHEMA. Class
naming (ProviderRequest/ProviderResponse, ProviderFailure(category)) and the invariant
that a provider's raw SDK response object never crosses this boundary are rescued from
Seed B (ADR-004 SS2(b)).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

FAILURE_CATEGORIES = frozenset(
    {
        # ProviderNotConfigured: missing key, extra not installed, unknown provider
        "not_configured",
        # ProviderTransient: 429, 5xx, network timeout -- retried by llm/policy.py
        "transient",
        # ProviderRejected: non-transient 4xx (bad request, unknown model)
        "rejected",
        # StructuredOutputInvalid: raw_json doesn't parse or doesn't match the schema
        "invalid_structured_output",
    }
)


class ProviderFailure(RuntimeError):
    """A sanitized provider failure, safe to include in reports.

    Implements ADR-002's four-exception taxonomy (ProviderNotConfigured/
    ProviderTransient/ProviderRejected/StructuredOutputInvalid) as one exception class
    discriminated by ``category``, so the engine's retry policy can dispatch on a single
    attribute instead of an isinstance() chain.
    """

    def __init__(self, category: str, message: str) -> None:
        if category not in FAILURE_CATEGORIES:
            raise ValueError(f"unknown ProviderFailure category: {category!r}")
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class Usage:
    """Token accounting for the report's ``meta.usage`` block (TRD SS4.3)."""

    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    reasoning_tokens: int


@dataclass(frozen=True)
class ProviderRequest:
    system_prompt: str
    user_content: (
        str  # egress payload (raw context pack or MINIMIZED_PATCH_V2), never the raw patch
    )
    output_schema: dict[str, Any]
    model: str
    temperature: float | None = None  # None = model-default


@dataclass(frozen=True)
class ProviderResponse:
    """Structured provider output; the provider's raw SDK response never crosses this boundary."""

    raw_json: str  # exactly what the model returned, untouched
    model: str  # model effectively used (a provider may resolve aliases)
    temperature_applied: str  # "0" | "model-default" -- stamped on the artifact
    usage: Usage | None
    attempts: int | None = None  # stamped by llm/policy.py after the retry loop completes


class Provider(Protocol):
    name: str

    def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
        """Return schema-validated output and safe provenance. Never raises a raw SDK exception."""
        ...
