"""Raw egress (default, ADR-004 SS3): the unmodified context pack -- the mode=="llm"
rules block, reference files (``context_files``), and the unified diff, as data.
Selected by ``config.egress == "raw"``.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from py_attest.review.context_pack import build_context
from py_attest.review.egress import EgressResult


def build_raw_egress(
    diff: str,
    repo_root: Path,
    context_files: Sequence[str] = (),
    *,
    description: str | None = None,
    rules_block: str | None = None,
) -> EgressResult:
    context = build_context(diff, repo_root, context_files, rules_block)
    if description is not None:
        context = _append_description(context, description)
    return EgressResult(
        mode="raw",
        user_content=context,
        report_block={"mode": "raw", "context_files": list(context_files)},
    )


def _append_description(context: str, description: str) -> str:
    return (
        f"{context.rstrip()}\n\n"
        "<author-stated-intent>\n"
        "Author's stated intent:\n"
        f"{description.rstrip()}\n"
        "</author-stated-intent>\n"
    )
