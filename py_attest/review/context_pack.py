"""Build the runtime reference context supplied to the reviewer."""

from collections.abc import Sequence
from pathlib import Path

from py_attest.standards.registry import Rule


class ContextPackError(RuntimeError):
    """Raised when the review context cannot be built."""


def render_rules_block(rules: Sequence[Rule]) -> str:
    """Render the mode=="llm" rules as data for the reviewer to cite rule_id from."""
    lines = ["<review-rules>"]
    for rule in rules:
        lines.append(f"- id: {rule.id}")
        lines.append(f"  title: {rule.title}")
        lines.append(f"  description: {rule.description.strip()}")
        if rule.evidence_required:
            lines.append(f"  evidence_required: {rule.evidence_required.strip()}")
        if rule.non_examples:
            lines.append("  non_examples:")
            lines.extend(f"    - {example}" for example in rule.non_examples)
    lines.append("</review-rules>")
    return "\n".join(lines) + "\n"


def build_context(
    diff: str,
    repo_root: Path,
    context_files: Sequence[str] = (),
    rules_block: str | None = None,
) -> str:
    """Return the rules block (if given), configured reference files, and the diff, with
    explicit boundaries.
    """
    resolved_root = repo_root.resolve()
    sections: list[str] = []
    if rules_block is not None:
        sections.append(rules_block.rstrip())
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
