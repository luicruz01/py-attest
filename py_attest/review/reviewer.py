"""Orchestrate the review pipeline (TRD SS5): diff -> deterministic -> secrets firewall ->
egress -> provider -> validation -> postfilter -> policy -> report. Never executes code
from the reviewed repository.
"""

import json
import re
from pathlib import Path
from typing import Any, NamedTuple

import click

from py_attest.config import Config
from py_attest.errors import InconclusiveError
from py_attest.llm.policy import run_with_policy
from py_attest.llm.prompts import PromptError, read_system_prompt
from py_attest.llm.registry import ProviderNotRegisteredError, load_provider
from py_attest.llm.types import Provider, ProviderFailure, ProviderRequest
from py_attest.review.context_pack import ContextPackError, render_rules_block
from py_attest.review.deterministic import run_checks as run_deterministic_checks
from py_attest.review.diff import (
    DiffError,
    _gate_commit,
    _merge_base,
    _resolve_sha,
    parse_unified_diff,
    patch_sha256,
)
from py_attest.review.egress import EgressResult
from py_attest.review.egress.minimized import EgressError, build_minimized_egress
from py_attest.review.egress.raw import build_raw_egress
from py_attest.review.models import REVIEW_SCHEMA, SchemaValidationError, validate_review_result
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
_REQUEST_TEMPERATURE = 0
_DETERMINISTIC_SECRET_RULE_ID = "secrets-1"  # noqa: S105 - a rule id, not a credential


class ReviewOutcome(NamedTuple):
    """Result of :func:`run_review`: the exit code and the full schema_version 3 report."""

    exit_code: int
    json_report: dict[str, Any]


