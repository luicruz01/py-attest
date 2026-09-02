import json
from pathlib import Path

from py_attest.review.policy import verdict
from py_attest.review.postfilter import merge_findings
from py_attest.review.validation import changed_line_index, validate_findings
from py_attest.standards.registry import Registry, load_registry

FIXTURES = Path(__file__).parent / "fixtures"
DEFAULTS = Path(__file__).parents[2] / "py_attest" / "standards" / "defaults"

DIFF = """diff --git a/app/main.py b/app/main.py
index 1111111..2222222 100644
--- a/app/main.py
+++ b/app/main.py
@@ -1,2 +1,2 @@
-old
-old again
+new value
+another value
"""


def _registry() -> Registry:
    return load_registry(DEFAULTS / "core.standards.yml", DEFAULTS / "domain.standards.yml")


def _finding(**overrides: object) -> dict:
    value = {
        "rule_id": "pii-1",
        "path": "app/main.py",
        "side": "new",
        "line_start": 1,
        "line_end": 1,
        "title": "PII logged",
        "evidence": "new value",
        "explanation": "Email reaches a log call.",
        "suggested_fix": "Redact the payload.",
        "confidence": "high",
    }
    value.update(overrides)
    return value


def test_changed_line_index_tracks_both_sides() -> None:
    index = changed_line_index(DIFF)

    assert index["new"]["app/main.py"] == {1, 2}
    assert index["old"]["app/main.py"] == {1, 2}


CONTEXT_AND_DASH_PREFIXED_DIFF = (
    "diff --git a/app/main.py b/app/main.py\n"
    "--- a/app/main.py\n"
    "+++ b/app/main.py\n"
    "@@ -1,3 +1,3 @@\n"
    " keep this line\n"
    "--- legacy marker\n"
    "+new value\n"
    " old tail\n"
)


def test_changed_line_index_does_not_mistake_a_dash_prefixed_body_line_for_a_header() -> None:
    # The hunk has a real, untouched context line at both ends (exercising the
    # `elif not text.startswith("\\")` branch, which no other test in this file hit
    # before) and a removed line whose own content starts with "-- ", which -- once
    # diff-prefixed with the removal marker "-" -- becomes the line "--- legacy marker".
    # That must be classified as hunk-body content (a removed old-side line), never
    # mistaken for a "--- a/file" header just because it starts in the active hunk.
    index = changed_line_index(CONTEXT_AND_DASH_PREFIXED_DIFF)

    assert index["old"]["app/main.py"] == {2}
    assert index["new"]["app/main.py"] == {2}
    # old_file must stay "app/main.py" -- not get overwritten with "legacy marker".
    assert "legacy marker" not in index["old"]
    assert "legacy marker" not in index["new"]


def test_valid_finding_gets_resolved_severity() -> None:
    result = validate_findings(
        [_finding()], registry=_registry(), diff=DIFF, evidence_policy="degrade"
    )

    assert len(result.findings) == 1
    assert result.findings[0]["severity"] == "S1"
    assert result.findings[0]["requires_human_classification"] is False
    assert result.findings[0]["evidence_verified"] is True
    assert result.filtered_out == []
    assert result.review_complete is True


DB_DIFF = (
    "diff --git a/app/db.py b/app/db.py\n"
    "--- a/app/db.py\n"
    "+++ b/app/db.py\n"
    "@@ -0,0 +1,3 @@\n"
    "+a\n"
    "+b\n"
    "+c\n"
)


def test_contextual_rule_gets_no_severity_and_requires_human_classification() -> None:
    result = validate_findings(
        [_finding(rule_id="retention-1", path="app/db.py", line_start=3, line_end=3)],
        registry=_registry(),
        diff=DB_DIFF,
        evidence_policy="degrade",
    )

    [resolved] = result.findings
    assert resolved["severity"] is None
    assert resolved["requires_human_classification"] is True
    assert verdict(result.findings) == ("COMMENT", 0)


def test_degrade_drops_deterministic_mode_rule_id_as_unknown() -> None:
    # secrets-1 is a real, valid registry entry -- but mode: deterministic, so it was
    # never shown to the model in the <review-rules> block (render_rules_block only
    # lists registry.llm_rules()). A finding citing it is just as unverifiable as one
    # citing a made-up id and must be rejected the same way.
    registry = _registry()
    assert "secrets-1" in registry
    assert registry.rule("secrets-1").mode == "deterministic"

    result = validate_findings(
        [_finding(rule_id="secrets-1")],
        registry=registry,
        diff=DIFF,
        evidence_policy="degrade",
    )

    assert result.findings == []
    assert result.filtered_out[0]["reason"] == "unknown_rule_id"


def test_degrade_drops_unknown_rule_id_into_filtered_out() -> None:
    result = validate_findings(
        [_finding(rule_id="does-not-exist-1")],
        registry=_registry(),
        diff=DIFF,
        evidence_policy="degrade",
    )

    assert result.findings == []
    assert result.filtered_out == [
        {"finding": _finding(rule_id="does-not-exist-1"), "reason": "unknown_rule_id"}
    ]
    assert result.review_complete is True


def test_degrade_drops_out_of_range_finding_into_filtered_out() -> None:
    result = validate_findings(
        [_finding(line_start=99, line_end=99)],
        registry=_registry(),
        diff=DIFF,
        evidence_policy="degrade",
    )

    assert result.findings == []
    assert result.filtered_out[0]["reason"] == "range_not_in_changed_lines"


def test_degrade_keeps_valid_findings_next_to_filtered_out_invalid_ones() -> None:
    good = _finding()
    bad = _finding(rule_id="does-not-exist-1", line_start=2, line_end=2)

    result = validate_findings(
        [good, bad], registry=_registry(), diff=DIFF, evidence_policy="degrade"
    )

    assert len(result.findings) == 1
    assert result.findings[0]["rule_id"] == "pii-1"
    assert len(result.filtered_out) == 1


def test_fail_closed_invalidates_the_entire_response_on_any_invalid_finding() -> None:
    good = _finding()
    bad = _finding(rule_id="does-not-exist-1", line_start=2, line_end=2)

    result = validate_findings(
        [good, bad], registry=_registry(), diff=DIFF, evidence_policy="fail_closed"
    )

    assert result.findings == []
    assert result.filtered_out == []
    assert result.review_complete is False
    assert result.invalid_count == 1
    assert result.total_count == 2
    assert result.invalidated_reasons == frozenset({"unknown_rule_id"})


def test_fail_closed_keeps_a_fully_valid_response() -> None:
    result = validate_findings(
        [_finding()], registry=_registry(), diff=DIFF, evidence_policy="fail_closed"
    )

    assert len(result.findings) == 1
    assert result.review_complete is True


def test_streaks_findings_validate_and_produce_block() -> None:
    review = json.loads((FIXTURES / "pr2_streaks_findings.json").read_text(encoding="utf-8"))
    diff = (FIXTURES / "streaks.patch").read_text(encoding="utf-8")

    result = validate_findings(
        review["findings"], registry=_registry(), diff=diff, evidence_policy="degrade"
    )

    assert result.filtered_out == []
    assert {f["rule_id"] for f in result.findings} == {"code-quality-6", "testing-3"}
    assert all(f["severity"] == "S2" for f in result.findings)
    merged = merge_findings(result.findings)
    assert verdict(merged) == ("BLOCK", 2)
