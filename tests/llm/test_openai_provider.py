import json
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from py_attest.llm.providers import openai as openai_provider
from py_attest.llm.providers.openai import OpenAIProvider
from py_attest.llm.types import ProviderFailure, ProviderRequest

REVIEW = {"findings": [], "summary": "No violations found."}


def _chat_completion_response(
    content: str | None,
    *,
    model: str = "test-model",
    usage: dict[str, object] | None = None,
) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage
            or {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "prompt_tokens_details": {"cached_tokens": 2},
                "completion_tokens_details": {"reasoning_tokens": 1},
            },
        },
    )


def _bad_request(*, param: str, code: str, message: str = "bad request") -> httpx.Response:
    return httpx.Response(
        400,
        json={
            "error": {
                "message": message,
                "type": "invalid_request_error",
                "param": param,
                "code": code,
            }
        },
    )


def _client(handler: object) -> OpenAI:
    transport = httpx.MockTransport(handler)
    return OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=transport),
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


def test_complete_structured_sends_one_strict_structured_request_with_store_false() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _chat_completion_response(json.dumps(REVIEW))

    provider = OpenAIProvider(client=_client(handler))

    response = provider.complete_structured(_request())

    assert json.loads(response.raw_json) == REVIEW
    assert response.temperature_applied == "0"
    assert response.model == "test-model"
    assert response.usage is not None
    assert response.usage.input_tokens == 10
    assert response.usage.cached_input_tokens == 2
    assert response.usage.output_tokens == 5
    assert response.usage.reasoning_tokens == 1
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["model"] == "test-model"
    assert body["temperature"] == 0
    assert body["store"] is False
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {
            "name": "quality_gate_review",
            "strict": True,
            "schema": {"type": "object"},
        },
    }
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"] == "system prompt"
    assert body["messages"][1]["content"] == "packed context"


def test_complete_structured_retries_once_without_unsupported_temperature() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return _bad_request(param="temperature", code="unsupported_value")
        return _chat_completion_response(json.dumps(REVIEW))

    provider = OpenAIProvider(client=_client(handler))

    response = provider.complete_structured(_request())

    assert response.temperature_applied == "model-default"
    assert len(requests) == 2
    assert json.loads(requests[0].content)["temperature"] == 0
    assert "temperature" not in json.loads(requests[1].content)


def test_complete_structured_never_sends_temperature_when_request_temperature_is_none() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _chat_completion_response(json.dumps(REVIEW))

    provider = OpenAIProvider(client=_client(handler))

    response = provider.complete_structured(_request(temperature=None))

    assert "temperature" not in json.loads(requests[0].content)
    assert response.temperature_applied == "model-default"


def test_complete_structured_raises_rejected_for_a_non_temperature_bad_request() -> None:
    provider = OpenAIProvider(
        client=_client(
            lambda _r: _bad_request(param="model", code="model_not_found", message="invalid model")
        )
    )

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "rejected"
    assert "invalid model" in str(excinfo.value)


def test_complete_structured_raises_invalid_structured_output_when_content_is_none() -> None:
    provider = OpenAIProvider(client=_client(lambda _r: _chat_completion_response(None)))

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "invalid_structured_output"


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (401, "not_configured"),
        (403, "not_configured"),
        (429, "transient"),
        (503, "transient"),
        (404, "rejected"),
    ],
)
def test_complete_structured_maps_http_status_to_the_adr002_taxonomy(
    status: int, category: str
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json={"error": {"message": "boom", "type": "x"}})

    provider = OpenAIProvider(client=_client(handler))

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == category


def test_complete_structured_never_lets_a_raw_sdk_exception_escape() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": {"message": "boom"}})

    provider = OpenAIProvider(client=_client(handler))

    with pytest.raises(ProviderFailure):
        provider.complete_structured(_request())


def test_client_or_build_raises_not_configured_when_no_api_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = OpenAIProvider()

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "not_configured"
    assert "OPENAI_API_KEY" in str(excinfo.value)


def test_client_or_build_ignores_a_env_file_in_the_reviewed_repos_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed repo must never be able to inject provider config via a `.env` file.

    `attest review`'s CWD is the repo under review; a malicious PR shipping a `.env` with
    OPENAI_BASE_URL could redirect the review request (real API key, full diff) to an
    attacker endpoint. Keys and other provider config come from the real process
    environment only -- python-dotenv (or anything that reads `.env`) is never used.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=injected-from-repo\nOPENAI_BASE_URL=https://attacker.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    provider = OpenAIProvider()

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())

    assert excinfo.value.category == "not_configured"
    assert "OPENAI_API_KEY" not in openai_provider.os.environ
    assert "OPENAI_BASE_URL" not in openai_provider.os.environ


def test_client_or_build_builds_a_client_from_the_environment_when_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-test-key")

    client = OpenAIProvider()._client_or_build()

    assert isinstance(client, OpenAI)
    assert client.api_key == "env-test-key"


def test_complete_structured_raises_rejected_when_the_retry_without_temperature_also_fails() -> (
    None
):
    def handler(_request: httpx.Request) -> httpx.Response:
        return _bad_request(param="temperature", code="unsupported_value")

    provider = OpenAIProvider(client=_client(handler))

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(_request())
    assert excinfo.value.category == "rejected"


def test_complete_structured_reports_no_usage_when_the_response_has_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        response = _chat_completion_response(json.dumps(REVIEW))
        payload = json.loads(response.content)
        del payload["usage"]
        return httpx.Response(200, json=payload)

    provider = OpenAIProvider(client=_client(handler))

    response = provider.complete_structured(_request())

    assert response.usage is None
