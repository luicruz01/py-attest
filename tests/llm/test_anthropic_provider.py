import json
from pathlib import Path

import httpx2
import pytest
from anthropic import Anthropic

from py_attest.llm.providers import anthropic as anthropic_provider
from py_attest.llm.providers.anthropic import AnthropicProvider
from py_attest.llm.types import ProviderFailure, ProviderRequest

REVIEW = {"findings": [], "summary": "No violations found."}


def _tool_use_response(
    review: dict[str, object] | None,
    *,
    model: str = "test-model",
    usage: dict[str, object] | None = None,
) -> httpx2.Response:
    content: list[dict[str, object]] = []
    if review is not None:
        content.append(
            {"type": "tool_use", "id": "toolu_1", "name": "quality_gate_review", "input": review}
        )
    return httpx2.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content,
            "stop_reason": "tool_use",
            "usage": usage
            or {
                "input_tokens": 10,
                "output_tokens": 5,
                "cache_read_input_tokens": 2,
                "output_tokens_details": {"thinking_tokens": 1},
            },
        },
    )


def _client(handler: object) -> Anthropic:
    transport = httpx2.MockTransport(handler)
    return Anthropic(
        api_key="test-key",
        base_url="https://anthropic.test",
        http_client=httpx2.Client(transport=transport),
        max_retries=0,
    )


def _request(**overrides: object) -> ProviderRequest:
    defaults: dict[str, object] = {
        "system_prompt": "system prompt",
        "user_content": "packed context",
        "output_schema": {"type": "object"},
        "model": "test-model",
        "temperature": 0,
    }
    defaults.update(overrides)
    return ProviderRequest(**defaults)  # type: ignore[arg-type]


def test_complete_structured_forces_tool_use_with_the_output_schema() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _tool_use_response(REVIEW)

    provider = AnthropicProvider(client=_client(handler))

    response = provider.complete_structured(_request())

    assert json.loads(response.raw_json) == REVIEW
    assert response.model == "test-model"
    assert response.temperature_applied == "model-default"
    assert response.usage is not None
    assert response.usage.input_tokens == 10
    assert response.usage.output_tokens == 5
    assert response.usage.cached_input_tokens == 2
    assert response.usage.reasoning_tokens == 1
    body = json.loads(requests[0].content)
    assert body["system"] == "system prompt"
    assert body["messages"] == [{"role": "user", "content": "packed context"}]
    assert body["tool_choice"] == {"type": "tool", "name": "quality_gate_review"}
    assert body["tools"] == [
        {
            "name": "quality_gate_review",
            "description": "Report the structured code review result.",
            "input_schema": {"type": "object"},
        }
    ]
    assert "temperature" not in body


def test_complete_structured_always_reports_model_default_temperature() -> None:
    """This SDK's Messages.create has no `temperature` parameter at all (only
    output_config.effort) -- a request-level temperature can never be honored, so the
    provider always reports "model-default", regardless of what the request asked for.
    """
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _tool_use_response(REVIEW)

    provider = AnthropicProvider(client=_client(handler))

    response = provider.complete_structured(_request(temperature=None))

    assert "temperature" not in json.loads(requests[0].content)
    assert response.temperature_applied == "model-default"


def test_complete_structured_raises_invalid_structured_output_without_a_tool_use_block() -> None:
    provider = AnthropicProvider(client=_client(lambda _r: _tool_use_response(None)))

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "invalid_structured_output"


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "not_configured"),
        (403, "not_configured"),
        (429, "transient"),
        (529, "transient"),
        (404, "rejected"),
    ],
)
def test_complete_structured_maps_http_status_to_the_adr002_taxonomy(
    status: int, category: str
) -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json={"error": {"message": "boom", "type": "x"}})

    provider = AnthropicProvider(client=_client(handler))

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == category


def test_complete_structured_never_lets_a_raw_sdk_exception_escape() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(500, json={"error": {"message": "boom"}})

    provider = AnthropicProvider(client=_client(handler))

    with pytest.raises(ProviderFailure):
        provider.complete_structured(_request())


def test_client_or_build_raises_not_configured_when_no_api_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = AnthropicProvider()

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "not_configured"
    assert "ANTHROPIC_API_KEY" in str(excinfo.value)


def test_client_or_build_ignores_a_env_file_in_the_reviewed_repos_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed repo must never be able to inject provider config via a `.env` file.

    Same bypass class as OpenAI (tests/llm/test_openai_provider.py): `attest review`'s
    CWD is the repo under review, so a malicious PR shipping a `.env` with
    ANTHROPIC_BASE_URL could redirect the review request to an attacker endpoint. Keys
    and other provider config come from the real process environment only.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "ANTHROPIC_API_KEY=injected-from-repo\nANTHROPIC_BASE_URL=https://attacker.example\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    provider = AnthropicProvider()

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())

    assert excinfo.value.category == "not_configured"
    assert "ANTHROPIC_API_KEY" not in anthropic_provider.os.environ
    assert "ANTHROPIC_BASE_URL" not in anthropic_provider.os.environ


def test_client_or_build_builds_a_client_from_the_environment_when_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-test-key")

    client = AnthropicProvider()._client_or_build()

    assert isinstance(client, Anthropic)
    assert client.api_key == "env-test-key"


def test_complete_structured_reports_no_usage_when_the_response_has_none() -> None:
    def handler(_request: httpx2.Request) -> httpx2.Response:
        response = _tool_use_response(REVIEW)
        payload = json.loads(response.content)
        del payload["usage"]
        return httpx2.Response(200, json=payload)

    provider = AnthropicProvider(client=_client(handler))

    response = provider.complete_structured(_request())

    assert response.usage is None
