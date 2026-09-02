# AI Quality Review: feature/score-validation
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S2 | 1-error-handling | app/main.py:52 | Missing validation for non-integer 'score' — can raise unhandled exception | high |
| S2 | 2-missing-tests-core-logic | app/main.py:52 | New numeric conversion logic is not covered by tests (core logic untested) | high |

## Details

### 1. [S2] Missing validation for non-integer 'score' — can raise unhandled exception

- Rule: `1-error-handling`
- Location: `app/main.py:52`
- Confidence: high
- Evidence: score = int(payload.get("score", 0))

This change converts external input with int(...) without handling conversion errors. TEAM-STANDARDS §1 requires: "Errors are handled explicitly. Silent exception handling is not acceptable." and "All external input is validated." If payload["score"] is a non-numeric string or another invalid type, int(...) will raise ValueError and produce a 500 response instead of a controlled 4xx validation error. The diff adds this conversion but does not catch or validate it, creating a potential crash path.

Suggested fix: Validate and handle non-integer scores explicitly. For example, wrap the conversion in try/except ValueError and raise HTTPException(status_code=422, detail="score must be an integer between 0 and 100") on failure. Also add unit tests for non-numeric score inputs to ensure the handler returns 422 rather than a 500.

### 2. [S2] New numeric conversion logic is not covered by tests (core logic untested)

- Rule: `2-missing-tests-core-logic`
- Location: `app/main.py:52`
- Confidence: high
- Evidence: score = int(payload.get("score", 0))

TEAM-STANDARDS §2 requires: "Every logic change includes tests that fail if the behavior breaks." The PR adds a numeric conversion of incoming payload['score'], which is core input-processing logic. The new tests in tests/test_score_validation.py cover out-of-range numeric values and unknown lessons but do not exercise non-numeric or otherwise invalid score values (e.g. "score": "abc", score omitted but present as null, or score as a JSON boolean). Without tests for these cases, a regression (ValueError from int(...)) would not be caught by the test suite.

Suggested fix: Extend tests/test_score_validation.py to include cases where 'score' is non-numeric (e.g. "abc"), null, or another invalid type, and assert the endpoint returns 422. This ensures the conversion logic is tested and prevents regressions that would surface as 500 errors.

## Summary

Two S2 findings: the handler uses int(...) on external input without explicit error handling or validation (violates TEAM-STANDARDS §1), and there are missing tests for non-numeric/invalid score inputs so the core conversion logic is not covered (violates TEAM-STANDARDS §2).
