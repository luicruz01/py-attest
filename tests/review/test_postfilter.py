from typing import Any

from py_attest.review.postfilter import files_in_diff, merge_findings


def finding(**overrides: Any) -> dict[str, Any]:
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
        "severity": "S1",
        "requires_human_classification": False,
        "evidence_verified": True,
    }
    value.update(overrides)
    return value


def test_merge_findings_keeps_distinct_findings() -> None:
    first = finding()
    second = finding(line_start=2, line_end=2, title="Second")

    assert merge_findings([first, second]) == [first, second]


def test_merge_findings_collapses_an_exact_duplicate_keeping_the_strongest() -> None:
    weak = finding(title="weak", severity="S3", confidence="low")
    strong = finding(title="strong", severity="S1", confidence="high")

    assert merge_findings([weak, strong]) == [strong]


def test_merge_findings_keeps_the_first_seen_item_on_an_exact_tie() -> None:
    """Load-bearing for the review/deterministic.py seam (spec §5.3): F0.3 prepends its
    deterministic findings to the list before calling merge_findings, so a tie against
    an equal-strength LLM duplicate resolves in the deterministic finding's favor.
    """
    first = finding(title="deterministic-origin")
    second = finding(title="llm-origin")

    assert merge_findings([first, second]) == [first]


def test_merge_findings_identity_ignores_title() -> None:
    first = finding(title="First phrasing")
    second = finding(title="Second phrasing")

    assert merge_findings([first, second]) == [first]


def test_merge_findings_treats_different_rule_ids_at_the_same_location_as_distinct() -> None:
    first = finding(rule_id="pii-1")
    second = finding(rule_id="pii-2")

    assert merge_findings([first, second]) == [first, second]


def test_merge_findings_empty_list() -> None:
    assert merge_findings([]) == []


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


def test_ignores_a_diff_git_header_with_unbalanced_quoting() -> None:
    diff = 'diff --git a/"unterminated b/"unterminated\n'

    assert files_in_diff(diff) == set()


def test_ignores_a_diff_git_header_with_too_few_tokens() -> None:
    diff = "diff --git only-one-token\n"

    assert files_in_diff(diff) == set()
