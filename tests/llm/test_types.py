import dataclasses

import pytest

from py_attest.llm.types import (
    FAILURE_CATEGORIES,
    ProviderFailure,
    ProviderRequest,
    ProviderResponse,
    Usage,
)


def test_provider_request_is_a_frozen_dataclass_with_the_adr002_contract() -> None:
    request = ProviderRequest(
        system_prompt="system",
        user_content="user",
        output_schema={"type": "object"},
        model="gpt-5-mini",
        temperature=0,
    )

    assert request.system_prompt == "system"
    assert request.user_content == "user"
    assert request.output_schema == {"type": "object"}
    assert request.model == "gpt-5-mini"
    assert request.temperature == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.model = "other"  # type: ignore[misc]


def test_provider_request_temperature_defaults_to_none_for_model_default() -> None:
    request = ProviderRequest(system_prompt="s", user_content="u", output_schema={}, model="m")

    assert request.temperature is None


def test_provider_response_carries_provenance_fields() -> None:
    usage = Usage(input_tokens=10, cached_input_tokens=2, output_tokens=5, reasoning_tokens=1)
    response = ProviderResponse(
        raw_json='{"findings": [], "summary": ""}',
        model="gpt-5-mini",
        temperature_applied="0",
        usage=usage,
        attempts=1,
    )

    assert response.raw_json == '{"findings": [], "summary": ""}'
    assert response.usage.input_tokens == 10
    assert response.attempts == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.attempts = 2  # type: ignore[misc]


def test_provider_response_attempts_defaults_to_none_until_policy_stamps_it() -> None:
    response = ProviderResponse(raw_json="{}", model="m", temperature_applied="0", usage=None)

    assert response.attempts is None
    assert response.usage is None


def test_provider_response_can_be_replaced_to_stamp_attempts() -> None:
    response = ProviderResponse(raw_json="{}", model="m", temperature_applied="0", usage=None)

    stamped = dataclasses.replace(response, attempts=3)

    assert stamped.attempts == 3
    assert stamped.raw_json == response.raw_json


def test_usage_is_a_frozen_dataclass_with_all_four_token_fields() -> None:
    usage = Usage(input_tokens=1, cached_input_tokens=0, output_tokens=2, reasoning_tokens=0)

    assert dataclasses.astuple(usage) == (1, 0, 2, 0)


@pytest.mark.parametrize("category", sorted(FAILURE_CATEGORIES))
def test_provider_failure_accepts_every_adr002_taxonomy_category(category: str) -> None:
    failure = ProviderFailure(category, "boom")

    assert failure.category == category
    assert str(failure) == "boom"
    assert isinstance(failure, RuntimeError)


def test_provider_failure_rejects_an_unknown_category() -> None:
    with pytest.raises(ValueError, match="unknown ProviderFailure category"):
        ProviderFailure("made_up_category", "boom")


def test_failure_categories_match_adr002_taxonomy() -> None:
    # ProviderNotConfigured / ProviderTransient / ProviderRejected / StructuredOutputInvalid
    # (ADR-002 "Taxonomia de errores"), implemented as one exception discriminated by category.
    assert FAILURE_CATEGORIES == {
        "not_configured",
        "transient",
        "rejected",
        "invalid_structured_output",
    }
