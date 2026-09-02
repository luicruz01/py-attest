"""Anthropic provider (ADR-002): structured output via a forced `tool_use`, whose
`input_schema` is the requested output schema -- Anthropic's canonical mechanism for
"return JSON matching this shape" (there is no `response_format`/json_schema mode).
No internal retries: SDK retries are disabled (`max_retries=0`) so `llm/policy.py` owns
the attempt count.
"""

from __future__ import annotations

import json
import os
from typing import Any

from anthropic import (
    Anthropic,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
)

from py_attest.llm.types import ProviderFailure, ProviderRequest, ProviderResponse, Usage

_TOOL_NAME = "quality_gate_review"
_DEFAULT_MAX_TOKENS = 4096


def _classify(exc: Exception) -> str:
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "not_configured"
    if isinstance(exc, (RateLimitError, APITimeoutError, APIConnectionError, OverloadedError)):
        return "transient"
    if isinstance(exc, APIStatusError) and 500 <= exc.status_code < 600:
        return "transient"
    return "rejected"


def _map_exception(exc: Exception) -> ProviderFailure:
    return ProviderFailure(_classify(exc), f"Anthropic request failed: {exc}")


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
        client: Anthropic | None = None,
    ) -> None:
        self._client = client
        self._timeout = timeout
        self._max_tokens = max_tokens

    def _client_or_build(self) -> Anthropic:
        if self._client is not None:
            return self._client
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ProviderFailure("not_configured", "ANTHROPIC_API_KEY is not set")
        return Anthropic(api_key=api_key, timeout=self._timeout, max_retries=0)

    def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
        client = self._client_or_build()
        tool = {
            "name": _TOOL_NAME,
            "description": "Report the structured code review result.",
            "input_schema": request.output_schema,
        }
        # This SDK's Messages.create has no `temperature` (or top_p/top_k) parameter --
        # sampling isn't exposed at all in this API version, only output_config.effort.
        # A request-level temperature therefore can never be honored; the provider always
        # reports "model-default", the same way OpenAI reports it after a rejected
        # explicit temperature.
        kwargs: dict[str, Any] = {
            "model": request.model,
            "max_tokens": self._max_tokens,
            "system": request.system_prompt,
            "messages": [{"role": "user", "content": request.user_content}],
            "tools": [tool],
            "tool_choice": {"type": "tool", "name": _TOOL_NAME},
        }

        try:
            response = client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 - mapped to ProviderFailure below
            raise _map_exception(exc) from exc

        tool_use = next(
            (block for block in response.content if getattr(block, "type", None) == "tool_use"),
            None,
        )
        if tool_use is None:
            raise ProviderFailure(
                "invalid_structured_output", "Anthropic did not return a tool_use block"
            )

        return ProviderResponse(
            raw_json=json.dumps(tool_use.input),
            model=response.model,
            temperature_applied="model-default",
            usage=_usage_from_response(response),
        )


def _usage_from_response(response: Any) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "output_tokens_details", None)
    return Usage(
        input_tokens=getattr(usage, "input_tokens", 0) or 0,
        cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        output_tokens=getattr(usage, "output_tokens", 0) or 0,
        reasoning_tokens=getattr(details, "thinking_tokens", 0) or 0,
    )
