"""Ported from Seed B's tests/quality_gate/test_egress.py: the pure `prepare_provider_payload`
tests port as-is (only the import path changes). The tests that exercised Seed B's whole
`reviewer.review()` pipeline (SpyProvider, git repos, decision/report assertions) are not
portable -- that pipeline isn't ported; equivalent end-to-end coverage (secret detection
blocking before any provider call, minimized mode wired into the report) lives in
tests/review/test_reviewer.py instead.
"""

import pytest

from py_attest.review.egress.minimized import (
    build_minimized_egress,
    prepare_provider_payload,
)


def test_literal_and_metadata_minimization_removes_positional_personal_data() -> None:
    full_name = "Avery" + " Exampleton"
    birthdate = "2012" + "-04-19"
    raw_patch = (
        """diff --git a/module.py b/module.py
index 1111111111111111111111111111111111111111..2222222222222222222222222222222222222222 100644
--- a/module.py
+++ b/module.py
@@ -1 +1,2 @@
 value = 1
+student = ("""
        + repr(full_name)
        + ", "
        + repr(birthdate)
        + ")\n"
    )

    payload = prepare_provider_payload(
        raw_patch,
        "Review for " + full_name,
        "Student birthdate " + birthdate,
    )

    combined = "\n".join((payload.patch, payload.title, payload.description))
    assert full_name not in combined
    assert birthdate not in combined
    assert payload.patch != raw_patch
    assert "module.py" not in payload.patch
    assert payload.path_aliases == {"file_0001.py": "module.py"}
    assert "student = ([MINIMIZED_TEXT]" not in payload.patch
    assert "student = ('[MINIMIZED_TEXT]', '[REDACTED_PII]')" in payload.patch
    assert payload.title == payload.description == "[MINIMIZED_TEXT]"


def test_minimized_patch_preserves_review_semantics_on_both_sides() -> None:
    raw_patch = """diff --git a/rules/eligibility.py b/rules/eligibility.py
index 1111111111111111111111111111111111111111..2222222222222222222222222222222222222222 100644
--- a/rules/eligibility.py
+++ b/rules/eligibility.py
@@ -1,2 +1,4 @@
-def evaluate(record):
-    return service.compute(record.score, 1)
+def evaluate(record):
+    if record.score >= 90 and record.attempts < 3:
+        return service.compute(record.score, 2)
+    return 0
"""

    payload = prepare_provider_payload(raw_patch, None, None)

    assert payload.path_aliases == {"file_0001.py": "rules/eligibility.py"}
    assert "rules/eligibility.py" not in payload.patch
    assert "-def evaluate(record):" in payload.patch
    assert "-    return service.compute(record.score, 1)" in payload.patch
    assert "+    if record.score >= 90 and record.attempts < 3:" in payload.patch
    assert "+        return service.compute(record.score, 2)" in payload.patch
    assert "+    return 0" in payload.patch


def test_rename_paths_receive_distinct_stable_aliases() -> None:
    raw_patch = """diff --git a/before.py b/after.py
similarity index 80%
rename from before.py
rename to after.py
--- a/before.py
+++ b/after.py
@@ -1 +1 @@
-old = calculate()
+new = calculate()
"""

    payload = prepare_provider_payload(raw_patch, None, None)

    assert payload.path_aliases == {"file_0001.py": "before.py", "file_0002.py": "after.py"}
    assert "diff --git a/file_0001.py b/file_0002.py" in payload.patch
    assert "rename from file_0001.py" in payload.patch
    assert "rename to file_0002.py" in payload.patch
    assert "--- a/file_0001.py" in payload.patch
    assert "+++ b/file_0002.py" in payload.patch


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("data.json", '{"name":"Avery Exampleton","identifier":123456789012}'),
        ("data.yaml", "name: Avery Exampleton"),
        ("data.toml", 'name = "Avery Exampleton"'),
        ("settings.env", "FULL_NAME=Avery Exampleton"),
        ("data.csv", "name,identifier\nAvery Exampleton,123456789012"),
        ("notes.md", "Student Avery Exampleton"),
        ("notes.txt", "Student Avery Exampleton"),
    ],
)
def test_data_file_values_are_not_provider_visible(path: str, body: str) -> None:
    lines = body.splitlines()
    raw_patch = "\n".join(
        [
            f"diff --git a/{path} b/{path}",
            "new file mode 100644",
            "--- /dev/null",
            f"+++ b/{path}",
            f"@@ -0,0 +1,{len(lines)} @@",
            *[f"+{line}" for line in lines],
            "",
        ]
    )

    payload = prepare_provider_payload(raw_patch, None, None)

    assert "Avery Exampleton" not in payload.patch
    assert "123456789012" not in payload.patch
    assert path not in payload.patch


def test_names_dates_long_identifiers_and_credentials_are_not_visible() -> None:
    jwt = "eyJ" + "a" * 12 + "." + "b" * 12 + "." + "c" * 12
    token = "gh" + "p_" + "d" * 24
    private_begin = "-----BEGIN " + "PRIVATE KEY-----"
    private_end = "-----END " + "PRIVATE KEY-----"
    raw_patch = f"""diff --git a/private/student.py b/private/student.py
new file mode 100644
--- /dev/null
+++ b/private/student.py
@@ -0,0 +1,6 @@
+name = "Avery Exampleton"
+birthdate = "2012-04-19"
+identifier = 123456789012
+token = "{token}"
+jwt = "{jwt}"
+key = "{private_begin} material {private_end}"
"""

    payload = prepare_provider_payload(
        raw_patch,
        "Review Avery Exampleton",
        "Birthdate 2012-04-19 and identifier 123456789012",
    )
    combined = "\n".join((payload.patch, payload.title, payload.description))

    for sensitive in (
        "Avery Exampleton",
        "2012-04-19",
        "123456789012",
        token,
        jwt,
        private_begin,
        private_end,
        "private/student.py",
    ):
        assert sensitive not in combined


def test_build_minimized_egress_returns_the_report_block_and_payload_version() -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_minimized_egress(diff, title="Add x", description="adds x")

    assert result.mode == "minimized"
    assert result.report_block == {"mode": "minimized", "payload_version": "MINIMIZED_PATCH_V2"}
    assert "MINIMIZED_PATCH_V2" in result.user_content
    assert "f.py" not in result.user_content


def test_build_minimized_egress_exposes_path_aliases_for_de_aliasing_the_response() -> None:
    """A model shown a minimized payload can only cite the aliased path it was given
    (e.g. file_0001.py) -- reviewer.py needs this mapping back to the real path so a
    finding's declared location can be checked against the real diff. Without this,
    every minimized-mode finding cites a path that never appears in the real diff and
    is unconditionally rejected as range_not_in_changed_lines, regardless of whether
    the finding is otherwise correct."""
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_minimized_egress(diff, title="Add x", description="adds x")

    assert result.path_aliases == {"file_0001.py": "f.py"}


def test_build_minimized_egress_propagates_egress_error_for_unsupported_text() -> None:
    from py_attest.review.egress.minimized import EgressError

    diff = "diff --git a/f b/f\n--- a/f\n+++ b/f\n@@ -0,0 +1 @@\n+\x01bad\n"

    with pytest.raises(EgressError):
        build_minimized_egress(diff)


def test_build_minimized_egress_includes_the_rules_block_when_given() -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_minimized_egress(
        diff, rules_block="<review-rules>\n- id: code-quality-3\n</review-rules>\n"
    )

    assert "<review-rules>" in result.user_content
    assert "code-quality-3" in result.user_content
