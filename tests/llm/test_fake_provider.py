import json
from pathlib import Path

import pytest

from py_attest.llm.providers.fake import FakeProvider, FakeProviderTimeout
from py_attest.llm.types import ProviderFailure, ProviderRequest

REQUEST = ProviderRequest(
    system_prompt="s", user_content="u", output_schema={}, model="fake-model", temperature=0
)


def test_fake_provider_returns_only_its_fixture_content(tmp_path: Path) -> None:
    review = {"findings": [], "summary": "clean"}
    fixture = tmp_path / "clean.json"
    fixture.write_text(json.dumps(review), encoding="utf-8")

    provider = FakeProvider(fixture)
    response = provider.complete_structured(REQUEST)

    assert json.loads(response.raw_json) == review
    assert response.model == "fake-model"
    assert response.temperature_applied == "0"
    assert provider.name == "fake"


def test_fake_provider_never_inspects_the_request_content(tmp_path: Path) -> None:
    fixture = tmp_path / "clean.json"
    fixture.write_text(json.dumps({"findings": [], "summary": "ok"}), encoding="utf-8")
    provider = FakeProvider(fixture)
    request = ProviderRequest(
        system_prompt="s",
        user_content="anything at all, never read",
        output_schema={"anything": True},
        model="ignored",
    )

    response = provider.complete_structured(request)

    assert json.loads(response.raw_json) == {"findings": [], "summary": "ok"}


def test_fake_provider_raises_invalid_structured_output_for_bad_json(tmp_path: Path) -> None:
    fixture = tmp_path / "broken.json"
    fixture.write_text("{not json", encoding="utf-8")
    provider = FakeProvider(fixture)

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(REQUEST)
    assert excinfo.value.category == "invalid_structured_output"


def test_fake_provider_simulate_timeout_control_document(tmp_path: Path) -> None:
    fixture = tmp_path / "control.json"
    fixture.write_text(json.dumps({"simulate": "timeout"}), encoding="utf-8")
    provider = FakeProvider(fixture)

    with pytest.raises(FakeProviderTimeout):
        provider.complete_structured(REQUEST)


def test_fake_provider_simulate_exception_control_document(tmp_path: Path) -> None:
    fixture = tmp_path / "control.json"
    fixture.write_text(json.dumps({"simulate": "exception"}), encoding="utf-8")
    provider = FakeProvider(fixture)

    with pytest.raises(RuntimeError, match="fake provider failed"):
        provider.complete_structured(REQUEST)


def test_fake_provider_raises_not_configured_when_fixture_file_is_missing(tmp_path: Path) -> None:
    provider = FakeProvider(tmp_path / "does-not-exist.json")

    with pytest.raises(ProviderFailure) as excinfo:
        provider.complete_structured(REQUEST)
    assert excinfo.value.category == "not_configured"
