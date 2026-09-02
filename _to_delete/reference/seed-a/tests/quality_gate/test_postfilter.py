import json
from pathlib import Path
from typing import Any

import pytest

from tools.quality_gate.gating import verdict
from tools.quality_gate.postfilter import files_in_diff, filter_findings

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


def finding(**overrides: Any) -> dict[str, Any]:
    value = {
        "rule": "3-PII-logging",
        "severity": "S1",
        "file": "app/main.py",
        "line": 1,
        "title": "PII logged",
        "evidence": "new value",
        "explanation": "Email reaches a log call.",
        "suggested_fix": "Redact the payload.",
        "confidence": "high",
    }
    value.update(overrides)
    return value


def apply(*findings: dict[str, Any]) -> dict[str, Any]:
    return filter_findings({"findings": list(findings), "summary": "summary"}, DIFF)


@pytest.fixture
def streaks_multifragment_review() -> tuple[dict[str, Any], str]:
    fixtures = Path(__file__).parent / "fixtures"
    review = json.loads(
        (fixtures / "pr2_streaks_multifragment_findings.json").read_text(encoding="utf-8")
    )
    diff = (fixtures / "streaks.patch").read_text(encoding="utf-8")
    return review, diff


def test_drops_findings_for_files_not_in_diff() -> None:
    result = apply(finding(file="app/privacy.py"))

    assert result["findings"] == []
    assert result["filtered_out"][0]["reason"] == "file_not_in_diff"


def test_drops_findings_with_invalid_severity() -> None:
    result = apply(finding(severity="S0"))

    assert result["findings"] == []
    assert result["filtered_out"][0]["reason"] == "invalid_severity"


def test_keeps_finding_when_evidence_and_line_match() -> None:
    matched = finding()

    result = apply(matched)

    assert result["findings"] == [{**matched, "evidence_verified": True}]
    assert result["filtered_out"] == []


def test_duplicate_collision_keeps_strongest_finding_in_reversed_order() -> None:
    weak = finding(title="weak", severity="S3", confidence="low")
    strong = finding(title="strong", severity="S1", confidence="high")

    result = apply(weak, strong)

    assert result["findings"] == [{**strong, "evidence_verified": True}]
    assert result["filtered_out"] == [
        {
            "finding": {**weak, "evidence_verified": True},
            "reason": "merged_duplicate",
        }
    ]


def test_file_level_findings_with_distinct_titles_both_survive() -> None:
    first = finding(line=None, title="First secret")
    second = finding(line=None, title="Second secret")

    result = apply(first, second)

    assert [value["title"] for value in result["findings"]] == ["First secret", "Second secret"]
    assert all(value["line"] == 1 for value in result["findings"])
    assert all(value["re_anchored"] is True for value in result["findings"])
    assert all(value["evidence_verified"] is True for value in result["findings"])


def test_keeps_distinct_findings_and_annotates_every_drop() -> None:
    first = finding()
    second = finding(line=2, evidence="another value")
    outside = finding(file="app/store.py")

    result = apply(first, second, outside)

    assert result["findings"] == [
        {**first, "evidence_verified": True},
        {**second, "evidence_verified": True},
    ]
    assert result["summary"] == "summary"
    assert result["filtered_out"] == [{"finding": outside, "reason": "file_not_in_diff"}]


def test_reanchors_evidence_to_its_added_source_line() -> None:
    misanchored = finding(line=99, evidence="  another value  ")

    result = apply(misanchored)

    assert result["findings"] == [
        {
            **misanchored,
            "line": 2,
            "evidence_verified": True,
            "re_anchored": True,
        }
    ]
    assert result["filtered_out"] == []


def test_degrades_evidence_that_is_not_in_added_lines() -> None:
    context_only = finding(evidence="old again")

    result = apply(context_only)

    assert result["findings"] == [{**context_only, "confidence": "low", "evidence_verified": False}]
    assert result["filtered_out"] == []


