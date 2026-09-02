"""System prompt loading for the reviewer -- provider-agnostic (ADR-002: a provider's job
is transport and structured-output mechanics, not prompt selection).
"""

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
PROMPT_PATH = _PROMPTS_DIR / "reviewer_v1.md"
PROMPT_PATHS = {
    "v1": PROMPT_PATH,
    "v2": _PROMPTS_DIR / "reviewer_v2.md",
    "v3": _PROMPTS_DIR / "reviewer_v3.md",
}


class PromptError(RuntimeError):
    """Raised when the reviewer system prompt cannot be resolved or read."""


def read_system_prompt(prompt_version: str = "v1") -> str:
    prompt_path = PROMPT_PATHS.get(prompt_version)
    if prompt_path is None:
        raise PromptError(f"unknown prompt version: {prompt_version}")
    try:
        return prompt_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptError(f"cannot read reviewer prompt: {prompt_path.name}") from exc
