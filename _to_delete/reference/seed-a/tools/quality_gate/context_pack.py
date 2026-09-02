"""Build the runtime reference context supplied to the reviewer."""

from pathlib import Path

CONTEXT_FILES = ("TEAM-STANDARDS.md", "app/models.py", "app/privacy.py")


class ContextPackError(RuntimeError):
    """Raised when the review context cannot be built."""


def build_context(diff: str, repo_root: Path | None = None) -> str:
    """Return seed references and the unified diff with explicit boundaries."""
    root = repo_root or Path(__file__).resolve().parents[2]
    sections: list[str] = []
    for relative_path in CONTEXT_FILES:
        path = root / relative_path
        try:
            content = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ContextPackError(f"required context file missing: {relative_path}") from exc
        except OSError as exc:
            raise ContextPackError(f"cannot read required context file: {relative_path}") from exc
        sections.append(f'<reference path="{relative_path}">\n{content.rstrip()}\n</reference>')

    sections.append(f"<unified-diff>\n{diff.rstrip()}\n</unified-diff>")
    return "\n\n".join(sections) + "\n"
