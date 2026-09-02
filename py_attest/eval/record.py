"""Record one real provider call per branch x egress mode into
eval/golden/<branch>/provider_response.<egress>.json (spec SS4). Reuses the exact
request-building internals reviewer.py uses for a live `attest review`, so a recording
is provably built from the same ProviderRequest the real pipeline sends -- everything
downstream of the network call (validation, postfilter, policy, report) then runs for
real when the recording is replayed by metrics.py's evaluate().

Tested here with --provider fake only. A real recording needs `uv run python -m
py_attest.eval.record --provider openai --egress raw ...` with a real API key --
run by a human, never from this package's own test suite (CLAUDE.md: no network calls
in tests; API keys only from environment variables).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import click

from py_attest.config import Config
from py_attest.llm.policy import run_with_policy
from py_attest.llm.prompts import PromptError, read_system_prompt
from py_attest.llm.types import ProviderFailure, ProviderRequest
from py_attest.review.context_pack import render_rules_block
from py_attest.review.models import REVIEW_SCHEMA
from py_attest.review.reviewer import _build_egress, _build_provider, _standards_paths
from py_attest.standards.registry import RegistryError, load_registry

_EGRESS_MODES = {"raw", "minimized"}
_REQUEST_TEMPERATURE = 0


class RecordError(ValueError):
    """Raised when a recording cannot be produced."""


def record_response(
    *,
    diff_path: Path,
    provider_name: str,
    egress_mode: str,
    out_path: Path,
    config: Config,
    repo_root: Path,
    fake_response: str | None = None,
    prompt_version: str = "v3",
    branch: str | None = None,
    force: bool = False,
) -> None:
    """Call `provider_name` exactly once and write its raw structured output to
    `out_path`, verbatim -- never decoded or validated (that happens on replay, in
    reviewer.run_review via metrics.py's evaluate(), so recording and replay can never
    silently disagree about what "valid" means)."""
    if out_path.exists() and not force:
        raise RecordError(
            f"{out_path} already exists; pass --force to overwrite a sealed recording"
        )
    if egress_mode not in _EGRESS_MODES:
        raise RecordError(f"unknown egress mode: {egress_mode!r}")

    try:
        diff = diff_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecordError(f"cannot read diff: {exc}") from exc

    try:
        core_path, domain_path = _standards_paths(repo_root, config)
        registry = load_registry(core_path, domain_path)
    except RegistryError as exc:
        raise RecordError(str(exc)) from exc

    rules_block = render_rules_block(registry.llm_rules())
    source_name = branch or diff_path.stem
    egress_result = _build_egress(
        egress_mode, diff, repo_root, config, None, source_name, rules_block
    )

    try:
        provider_instance = _build_provider(
            provider_name, config=config, fake_response=fake_response
        )
    except click.UsageError as exc:
        # _build_provider raises click.UsageError for an unregistered provider name or a
        # missing --fake-response; record.py has no click.Group of its own to catch
        # this, so surface it uniformly as RecordError like every other failure here.
        raise RecordError(str(exc)) from exc

    try:
        system_prompt = read_system_prompt(prompt_version)
    except PromptError as exc:
        raise RecordError(str(exc)) from exc

    request = ProviderRequest(
        system_prompt=system_prompt,
        user_content=egress_result.user_content,
        output_schema=REVIEW_SCHEMA,
        model=config.model,
        temperature=_REQUEST_TEMPERATURE,
    )
    try:
        response = run_with_policy(provider_instance, request)
    except ProviderFailure as exc:
        raise RecordError(f"provider call failed: {exc}") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(response.raw_json, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, required=True, dest="diff_path")
    parser.add_argument("--provider", required=True, dest="provider_name")
    parser.add_argument("--egress", required=True, choices=sorted(_EGRESS_MODES))
    parser.add_argument("--out", type=Path, required=True, dest="out_path")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), dest="repo_root")
    parser.add_argument("--fake-response")
    parser.add_argument("--branch")
    parser.add_argument("--prompt-version", default="v3")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        record_response(
            diff_path=args.diff_path,
            provider_name=args.provider_name,
            egress_mode=args.egress,
            out_path=args.out_path,
            config=Config(),
            repo_root=args.repo_root,
            fake_response=args.fake_response,
            prompt_version=args.prompt_version,
            branch=args.branch,
            force=args.force,
        )
    except RecordError as exc:
        sys.stderr.write(f"record failed: {exc}\n")
        return 2

    sys.stdout.write(f"wrote {args.out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
