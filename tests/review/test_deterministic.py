"""Ported from Seed B's tests/quality_gate/test_controls.py (deterministic-specific
cases only; the redaction.py cases live in tests/review/test_redaction.py). Adapted to
build the synthetic patch via review/diff.py's ChangedFile/Hunk/AddedLine, and to the
canonical finding shape (rule_id/path/side/line_start/line_end/severity/
requires_human_classification/evidence_verified) resolved against a real Registry --
severity is never a local constant (ADR-001).
"""

from py_attest.review.deterministic import run_checks
from py_attest.review.diff import AddedLine, ChangedFile, Hunk
from py_attest.standards.registry import Registry, Rule, Section

REGISTRY = Registry(
    core_sections=(
        Section(
            slug="code-quality",
            title="Code quality",
            rules=(
                Rule(
                    id="code-quality-5",
                    title="Reference a ticket in TODOs",
                    mode="deterministic",
                    description="A TODO introduced by a patch must include a ticket reference.",
                    severity="S3",
                    check="todo-ticket-ref",
                ),
            ),
        ),
        Section(
            slug="secrets",
            title="Secrets",
            rules=(
                Rule(
                    id="secrets-1",
                    title="No committed secrets",
                    mode="deterministic",
                    description="Secrets are provided through environment variables only.",
                    severity="S1",
                    check="gitleaks",
                ),
            ),
        ),
    ),
    domain_sections=(),
)


def synthetic_files(*lines: str) -> tuple[ChangedFile, ...]:
    added = tuple(AddedLine(number, content) for number, content in enumerate(lines, 1))
    changed = ChangedFile("module.py", None, "added", (Hunk(0, 0, 1, len(lines), added),))
    return (changed,)


def test_todo_requires_ticket_reference() -> None:
    findings = run_checks(
        synthetic_files("# TODO improve", "# TODO ABC-123 improve", "# TODO #42 improve"),
        REGISTRY,
    )

    assert [(item["rule_id"], item["line_start"]) for item in findings] == [("code-quality-5", 1)]
    [todo_finding] = findings
    assert todo_finding["severity"] == "S3"
    assert todo_finding["path"] == "module.py"
    assert todo_finding["side"] == "new"
    assert todo_finding["line_end"] == todo_finding["line_start"]
    assert todo_finding["requires_human_classification"] is False
    assert todo_finding["evidence_verified"] is True
    assert todo_finding["confidence"] == "high"


def test_secret_evidence_never_contains_value() -> None:
    secret = "x" * 24
    findings = run_checks(synthetic_files("api_key = '" + secret + "'"), REGISTRY)

    assert findings[0]["rule_id"] == "secrets-1"
    assert findings[0]["severity"] == "S1"
    assert secret not in findings[0]["evidence"]
    assert "[REDACTED_SECRET]" in findings[0]["evidence"]


def test_findings_are_high_confidence_and_evidence_verified() -> None:
    findings = run_checks(synthetic_files("api_key = '" + "x" * 24 + "'"), REGISTRY)

    assert findings[0]["confidence"] == "high"
    assert findings[0]["evidence_verified"] is True
    assert findings[0]["requires_human_classification"] is False


def test_clean_lines_produce_no_findings() -> None:
    findings = run_checks(synthetic_files("value = 1", "# TODO ABC-123 improve"), REGISTRY)

    assert findings == ()


def test_severity_is_resolved_from_the_registry_not_a_local_constant() -> None:
    """Regression test: severity must come from `registry.fixed_severity(rule_id)`, so a
    registry with different severities for these rules changes what deterministic.py reports.
    """
    downgraded = Registry(
        core_sections=(
            Section(
                slug="secrets",
                title="Secrets",
                rules=(
                    Rule(
                        id="secrets-1",
                        title="No committed secrets",
                        mode="deterministic",
                        description="...",
                        severity="S2",
                    ),
                ),
            ),
        ),
        domain_sections=(),
    )

    [committed_secret] = run_checks(synthetic_files("api_key = '" + "x" * 24 + "'"), downgraded)

    assert committed_secret["severity"] == "S2"
