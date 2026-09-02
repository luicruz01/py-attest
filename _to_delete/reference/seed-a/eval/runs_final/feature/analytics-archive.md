# AI Quality Review: feature/analytics-archive
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

> **HUMAN REVIEW REQUESTED:** Low-confidence S1/S2 finding; merge is not blocked.

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S1 | 4-data-retention | app/archive.py:1 | Indefinite retention of archived progress created without a retention declaration | low |
| S1 | 3-PII-logging | app/archive.py:15 | Archive stores raw PII (including birthdate) and is indexed by is_minor | high |
| S2 | 2-testing | app/archive.py:11 | New archiving core logic added without tests that would detect regressions | high |

## Details

### 1. [S1] Indefinite retention of archived progress created without a retention declaration

- Rule: `4-data-retention`
- Location: `app/archive.py:1`
- Confidence: low
- Evidence: Se conserva indefinidamente para poder comparar year-over-year.

TEAM-STANDARDS §4 requires every persisted or copied dataset to declare its retention category in app.privacy.RETENTION_DAYS. This module's top-level text explicitly states the archive is kept "indefinidamente" and the code creates an ARCHIVE dataset, but no retention category was added to app.privacy.RETENTION_DAYS and no legal basis for indefinite retention (or for retaining minors' data beyond 90 days) is documented in the PR.

Suggested fix: Declare a retention category for this archive in app.privacy.RETENTION_DAYS (e.g. "progress_archive" and "progress_archive_minor") and enforce the appropriate retention (minors <= 90 days) or include a documented legal basis for longer retention in the PR. If analytics needs are satisfied without retaining full PII, minimize stored fields (see next finding).

### 2. [S1] Archive stores raw PII (including birthdate) and is indexed by is_minor

- Rule: `3-PII-logging`
- Location: `app/archive.py:15`
- Confidence: high
- Evidence: "full_name": student.full_name,<br>"birthdate": student.birthdate,<br>"is_minor": student.is_minor,

TEAM-STANDARDS §3 classifies full_name, email, and birthdate as PII (and pii-minor when is_minor is true). The archive stores student.full_name and student.birthdate verbatim and also records is_minor. Combined, this creates a dataset containing minors' PII. Storing minors' PII in an archival dataset without minimization or documented legal basis is a PII/minor-aggravated risk and must be handled per the standards (data minimization, retention, and legal basis).

Suggested fix: Avoid storing direct identifiers and sensitive fields. Replace full_name and birthdate with a pseudonymous identifier or hashed token, and store only non-identifying attributes needed for analytics (or aggregate data). If storing PII is required, add a retention category with a <=90-day retention for minors and document legal basis in the PR.

### 3. [S2] New archiving core logic added without tests that would detect regressions

- Rule: `2-testing`
- Location: `app/archive.py:11`
- Confidence: high
- Evidence: def archive_progress(student, record) -> None:

TEAM-STANDARDS §2 requires that every logic change include tests that fail if the behavior breaks. The diff adds core behavior (appending progress and student attributes into ARCHIVE) but provides no accompanying tests. Without tests that assert the archive receives the expected fields, enforces minimization for minors, and respects retention rules, regressions in archiving or inadvertent PII exposure will not be detected.

Suggested fix: Add unit tests for archive_progress that: (a) assert ARCHIVE length increases and contains the expected keys and values after a call; (b) verify that PII fields are handled according to policy (e.g. pseudonymized or omitted for minors); and (c) verify behavior when record or student have edge-case values. Also add integration tests that exercise the main.record_progress -> archive_progress flow so CI would catch regressions.

## Summary

The patch introduces an analytics archive that copies student PII (full_name, birthdate) and stores it indefinitely without declaring a retention category or documenting legal basis. This is a high-severity privacy and retention violation for minors' data (S1). Additionally, the new archiving behavior is not covered by tests (S2). Fixes should include adding retention categories in app.privacy.RETENTION_DAYS (with <=90 days for minors or legal justification), minimizing stored PII, and adding tests that would fail on regressions.
