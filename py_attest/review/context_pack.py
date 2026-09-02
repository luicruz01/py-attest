"""Build the runtime reference context supplied to the reviewer."""

from collections.abc import Sequence
from pathlib import Path


class ContextPackError(RuntimeError):
    """Raised when the review context cannot be built."""


def build_context(diff: str, repo_root: Path, context_files: Sequence[str] = ()) -> str:
    """Return configured reference files and the unified diff with explicit boundaries."""
    resolved_root = repo_root.resolve()
    sections: list[str] = []
    for relative_path in context_files:
        # context_files is read from the reviewed repo's own [tool.attest] config
        # (Config.context_files), so an absolute path or a `..` escape here is
        # attacker-controlled: a PR could otherwise point this at files outside the
        # repo (e.g. `../../.aws/credentials`) and have them transmitted to the LLM
        # provider. Containment is required, not just documented.
        candidate = (repo_root / relative_path).resolve()
        try:
            candidate.relative_to(resolved_root)
        except ValueError as exc:
            raise ContextPackError(f"context file escapes the repo root: {relative_path}") from exc
        path = candidate
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ContextPackError(f"required context file missing: {relative_path}") from exc
        except OSError as exc:
            raise ContextPackError(f"cannot read required context file: {relative_path}") from exc
        sections.append(f'<reference path="{relative_path}">\n{content.rstrip()}\n</reference>')

    sections.append(f"<unified-diff>\n{diff.rstrip()}\n</unified-diff>")
    return "\n\n".join(sections) + "\n"
