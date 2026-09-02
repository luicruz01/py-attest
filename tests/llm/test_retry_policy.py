from dataclasses import dataclass, field

import pytest

from py_attest.llm.policy import BACKOFF_SECONDS, run_with_policy
from py_attest.llm.types import ProviderFailure, ProviderRequest, ProviderResponse

REQUEST = ProviderRequest(
    system_prompt="s", user_content="u", output_schema={}, model="m", temperature=0
)


@dataclass
class ScriptedProvider:
    """Test double that raises/returns according to a scripted sequence of outcomes."""

    name: str
    outcomes: list[object]
    calls: int = field(default=0, init=False)

    def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
        del request
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def ok_response() -> ProviderResponse:
    return ProviderResponse(raw_json="{}", model="m", temperature_applied="0", usage=None)


def test_a_successful_first_call_makes_one_attempt_and_no_sleep() -> None:
    provider = ScriptedProvider("fake", [ok_response()])
    sleeps: list[float] = []

    response = run_with_policy(provider, REQUEST, sleep=sleeps.append)

    assert provider.calls == 1
    assert response.attempts == 1
    assert sleeps == []


def test_transient_failure_retries_with_2s_then_6s_backoff_up_to_three_attempts() -> None:
    provider = ScriptedProvider(
        "fake",
        [
            ProviderFailure("transient", "429"),
            ProviderFailure("transient", "429"),
            ok_response(),
        ],
    )
    sleeps: list[float] = []

    response = run_with_policy(provider, REQUEST, sleep=sleeps.append)

    assert provider.calls == 3
    assert response.attempts == 3
    assert sleeps == list(BACKOFF_SECONDS)


def test_transient_failure_gives_up_after_two_additional_attempts() -> None:
    provider = ScriptedProvider(
        "fake",
        [
            ProviderFailure("transient", "429"),
            ProviderFailure("transient", "429"),
            ProviderFailure("transient", "still failing"),
        ],
    )
    sleeps: list[float] = []

    with pytest.raises(ProviderFailure, match="still failing"):
        run_with_policy(provider, REQUEST, sleep=sleeps.append)

    assert provider.calls == 3
    assert sleeps == list(BACKOFF_SECONDS)


def test_invalid_structured_output_retries_exactly_once() -> None:
    provider = ScriptedProvider(
        "fake",
        [
            ProviderFailure("invalid_structured_output", "bad json"),
            ok_response(),
        ],
    )

    response = run_with_policy(provider, REQUEST, sleep=lambda _seconds: None)

    assert provider.calls == 2
    assert response.attempts == 2


def test_invalid_structured_output_gives_up_after_one_retry() -> None:
    provider = ScriptedProvider(
        "fake",
        [
            ProviderFailure("invalid_structured_output", "bad json"),
            ProviderFailure("invalid_structured_output", "still bad"),
        ],
    )

    with pytest.raises(ProviderFailure, match="still bad"):
        run_with_policy(provider, REQUEST, sleep=lambda _seconds: None)


@pytest.mark.parametrize("category", ["not_configured", "rejected"])
def test_not_configured_and_rejected_never_retry(category: str) -> None:
    provider = ScriptedProvider("fake", [ProviderFailure(category, "no retry")])

    def fail_if_called(_seconds: float) -> None:
        raise AssertionError("must not sleep/retry for this category")

    with pytest.raises(ProviderFailure, match="no retry"):
        run_with_policy(provider, REQUEST, sleep=fail_if_called)

    assert provider.calls == 1


def test_a_non_provider_failure_exception_is_never_caught_or_retried() -> None:
    provider = ScriptedProvider("fake", [RuntimeError("SDK leaked a raw exception")])

    with pytest.raises(RuntimeError, match="SDK leaked a raw exception"):
        run_with_policy(provider, REQUEST, sleep=lambda _seconds: None)

    assert provider.calls == 1
