# AI Quality Review: fix/mobile-sync-visibility
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S1 | 3-PII-logging | app/main.py:57 | Direct logging of PII (full_name and email) | high |

## Details

### 1. [S1] Direct logging of PII (full_name and email)

- Rule: `3-PII-logging`
- Location: `app/main.py:57`
- Confidence: high
- Evidence: logger.info(<br>    "sync: progress recorded for %s (%s) lesson=%s score=%s",<br>    student.full_name,<br>    student.email,<br>    record.lesson_id,<br>    record.score,<br>)

The new logging statement writes student.full_name and student.email directly to logs. TEAM-STANDARDS.md §3 forbids writing PII (and especially pii-minor) to logs; logs must use app.privacy.redact() to avoid direct or indirect exposure. Even though another log line uses redact() for student_id and lesson_id, this new statement bypasses redaction and will expose personal data (and for minors this is an S1 violation because minors' data must not be logged or leave the service).

Suggested fix: Remove the name and email from logs, or redact the payload before logging. For example, log only non-PII identifiers (student.id) or call app.privacy.redact() on a dict and log that. If logging is required for support/analytics, ensure data minimization and document a legal basis and retention policy in the PR; do not log pii-minor at all without explicit documented justification.

## Summary

One S1 finding: added logger.info writes student.full_name and student.email to logs, violating TEAM-STANDARDS.md §3 (PII logging).
