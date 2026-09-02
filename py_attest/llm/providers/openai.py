"""OpenAI provider (ADR-002): Chat Completions with strict json_schema structured
output and a one-shot temperature fallback (Seed A), adapted to the Provider protocol,
with `store=False` (Seed B, ADR-004 SS2(b)). No internal retries: SDK retries are
disabled (`max_retries=0`) so `llm/policy.py` owns the attempt count.
"""

from __future__ import annotations

import os
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    OpenAI,
    PermissionDeniedError,
    RateLimitError,
)

from py_attest.llm.types import ProviderFailure, ProviderRequest, ProviderResponse, Usage

_STRUCTURED_OUTPUT_NAME = "quality_gate_review"


def _classify(exc: Exception) -> str:
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return "not_configured"
    if isinstance(exc, RateLimitError):
        return "transient"
    if isinstance(exc, APITimeoutError):
        return "transient"
    if isinstance(exc, APIConnectionError):
        return "transient"
    if isinstance(exc, APIStatusError) and 500 <= exc.status_code < 600:
        return "transient"
    return "rejected"


def _map_exception(exc: Exception) -> ProviderFailure:
    return ProviderFailure(_classify(exc), f"OpenAI request failed: {exc}")


class OpenAIProvider:
    name = "openai"

    def __init__(self, *, timeout: float = 30.0, client: OpenAI | None = None) -> None:
        self._client = client
        self._timeout = timeout

    def _client_or_build(self) -> OpenAI:
        if self._client is not None:
            return self._client
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ProviderFailure("not_configured", "OPENAI_API_KEY is not set")
        return OpenAI(api_key=api_key, timeout=self._timeout, max_retries=0)

    def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
        client = self._client_or_build()
        base_kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": _STRUCTURED_OUTPUT_NAME,
                    "strict": True,
                    "schema": request.output_schema,
                },
            },
            "store": False,
        }

        temperature_applied = "model-default"
        kwargs = dict(base_kwargs)
        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        try:
            response = client.chat.completions.create(**kwargs)
            if request.temperature is not None:
                temperature_applied = str(request.temperature)
        except BadRequestError as exc:
            if (
                request.temperature is None
                or exc.param != "temperature"
                or (exc.code != "unsupported_value")
            ):
                raise _map_exception(exc) from exc
            try:
                response = client.chat.completions.create(**base_kwargs)
            except Exception as retry_exc:  # noqa: BLE001 - mapped to ProviderFailure below
                raise _map_exception(retry_exc) from retry_exc
        except Exception as exc:  # noqa: BLE001 - mapped to ProviderFailure below
            raise _map_exception(exc) from exc

        content = response.choices[0].message.content
        if content is None:
            raise ProviderFailure(
                "invalid_structured_output", "OpenAI returned no structured review content"
            )
        return ProviderResponse(
            raw_json=content,
            model=response.model,
            temperature_applied=temperature_applied,
            usage=_usage_from_response(response),
        )


def _usage_from_response(response: Any) -> Usage | None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    details = getattr(usage, "prompt_tokens_details", None)
    completion_details = getattr(usage, "completion_tokens_details", None)
    return Usage(
        input_tokens=getattr(usage, "prompt_tokens", 0) or 0,
        cached_input_tokens=getattr(details, "cached_tokens", 0) or 0,
        output_tokens=getattr(usage, "completion_tokens", 0) or 0,
        reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
    )
