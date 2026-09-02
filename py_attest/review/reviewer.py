"""Orchestrate the review pipeline: diff -> secrets firewall -> egress -> provider ->
validation -> policy -> report. Never executes code from the reviewed repository.
"""

import json
import re
from pathlib import Path
from typing import Any, NamedTuple

import click

from py_attest.config import Config
from py_attest.errors import InconclusiveError
from py_attest.llm.providers.openai import LLMReviewError, MissingProviderKeyError, review_context
from py_attest.review.context_pack import ContextPackError, build_context, render_rules_block
from py_attest.review.diff import DiffError, _gate_commit, _merge_base, _resolve_sha, patch_sha256
from py_attest.review.policy import verdict
from py_attest.review.postfilter import merge_findings
from py_attest.review.report import build_json_report, render_markdown
from py_attest.review.secrets_gate import SecretsGateError, findings_for_diff
from py_attest.review.validation import validate_findings
from py_attest.standards.registry import RegistryError, load_registry

FIREWALL_SKIP_NOTE = "LLM review skipped: secret detected in diff; diff was not transmitted."
CONTEXT_FIREWALL_SKIP_NOTE = (
    "LLM review skipped: secret detected in the assembled review context "
    "(context_files or --description); nothing was transmitted."
)
_STANDARDS_DEFAULTS_DIR = Path(__file__).resolve().parents[1] / "standards" / "defaults"


class ReviewOutcome(NamedTuple):
    """Result of :func:`run_review`: the exit code and the full schema_version 3 report."""

    exit_code: int
    json_report: dict[str, Any]


def _standards_paths(repo_root: Path, config: Config) -> tuple[Path, Path]:
    """Repo-local standards.yml if present, else the packaged defaults -- so a repo that
    hasn't run `attest new`/`attest upgrade` yet still gets a working review (spec §5.3).
    """
    core = repo_root / config.standards.core
    domain = repo_root / config.standards.domain
    if not core.is_file():
        core = _STANDARDS_DEFAULTS_DIR / "core.standards.yml"
    if not domain.is_file():
        domain = _STANDARDS_DEFAULTS_DIR / "domain.standards.yml"
    return core, domain