def test_evidence_match_normalizes_whitespace() -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -1,0 +1 @@\n"
        "+result = call(  one,   two)\n"
    )
    matched = finding(evidence="result = call( one, two)")

    result = filter_findings({"findings": [matched], "summary": "summary"}, diff)

    assert result["findings"] == [{**matched, "evidence_verified": True}]


def test_short_fragments_do_not_invalidate_matching_evidence() -> None:
    matched = finding(evidence="missing\n...\nnew value")

    result = apply(matched)

    assert result["findings"] == [{**matched, "evidence_verified": True}]


def test_every_substantive_fragment_must_match() -> None:
    partially_matched = finding(evidence="new value...missing fragment")

    result = apply(partially_matched)

    assert result["findings"] == [
        {**partially_matched, "confidence": "low", "evidence_verified": False}
    ]
    assert result["filtered_out"] == []


def test_pr2_streaks_multifragment_findings_survive_verified(
    streaks_multifragment_review: tuple[dict[str, Any], str],
) -> None:
    review, diff = streaks_multifragment_review

    result = filter_findings(review, diff)

    assert len(result["findings"]) == 2
    assert result["filtered_out"] == []
    assert [value["line"] for value in result["findings"]] == [6, 5]
    assert all(value["re_anchored"] is True for value in result["findings"])
    assert all(value["evidence_verified"] is True for value in result["findings"])
    assert all(value["confidence"] == "high" for value in result["findings"])
    assert verdict(result["findings"]) == ("BLOCK", 2)


def test_context_line_evidence_is_kept_low_confidence_and_cannot_block() -> None:
    diff = (
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n"
        "+++ b/app/main.py\n"
        "@@ -48,6 +48,7 @@ def record_progress(student_id: str, payload: dict):\n"
        "     student = _get_student(student_id)\n"
        '+    score = int(payload.get("score", 0))\n'
        '     logger.info("progress recorded %s", '
        'redact({"student_id": student.id, "lesson_id": record.lesson_id}))\n'
    )
    context_only = {
        "rule": "3-PII-logging",
        "severity": "S1",
        "file": "app/main.py",
        "line": 53,
        "title": "PII exposure in logs",
        "evidence": (
            'logger.info("progress recorded %s", '
            'redact({"student_id": student.id, "lesson_id": record.lesson_id}))'
        ),
        "explanation": "The log statement includes the student_id.",
        "suggested_fix": "Remove it from the log statement.",
        "confidence": "high",
    }

    result = filter_findings({"findings": [context_only], "summary": "One false positive."}, diff)

    assert result["findings"] == [{**context_only, "confidence": "low", "evidence_verified": False}]
    assert result["filtered_out"] == []
    assert verdict(result["findings"]) == ("COMMENT", 0)


def test_only_structural_failures_are_filtered_out() -> None:
    duplicate = finding(title="Duplicate")
    result = apply(
        duplicate,
        finding(title="Duplicate"),
        finding(file="app/store.py"),
        finding(severity="S0"),
        finding(
            rule="4-retention",
            line=2,
            evidence="unchanged context evidence",
        ),
    )

    assert len(result["findings"]) == 2
    assert result["findings"][1]["evidence_verified"] is False
    assert result["findings"][1]["confidence"] == "low"
    assert {value["reason"] for value in result["filtered_out"]} == {
        "merged_duplicate",
        "file_not_in_diff",
        "invalid_severity",
    }


def test_extracts_paths_from_standard_unified_diff_headers() -> None:
    diff = "--- app/old.py\n+++ app/new.py\n@@ -1 +1 @@\n-old\n+new\n"

    assert files_in_diff(diff) == {"app/old.py", "app/new.py"}


def test_extracts_non_ascii_paths_from_pure_rename_diff() -> None:
    diff = (
        "diff --git a/oldé.py b/newé.py\n"
        "similarity index 100%\n"
        "rename from oldé.py\n"
        "rename to newé.py\n"
    )

    assert files_in_diff(diff) == {"oldé.py", "newé.py"}
