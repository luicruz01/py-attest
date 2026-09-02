from importlib.metadata import EntryPoint

import pytest

from py_attest.llm import registry
from py_attest.llm.registry import ProviderNotRegisteredError, load_provider


def test_load_provider_resolves_the_fake_provider_by_entry_point_name() -> None:
    provider_class = load_provider("fake")

    assert provider_class.__name__ == "FakeProvider"


def test_load_provider_raises_for_an_unknown_provider_name() -> None:
    with pytest.raises(ProviderNotRegisteredError, match="unknown provider: 'made-up'"):
        load_provider("made-up")


def test_load_provider_does_not_import_openai_or_anthropic_modules_to_load_fake(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Loading `fake` must never require the `openai`/`anthropic` extras to be
    installed -- the base install stays free of LLM SDKs (ADR-002).
    """
    import sys

    for module_name in list(sys.modules):
        if module_name in {"openai", "anthropic"} or module_name.startswith(
            ("openai.", "anthropic.")
        ):
            monkeypatch.delitem(sys.modules, module_name)
    blocked = {"openai", "anthropic"}
    real_import = __import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        if name in blocked or any(name.startswith(f"{b}.") for b in blocked):
            raise AssertionError(f"loading 'fake' must not import {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", guarded_import)

    load_provider("fake")


def test_entry_points_are_registered_under_the_py_attest_providers_group() -> None:
    names = {entry_point.name for entry_point in registry._provider_entry_points()}

    assert {"fake", "openai", "anthropic"} <= names


def test_provider_entry_points_uses_the_configured_group_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_entry_points(**kwargs: object) -> tuple[EntryPoint, ...]:
        captured.update(kwargs)
        return ()

    monkeypatch.setattr(registry, "entry_points", fake_entry_points)

    registry._provider_entry_points()

    assert captured == {"group": "py_attest.providers"}
