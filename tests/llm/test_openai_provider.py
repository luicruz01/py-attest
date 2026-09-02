import json
from hashlib import sha256
from pathlib import Path

import httpx
import pytest
from openai import OpenAI

from py_attest.llm.providers import openai as openai_provider
from py_attest.llm.providers.openai import (
    MAX_DIFF_BYTES,
    PROMPT_PATH,
    LLMReviewError,
    MissingProviderKeyError,
    _client_from_environment,
    _read_system_prompt,
    review_context,
)
from py_attest.review.models import REVIEW_SCHEMA


def test_review_context_sends_one_strict_structured_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[httpx.Request] = []
    review = {"findings": [], "summary": "No violations found."}
    monkeypatch.setenv("OPENAI_MODEL", "environment-model")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
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

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAI(api_key="test-key", base_url="https://openai.test/v1", http_client=http_client)

    result = review_context("packed context", "small diff", client=client)

    assert result == {**review, "metadata": {"temperature": "0"}}
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    assert body["model"] == "environment-model"
    assert body["temperature"] == 0
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "quality_gate_review", "strict": True, "schema": REVIEW_SCHEMA},
    }
    assert [message["role"] for message in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"].startswith("# LMS pull request reviewer v2")
    assert body["messages"][1]["content"] == "packed context"


def test_review_context_retries_once_without_unsupported_temperature() -> None:
    requests: list[httpx.Request] = []
    review = {"findings": [], "summary": "No violations found."}

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Unsupported value: 'temperature' does not support 0.",
                        "type": "invalid_request_error",
                        "param": "temperature",
                        "code": "unsupported_value",
                    }
                },
            )
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

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=http_client,
    )

    result = review_context("packed context", "small diff", client=client, model="test-model")

    assert result == {**review, "metadata": {"temperature": "model-default"}}
    assert len(requests) == 2
    assert json.loads(requests[0].content)["temperature"] == 0
    assert "temperature" not in json.loads(requests[1].content)


def test_diff_too_large_fails_before_any_api_call() -> None:
    with pytest.raises(LLMReviewError, match="diff too large"):
        review_context("context", "x" * (MAX_DIFF_BYTES + 1), model="test-model")


def test_review_context_reraises_non_temperature_bad_request_errors() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "invalid model",
                    "type": "invalid_request_error",
                    "param": "model",
                    "code": "model_not_found",
                }
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(Exception, match="invalid model"):
        review_context("context", "diff", client=client, model="test-model")


def test_review_context_raises_when_content_is_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
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
                        "message": {"role": "assistant", "content": None},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(LLMReviewError, match="no structured review content"):
        review_context("context", "diff", client=client, model="test-model")


def test_review_context_raises_on_invalid_structured_review() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
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
                        "message": {"role": "assistant", "content": "{not valid json"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=transport),
    )

    with pytest.raises(LLMReviewError, match="invalid structured review"):
        review_context("context", "diff", client=client, model="test-model")


def test_review_context_builds_a_client_from_the_environment_when_none_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    review = {"findings": [], "summary": "No violations found."}

    def handler(_request: httpx.Request) -> httpx.Response:
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

    transport = httpx.MockTransport(handler)
    fake_client = OpenAI(
        api_key="test-key",
        base_url="https://openai.test/v1",
        http_client=httpx.Client(transport=transport),
    )
    monkeypatch.setattr(openai_provider, "_client_from_environment", lambda: fake_client)

    result = review_context("context", "diff", model="test-model")

    assert result == {**review, "metadata": {"temperature": "0"}}


def test_client_from_environment_raises_when_no_api_key_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(MissingProviderKeyError, match="OPENAI_API_KEY is not set"):
        _client_from_environment()


def test_client_from_environment_ignores_a_env_file_in_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reviewed repo must never be able to inject provider config via a `.env` file.

    Seed A's llm.py called `load_dotenv()`, which reads `.env` from the CWD — for
    `attest review` the CWD is the repo under review, so a malicious PR shipping a `.env`
    with OPENAI_BASE_URL could redirect the review request (real API key, full diff) to
    an attacker endpoint. python-dotenv is dropped entirely; keys and other provider
    config come from the real process environment only.
    """
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "OPENAI_API_KEY=injected-from-repo\nOPENAI_BASE_URL=https://attacker.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(MissingProviderKeyError, match="OPENAI_API_KEY is not set"):
        _client_from_environment()

    assert "OPENAI_API_KEY" not in openai_provider.os.environ
    assert "OPENAI_BASE_URL" not in openai_provider.os.environ


def test_client_from_environment_builds_a_client_when_key_is_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "env-test-key")

    client = _client_from_environment()

    assert isinstance(client, OpenAI)
    assert client.api_key == "env-test-key"


def test_read_system_prompt_raises_for_an_unknown_version() -> None:
    with pytest.raises(LLMReviewError, match="unknown prompt version"):
        _read_system_prompt("v99")


def test_read_system_prompt_raises_when_the_file_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(openai_provider.PROMPT_PATHS, "v1", Path("/nonexistent/reviewer_v1.md"))

    with pytest.raises(LLMReviewError, match="cannot read reviewer prompt"):
        _read_system_prompt("v1")


def test_v2_prompt_has_full_checklist_and_evidence_contract_without_changing_v1() -> None:
    prompt_v2 = _read_system_prompt("v2")

    for section in range(1, 7):
        assert f"{section}. **" in prompt_v2
    assert "would this test FAIL if the behavior broke?" in prompt_v2
    assert "Trivial assertions (type checks, >=0)" in prompt_v2
    assert "Every finding MUST include `evidence`" in prompt_v2
    assert sha256(PROMPT_PATH.read_bytes()).hexdigest() == (
        "8552d80749e74cd66e6d97efc1e27aeafe2f1ed1e8520a2079d15fc1313d2d89"
    )
