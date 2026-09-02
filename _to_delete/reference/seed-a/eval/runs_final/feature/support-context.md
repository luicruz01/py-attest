# AI Quality Review: feature/support-context
Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 6e10c5e

> **VERDICT: BLOCK**

## Findings

| Severity | Rule | File:line | Title | Confidence |
| --- | --- | --- | --- | --- |
| S1 | 3-PII-logging | app/support.py:37 | Unredacted PII (including birthdate) collected and logged | high |
| S2 | 2-testing | app/support.py:4 | New support logic added without tests | high |

## Details

### 1. [S1] Unredacted PII (including birthdate) collected and logged

- Rule: `3-PII-logging`
- Location: `app/support.py:37`
- Confidence: high
- Evidence: logger.info("progress lookup %s", build_support_context(student, records))<br><br>def build_support_context(student, records):<br>    return {<br>        "student": f"{student.full_name} <{student.email}>",<br>        "birthdate": student.birthdate,<br>        "country": student.country,<br>        "records": len(records),<br>    }

The new support context assembles and the code logs direct personal data fields: full_name, email, and birthdate. TEAM-STANDARDS.md §3 requires that PII must not be written to logs and that app.privacy.redact() be used. birthdate explicitly reveals age and, if the student is a minor, this is `pii-minor` — PII exposure involving minors is S1 and blocks merge.

Suggested fix: Do not log unredacted PII. Build a minimised, non-identifying support payload and/or apply app.privacy.redact() to any payload before logging. For example, log only non-PII (country, records count) and if an identifying field is required for support, log a redacted version: redact({"full_name": student.full_name, "email": student.email, "birthdate": student.birthdate, ...}). Also ensure code avoids including minors' data in logs unless a documented legal basis is present in the PR.

### 2. [S2] New support logic added without tests

- Rule: `2-testing`
- Location: `app/support.py:4`
- Confidence: high
- Evidence: def build_support_context(student, records):

The PR adds new behavior (build_support_context) that composes a support payload containing personal data and is used by the logged path in get_progress. TEAM-STANDARDS.md §2 requires that every logic change includes tests that fail if the behavior breaks. There are no accompanying tests in this diff that would catch regressions in how the support context is constructed or that logging doesn't inadvertently include PII.

Suggested fix: Add unit tests for build_support_context to validate the exact structure returned, ensure PII fields are handled appropriately (e.g. redacted when required), and tests for get_progress to assert that logging occurs only with safe/redacted payloads. Tests should fail if PII is exposed or if the support payload shape changes unexpectedly.

## Summary

The PR introduces a support context builder and logs its output. This directly constructs and logs unredacted personal fields (full_name, email, birthdate), which is a PII exposure and — if the student is a minor — escalates to pii-minor handling rules (S1). Additionally, the new logic is untested (S2). Fix by removing unredacted PII from logs (use app.privacy.redact() or log only non-identifying fields) and adding unit tests that would catch regressions and any accidental PII exposure.
