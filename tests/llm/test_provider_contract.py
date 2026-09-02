"""ADR-002 Action Item 6: a contract suite every provider must pass -- raw JSON crosses
the boundary untouched, the temperature fallback is reported honestly, every SDK
exception maps to a `ProviderFailure` category, and no raw SDK exception ever escapes.
Runs against `fake`, `openai`, and `anthropic` with recorded/mocked transports; no
provider here ever makes a real network call.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import httpx2
import pytest
from anthropic import Anthropic
from openai import OpenAI

from py_attest.llm.providers.anthropic import AnthropicProvider
from py_attest.llm.providers.fake import FakeProvider
from py_attest.llm.providers.openai import OpenAIProvider
from py_attest.llm.types import Provider, ProviderFailure, ProviderRequest

REVIEW = {"findings": [], "summary": "No violations found."}


def _openai_provider(review: dict[str, object], *, status: int = 200) -> Provider:
    def handler(_request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "boom", "type": "x"}})
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 0,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": json.dumps(review)},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_retries=0,
    )
    return OpenAIProvider(client=client)


def _anthropic_provider(review: dict[str, object], *, status: int = 200) -> Provider:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        if status != 200:
            return httpx2.Response(status, json={"error": {"message": "boom", "type": "x"}})
        return httpx2.Response(
            200,
            json={
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": "test-model",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "quality_gate_review",
                        "input": review,
                    }
                ],
                "stop_reason": "tool_use",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = Anthropic(
        api_key="test-key",
        base_url="https://anthropic.test",
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
        max_retries=0,
    )
    return AnthropicProvider(client=client)


def _fake_provider(review: dict[str, object], tmp_path: Path) -> Provider:
    fixture = tmp_path / "fixture.json"
    fixture.write_text(json.dumps(review), encoding="utf-8")
    return FakeProvider(fixture)


def _request() -> ProviderRequest:
    return ProviderRequest(
        system_prompt="system",
        user_content="user content",
        output_schema={"type": "object"},
        model="test-model",
        temperature=0,
    )


ProviderFactory = Callable[[Path], Provider]

PROVIDERS: dict[str, ProviderFactory] = {
    "fake": lambda tmp_path: _fake_provider(REVIEW, tmp_path),
    "openai": lambda _tmp_path: _openai_provider(REVIEW),
    "anthropic": lambda _tmp_path: _anthropic_provider(REVIEW),
}

FAILING_PROVIDERS: dict[str, Callable[[Path], Provider]] = {
    "openai": lambda _tmp_path: _openai_provider(REVIEW, status=500),
    "anthropic": lambda _tmp_path: _anthropic_provider(REVIEW, status=500),
}


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_provider_name_matches_its_registry_key(name: str, tmp_path: Path) -> None:
    provider = PROVIDERS[name](tmp_path)
    assert provider.name == name


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_raw_json_crosses_the_boundary_untouched(name: str, tmp_path: Path) -> None:
    provider = PROVIDERS[name](tmp_path)

    response = provider.complete_structured(_request())

    assert json.loads(response.raw_json) == REVIEW


@pytest.mark.parametrize("name", sorted(PROVIDERS))
def test_response_reports_temperature_applied_as_a_string(name: str, tmp_path: Path) -> None:
    provider = PROVIDERS[name](tmp_path)

    response = provider.complete_structured(_request())

    assert response.temperature_applied in {"0", "model-default"}


@pytest.mark.parametrize("name", sorted(FAILING_PROVIDERS))
def test_every_sdk_exception_maps_to_a_provider_failure_category(name: str, tmp_path: Path) -> None:
    provider = FAILING_PROVIDERS[name](tmp_path)

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "transient"


@pytest.mark.parametrize("name", sorted(FAILING_PROVIDERS))
def test_no_raw_sdk_exception_ever_escapes(name: str, tmp_path: Path) -> None:
    """`complete_structured` must only ever raise ProviderFailure (or, for `fake`'s
    control documents, its own documented simulate-only exceptions) -- never a raw
    exception type from an underlying SDK.
    """
    provider = FAILING_PROVIDERS[name](tmp_path)

    try:
        provider.complete_structured(_request())
    except ProviderFailure:
        pass
    except Exception as exc:  # noqa: BLE001 - the assertion itself is the point
        pytest.fail(f"a raw SDK exception escaped complete_structured: {exc!r}")


def test_fake_provider_returns_only_its_explicit_fixture_never_inferring_findings(
    tmp_path: Path,
) -> None:
    provider = _fake_provider({"findings": [], "summary": "hand-authored fixture"}, tmp_path)
    request = ProviderRequest(
        system_prompt="irrelevant",
        user_content="a diff with obvious problems everywhere",
        output_schema={},
        model="ignored",
    )

    response = provider.complete_structured(request)

    assert json.loads(response.raw_json) == {"findings": [], "summary": "hand-authored fixture"}
