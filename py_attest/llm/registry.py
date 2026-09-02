"""Provider registration by entry point (ADR-002): built-ins register the same way a
third party would, so `py-attest[litellm]` (or anything else) can exist someday as just
another entry under `py_attest.providers`, without touching the engine.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

from py_attest.llm.types import Provider

_GROUP = "py_attest.providers"


class ProviderNotRegisteredError(RuntimeError):
    """Raised when no entry point in ``py_attest.providers`` matches the requested name."""


def _provider_entry_points() -> tuple[EntryPoint, ...]:
    return tuple(entry_points(group=_GROUP))


def load_provider(name: str) -> type[Provider]:
    """Resolve and import the provider class registered under ``name``. Lazy: importing
    `fake` never imports `openai`/`anthropic`, so the base install stays free of LLM SDKs.
    """
    for entry_point in _provider_entry_points():
        if entry_point.name == name:
            return entry_point.load()
    raise ProviderNotRegisteredError(f"unknown provider: {name!r}")
