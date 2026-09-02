# AI Quality Review: feature/streaks
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

> **HUMAN REVIEW REQUESTED:** Low-confidence S1/S2 finding; merge is not blocked.

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S2 | 1-code-quality | app/streaks.py:1 | Docstring claims streak 'terminando hoy' but implementation excludes today | high |
| S2 | 2-testing | app/streaks.py:5 | Core streak logic lacks effective tests that would catch regressions | low |

## Details

### 1. [S2] Docstring claims streak 'terminando hoy' but implementation excludes today

- Rule: `1-code-quality`
- Location: `app/streaks.py:1`
- Confidence: high
- Evidence: """Racha de dias consecutivos con actividad, para gamification."""<br><br>def current_streak(activity_dates: list[date], today: date \| None = None) -> int:<br>    """Cantidad de dias consecutivos con actividad, terminando hoy."""<br>    today = today or date.today()<br>    days = set(activity_dates)<br>    streak = 0<br>    day = today - timedelta(days=1)<br>    while day in days:<br>        streak += 1<br>        day -= timedelta(days=1)<br>    return streak

The function's docstring says the streak ends 'today' (i.e. it should include today's activity), but the implementation begins checking from yesterday (today - 1 day) and therefore never counts activity that happened on today. This is a logic bug: the function will produce incorrect streak counts when activity includes today, contradicting its documented behavior.

Suggested fix: Either update the implementation to include today in the streak calculation (for example, start with day = today and check while day in days incrementing streak, or explicitly check today first), or change the docstring to precisely describe the implemented behavior. Add unit tests that assert the expected result when activity includes today.

### 2. [S2] Core streak logic lacks effective tests that would catch regressions

- Rule: `2-testing`
- Location: `app/streaks.py:5`
- Confidence: low
- Evidence: def current_streak(activity_dates: list[date], today: date \| None = None) -> int:<br><br># from tests/test_streaks.py<br>assert isinstance(current_streak([date(2026, 7, 1)]), int)<br>assert current_streak([]) >= 0<br><br>today = date(2026, 7, 22)<br>dates = [date(2026, 7, 21), date(2026, 7, 21)]<br>assert current_streak(dates, today=today) >= 0

A new piece of core business logic (current_streak) was added, but the tests provided are trivial and would not fail if the function's behavior were incorrect. The tests only check the return type and non-negativity, and they do not assert any concrete expected streak values (for example: when today is present in activity_dates; when there is a 3-day consecutive streak; when there is a break). According to TEAM-STANDARDS.md §2, every logic change must include tests that fail if the behavior breaks; these tests do not satisfy that requirement.

Suggested fix: Add unit tests that assert exact streak counts for representative scenarios, including at minimum:
- activity includes today (ensure today's activity is counted if intended),
- multi-day consecutive streaks (e.g. 3 consecutive days including today),
- a break in the streak,
- duplicates in input (already present but assert exact value),
- empty input (should be 0).
Each test should assert concrete numeric results so regressions are detected.

## Summary

Two S2 findings: (1) implementation contradicts its docstring by excluding today from the streak calculation, producing incorrect results; (2) the tests are insufficient to catch that regression — they use trivial assertions and do not assert expected numeric streak values.
