"""Moved from tests/llm/test_openai_provider.py: prompt loading isn't provider-specific."""

from hashlib import sha256
from pathlib import Path

import pytest

from py_attest.llm.prompts import PROMPT_PATH, PROMPT_PATHS, PromptError, read_system_prompt


def test_read_system_prompt_raises_for_an_unknown_version() -> None:
    with pytest.raises(PromptError, match="unknown prompt version"):
        read_system_prompt("v99")


def test_read_system_prompt_raises_when_the_file_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(PROMPT_PATHS, "v1", Path("/nonexistent/reviewer_v1.md"))

    with pytest.raises(PromptError, match="cannot read reviewer prompt"):
        read_system_prompt("v1")


def test_v2_prompt_has_full_checklist_and_evidence_contract_without_changing_v1() -> None:
    prompt_v2 = read_system_prompt("v2")

    for section in range(1, 7):
        assert f"{section}. **" in prompt_v2
    assert "would this test FAIL if the behavior broke?" in prompt_v2
    assert "Trivial assertions (type checks, >=0)" in prompt_v2
    assert "Every finding MUST include `evidence`" in prompt_v2
    assert sha256(PROMPT_PATH.read_bytes()).hexdigest() == (
        "8552d80749e74cd66e6d97efc1e27aeafe2f1ed1e8520a2079d15fc1313d2d89"
    )


def test_v3_prompt_loads() -> None:
    assert read_system_prompt("v3")