def _standards_paths(repo_root: Path, config: Config) -> tuple[Path, Path]:
    """Repo-local standards.yml if present, else the packaged defaults -- so a repo that
    hasn't run `attest new`/`attest upgrade` yet still gets a working review (spec SS5.3).
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
    egress: str | None = None,
    fake_response: str | None = None,
    evidence_policy: str | None = None,
    branch_source: tuple[str, str] | None = None,
    as_json: bool = False,
) -> ReviewOutcome:
    """Run the full review pipeline, write JSON+MD reports, return the outcome."""
    egress_mode = egress or config.egress
    egress_report_block = _egress_report_block(egress_mode, config.context_files)
    resolved_evidence_policy = evidence_policy or config.evidence_policy
    provider_name = provider or config.provider

    diff_bytes = len(diff.encode("utf-8"))
    if diff_bytes > config.limits.max_patch_bytes:
        raise InconclusiveError(
            f"diff too large: {diff_bytes} bytes exceeds the "
            f"{config.limits.max_patch_bytes}-byte limit"
        )

    try:
        core_path, domain_path = _standards_paths(repo_root, config)
        registry = load_registry(core_path, domain_path)
    except RegistryError as exc:
        raise InconclusiveError(str(exc)) from exc

    # Deterministic findings are computed once, up front, regardless of which branch
    # below runs -- they are trusted by construction (not LLM output) and never go
    # through review/validation.py (which rejects any rule_id whose registry mode isn't
    # "llm"). They're merged into `review["findings"]` in exactly one place, at the end
    # of this function, common to all three branches below.
    try:
        changed_files = parse_unified_diff(diff)
    except DiffError as exc:
        raise InconclusiveError(str(exc)) from exc
    deterministic_findings = run_deterministic_checks(changed_files, registry)
    deterministic_secret_findings = [
        f for f in deterministic_findings if f["rule_id"] == _DETERMINISTIC_SECRET_RULE_ID
    ]

    # The gitleaks firewall always runs, regardless of what the deterministic layer
    # already found -- CLAUDE.md: it "runs before any LLM call" and a missing binary is
    # "never a silent skip". If the same secret trips both (both now cite rule_id
    # "secrets-1" -- one id per violation type, regardless of detection mechanism), the
    # final merge_findings call below collapses them into one finding when they share a
    # location; distinct locations survive as distinct findings.
    try:
        secret_findings = findings_for_diff(diff, repo_root)
    except SecretsGateError as exc:
        raise InconclusiveError(str(exc)) from exc

    review: dict[str, Any]
    metadata: dict[str, Any]
    review_complete: bool = True

    if deterministic_secret_findings or secret_findings:
        review = _blocked_review(secret_findings, note=FIREWALL_SKIP_NOTE, anchor_to_diff=True)
        llm_layer = "skipped:secret_detected"
        metadata = {}
    elif no_llm:
        review = {"findings": [], "summary": "LLM review skipped (--no-llm).", "filtered_out": []}
        llm_layer = "skipped:--no-llm"
        metadata = {}
    else:
        rules_block = render_rules_block(registry.llm_rules())
        try:
            egress_result = _build_egress(
                egress_mode, diff, repo_root, config, description, source_name, rules_block
            )
        except (EgressError, ContextPackError) as exc:
            raise InconclusiveError(str(exc)) from exc

        # The diff-only scans above cover only `diff`; the payload actually sent to the
        # provider is the egress result (raw: rules block + diff + context_files/
        # --description; minimized: rules block + the minimized patch + title/
        # description), which is otherwise unbounded and must clear its own size and
        # secret-firewall checks before any network call -- never trust the diff-only
        # checks to cover the full payload.
        context_bytes = len(egress_result.user_content.encode("utf-8"))
        if context_bytes > config.limits.max_patch_bytes:
            raise InconclusiveError(
                f"review context too large: {context_bytes} bytes exceeds the "
                f"{config.limits.max_patch_bytes}-byte limit (context_files/--description "
                "included)"
            )

        try:
            context_secret_findings = findings_for_diff(
                egress_result.user_content, repo_root, require_location=False
            )
        except SecretsGateError as exc:
            raise InconclusiveError(str(exc)) from exc

        if context_secret_findings:
            # findings_for_diff parses its input as a unified diff to locate a secret;
            # applied to the assembled egress payload it can latch onto the diff
            # embedded inside it and report a fabricated file:line for a secret that was
            # actually in a context_file or --description. Don't trust that location.
            review = _blocked_review(
                context_secret_findings, note=CONTEXT_FIREWALL_SKIP_NOTE, anchor_to_diff=False
            )
            llm_layer = "skipped:secret_detected"
            metadata = {}
        else:
            try:
                raw_review, metadata = _call_provider(
                    provider_name=provider_name,
                    config=config,
                    fake_response=fake_response,
                    egress_result=egress_result,
                    prompt_version=prompt_version,
                )
                llm_layer = "ran"
            except _NoProviderKey:
                raw_review = {"findings": [], "summary": "LLM review skipped (no provider key)."}
                metadata = {}
                llm_layer = "skipped:no_provider_key"

            validation = validate_findings(
                raw_review["findings"],
                registry=registry,
                diff=diff,
                evidence_policy=resolved_evidence_policy,
            )
            review = {
                "findings": validation.findings,
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

    # F0.3 seam (spec SS5.3): deterministic findings are prepended, not appended --
    # merge_findings keeps the first-seen item on a tie, so a deterministic finding wins
    # over an equal-strength duplicate from the LLM or from gitleaks (also merge_findings
    # keeps here, above under "trust the firewall unconditionally, dedup afterward").
    # `review_complete=False` alongside a deterministic-origin BLOCK is safe by
    # review/policy.py's own documented contract: BLOCK always wins over INCONCLUSIVE,
    # and a deterministic finding is never the "untrusted LLM-origin" content that
    # contract is guarding against.
    review["findings"] = merge_findings([*deterministic_findings, *review["findings"]])
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

    temperature = metadata.get("temperature_applied", "not-used")
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
            "deterministic": "ran",
            "secrets": secrets_layer,
            "llm": llm_layer,
        },
        egress=egress_report_block,
        source=source,
        review_complete=review_complete,
        meta_extra={
            "prompt_version": prompt_version,
            "provider": provider_name,
            "model": config.model,
            "temperature_applied": temperature,
            "attempts": metadata.get("attempts"),
            "usage": metadata.get("usage"),
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


class _NoProviderKey(Exception):
    """Internal signal: the selected provider has no key/extra configured."""


def _egress_report_block(egress_mode: str, context_files: tuple[str, ...]) -> dict[str, Any]:
    """The report's `egress` block (TRD SS4.3), shaped by the *configured* mode --
    computed upfront so an unsupported `egress` value is rejected the same way whether
    or not egress assembly ever actually runs (e.g. the diff is blocked before it).
    """
    if egress_mode == "raw":
        return {"mode": "raw", "context_files": list(context_files)}
    if egress_mode == "minimized":
        return {"mode": "minimized", "payload_version": "MINIMIZED_PATCH_V2"}
    raise click.UsageError(f"egress={egress_mode!r} is not implemented yet")


def _build_egress(
    egress_mode: str,
    diff: str,
    repo_root: Path,
    config: Config,
    description: str | None,
    source_name: str,
    rules_block: str,
) -> EgressResult:
    if egress_mode == "raw":
        return build_raw_egress(
            diff, repo_root, config.context_files, description=description, rules_block=rules_block
        )
    return build_minimized_egress(
        diff, title=source_name, description=description, rules_block=rules_block
    )


def _build_provider(name: str, *, config: Config, fake_response: str | None) -> Provider:
    try:
        provider_class = load_provider(name)
    except ProviderNotRegisteredError as exc:
        raise click.UsageError(str(exc)) from exc
    if name == "fake":
        if not fake_response:
            raise click.UsageError("--fake-response is required when --provider fake")
        return provider_class(fake_response)  # type: ignore[call-arg]
    return provider_class(timeout=config.limits.provider_timeout)  # type: ignore[call-arg]


def _call_provider(
    *,
    provider_name: str,
    config: Config,
    fake_response: str | None,
    egress_result: EgressResult,
    prompt_version: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    provider_instance = _build_provider(provider_name, config=config, fake_response=fake_response)
    try:
        system_prompt = read_system_prompt(prompt_version)
    except PromptError as exc:
        raise InconclusiveError(str(exc)) from exc

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
        if exc.category == "not_configured":
            raise _NoProviderKey from exc
        raise InconclusiveError(str(exc)) from exc

    try:
        decoded = json.loads(response.raw_json)
        result = validate_review_result(decoded)
    except (json.JSONDecodeError, SchemaValidationError) as exc:
        raise InconclusiveError(f"provider returned an invalid structured review: {exc}") from exc

    usage = None
    if response.usage is not None:
        usage = {
            "input_tokens": response.usage.input_tokens,
            "cached_input_tokens": response.usage.cached_input_tokens,
            "output_tokens": response.usage.output_tokens,
            "reasoning_tokens": response.usage.reasoning_tokens,
        }
    metadata = {
        "temperature_applied": response.temperature_applied,
        "attempts": response.attempts,
        "usage": usage,
    }
    return result, metadata


def _blocked_review(
    secret_findings: list[dict[str, Any]], *, note: str, anchor_to_diff: bool
) -> dict[str, Any]:
    """Build the review dict for a firewall-blocked run, bypassing validation entirely.

    `review/validation.py`'s `degrade`/`fail_closed` policy exists to handle *untrusted*
    LLM-origin findings whose rule_id/location can't be verified -- correct for model
    output, wrong here: gitleaks findings are deterministic ground truth, and a real
    secret must always BLOCK, never quietly degrade (or, under fail_closed, be discarded)
    the way an unverifiable LLM finding would be.

    `anchor_to_diff=False` means the findings came from scanning the assembled egress
    payload (context_files/--description), not `diff` -- `findings_for_diff`'s file:line
    inference assumes its input IS a unified diff, so applied to the egress payload it
    can latch onto the diff embedded inside it and report a location for a different
    file entirely. Don't publish a fabricated pointer; say plainly where it can't be
    trusted. This only touches the findings passed in here (the firewall hit itself) --
    deterministic findings merged in afterward keep their real, verified location.
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


def _safe_output_name(source_name: str) -> str:
    output_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_name).strip("-.")
    return output_name or "review"
