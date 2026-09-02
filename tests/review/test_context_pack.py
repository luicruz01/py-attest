from pathlib import Path

import pytest

from py_attest.review.context_pack import ContextPackError, build_context

CONTEXT_FILES = ("TEAM-STANDARDS.md", "app/models.py", "app/privacy.py")


def write_context_files(root: Path) -> None:
    for index, relative_path in enumerate(CONTEXT_FILES):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content-{index}\n", encoding="utf-8")


def test_build_context_reads_configured_files_and_diff(tmp_path: Path) -> None:
    write_context_files(tmp_path)
    diff = "diff --git a/app/main.py b/app/main.py\n+changed\n"

    context = build_context(diff, tmp_path, CONTEXT_FILES)

    for index, relative_path in enumerate(CONTEXT_FILES):
        assert f'<reference path="{relative_path}">\ncontent-{index}\n</reference>' in context
    assert f"<unified-diff>\n{diff.rstrip()}\n</unified-diff>" in context


def test_build_context_fails_clearly_when_a_configured_file_is_missing(tmp_path: Path) -> None:
    write_context_files(tmp_path)
    (tmp_path / "app/privacy.py").unlink()

    with pytest.raises(ContextPackError, match="required context file missing: app/privacy.py"):
        build_context("diff", tmp_path, CONTEXT_FILES)


def test_build_context_with_no_context_files_wraps_only_the_diff(tmp_path: Path) -> None:
    diff = "diff --git a/app/main.py b/app/main.py\n+changed\n"

    context = build_context(diff, tmp_path)

    assert context == f"<unified-diff>\n{diff.rstrip()}\n</unified-diff>\n"


def test_build_context_fails_clearly_when_a_configured_file_is_not_readable(
    tmp_path: Path,
) -> None:
    (tmp_path / "a-directory").mkdir()

    with pytest.raises(ContextPackError, match="cannot read required context file: a-directory"):
        build_context("diff", tmp_path, ["a-directory"])


def test_build_context_rejects_a_context_file_that_escapes_the_repo_root(
    tmp_path: Path,
) -> None:
    """context_files comes from the reviewed repo's own [tool.attest] config, so a `..`
    escape here is attacker-controlled -- a PR could otherwise point this at files
    outside the repo (e.g. credentials) and have them transmitted to the LLM provider.
    """
    outside = tmp_path.parent / "outside-secret.txt"
    outside.write_text("do-not-transmit-this\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(ContextPackError, match="context file escapes the repo root"):
        build_context("diff", repo_root, [f"../{outside.name}"])


def test_build_context_rejects_an_absolute_context_file_path(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("do-not-transmit-this\n", encoding="utf-8")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()

    with pytest.raises(ContextPackError, match="context file escapes the repo root"):
        build_context("diff", repo_root, [str(outside)])
