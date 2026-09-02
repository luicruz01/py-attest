"""Diff-scoped Gitleaks firewall for the AI reviewer."""

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from py_attest.review.postfilter import files_in_diff

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_ASSIGNMENT_NAME = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*(?::|=)")


class SecretsGateError(RuntimeError):
    """Raised when the deterministic secrets scan cannot complete."""


def findings_for_diff(diff: str, repo_root: Path) -> list[dict[str, Any]]:  # noqa: ARG001
    """Run Gitleaks on ``diff`` via stdin and return redacted S1 findings.

    ``repo_root`` is accepted for API stability but deliberately NOT used as the
    subprocess cwd: gitleaks auto-discovers `.gitleaks.toml`/`.gitleaksignore` from its
    working directory (TOML precedence: --config > $GITLEAKS_CONFIG > (cwd)/.gitleaks.toml
    > embedded default), and the reviewed repo controls whatever is at ``repo_root``. A
    PR shipping a `.gitleaks.toml` with an allow-all regex, or a `.gitleaksignore`
    matching the leaked secret's fingerprint, would silently disable this firewall and
    let a real secret reach the LLM provider. The scan is stdin-only and needs no files
    from the repo, so it runs from a throwaway directory the reviewed repo cannot reach.
    """
    gitleaks_executable = shutil.which("gitleaks")
    if gitleaks_executable is None:
        raise SecretsGateError("cannot scan diff: gitleaks executable not found")

    with tempfile.TemporaryDirectory(prefix="attest-secrets-gate-") as neutral_cwd:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            [
                gitleaks_executable,
                "stdin",
                "--redact=100",
                "--report-format",
                "json",
                "--report-path",
                "-",
                "--no-banner",
                "--no-color",
                "--log-level",
                "error",
            ],
            cwd=neutral_cwd,
            input=diff,
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode not in {0, 1}:
        raise SecretsGateError(f"gitleaks diff scan failed with exit code {result.returncode}")

    try:
        leaks = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        raise SecretsGateError("gitleaks returned an invalid JSON report") from exc
    if not isinstance(leaks, list):
        raise SecretsGateError("gitleaks returned an invalid JSON report")

    findings: list[dict[str, Any]] = []
    for index, leak_value in enumerate(leaks, start=1):
        if not isinstance(leak_value, dict):
            raise SecretsGateError("gitleaks returned an invalid leak entry")
        detector = _safe_detector_name(leak_value.get("RuleID"))
        diff_line = _positive_int(leak_value.get("StartLine"))
        file_name, source_line = _location_for_diff_line(diff, diff_line)
        if file_name is None:
            file_name = _fallback_file(diff, leak_value.get("File"))
        evidence = _safe_evidence_for_diff_line(diff, diff_line)
        findings.append(
            {
                "rule": "5-secrets",
                "severity": "S1",
                "file": file_name,
                "line": source_line,
                "title": f"Secret detected ({detector}, occurrence {index})",
                "evidence": evidence,
                "explanation": (
                    f"Gitleaks detector {detector} identified a potential secret in the diff. "
                    "The secret value is redacted."
                ),
                "suggested_fix": "Remove and rotate the secret before requesting another review.",
                "confidence": "high",
            }
        )
    return findings


def _safe_evidence_for_diff_line(diff: str, target_line: int | None) -> str:
    if target_line is None:
        return "<redacted secret evidence>"
    lines = diff.splitlines()
    if target_line > len(lines):
        return "<redacted secret evidence>"
    diff_text = lines[target_line - 1]
    if not diff_text.startswith("+") or diff_text.startswith("+++"):
        return "<redacted secret evidence>"

    added_text = diff_text[1:]
    assignment = _ASSIGNMENT_NAME.match(added_text)
    if assignment:
        return assignment.group(1)
    if "=" in added_text:
        return "="
    if ":" in added_text:
        return ":"
    for character in added_text:
        if not character.isspace():
            return character
    return "<redacted secret evidence>"


def _safe_detector_name(value: object) -> str:
    detector = str(value or "unknown-rule")
    return re.sub(r"[^A-Za-z0-9._-]+", "-", detector).strip("-") or "unknown-rule"


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _fallback_file(diff: str, report_file: object) -> str:
    if isinstance(report_file, str) and report_file:
        return report_file.removeprefix("a/").removeprefix("b/")
    diff_files = sorted(files_in_diff(diff))
    if diff_files:
        return diff_files[0]
    return "<diff>"


def _location_for_diff_line(diff: str, target_line: int | None) -> tuple[str | None, int | None]:
    if target_line is None:
        return None, None

    old_file: str | None = None
    new_file: str | None = None
    old_line: int | None = None
    new_line: int | None = None
    for diff_line, text in enumerate(diff.splitlines(), start=1):
        if text.startswith("--- "):
            old_file = _header_path(text[4:])
        elif text.startswith("+++ "):
            new_file = _header_path(text[4:])
        else:
            match = _HUNK_HEADER.match(text)
            if match:
                old_line, new_line = (int(value) for value in match.groups())
            elif old_line is not None and new_line is not None:
                if text.startswith("+"):
                    if diff_line == target_line:
                        return new_file, new_line
                    new_line += 1
                elif text.startswith("-"):
                    if diff_line == target_line:
                        return old_file, old_line
                    old_line += 1
                elif not text.startswith("\\"):
                    if diff_line == target_line:
                        return new_file or old_file, new_line
                    old_line += 1
                    new_line += 1
        if diff_line == target_line:
            return new_file or old_file, None
    return new_file or old_file, None


def _header_path(header: str) -> str | None:
    path = header.split("\t", maxsplit=1)[0]
    if path == "/dev/null":
        return None
    return path.removeprefix("a/").removeprefix("b/")
