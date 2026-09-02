import sys

import click

from py_attest import __version__
from py_attest.config import load_config
from py_attest.errors import AttestError, BlockedError, IncompatibleError, InconclusiveError


def exit_code_for(exc: BaseException) -> int:
    """Map an exception to its contractual exit code (TRD §4.1)."""
    if isinstance(exc, click.UsageError):
        return 64
    if isinstance(exc, BlockedError):
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
def check(path: str | None, no_tests: bool, no_lint: bool, as_json: bool) -> None:
    """Run deterministic checks (ruff, pytest+cov, gitleaks) against the repo."""
    click.echo("check: not implemented yet")


@cli.command()
@click.option("--branch")
@click.option("--base")
@click.option("--head")
@click.option("--diff-file", type=click.Path())
@click.option("--provider", type=click.Choice(["fake", "openai", "anthropic"]))
@click.option("--fake-response")
@click.option("--egress", type=click.Choice(["raw", "minimized"]))
@click.option("--description")
@click.option("--out", type=click.Path())
@click.option("--json", "as_json", is_flag=True)
@click.option("--prompt-version")
def review(
    branch: str | None,
    base: str | None,
    head: str | None,
    diff_file: str | None,
    provider: str | None,
    fake_response: str | None,
    egress: str | None,
    description: str | None,
    out: str | None,
    as_json: bool,
    prompt_version: str | None,
) -> None:
    """Run the LLM-backed review over a diff. Never executes repo code."""
    if not any([branch, base, head, diff_file]):
        raise click.UsageError("review requires one of --branch, --base, --head, or --diff-file")
    click.echo("review: not implemented yet")


@cli.command()
@click.option("--branch", required=True)
@click.option("--base")
@click.option("--out", type=click.Path())
@click.option("--no-llm", is_flag=True)
def gate(branch: str, base: str | None, out: str | None, no_llm: bool) -> None:
    """Run check + review over base...branch; exit code is the max of both."""
    click.echo("gate: not implemented yet")


@cli.command()
def doctor() -> None:
    """Report the registered check catalog and environment diagnostics."""
    click.echo("no checks registered")


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
def build() -> None:
    """Build TEAM-STANDARDS.md from core/domain standards.yml."""
    click.echo("build: not implemented yet")


@standards.command()
def lint() -> None:
    """Lint standards.yml against the ADR-001 schema."""
    click.echo("lint: not implemented yet")


@standards.command(name="new-rule")
def new_rule() -> None:
    """Scaffold a new standards rule entry."""
    click.echo("new-rule: not implemented yet")
