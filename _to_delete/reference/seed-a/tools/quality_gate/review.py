"""CLI entry point for the AI Quality Gate reviewer."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.quality_gate.context_pack import ContextPackError, build_context
from tools.quality_gate.gating import verdict
from tools.quality_gate.llm import DEFAULT_MODEL, LLMReviewError, review_context
from tools.quality_gate.postfilter import filter_findings
from tools.quality_gate.secrets_gate import SecretsGateError, findings_for_diff

FIREWALL_SKIP_NOTE = "LLM review skipped: secret detected in diff; diff was not transmitted."


def main(argv: list[str] | None = None) -> int:
    """Review one branch diff or patch file and write JSON and Markdown reports."""
    parser = _parser()
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[2]

    try:
        if args.branch:
            diff = _branch_diff(repo_root, args.base, args.branch)
            source_name = args.branch
        else:
            diff_path = Path(args.diff_file)
            diff = diff_path.read_text(encoding="utf-8")
            source_name = diff_path.name

        secret_findings = findings_for_diff(diff, repo_root)
        if secret_findings:
            raw_review = {
                "findings": secret_findings,
                "summary": "Secret detection blocked review before any LLM transmission.",
            }
        elif args.secrets_only:
            sys.stdout.write("No secrets detected in diff.\n")
            return 0
        else:
            context = build_context(diff, repo_root)
            if args.description is not None:
                context = _append_description(context, args.description)
            raw_review = review_context(
                context,
                diff,
                prompt_version=args.prompt_version,
            )
        review = filter_findings(raw_review, diff)
        if secret_findings:
            review["note"] = FIREWALL_SKIP_NOTE
        metadata = review.pop("metadata", {})
        review["meta"] = {
            "prompt_version": args.prompt_version,
            "model": os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            "temperature": metadata.get("temperature", "not-used"),
            "gate_commit": _gate_commit(repo_root),
        }
        verdict_name, exit_code = verdict(review["findings"])
        review["verdict"] = verdict_name
        output_name = _safe_output_name(source_name)
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / f"{output_name}.json"
        markdown_path = out_dir / f"{output_name}.md"
        json_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        markdown_path.write_text(render_markdown(source_name, review), encoding="utf-8")
    except (
        ContextPackError,
        LLMReviewError,
        SecretsGateError,
        OSError,
        subprocess.CalledProcessError,
    ) as exc:
        sys.stderr.write(f"quality gate review failed: {exc}\n")
        return 2

    sys.stdout.write(f"Verdict: {verdict_name}\nWrote {json_path} and {markdown_path}\n")
    return exit_code


def render_markdown(source_name: str, review: dict[str, Any]) -> str:
    """Render a report using the deterministic verdict derived from its findings."""
    findings = review["findings"]
    verdict_name, _exit_code = verdict(findings)
    meta = review["meta"]
    provenance = (
        f"Reviewed with prompt {meta['prompt_version']} · {meta['model']} · "
        f"temp {meta['temperature']} · gate {meta['gate_commit']}"
    )
    lines = [f"# AI Quality Review: {source_name}", provenance, ""]
    note = review.get("note")
    if note:
        lines.extend([f"> **{note}**", ""])

    if not findings:
        lines.extend(["> **APPROVED — no findings**", "", "## Summary", "", review["summary"]])
        return "\n".join(lines).rstrip() + "\n"

    lines.extend([f"> **VERDICT: {verdict_name}**", ""])
    if any(
        finding["severity"] in {"S1", "S2"} and finding["confidence"] == "low"
        for finding in findings
    ):
        lines.extend(
            [
                "> **HUMAN REVIEW REQUESTED:** Low-confidence S1/S2 finding; merge is not blocked.",
                "",
            ]
        )

    lines.extend(
        [
            "## Findings",
            "",
            "| Severity | Rule | File:line | Title | Confidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for finding in findings:
        location = _finding_location(finding)
        cells = (
            finding["severity"],
            finding["rule"],
            location,
            finding["title"],
            finding["confidence"],
        )
        lines.append("| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |")

    lines.extend(["", "## Details", ""])
    for index, finding in enumerate(findings, start=1):
        location = _finding_location(finding)
        lines.extend(
            [
                f"### {index}. [{finding['severity']}] {finding['title']}",
                "",
                f"- Rule: `{finding['rule']}`",
                f"- Location: `{location}`",
                f"- Confidence: {finding['confidence']}",
                f"- Evidence: {_markdown_cell(finding['evidence'])}",
                "",
                finding["explanation"],
                "",
                f"Suggested fix: {finding['suggested_fix']}",
                "",
            ]
        )
    lines.extend(["## Summary", "", review["summary"]])
    return "\n".join(lines).rstrip() + "\n"


def _finding_location(finding: dict[str, Any]) -> str:
    location = str(finding["file"])
    if finding["line"] is not None:
        location += f":{finding['line']}"
    return location


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review a PR diff against TEAM-STANDARDS.md")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--branch", help="branch to diff against --base")
    source.add_argument("--diff-file", help="unified diff file to review")
    parser.add_argument("--base", default="main", help="base branch (default: main)")
    parser.add_argument("--out", default="reports/", help="report directory (default: reports/)")
    parser.add_argument(
        "--prompt-version",
        choices=("v1", "v2", "v3"),
        default="v3",
        help="reviewer prompt version (default: v3)",
    )
    parser.add_argument(
        "--description",
        help="author's stated intent (for example, the PR title and body)",
    )
    parser.add_argument("--secrets-only", action="store_true", help=argparse.SUPPRESS)
    return parser


def _append_description(context: str, description: str) -> str:
    return (
        f"{context.rstrip()}\n\n"
        "<author-stated-intent>\n"
        "Author's stated intent:\n"
        f"{description.rstrip()}\n"
        "</author-stated-intent>\n"
    )


def _branch_diff(repo_root: Path, base: str, branch: str) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise LLMReviewError("cannot create branch diff: git executable not found")
    try:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            [
                git_executable,
                "-c",
                "core.quotepath=false",
                "diff",
                "--no-ext-diff",
                f"{base}...{branch}",
                "--",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "git diff failed"
        raise LLMReviewError(f"cannot diff {base}...{branch}: {detail}") from exc
    return result.stdout


def _gate_commit(repo_root: Path) -> str:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise LLMReviewError("cannot resolve gate commit: git executable not found")
    try:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            [git_executable, "rev-parse", "--short", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "git rev-parse failed"
        raise LLMReviewError(f"cannot resolve gate commit: {detail}") from exc
    return result.stdout.strip()


def _safe_output_name(source_name: str) -> str:
    output_name = re.sub(r"[^A-Za-z0-9._-]+", "-", source_name).strip("-.")
    return output_name or "review"


if __name__ == "__main__":
    raise SystemExit(main())
