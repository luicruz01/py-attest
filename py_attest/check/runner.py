"""Run ruff, pytest+coverage, and gitleaks over the working tree.

Each layer's failure becomes a deterministic finding in the same shape review findings
use, so the verdict is computed by the one policy engine (review/policy.py) rather than
a second mapping table.
"""

import json
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

from py_attest.review.policy import verdict

_DETECTOR_SANITIZER = re.compile(r"[^A-Za-z0-9._-]+")
_DEFAULT_GITLEAKS_EXCLUDES = Path(__file__).with_name("gitleaks-default-excludes.toml")


class CheckExecutionError(RuntimeError):
    """Raised when a check layer cannot run at all (missing binary, invalid report)."""


def run_check(
    *,
    path: Path,
    no_tests: bool = False,
    no_lint: bool = False,
) -> dict[str, Any]:
    """Run the configured layers over ``path`` and return findings + policy verdict."""
    findings: list[dict[str, Any]] = []

    if not no_lint:
        findings.extend(_ruff_check(path))
        findings.extend(_ruff_format_check(path))

    if not no_tests:
        findings.extend(_pytest_with_coverage(path))

    findings.extend(_gitleaks_tree(path))

    verdict_name, exit_code = verdict(findings)
    return {"findings": findings, "verdict": verdict_name, "exit_code": exit_code}


