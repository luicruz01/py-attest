from pathlib import Path

import pytest

from py_attest.review.context_pack import ContextPackError
from py_attest.review.egress.raw import build_raw_egress


def test_build_raw_egress_wraps_the_context_pack_and_reports_context_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "STANDARDS.md").write_text("be nice", encoding="utf-8")
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_raw_egress(diff, tmp_path, ("STANDARDS.md",))

    assert result.mode == "raw"
    assert result.report_block == {"mode": "raw", "context_files": ["STANDARDS.md"]}
    assert "be nice" in result.user_content
    assert "<unified-diff>" in result.user_content


def test_build_raw_egress_appends_the_author_stated_intent(tmp_path: Path) -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_raw_egress(diff, tmp_path, description="fixes a bug")

    assert "Author's stated intent:\nfixes a bug" in result.user_content


def test_build_raw_egress_propagates_context_pack_errors(tmp_path: Path) -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n+x\n"

    with pytest.raises(ContextPackError, match="required context file missing"):
        build_raw_egress(diff, tmp_path, ("missing.md",))


def test_build_raw_egress_includes_the_rules_block_when_given(tmp_path: Path) -> None:
    diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+x = 1\n"

    result = build_raw_egress(
        diff, tmp_path, rules_block="<review-rules>\n- id: code-quality-3\n</review-rules>\n"
    )

    assert "<review-rules>" in result.user_content
    assert "code-quality-3" in result.user_content
