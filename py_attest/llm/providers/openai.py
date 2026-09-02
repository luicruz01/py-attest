"""OpenAI client wrapper for structured review requests."""

import json
import os
from pathlib import Path
from typing import Any

from openai import BadRequestError, OpenAI

from py_attest.review.models import REVIEW_SCHEMA, SchemaValidationError, validate_review_result

DEFAULT_MODEL = "gpt-5-mini"
MAX_DIFF_BYTES = 60 * 1024
PROMPT_PATH = Path(__file__).parents[1] / "prompts" / "reviewer_v1.md"
PROMPT_PATHS = {
    "v1": PROMPT_PATH,
    "v2": Path(__file__).parents[1] / "prompts" / "reviewer_v2.md",
    "v3": Path(__file__).parents[1] / "prompts" / "reviewer_v3.md",
}


class LLMReviewError(RuntimeError):
    """Raised when an LLM review cannot be requested or decoded."""


class MissingProviderKeyError(LLMReviewError):
    """Raised when no OPENAI_API_KEY is configured; callers should skip gracefully."""


def review_context(
    context: str,
    diff: str,
    *,
    client: OpenAI | None = None,
    model: str | None = None,
    prompt_version: str = "v2",
) -> dict[str, Any]:
    """Request a structured review, with one unsupported-temperature fallback."""
    diff_size = len(diff.encode("utf-8"))
    if diff_size > MAX_DIFF_BYTES:
        raise LLMReviewError(
            f"diff too large: {diff_size} bytes exceeds the {MAX_DIFF_BYTES}-byte limit"
        )

    if client is None:
        client = _client_from_environment()
    selected_model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    system_prompt = _read_system_prompt(prompt_version)

    request = {
        "model": selected_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "quality_gate_review",
                "strict": True,
                "schema": REVIEW_SCHEMA,
            },
        },
    }
    temperature = "0"
    try:
        response = client.chat.completions.create(temperature=0, **request)
    except BadRequestError as exc:
        if exc.param != "temperature" or exc.code != "unsupported_value":
            raise
        response = client.chat.completions.create(**request)
        temperature = "model-default"

    content = response.choices[0].message.content
    if content is None:
        raise LLMReviewError("OpenAI returned no structured review content")
    try:
        decoded = json.loads(content)
        result = validate_review_result(decoded)
        result["metadata"] = {"temperature": temperature}
        return result
    except (json.JSONDecodeError, SchemaValidationError) as exc:
        raise LLMReviewError(f"OpenAI returned an invalid structured review: {exc}") from exc


def _client_from_environment() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise MissingProviderKeyError("OPENAI_API_KEY is not set; add it to the environment")
    return OpenAI(api_key=api_key, max_retries=0)


def _read_system_prompt(prompt_version: str = "v1") -> str:
    prompt_path = PROMPT_PATHS.get(prompt_version)
    if prompt_path is None:
        raise LLMReviewError(f"unknown prompt version: {prompt_version}")
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LLMReviewError(f"cannot read reviewer prompt: {prompt_path.name}") from exc