def _ruff_check(path: Path) -> list[dict[str, Any]]:
    ruff_executable = shutil.which("ruff")
    if ruff_executable is None:
        raise CheckExecutionError("cannot run lint: ruff executable not found")
    result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
        [ruff_executable, "check", ".", "--output-format", "json"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    return [
        _finding(
            rule="code-quality-1",
            severity="S3",
            file="<ruff check>",
            title="ruff check reported violations",
            # Count only: raw ruff output echoes the offending source line, which does
            # not belong in a shared report artifact (TRD §4.3/§8: no stack traces or
            # source snippets in artifacts).
            evidence=_violation_count_summary(result.stdout, "violation"),
            explanation="ruff check found lint violations in the working tree.",
            suggested_fix="Run `ruff check --fix` or address the reported violations.",
        )
    ]


def _ruff_format_check(path: Path) -> list[dict[str, Any]]:
    ruff_executable = shutil.which("ruff")
    if ruff_executable is None:
        raise CheckExecutionError("cannot run lint: ruff executable not found")
    result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
        [ruff_executable, "format", "--check", "."],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    count = result.stdout.count("Would reformat:")
    evidence = f"{count} file(s) would be reformatted" if count else "files would be reformatted"
    return [
        _finding(
            rule="code-quality-2",
            severity="S3",
            file="<ruff format>",
            title="ruff format --check reported unformatted files",
            evidence=evidence,
            explanation="ruff format --check found files that are not formatted.",
            suggested_fix="Run `ruff format` to reformat the reported files.",
        )
    ]


def _pytest_with_coverage(path: Path) -> list[dict[str, Any]]:
    result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
        # -q --tb=no keeps output to per-test dots; --no-summary additionally drops the
        # "short test summary info" section, which otherwise prints "FAILED test::name -
        # <exception repr>" per failure -- and an assertion or exception message can
        # itself contain a reviewed-repo runtime value (a token, a compared secret) that
        # must never land in a shared report artifact (TRD §4.3/§8). What's left is just
        # the final pass/fail counts line.
        [sys.executable, "-m", "pytest", "-q", "--no-header", "--tb=no", "--no-summary"],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    fail_under = _coverage_fail_under(path)
    threshold_note = f" (coverage fail_under={fail_under})" if fail_under is not None else ""
    return [
        _finding(
            rule="testing-1",
            severity="S2",
            file="<pytest>",
            title="pytest failed or coverage is below the configured threshold",
            evidence=_last_nonempty_line(result.stdout or result.stderr),
            explanation=f"pytest exited non-zero{threshold_note}.",
            suggested_fix="Fix the failing tests, or add coverage until the threshold passes.",
        )
    ]


def _violation_count_summary(stdout: str, noun: str) -> str:
    try:
        violations = json.loads(stdout or "[]")
    except json.JSONDecodeError:
        return f"ruff reported {noun}s (unparseable output)"
    if not isinstance(violations, list):
        return f"ruff reported {noun}s (unparseable output)"
    return f"{len(violations)} {noun}(s) reported by ruff"


def _gitleaks_tree(path: Path) -> list[dict[str, Any]]:
    gitleaks_executable = shutil.which("gitleaks")
    if gitleaks_executable is None:
        raise CheckExecutionError("cannot scan working tree: gitleaks executable not found")
    command = [
        gitleaks_executable,
        "detect",
        "--source",
        ".",  # relative to cwd=path, so File/Fingerprint stay repo-relative and
        # portable -- an absolute --source makes gitleaks emit absolute-path
        # fingerprints, which breaks a machine-independent .gitleaksignore.
        "--no-git",
        "--no-banner",
        "--no-color",
        "--report-format",
        "json",
        "--report-path",
        "-",
        "--log-level",
        "error",
    ]
    # `--no-git` scans every file on disk, ignored or not: regenerated build artifacts
    # (__pycache__, .venv, node_modules, ...) routinely embed the same string constants
    # as the source that produced them, and would otherwise BLOCK a clean tree the moment
    # `pytest` has run once. `check` isn't crossing review's trust boundary (this is the
    # repo's own gitleaks config, for its own tree), so if the repo ships its own
    # .gitleaks.toml, let gitleaks discover that instead of overriding it.
    if not (path / ".gitleaks.toml").is_file():
        command += ["--config", str(_DEFAULT_GITLEAKS_EXCLUDES)]
    result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
        command,
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise CheckExecutionError(f"gitleaks tree scan failed with exit code {result.returncode}")
    try:
        leaks = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise CheckExecutionError("gitleaks returned an invalid JSON report") from exc
    if not isinstance(leaks, list):
        raise CheckExecutionError("gitleaks returned an invalid JSON report")

    findings: list[dict[str, Any]] = []
    for index, leak_value in enumerate(leaks, start=1):
        if not isinstance(leak_value, dict):
            raise CheckExecutionError("gitleaks returned an invalid leak entry")
        detector = _safe_detector_name(leak_value.get("RuleID"))
        findings.append(
            _finding(
                rule="secrets-1",
                severity="S1",
                file=str(leak_value.get("File") or "<working tree>"),
                title=f"Secret detected in working tree ({detector}, occurrence {index})",
                evidence="<redacted secret evidence>",
                explanation=(
                    f"Gitleaks detector {detector} identified a potential secret in the "
                    "working tree. The secret value is redacted."
                ),
                suggested_fix="Remove and rotate the secret before requesting another review.",
                line=_positive_int(leak_value.get("StartLine")),
            )
        )
    return findings


def _coverage_fail_under(path: Path) -> float | None:
    pyproject_path = path / "pyproject.toml"
    if not pyproject_path.is_file():
        return None
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError:
        return None
    value = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    return value if isinstance(value, int | float) else None


def _finding(
    *,
    rule: str,
    severity: str,
    file: str,
    title: str,
    evidence: str,
    explanation: str,
    suggested_fix: str,
    line: int | None = None,
) -> dict[str, Any]:
    return {
        "rule": rule,
        "severity": severity,
        "file": file,
        "line": line,
        "title": title,
        "evidence": evidence,
        "explanation": explanation,
        "suggested_fix": suggested_fix,
        "confidence": "high",
    }


def _safe_detector_name(value: object) -> str:
    detector = str(value or "unknown-rule")
    return _DETECTOR_SANITIZER.sub("-", detector).strip("-") or "unknown-rule"


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _last_nonempty_line(text: str, limit: int = 500) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    line = lines[-1].strip() if lines else ""
    return line[-limit:] if len(line) > limit else line
