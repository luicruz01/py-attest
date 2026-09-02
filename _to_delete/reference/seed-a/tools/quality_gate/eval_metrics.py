"""Measure reviewer verdicts and findings against the labeled golden set."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

VERDICTS = {"APPROVE", "BLOCK"}
RULE_SECTION_RE = re.compile(r"^\s*(\d+)")


class EvaluationError(ValueError):
    """Raised when evaluation inputs do not have the expected structure."""


@dataclass(frozen=True)
class FindingRecord:
    """A finding together with its source branch."""

    branch: str
    finding: dict[str, Any]


@dataclass(frozen=True)
class FindingMatch:
    """A one-to-one match between a golden and predicted finding."""

    expected: FindingRecord
    predicted: FindingRecord


@dataclass
class FindingResults:
    """Finding-level evaluation results."""

    true_positives: list[FindingMatch]
    false_positives: list[FindingRecord]
    false_negatives: list[FindingRecord]
    unreachable: list[FindingRecord]
    unreachable_detected: list[FindingMatch]

    @property
    def precision(self) -> float:
        """Return finding precision over reachable labels."""
        denominator = len(self.true_positives) + len(self.false_positives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def recall(self) -> float:
        """Return finding recall with unreachable labels excluded."""
        denominator = len(self.true_positives) + len(self.false_negatives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def f1(self) -> float:
        """Return the harmonic mean of finding precision and recall."""
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)


@dataclass(frozen=True)
class BranchResults:
    """Evaluation details for one branch."""

    branch: str
    expected_verdict: str
    predicted_verdict: str | None
    artifact: Path | None
    finding_results: FindingResults


@dataclass(frozen=True)
class EvaluationResults:
    """Complete verdict- and finding-level evaluation results."""

    branches: list[BranchResults]
    findings: FindingResults

    @property
    def block_precision(self) -> float:
        """Return precision when BLOCK is the positive verdict."""
        true_blocks = sum(
            row.expected_verdict == "BLOCK" and row.predicted_verdict == "BLOCK"
            for row in self.branches
        )
        predicted_blocks = sum(row.predicted_verdict == "BLOCK" for row in self.branches)
        return _ratio(true_blocks, predicted_blocks)

    @property
    def block_recall(self) -> float:
        """Return recall when BLOCK is the positive verdict."""
        true_blocks = sum(
            row.expected_verdict == "BLOCK" and row.predicted_verdict == "BLOCK"
            for row in self.branches
        )
        expected_blocks = sum(row.expected_verdict == "BLOCK" for row in self.branches)
        return _ratio(true_blocks, expected_blocks)

    @property
    def accuracy(self) -> float:
        """Return verdict accuracy; a missing artifact is an incorrect result."""
        correct = sum(
            row.predicted_verdict is not None and row.expected_verdict == row.predicted_verdict
            for row in self.branches
        )
        return _ratio(correct, len(self.branches))


def rule_section(rule: object) -> str | None:
    """Extract the leading TEAM-STANDARDS section number from a rule value."""
    match = RULE_SECTION_RE.match(str(rule))
    return match.group(1) if match else None


def findings_match(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    """Match findings by file and leading rule section number."""
    expected_section = rule_section(expected.get("rule", ""))
    predicted_section = rule_section(predicted.get("rule", ""))
    return (
        bool(expected_section)
        and expected_section == predicted_section
        and expected.get("file") == predicted.get("file")
    )


def match_findings(
    branch: str,
    expected: list[dict[str, Any]],
    predicted: list[dict[str, Any]],
) -> FindingResults:
    """Perform deterministic one-to-one finding matching for one branch."""
    reachable = [finding for finding in expected if finding.get("llm_reachable", True)]
    unreachable = [finding for finding in expected if not finding.get("llm_reachable", True)]
    remaining_predictions = list(predicted)
    true_positives: list[FindingMatch] = []
    false_negatives: list[FindingRecord] = []

    for expected_finding in reachable:
        match_index = _first_match(expected_finding, remaining_predictions)
        expected_record = FindingRecord(branch, expected_finding)
        if match_index is None:
            false_negatives.append(expected_record)
            continue
        predicted_finding = remaining_predictions.pop(match_index)
        true_positives.append(
            FindingMatch(expected_record, FindingRecord(branch, predicted_finding))
        )

    unreachable_records = [FindingRecord(branch, finding) for finding in unreachable]
    unreachable_detected: list[FindingMatch] = []
    for expected_record in unreachable_records:
        match_index = _first_match(expected_record.finding, remaining_predictions)
        if match_index is None:
            continue
        predicted_finding = remaining_predictions.pop(match_index)
        unreachable_detected.append(
            FindingMatch(expected_record, FindingRecord(branch, predicted_finding))
        )

    return FindingResults(
        true_positives=true_positives,
        false_positives=[FindingRecord(branch, finding) for finding in remaining_predictions],
        false_negatives=false_negatives,
        unreachable=unreachable_records,
        unreachable_detected=unreachable_detected,
    )


def evaluate(
    ground_truth_path: Path,
    prs_path: Path,
    runs_root: Path,
    *,
    runs_dir: Path | None = None,
) -> EvaluationResults:
    """Load evaluation inputs and compute verdict and finding metrics."""
    ground_truth = _load_ground_truth(ground_truth_path)
    pr_numbers = _load_pr_numbers(prs_path) if runs_dir is None else {}
    branch_results: list[BranchResults] = []

    for branch, expected_review in ground_truth.items():
        if runs_dir is None:
            artifact, predicted_review = _load_review(branch, pr_numbers, runs_root)
        else:
            artifact, predicted_review = _load_branch_review(branch, runs_dir)
        predicted_findings = predicted_review["findings"] if predicted_review else []
        finding_results = match_findings(
            branch,
            expected_review["findings"],
            predicted_findings,
        )
        branch_results.append(
            BranchResults(
                branch=branch,
                expected_verdict=expected_review["verdict"],
                predicted_verdict=(
                    _verdict_class(predicted_review["verdict"]) if predicted_review else None
                ),
                artifact=artifact,
                finding_results=finding_results,
            )
        )

    return EvaluationResults(branch_results, _combine_findings(branch_results))


def render_markdown(results: EvaluationResults, label: str = "v1") -> str:
    """Render a complete, deterministic Markdown evaluation report."""
    confusion = _confusion(results.branches)
    findings = results.findings
    lines = [
        f"# Reviewer Evaluation Metrics {label}",
        "",
        "## Verdict-level metrics",
        "",
        "| Actual \\ Predicted | APPROVE | BLOCK | MISSING |",
        "| --- | ---: | ---: | ---: |",
        (
            f"| APPROVE | {confusion[('APPROVE', 'APPROVE')]} | "
            f"{confusion[('APPROVE', 'BLOCK')]} | {confusion[('APPROVE', 'MISSING')]} |"
        ),
        (
            f"| BLOCK | {confusion[('BLOCK', 'APPROVE')]} | "
            f"{confusion[('BLOCK', 'BLOCK')]} | {confusion[('BLOCK', 'MISSING')]} |"
        ),
        "",
        f"- Block precision: {_percent(results.block_precision)}",
        f"- Block recall: {_percent(results.block_recall)}",
        f"- Accuracy: {_percent(results.accuracy)}",
        "",
        "## Per-branch results",
        "",
        "| Branch | Expected | Predicted | Verdict result | Finding TP | FP | FN | Artifact |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in results.branches:
        lines.append(_branch_row(row))

    lines.extend(
        [
            "",
            "## Finding-level metrics",
            "",
            f"- Precision: {_percent(findings.precision)}",
            f"- Recall: {_percent(findings.recall)}",
            f"- F1: {_percent(findings.f1)}",
            f"- TP: {len(findings.true_positives)}",
            f"- FP: {len(findings.false_positives)}",
            f"- FN: {len(findings.false_negatives)}",
            "",
            "### True positives (TP)",
            "",
        ]
    )
    _append_matches(lines, findings.true_positives)
    lines.extend(["", "### False positives (FP)", ""])
    _append_records(lines, findings.false_positives)
    lines.extend(["", "### False negatives (FN)", ""])
    _append_records(lines, findings.false_negatives)
    lines.extend(["", "### By-design unreachable (secrets firewall)", ""])
    if findings.unreachable:
        detected_keys = {
            (match.expected.branch, id(match.expected.finding))
            for match in findings.unreachable_detected
        }
        for record in findings.unreachable:
            status = (
                "detected outside LLM metrics"
                if (record.branch, id(record.finding)) in detected_keys
                else "excluded from LLM recall denominator"
            )
            lines.append(f"- `{record.branch}` — {status}: `{_finding_json(record.finding)}`")
    else:
        lines.append("- None")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Compute metrics, write the versioned report, and echo it to stdout."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        results = evaluate(
            args.ground_truth,
            args.prs,
            args.runs_root,
            runs_dir=args.runs_dir,
        )
        report = render_markdown(results, args.label)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except (EvaluationError, OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"evaluation failed: {exc}\n")
        return 2
    sys.stdout.write(report)
    return 0


def _parser() -> argparse.ArgumentParser:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ground-truth",
        type=Path,
        default=repo_root / "eval" / "ground_truth.yml",
    )
    parser.add_argument("--prs", type=Path, default=repo_root / "eval" / "runs" / "prs.json")
    parser.add_argument("--runs-root", type=Path, default=repo_root / "eval" / "runs")
    parser.add_argument(
        "--runs-dir",
        type=Path,
        help="directory of branch-name keyed local reviewer JSON files",
    )
    parser.add_argument("--label", default="v1", help="report label (default: v1)")
    parser.add_argument("--output", type=Path, default=repo_root / "eval" / "metrics_v1.md")
    return parser


def _load_ground_truth(path: Path) -> dict[str, dict[str, Any]]:
    documents = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
    if len(documents) not in {1, 2} or (len(documents) == 2 and documents[1] is not None):
        raise EvaluationError("ground truth must contain one non-empty YAML document")
    payload = documents[0]
    if not isinstance(payload, dict) or not isinstance(payload.get("branches"), dict):
        raise EvaluationError("ground truth must contain a 'branches' mapping")
    branches: dict[str, dict[str, Any]] = {}
    for branch, review in payload["branches"].items():
        if not isinstance(branch, str) or not isinstance(review, dict):
            raise EvaluationError("each ground-truth branch must map to an object")
        verdict = review.get("verdict")
        findings = review.get("findings")
        if verdict not in VERDICTS or not isinstance(findings, list):
            raise EvaluationError(f"invalid ground truth for branch {branch}")
        if not all(isinstance(finding, dict) for finding in findings):
            raise EvaluationError(f"invalid finding for branch {branch}")
        branches[branch] = {"verdict": verdict, "findings": findings}
    return branches


def _load_pr_numbers(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise EvaluationError("prs.json must contain a list")
    result: dict[str, int] = {}
    for pr in payload:
        if not isinstance(pr, dict):
            raise EvaluationError("each prs.json entry must be an object")
        branch = pr.get("headRefName")
        number = pr.get("number")
        if not isinstance(branch, str) or not isinstance(number, int):
            raise EvaluationError("each PR needs string headRefName and integer number")
        if branch not in result or pr.get("state") == "OPEN":
            result[branch] = number
    return result


def _load_review(
    branch: str,
    pr_numbers: dict[str, int],
    runs_root: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    number = pr_numbers.get(branch)
    if number is None:
        return None, None
    artifacts_root = runs_root / f"pr-{number}" / "artifacts"
    reviews: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(artifacts_root.rglob("*.json")) if artifacts_root.is_dir() else []:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or "verdict" not in payload or "findings" not in payload:
            continue
        verdict = payload["verdict"]
        findings = payload["findings"]
        if not isinstance(verdict, str) or not isinstance(findings, list):
            raise EvaluationError(f"invalid reviewer artifact: {path}")
        if not all(isinstance(finding, dict) for finding in findings):
            raise EvaluationError(f"invalid reviewer finding: {path}")
        reviews.append((path, {"verdict": verdict, "findings": findings}))
    if not reviews:
        return None, None
    if len(reviews) > 1:
        raise EvaluationError(f"multiple reviewer artifacts for branch {branch}")
    return reviews[0]


def _load_branch_review(
    branch: str,
    runs_dir: Path,
) -> tuple[Path | None, dict[str, Any] | None]:
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", branch).strip("-.") or "review"
    candidates = [runs_dir / f"{branch}.json", runs_dir / f"{safe_name}.json"]
    artifacts = [path for path in dict.fromkeys(candidates) if path.is_file()]
    if not artifacts:
        return None, None
    if len(artifacts) > 1:
        raise EvaluationError(f"multiple reviewer artifacts for branch {branch}")

    path = artifacts[0]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise EvaluationError(f"invalid reviewer artifact: {path}")
    verdict = payload.get("verdict")
    findings = payload.get("findings")
    if not isinstance(verdict, str) or not isinstance(findings, list):
        raise EvaluationError(f"invalid reviewer artifact: {path}")
    if not all(isinstance(finding, dict) for finding in findings):
        raise EvaluationError(f"invalid reviewer finding: {path}")
    return path, {"verdict": verdict, "findings": findings}


def _verdict_class(verdict: str) -> str:
    if verdict == "BLOCK":
        return "BLOCK"
    if verdict in {"APPROVE", "COMMENT"}:
        return "APPROVE"
    raise EvaluationError(f"unknown reviewer verdict: {verdict}")


def _first_match(expected: dict[str, Any], predicted: list[dict[str, Any]]) -> int | None:
    return next(
        (
            index
            for index, predicted_finding in enumerate(predicted)
            if findings_match(expected, predicted_finding)
        ),
        None,
    )


def _combine_findings(branches: list[BranchResults]) -> FindingResults:
    return FindingResults(
        true_positives=[match for row in branches for match in row.finding_results.true_positives],
        false_positives=[
            finding for row in branches for finding in row.finding_results.false_positives
        ],
        false_negatives=[
            finding for row in branches for finding in row.finding_results.false_negatives
        ],
        unreachable=[finding for row in branches for finding in row.finding_results.unreachable],
        unreachable_detected=[
            match for row in branches for match in row.finding_results.unreachable_detected
        ],
    )


def _confusion(branches: list[BranchResults]) -> dict[tuple[str, str], int]:
    counts = {
        (expected, predicted): 0
        for expected in ("APPROVE", "BLOCK")
        for predicted in ("APPROVE", "BLOCK", "MISSING")
    }
    for row in branches:
        counts[(row.expected_verdict, row.predicted_verdict or "MISSING")] += 1
    return counts


def _branch_row(row: BranchResults) -> str:
    predicted = row.predicted_verdict or "MISSING"
    if row.predicted_verdict is None:
        verdict_result = "MISSING"
    elif row.expected_verdict == "BLOCK":
        verdict_result = "TP" if predicted == "BLOCK" else "FN"
    else:
        verdict_result = "TN" if predicted == "APPROVE" else "FP"
    artifact = str(row.artifact) if row.artifact else "missing"
    finding_results = row.finding_results
    cells = (
        row.branch,
        row.expected_verdict,
        predicted,
        verdict_result,
        len(finding_results.true_positives),
        len(finding_results.false_positives),
        len(finding_results.false_negatives),
        artifact,
    )
    return "| " + " | ".join(_markdown_cell(cell) for cell in cells) + " |"


def _append_matches(lines: list[str], matches: list[FindingMatch]) -> None:
    if not matches:
        lines.append("- None")
        return
    for match in matches:
        lines.append(
            f"- `{match.expected.branch}` — expected `{_finding_json(match.expected.finding)}`; "
            f"predicted `{_finding_json(match.predicted.finding)}`"
        )


def _append_records(lines: list[str], records: list[FindingRecord]) -> None:
    if not records:
        lines.append("- None")
        return
    for record in records:
        lines.append(f"- `{record.branch}` — `{_finding_json(record.finding)}`")


def _finding_json(finding: dict[str, Any]) -> str:
    return json.dumps(finding, ensure_ascii=False, separators=(",", ":"))


def _markdown_cell(value: object) -> str:
    return str(value).replace("|", r"\|").replace("\n", "<br>")


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _percent(value: float) -> str:
    return f"{value:.1%}"


if __name__ == "__main__":
    raise SystemExit(main())
