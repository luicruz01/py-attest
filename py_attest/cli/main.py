import json
import sys
from pathlib import Path

import click

from py_attest import __version__
from py_attest.check.runner import CheckExecutionError, run_check
from py_attest.config import Config, load_config
from py_attest.doctor.check import DoctorContext
from py_attest.doctor.report import to_json, to_markdown
from py_attest.doctor.runner import run_doctor
from py_attest.errors import (
    AttestError,
    BlockedError,
    IncompatibleError,
    InconclusiveError,
    StandardsDriftError,
)
from py_attest.review.diff import DiffError, _branch_diff, acquire_patch
from py_attest.review.reviewer import run_review
from py_attest.standards.build import build as build_standards
from py_attest.standards.lint import lint as lint_standards
from py_attest.standards.registry import RegistryError


def exit_code_for(exc: BaseException) -> int:
    """Map an exception to its contractual exit code (TRD §4.1)."""
    if isinstance(exc, click.UsageError):
        return 64
    if isinstance(exc, (BlockedError, StandardsDriftError)):
        return 2
    if isinstance(exc, IncompatibleError):
        return 3
    if isinstance(exc, InconclusiveError):
        return 4
    return 4


class AttestGroup(click.Group):
    """Click group that owns the exception -> exit code mapping in one place."""

    def main(self, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("standalone_mode", False)
        try:
            rv = super().main(*args, **kwargs)
        except click.UsageError as exc:
            exc.show()
            sys.exit(exit_code_for(exc))
        except AttestError as exc:
            click.echo(str(exc), err=True)
            sys.exit(exit_code_for(exc))
        except Exception as exc:
            click.echo(f"error: {exc}", err=True)
            sys.exit(exit_code_for(exc))
        sys.exit(rv if isinstance(rv, int) else 0)


@click.group(cls=AttestGroup)
@click.version_option(__version__, prog_name="attest")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """attest: CLI + quality-gate engine for Python repos."""
    ctx.obj = load_config()


@cli.command()
@click.argument("path", required=False, type=click.Path())
@click.option("--no-tests", is_flag=True)
@click.option("--no-lint", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def check(path: str | None, no_tests: bool, no_lint: bool, as_json: bool) -> int:
    """Run deterministic checks (ruff, pytest+cov, gitleaks) against the repo."""
    target = Path(path) if path else Path.cwd()
    try:
        result = run_check(path=target, no_tests=no_tests, no_lint=no_lint)
    except CheckExecutionError as exc:
        raise InconclusiveError(str(exc)) from exc

    if as_json:
        click.echo(json.dumps(result, indent=2))
    else:
        click.echo(f"Verdict: {result['verdict']}")
        for finding in result["findings"]:
            click.echo(f"- [{finding['severity']}] {finding['rule']}: {finding['title']}")
    return result["exit_code"]


@cli.command()
@click.option("--branch")
@click.option("--base")
@click.option("--head")
@click.option("--diff-file", type=click.Path(exists=True))
@click.option("--provider", type=click.Choice(["fake", "openai", "anthropic"]))
@click.option("--fake-response")
@click.option("--egress", type=click.Choice(["raw", "minimized"]))
@click.option("--evidence-policy", type=click.Choice(["degrade", "fail_closed"]))
@click.option("--description")
@click.option("--out", type=click.Path())
@click.option("--json", "as_json", is_flag=True)
@click.option("--prompt-version")
@click.option("--no-llm", is_flag=True)
@click.pass_obj
def review(
    config: Config,
    branch: str | None,
    base: str | None,
    head: str | None,
    diff_file: str | None,
    provider: str | None,
    fake_response: str | None,
    egress: str | None,
    evidence_policy: str | None,
    description: str | None,
    out: str | None,
    as_json: bool,
    prompt_version: str | None,
    no_llm: bool,
) -> int:
    """Run the LLM-backed review over a diff. Never executes repo code."""
    if not any([branch, head, diff_file]):
        raise click.UsageError("review requires one of --branch, --head, or --diff-file")

    repo_root = Path.cwd()
    branch_source = None
    if diff_file:
        diff_path = Path(diff_file)
        diff = diff_path.read_text(encoding="utf-8")
        source_name = diff_path.name
    elif head:
        base_ref = base or config.base_branch
        try:
            diff = acquire_patch(repo_root, base_ref, head, config.limits).raw_text
        except DiffError as exc:
            raise InconclusiveError(str(exc)) from exc
        source_name = head
        branch_source = (base_ref, head)
    else:
        base_ref = base or config.base_branch
        try:
            diff = _branch_diff(repo_root, base_ref, branch, config.limits)
        except DiffError as exc:
            raise InconclusiveError(str(exc)) from exc
        source_name = branch
        branch_source = (base_ref, branch)

    out_dir = Path(out) if out else Path(config.reports_dir)
    outcome = run_review(
        diff=diff,
        source_name=source_name,
        repo_root=repo_root,
        config=config,
        out_dir=out_dir,
        description=description,
        prompt_version=prompt_version or "v3",
        no_llm=no_llm,
        provider=provider,
        evidence_policy=evidence_policy,
        egress=egress,
        fake_response=fake_response,
        branch_source=branch_source,
        as_json=as_json,
    )
    return outcome.exit_code


@cli.command()
@click.option("--branch", required=True)
@click.option("--base")
@click.option("--out", type=click.Path())
@click.option("--no-llm", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def gate(
    config: Config,
    branch: str,
    base: str | None,
    out: str | None,
    no_llm: bool,
    as_json: bool,
) -> int:
    """Run check + review over base...branch; exit code is the max of both."""
    repo_root = Path.cwd()

    try:
        check_result = run_check(path=repo_root)
    except CheckExecutionError as exc:
        raise InconclusiveError(str(exc)) from exc

    check_exit = check_result["exit_code"]
    if check_exit != 0:
        # check failed or blocked: don't spend LLM budget or expose secrets on a broken tree.
        if as_json:
            click.echo(
                json.dumps(
                    {
                        "stage": "gate",
                        "exit_code": check_exit,
                        "check": check_result,
                        "review": None,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(
                f"check verdict: {check_result['verdict']} (exit {check_exit}); skipping review"
            )
        return check_exit

    base_ref = base or config.base_branch
    try:
        diff = _branch_diff(repo_root, base_ref, branch, config.limits)
    except DiffError as exc:
        raise InconclusiveError(str(exc)) from exc

    out_dir = Path(out) if out else Path(config.reports_dir)
    review_outcome = run_review(
        diff=diff,
        source_name=branch,
        repo_root=repo_root,
        config=config,
        out_dir=out_dir,
        no_llm=no_llm,
        branch_source=(base_ref, branch),
        as_json=as_json,
    )
    exit_code = max(check_exit, review_outcome.exit_code)

    if as_json:
        click.echo(
            json.dumps(
                {
                    "stage": "gate",
                    "exit_code": exit_code,
                    "check": check_result,
                    "review": review_outcome.json_report,
                },
                indent=2,
            )
        )
    return exit_code


@cli.command()
@click.argument("path", required=False, type=click.Path())
@click.option("--strict", is_flag=True, help="Exit 2 if any S1 check fails.")
@click.option("--compat", is_flag=True, help="Restrict to the ADR-003 compat_* checks.")
@click.option("--offline", is_flag=True, help="Skip network-dependent checks (none yet).")
@click.option("--json", "as_json", is_flag=True)
@click.option("--only", help="Comma-separated check ids to run instead of the full set.")
def doctor(
    path: str | None,
    strict: bool,
    compat: bool,
    offline: bool,
    as_json: bool,
    only: str | None,
) -> int:
    """Audit a repo against the standards registry and the ADR-003 compat contract."""
    target = Path(path) if path else Path.cwd()
    only_ids = {check_id.strip() for check_id in only.split(",")} if only else None
    ctx = DoctorContext(repo_root=target, offline=offline, config=load_config(target))

    report = run_doctor(ctx, only=only_ids, compat=compat, strict=strict)

    if as_json:
        click.echo(json.dumps(to_json(report), indent=2))
    else:
        click.echo(to_markdown(report))

    return 2 if report.blocked else 0


@cli.command()
def new() -> None:
    """Scaffold a new repo from the py-attest-template."""
    click.echo("new: not implemented yet")


@cli.command()
def upgrade() -> None:
    """Upgrade an existing repo's template/config to the current version."""
    click.echo("upgrade: not implemented yet")


@cli.command()
@click.option("--provider", type=click.Choice(["fake", "openai", "anthropic"]))
def calibrate(provider: str | None) -> None:
    """Calibrate provider/model settings against the eval golden set."""
    click.echo("calibrate: not implemented yet")


@cli.group()
def standards() -> None:
    """Build, lint, or scaffold standards.yml / TEAM-STANDARDS.md."""


@standards.command()
@click.option("--check", is_flag=True, help="Fail with exit 2 if TEAM-STANDARDS.md is out of date.")
@click.pass_obj
def build(config: Config, check: bool) -> int:
    """Build TEAM-STANDARDS.md from core/domain standards.yml."""
    repo_root = Path.cwd()
    core = repo_root / config.standards.core
    domain = repo_root / config.standards.domain
    output = repo_root / config.standards.output
    try:
        build_standards(core, domain, output, check=check)
    except RegistryError as exc:
        # A malformed/missing core.standards.yml is a usage error, same as `lint`'s
        # behavior for the identical input (exit 64) -- not an unmapped exit 4.
        # StandardsDriftError (raised directly by build_standards on drift) is a
        # ValueError-derived AttestError sibling, not a RegistryError, and is
        # deliberately left to propagate untouched to its own exit-2 path.
        raise click.UsageError(str(exc)) from exc
    click.echo(f"wrote {output}" if not check else f"{output} is up to date")
    return 0


@standards.command()
@click.pass_obj
def lint(config: Config) -> int:
    """Lint standards.yml against the ADR-001 schema."""
    repo_root = Path.cwd()
    core = repo_root / config.standards.core
    domain = repo_root / config.standards.domain
    errors = lint_standards(core, domain)
    if errors:
        raise click.UsageError("\n".join(error.message for error in errors))
    click.echo("standards.yml is valid")
    return 0


@standards.command(name="new-rule")
def new_rule() -> None:
    """Scaffold a new standards rule entry."""
    click.echo("new-rule: not implemented yet")
