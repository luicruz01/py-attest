"""Tests for the golden-set matcher and finding-level readings."""

from py_attest.eval.metrics import FindingResults, findings_match, match_findings


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
