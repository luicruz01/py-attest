"""Tests for the golden-set matcher and finding-level readings."""

from py_attest.eval.metrics import (
    FindingResults,
    apply_adjudications,
    findings_match,
    match_findings,
    severity_exact_results,
)


def _finding(rule_id: str, path: str, line_start: int, line_end: int, **extra) -> dict:
    return {
        "rule_id": rule_id,
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        **extra,
    }


def test_findings_match_requires_rule_id_and_path_and_overlapping_lines() -> None:
    expected = _finding("code-quality-6", "app/streaks.py", 10, 10)

    assert findings_match(expected, _finding("code-quality-6", "app/streaks.py", 10, 10))
    assert findings_match(expected, _finding("code-quality-6", "app/streaks.py", 8, 12))  # overlap
    assert not findings_match(expected, _finding("code-quality-6", "app/other.py", 10, 10))
    assert not findings_match(expected, _finding("testing-3", "app/streaks.py", 10, 10))
    assert not findings_match(expected, _finding("code-quality-6", "app/streaks.py", 20, 25))


def test_findings_match_tolerates_a_missing_predicted_line_range() -> None:
    expected = _finding("pii-1", "app/main.py", 37, 37)
    predicted = {"rule_id": "pii-1", "path": "app/main.py", "line_start": None, "line_end": None}

    assert not findings_match(expected, predicted)


def test_match_findings_is_one_to_one() -> None:
    expected = [_finding("testing-3", "app/streaks.py", 10, 13)]
    predicted = [
        _finding("testing-3", "app/streaks.py", 10, 13, title="first"),
        _finding("testing-3", "app/streaks.py", 10, 13, title="duplicate"),
    ]

    results = match_findings("feature/streaks", expected, predicted)

    assert len(results.true_positives) == 1
    assert [record.finding["title"] for record in results.false_positives] == ["duplicate"]
    assert results.false_negatives == []


def test_match_findings_reports_a_miss_as_a_false_negative() -> None:
    expected = [_finding("retention-2", "app/archive.py", 4, 8)]

    results = match_findings("feature/analytics-archive", expected, [])

    assert results.true_positives == []
    assert len(results.false_negatives) == 1
    assert results.false_negatives[0].finding["rule_id"] == "retention-2"


def test_unreachable_findings_are_excluded_from_the_recall_denominator() -> None:
    expected = [
        _finding("code-quality-5", "app/notifications.py", 6, 6, llm_reachable=True),
        _finding("pii-1", "app/notifications.py", 13, 13, llm_reachable=False),
    ]
    predicted = [_finding("code-quality-5", "app/notifications.py", 6, 6)]

    results = match_findings("feature/email-reminders", expected, predicted)

    assert len(results.true_positives) == 1
    assert results.false_negatives == []  # the unreachable pii-1 never counts as a miss
    assert results.recall == 1.0


def test_finding_results_precision_recall_f1() -> None:
    results = FindingResults(
        true_positives=[object(), object()],  # 2 TP
        false_positives=[object()],  # 1 FP
        false_negatives=[object()],  # 1 FN
    )

    assert results.precision == 2 / 3
    assert results.recall == 2 / 3
    assert round(results.f1, 4) == round(2 * (2 / 3) * (2 / 3) / ((2 / 3) + (2 / 3)), 4)


def test_finding_results_ratios_are_zero_not_a_crash_on_empty_input() -> None:
    results = FindingResults(true_positives=[], false_positives=[], false_negatives=[])

    assert results.precision == 0.0
    assert results.recall == 0.0
    assert results.f1 == 0.0


def test_severity_exact_demotes_a_mismatched_severity_to_fn_plus_fp() -> None:
    expected = _finding("code-quality-3", "app/main.py", 52, 52, severity="S2")
    predicted = _finding("code-quality-3", "app/main.py", 52, 52, severity="S3")
    strict = match_findings("feature/score-validation", [expected], [predicted])
    assert len(strict.true_positives) == 1  # strict ignores severity entirely

    exact = severity_exact_results(strict)

    assert exact.true_positives == []
    assert len(exact.false_negatives) == 1  # expected S2 never matched
    assert len(exact.false_positives) == 1  # predicted S3 never matched


def test_severity_exact_keeps_a_matching_severity_as_tp() -> None:
    expected = _finding("pii-1", "app/main.py", 37, 37, severity="S1")
    predicted = _finding("pii-1", "app/main.py", 37, 37, severity="S1")
    strict = match_findings("feature/support-context", [expected], [predicted])

    exact = severity_exact_results(strict)

    assert len(exact.true_positives) == 1
    assert exact.false_positives == []
    assert exact.false_negatives == []


def test_severity_exact_carries_over_unmatched_findings_unchanged() -> None:
    expected = [_finding("retention-2", "app/archive.py", 4, 8, severity="S1")]
    strict = match_findings("feature/analytics-archive", expected, [])  # no prediction -> 1 FN

    exact = severity_exact_results(strict)

    assert len(exact.false_negatives) == 1
    assert exact.true_positives == []
    assert exact.false_positives == []


def test_adjudications_credit_a_documented_mismatch_without_changing_strict() -> None:
    expected = [_finding("code-quality-6", "app/streaks.py", 10, 10)]
    predicted = [
        _finding("code-quality-6", "app/main.py", 5, 5, title="filed under the wrong path")
    ]
    strict = match_findings("feature/streaks", expected, predicted)
    assert strict.true_positives == []
    assert len(strict.false_negatives) == 1
    assert len(strict.false_positives) == 1

    adjudications = [
        {
            "branch": "feature/streaks",
            "expected": {"rule_id": "code-quality-6", "path": "app/streaks.py"},
            "predicted": {"rule_id": "code-quality-6", "path": "app/main.py"},
            "reason": "same root cause, filed under a neighboring path",
        }
    ]

    adjudicated = apply_adjudications("feature/streaks", strict, predicted, adjudications)

    assert len(adjudicated.true_positives) == 1
    assert adjudicated.false_negatives == []
    assert adjudicated.false_positives == []
    # strict itself is untouched
    assert len(strict.false_negatives) == 1
    assert len(strict.false_positives) == 1


def test_adjudications_only_apply_to_their_own_branch() -> None:
    expected = [_finding("code-quality-6", "app/streaks.py", 10, 10)]
    predicted = [_finding("code-quality-6", "app/main.py", 5, 5)]
    strict = match_findings("feature/other-branch", expected, predicted)

    adjudications = [
        {
            "branch": "feature/streaks",  # different branch
            "expected": {"rule_id": "code-quality-6", "path": "app/streaks.py"},
            "predicted": {"rule_id": "code-quality-6", "path": "app/main.py"},
            "reason": "n/a",
        }
    ]

    adjudicated = apply_adjudications("feature/other-branch", strict, predicted, adjudications)

    assert adjudicated.true_positives == []
    assert len(adjudicated.false_negatives) == 1
    assert len(adjudicated.false_positives) == 1
