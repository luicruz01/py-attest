# AI Quality Review: fix/progress-percentage
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S2 | 2-testing | app/main.py:38 | Core percentage calculation changed without complete test coverage (behavioral regression risk) | high |
| S2 | 1-code-quality | tests/test_progress.py:25 | New behavior (100% for zero lessons) lacks documentation and justification | high |

## Details

### 1. [S2] Core percentage calculation changed without complete test coverage (behavioral regression risk)

- Rule: `2-testing`
- Location: `app/main.py:38`
- Confidence: high
- Evidence: percentage = int(100 * completed / total) if total else 100

The PR changes the core progress-percentage calculation in two ways: it replaces round(...) with int(...), changing rounding semantics (truncation instead of rounding), and it changes the empty-lessons branch from 0 to 100. This is a behavioral change to core logic that affects reported progress values. TEAM-STANDARDS.md §2 requires that every logic change includes tests that fail if the behavior breaks. The tests added cover only the no-lessons case (asserting 100) but do not cover the changed rounding behavior (round->int) for non-zero totals. As a result, the test-suite would not detect regressions in rounding semantics, and the change may produce incorrect data (S2 per TEAM-STANDARDS §6).

Suggested fix: Either (a) revert to the previous behavior for the no-lessons case (0) if that was correct, or (b) if 100% for no lessons is intended, document this decision in the function docstring and add explicit tests that assert the intended rounding semantics for representative cases (e.g. scenarios where 100 * completed / total produces fractional values that would round up vs truncate). Ensure tests would fail if rounding semantics or the empty-case are changed inadvertently.

### 2. [S2] New behavior (100% for zero lessons) lacks documentation and justification

- Rule: `1-code-quality`
- Location: `tests/test_progress.py:25`
- Confidence: high
- Evidence: def test_progress_percentage_no_lessons(monkeypatch):

The test asserts that percentage == 100 when there are zero lessons, signaling an intentional behavioral change in the application logic. TEAM-STANDARDS.md §1 requires code changes to be clear and documented; this change to a counterintuitive default (reporting 100% when there are no lessons) has no accompanying code comment or docstring explaining the rationale. Such unexplained behavior increases maintenance risk and may hide a logic bug.

Suggested fix: Add a short docstring or comment in the get_progress implementation explaining why an empty lesson set should report 100% (business rule, UX expectation, or to match external consumers). If the behavior was accidental, revert to the prior sensible default (0%).

## Summary

The diff modifies the progress-percentage calculation (round -> int and empty-lessons default 0 -> 100). Tests only cover the empty-lessons case but do not cover the changed rounding semantics. The behavioral change is not documented in code. These issues amount to an S2 logic/coverage problem per TEAM-STANDARDS.md §2 and §1.
