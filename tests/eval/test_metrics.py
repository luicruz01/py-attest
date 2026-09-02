"""Tests for deterministic reviewer evaluation metrics."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from py_attest.eval.metrics import (
    BranchResults,
    EvaluationError,
    EvaluationResults,
    _load_pr_numbers,
    _load_review,
    _verdict_class,
    evaluate,
    findings_match,
    main,
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


def test_unreachable_detected_is_reported_outside_llm_metrics() -> None:
    expected = [
        {
            "file": "app/notifications.py",
            "rule": "3",
            "llm_reachable": False,
        }
    ]
    predicted = [{"file": "app/notifications.py", "rule": "3-secrets", "title": "found anyway"}]

    results = match_findings("feature/example", expected, predicted)

    assert len(results.unreachable_detected) == 1
    evaluation = EvaluationResults(
        branches=[
            BranchResults(
                branch="feature/example",
                expected_verdict="BLOCK",
                predicted_verdict="BLOCK",
                artifact=None,
                finding_results=results,
            )
        ],
        findings=results,
    )

    markdown = render_markdown(evaluation)

    assert "detected outside LLM metrics" in markdown


def test_load_review_finds_a_single_artifact_by_pr_number(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "pr-7" / "artifacts" / "run"
    artifacts_root.mkdir(parents=True)
    (artifacts_root / "report.json").write_text(
        json.dumps({"verdict": "BLOCK", "findings": [{"rule": "2", "file": "app/main.py"}]}),
        encoding="utf-8",
    )

    artifact, review = _load_review("feature/x", {"feature/x": 7}, tmp_path)

    assert artifact == artifacts_root / "report.json"
    assert review == {"verdict": "BLOCK", "findings": [{"rule": "2", "file": "app/main.py"}]}


def test_load_review_returns_none_when_branch_has_no_pr(tmp_path: Path) -> None:
    assert _load_review("feature/unknown", {}, tmp_path) == (None, None)


def test_load_review_rejects_multiple_artifacts_for_one_branch(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "pr-7" / "artifacts"
    for name in ("a", "b"):
        run_dir = artifacts_root / name
        run_dir.mkdir(parents=True)
        (run_dir / "report.json").write_text(
            json.dumps({"verdict": "BLOCK", "findings": []}), encoding="utf-8"
        )

    with pytest.raises(EvaluationError, match="multiple reviewer artifacts"):
        _load_review("feature/x", {"feature/x": 7}, tmp_path)


def test_load_review_rejects_an_invalid_artifact(tmp_path: Path) -> None:
    artifacts_root = tmp_path / "pr-7" / "artifacts" / "run"
    artifacts_root.mkdir(parents=True)
    (artifacts_root / "report.json").write_text(
        json.dumps({"verdict": "BLOCK", "findings": ["not-a-dict"]}), encoding="utf-8"
    )

    with pytest.raises(EvaluationError, match="invalid reviewer finding"):
        _load_review("feature/x", {"feature/x": 7}, tmp_path)


def test_load_pr_numbers_prefers_the_open_pr_for_a_reused_branch_name(tmp_path: Path) -> None:
    prs = tmp_path / "prs.json"
    prs.write_text(
        json.dumps(
            [
                {"headRefName": "feature/x", "number": 1, "state": "CLOSED"},
                {"headRefName": "feature/x", "number": 2, "state": "OPEN"},
            ]
        ),
        encoding="utf-8",
    )

    assert _load_pr_numbers(prs) == {"feature/x": 2}


def test_load_pr_numbers_rejects_a_non_list_payload(tmp_path: Path) -> None:
    prs = tmp_path / "prs.json"
    prs.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    with pytest.raises(EvaluationError, match="must contain a list"):
        _load_pr_numbers(prs)


def test_verdict_class_rejects_an_unknown_verdict() -> None:
    with pytest.raises(EvaluationError, match="unknown reviewer verdict"):
        _verdict_class("MAYBE")


def test_main_writes_the_report_and_returns_zero(tmp_path: Path) -> None:
    ground_truth = tmp_path / "ground_truth.yml"
    ground_truth.write_text(
        "---\nbranches:\n  feature/example:\n    verdict: APPROVE\n    findings: []\n",
        encoding="utf-8",
    )
    output = tmp_path / "out" / "metrics.md"
    prs = tmp_path / "prs.json"
    prs.write_text("[]", encoding="utf-8")

    exit_code = main(
        [
            "--ground-truth",
            str(ground_truth),
            "--prs",
            str(prs),
            "--runs-root",
            str(tmp_path / "missing-runs"),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 0
    assert output.is_file()
    assert "Reviewer Evaluation Metrics v1" in output.read_text(encoding="utf-8")


def test_main_reports_evaluation_errors_as_exit_2(tmp_path: Path) -> None:
    ground_truth = tmp_path / "ground_truth.yml"
    ground_truth.write_text("not: valid\n", encoding="utf-8")

    exit_code = main(["--ground-truth", str(ground_truth)])

    assert exit_code == 2


@pytest.mark.xfail(
    reason=(
        "tests Seed A's `make eval-run` target and its live seed branches; "
        "golden-set fixtures and eval-run orchestration are F0.5 scope (TRD §11)"
    ),
    strict=True,
)
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
