from pathlib import Path

import pytest

from tools.quality_gate.context_pack import CONTEXT_FILES, ContextPackError, build_context


def write_seed_context(root: Path) -> None:
    for index, relative_path in enumerate(CONTEXT_FILES):
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"content-{index}\n", encoding="utf-8")


def test_build_context_reads_runtime_files_and_diff(tmp_path: Path) -> None:
    write_seed_context(tmp_path)
    diff = "diff --git a/app/main.py b/app/main.py\n+changed\n"

    context = build_context(diff, tmp_path)

    for index, relative_path in enumerate(CONTEXT_FILES):
        assert f'<reference path="{relative_path}">\ncontent-{index}\n</reference>' in context
    assert f"<unified-diff>\n{diff.rstrip()}\n</unified-diff>" in context


def test_build_context_fails_clearly_when_seed_file_is_missing(tmp_path: Path) -> None:
    write_seed_context(tmp_path)
    (tmp_path / "app/privacy.py").unlink()

    with pytest.raises(ContextPackError, match="required context file missing: app/privacy.py"):
        build_context("diff", tmp_path)
