"""Tests for deterministic reviewer evaluation metrics."""

import json
import shutil
import subprocess
from pathlib import Path

from tools.quality_gate.eval_metrics import (
    evaluate,
    findings_match,
    match_findings,
    render_markdown,
)


def test_matcher_uses_file_and_rule_section_prefix() -> None:
    expected = {"file": "app/main.py", "rule": "3"}

    assert findings_match(expected, {"file": "app/main.py", "rule": "3-PII-logging"})
    assert not findings_match(expected, {"file": "app/other.py", "rule": "3-PII"})
    assert not findings_match(expected, {"file": "app/main.py", "rule": "13-PII"})


def test_matcher_is_one_to_one() -> None:
    expected = [{"file": "app/main.py", "rule": "2", "note": "golden"}]
    predicted = [
        {"file": "app/main.py", "rule": "2-tests", "title": "first"},
        {"file": "app/main.py", "rule": "2-tests", "title": "duplicate"},
    ]

    results = match_findings("feature/example", expected, predicted)

    assert len(results.true_positives) == 1
    assert [record.finding["title"] for record in results.false_positives] == ["duplicate"]
    assert results.false_negatives == []


def test_unreachable_findings_are_excluded_from_recall_denominator() -> None:
    expected = [
        {"file": "app/main.py", "rule": "2", "note": "reachable"},
        {
            "file": "app/notifications.py",
            "rule": "3",
            "note": "hidden behind firewall",
            "llm_reachable": False,
        },
    ]

    predicted = [{"file": "app/main.py", "rule": "2-tests", "title": "found"}]

    results = match_findings("feature/example", expected, predicted)

    assert len(results.true_positives) == 1
    assert results.false_negatives == []
    assert len(results.unreachable) == 1
    assert results.recall == 1.0


def test_missing_artifact_is_reported_without_network_or_crash(tmp_path: Path) -> None:
    ground_truth = tmp_path / "ground_truth.yml"
    ground_truth.write_text(
        "---\nbranches:\n  feature/missing:\n    verdict: BLOCK\n    findings:\n"
        "    - {rule: '2', file: app/main.py}\n",
        encoding="utf-8",
    )
    prs = tmp_path / "prs.json"
    prs.write_text(
        json.dumps([{"headRefName": "feature/missing", "number": 42, "state": "OPEN"}]),
        encoding="utf-8",
    )

    results = evaluate(ground_truth, prs, tmp_path)

    assert len(results.branches) == 1
    assert results.branches[0].predicted_verdict is None
    assert results.branches[0].artifact is None
    assert len(results.findings.false_negatives) == 1
    assert results.block_recall == 0.0
    assert "| feature/missing | BLOCK | MISSING | MISSING |" in render_markdown(results)


def test_branch_keyed_runs_dir_needs_no_pr_mapping_and_uses_label(tmp_path: Path) -> None:
    ground_truth = tmp_path / "ground_truth.yml"
    ground_truth.write_text(
        "---\nbranches:\n  feature/example:\n    verdict: BLOCK\n    findings:\n"
        "    - {rule: '2', file: app/main.py}\n",
        encoding="utf-8",
    )
    runs_dir = tmp_path / "runs_v2"
    artifact = runs_dir / "feature/example.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text(
        json.dumps(
            {
                "verdict": "BLOCK",
                "findings": [{"rule": "2-testing", "file": "app/main.py"}],
            }
        ),
        encoding="utf-8",
    )

    results = evaluate(
        ground_truth,
        tmp_path / "prs-does-not-exist.json",
        tmp_path / "runs-does-not-exist",
        runs_dir=runs_dir,
    )

    assert results.branches[0].artifact == artifact
    assert results.block_recall == 1.0
    assert len(results.findings.true_positives) == 1
    assert render_markdown(results, "v2").startswith("# Reviewer Evaluation Metrics v2\n")


def test_make_eval_run_routes_all_seed_branches_through_selected_prompt() -> None:
    make_executable = shutil.which("make")
    assert make_executable is not None

    result = subprocess.run(  # noqa: S603 - resolved executable and fixed arguments
        [make_executable, "--dry-run", "eval-run", "VERSION=v1"],
        cwd=Path.cwd(),
        check=True,
        capture_output=True,
        text=True,
    )

    for branch in (
        "feature/lessons-pagination",
        "feature/score-validation",
        "fix/mobile-sync-visibility",
        "feature/support-context",
        "feature/email-reminders",
        "feature/streaks",
        "feature/analytics-archive",
        "fix/progress-percentage",
    ):
        assert branch in result.stdout
    assert 'runs_dir="eval/runs_v1"' in result.stdout
    assert '--prompt-version "v1"' in result.stdout
