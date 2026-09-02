# Team Standards — Open English LMS

All pull requests are reviewed against this document.

## 1. Code quality

- Code is simple and readable. No dead code. No TODOs without a ticket reference.
- Errors are handled explicitly. Silent exception handling is not acceptable.
- All external input is validated.

## 2. Testing

- Every logic change includes tests that fail if the behavior breaks.
- Tests that cannot detect a regression (trivial assertions, fully mocked logic, no coverage of the business case) do not count as test coverage.
- Tests document expected behavior, including edge cases.

## 3. PII and logging

- Classification: `pii` (personal data of any user) and `pii-minor` (personal data of users under 18, subject to stricter handling). In this service, `full_name`, `email`, and `birthdate` are PII; when `is_minor` is true, they are `pii-minor`.
- PII must not be written to logs, directly or indirectly (through helper functions, `extra` fields, or object serialization). Use `app.privacy.redact()`.
- Data belonging to minors must not leave this service (analytics, support tooling, third parties) without data minimization and a documented legal basis.

## 4. Data retention

- Every persisted or copied dataset declares its retention category in `app.privacy.RETENTION_DAYS`.
- Data belonging to minors is retained for a maximum of 90 days unless a legal basis is documented in the pull request.
- Secondary copies of personal data without a defined purpose and retention period are not permitted. Apply data minimization.

## 5. Secrets

- Secrets are provided through environment variables only, never committed to the repository. A committed secret is treated as a security incident regardless of environment.

## 6. Review severities

- **S1 — blocks merge:** PII exposure (aggravated when `pii-minor` is involved), committed secrets, retention or minimization violations involving minors' data.
- **S2 — blocks merge:** logic bugs that produce incorrect data; core logic without effective tests.
- **S3 — comment, does not block:** style, naming, refactoring opportunities.