def run_review(
    *,
    diff: str,
    source_name: str,
    repo_root: Path,
    config: Config,
    out_dir: Path,
    description: str | None = None,
    prompt_version: str = "v3",
    no_llm: bool = False,
    provider: str | None = None,
    evidence_policy: str | None = None,
    branch_source: tuple[str, str] | None = None,
    as_json: bool = False,
) -> ReviewOutcome:
    """Run the full review pipeline, write JSON+MD reports, return the outcome."""
    if config.egress != "raw":
        raise click.UsageError(f"egress={config.egress!r} is not implemented yet (F0.3)")
    resolved_evidence_policy = evidence_policy or config.evidence_policy

    provider_name = provider or config.provider

    try:
        secret_findings = findings_for_diff(diff, repo_root)
    except SecretsGateError as exc:
        raise InconclusiveError(str(exc)) from exc

    review: dict[str, Any]
    metadata: dict[str, Any]
    review_complete: bool = True

    if secret_findings:
        review = _blocked_review(secret_findings, note=FIREWALL_SKIP_NOTE, anchor_to_diff=True)
        llm_layer = "skipped:secret_detected"
        metadata = {}
    elif no_llm:
        review = {"findings": [], "summary": "LLM review skipped (--no-llm).", "filtered_out": []}
        llm_layer = "skipped:--no-llm"
        metadata = {}
    elif provider_name != "openai":
        raise click.UsageError(f"provider {provider_name!r} is not implemented yet (F0.3)")
    else:
        try:
            core_path, domain_path = _standards_paths(repo_root, config)
            registry = load_registry(core_path, domain_path)
        except RegistryError as exc:
            raise InconclusiveError(str(exc)) from exc
        rules_block = render_rules_block(registry.llm_rules())
        try:
            context = build_context(diff, repo_root, config.context_files, rules_block)
            if description is not None:
                context = _append_description(context, description)
        except ContextPackError as exc:
            raise InconclusiveError(str(exc)) from exc

        # MAX_DIFF_BYTES (llm/providers/openai.py) only bounds `diff`; the payload
        # actually sent to the provider is `context` (diff + context_files +
        # --description), which is otherwise unbounded -- a repo could configure a huge
        # context_files list, or a caller could pass a huge --description, to bypass that
        # limit entirely. Reuse the existing acquisition limit rather than a new field.
        context_bytes = len(context.encode("utf-8"))
        if context_bytes > config.limits.max_patch_bytes:
            raise InconclusiveError(
                f"review context too large: {context_bytes} bytes exceeds the "
                f"{config.limits.max_patch_bytes}-byte limit (context_files/--description "
                "included)"
            )

        # The diff-only scan above covers only `diff`; context_files and --description
        # are folded into `context` and transmitted too, so they must clear the same
        # firewall before any network call -- never trust the diff scan alone to cover
        # the full payload sent to the provider.
        try:
            context_secret_findings = findings_for_diff(context, repo_root)
        except SecretsGateError as exc:
            raise InconclusiveError(str(exc)) from exc

        if context_secret_findings:
            secret_findings = context_secret_findings
            # findings_for_diff parses its input as a unified diff to locate a secret;
            # applied to `context` it can latch onto the diff embedded inside it and
            # report a fabricated file:line for a secret that was actually in a
            # context_file or --description. Don't trust that location -- say so plainly.
            review = _blocked_review(
                secret_findings, note=CONTEXT_FIREWALL_SKIP_NOTE, anchor_to_diff=False
            )
            llm_layer = "skipped:secret_detected"
            metadata = {}
        else:
            try:
                raw_review = review_context(
                    context, diff, prompt_version=prompt_version, model=config.model
                )
                llm_layer = "ran"
            except MissingProviderKeyError:
                raw_review = {"findings": [], "summary": "LLM review skipped (no provider key)."}
                llm_layer = "skipped:no_provider_key"
            except LLMReviewError as exc:
                raise InconclusiveError(str(exc)) from exc
            metadata = raw_review.pop("metadata", {})
            validation = validate_findings(
                raw_review["findings"],
                registry=registry,
                diff=diff,
                evidence_policy=resolved_evidence_policy,
            )
            # F0.3 seam (spec §5.3): once review/deterministic.py exists, prepend its
            # findings here -- `merge_findings(deterministic_findings + validation.findings)`
            # -- so a tie against an equal-strength LLM duplicate favors the deterministic
            # finding (postfilter.merge_findings keeps the first-seen item on a tie).
            review = {
                "findings": merge_findings(validation.findings),
                "summary": raw_review.get("summary", ""),
                "filtered_out": validation.filtered_out,
            }
            review_complete = validation.review_complete
            if not review_complete:
                reasons = "/".join(sorted(validation.invalidated_reasons))
                review["note"] = (
                    f"LLM review invalidated: {validation.invalid_count} of "
                    f"{validation.total_count} findings failed validation ({reasons}); "
                    "response discarded (fail_closed)."
                )

    secrets_layer = "fail" if secret_findings else "pass"

    try:
        gate_commit = _gate_commit(repo_root)
    except DiffError as exc:
        raise InconclusiveError(str(exc)) from exc

    source: dict[str, Any] = {
        "base_sha": None,
        "head_sha": None,
        "merge_base_sha": None,
        "patch_sha256": patch_sha256(diff),
    }
    if branch_source is not None:
        base, branch = branch_source
        try:
            source["base_sha"] = _resolve_sha(repo_root, base)
            source["head_sha"] = _resolve_sha(repo_root, branch)
            source["merge_base_sha"] = _merge_base(repo_root, base, branch)
        except DiffError as exc:
            raise InconclusiveError(str(exc)) from exc

    temperature = metadata.get("temperature", "not-used")
    review["meta"] = {
        "prompt_version": prompt_version,
        "model": config.model,
        "temperature": temperature,
        "gate_commit": gate_commit,
    }
    verdict_name, exit_code = verdict(review["findings"], review_complete=review_complete)
    review["verdict"] = verdict_name

    json_report = build_json_report(
        review=review,
        stage="review",
        layers={
            "deterministic": "skipped:not_implemented",
            "secrets": secrets_layer,
            "llm": llm_layer,
        },
        egress={"mode": config.egress, "context_files": list(config.context_files)},
        source=source,
        review_complete=review_complete,
        meta_extra={
            "prompt_version": prompt_version,
            "provider": provider_name,
            "model": config.model,
            "temperature_applied": temperature,
            "gate_commit": gate_commit,
        },
    )

    output_name = _safe_output_name(source_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{output_name}.json"
    markdown_path = out_dir / f"{output_name}.md"
    json_path.write_text(json.dumps(json_report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(source_name, review), encoding="utf-8")

    if as_json:
        click.echo(json.dumps(json_report, indent=2))
    else:
        click.echo(f"Verdict: {verdict_name}\nWrote {json_path} and {markdown_path}")
    return ReviewOutcome(exit_code=exit_code, json_report=json_report)


def _blocked_review(
    secret_findings: list[dict[str, Any]], *, note: str, anchor_to_diff: bool
) -> dict[str, Any]:
    """Build the review dict for a firewall-blocked run, bypassing postfilter entirely.

    `postfilter.filter_findings` degrades a finding's confidence when its evidence can't
    be re-anchored to an added diff line -- correct for model output, wrong here: gitleaks
    findings are deterministic ground truth, and a real secret must always BLOCK, never
    quietly soften to a low-confidence COMMENT because it came from a context file or
    --description rather than the diff itself.

    `anchor_to_diff=False` means the findings came from scanning the assembled context
    (context_files/--description), not `diff` -- `findings_for_diff`'s file:line
    inference assumes its input IS a unified diff, so applied to `context` it can latch
    onto the diff embedded inside it and report a location for a different file
    entirely. Don't publish a fabricated pointer; say plainly where it can't be trusted.
    """
    findings = []
    for finding in secret_findings:
        finding = {**finding, "evidence_verified": True}
        if not anchor_to_diff:
            finding["path"] = "<review context: context_files or --description>"
            finding["side"] = None
            finding["line_start"] = None
            finding["line_end"] = None
        findings.append(finding)
    return {
        "findings": findings,
        "summary": "Secret detection blocked review before any LLM transmission.",
        "filtered_out": [],
        "note": note,
    }


def _append_description(context: str, description: str) -> str:
    return (
        f"{context.rstrip()}\n\n"
        "<author-stated-intent>\n"
        "Author's stated intent:\n"
        f"{description.rstrip()}\n"
        "</author-stated-intent>\n"
    )


def _safe_output_name(source_name: str) -> str:
    output_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_name).strip("-.")
    return output_name or "review"
