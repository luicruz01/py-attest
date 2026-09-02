import json
from hashlib import sha256

import httpx
import pytest
from openai import OpenAI

from tools.quality_gate.llm import (
    MAX_DIFF_BYTES,
    PROMPT_PATH,
    LLMReviewError,
    _read_system_prompt,
    review_context,
)
from tools.quality_gate.schema import REVIEW_SCHEMA


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
