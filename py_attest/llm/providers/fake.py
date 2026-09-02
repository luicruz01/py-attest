"""Fixture-only provider (ADR-004 SS2(b)): returns only its explicit fixture, never
inspects a repository or the request, and never touches the network. Official provider
for tests, `calibrate`, and CI without a key.
"""

from __future__ import annotations

import json
from pathlib import Path

from py_attest.llm.types import ProviderFailure, ProviderRequest, ProviderResponse


class FakeProviderTimeout(TimeoutError):
    """Raised when the fixture is a ``{"simulate": "timeout"}`` control document."""


class FakeProvider:
    name = "fake"

    def __init__(self, response_file: str | Path) -> None:
        self.response_file = Path(response_file)

    def complete_structured(self, request: ProviderRequest) -> ProviderResponse:
        try:
            raw = self.response_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProviderFailure(
                "not_configured", f"fake provider fixture not found: {self.response_file}"
            ) from exc
        try:
            control = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ProviderFailure(
                "invalid_structured_output", "fake provider fixture is not valid JSON"
            ) from exc
        if isinstance(control, dict) and set(control) == {"simulate"}:
            if control["simulate"] == "timeout":
                raise FakeProviderTimeout("fake provider timed out")
            if control["simulate"] == "exception":
                raise RuntimeError("fake provider failed")
        temperature_applied = "0" if request.temperature == 0 else "model-default"
        return ProviderResponse(
            raw_json=raw,
            model=request.model,
            temperature_applied=temperature_applied,
            usage=None,
        )
