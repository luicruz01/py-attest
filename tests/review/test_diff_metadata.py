"""Tests for the git-metadata helpers in review/diff.py (source.* fields, TRD §4.3).

These are new in F0.2 (needed for the report's `source` block); Seed A's diff.py only
had `_branch_diff`/`_gate_commit`, ported in tests/review/test_reviewer.py.
"""

import subprocess
from pathlib import Path
from typing import Any

import pytest

from py_attest.review import diff as diff_module
from py_attest.review.diff import (
    DiffError,
    _branch_diff,
    _gate_commit,
    _merge_base,
    _resolve_sha,
    patch_sha256,
)


def test_resolve_sha_returns_the_full_commit_sha_for_head() -> None:
    sha = _resolve_sha(Path.cwd(), "HEAD")

    assert len(sha) == 40
    assert sha.isalnum()


def test_gate_commit_returns_the_short_sha_for_head() -> None:
    short = _gate_commit(Path.cwd())

    assert 4 <= len(short) <= 40


def test_merge_base_of_head_and_itself_is_head() -> None:
    head = _resolve_sha(Path.cwd(), "HEAD")

    assert _merge_base(Path.cwd(), "HEAD", "HEAD") == head


def test_patch_sha256_is_deterministic_and_content_addressed() -> None:
    assert patch_sha256("same diff") == patch_sha256("same diff")
    assert patch_sha256("diff a") != patch_sha256("diff b")
    assert len(patch_sha256("x")) == 64


def test_resolve_sha_raises_diff_error_for_an_unknown_ref() -> None:
    with pytest.raises(DiffError, match="cannot resolve"):
        _resolve_sha(Path.cwd(), "not-a-real-ref-xyz")


def test_merge_base_raises_diff_error_for_unrelated_refs() -> None:
    with pytest.raises(DiffError, match="cannot resolve merge base"):
        _merge_base(Path.cwd(), "HEAD", "not-a-real-ref-xyz")


def test_branch_diff_raises_diff_error_when_git_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diff_module.shutil, "which", lambda _name: None)

    with pytest.raises(DiffError, match="git executable not found"):
        diff_module._branch_diff(Path.cwd(), "main", "feature/x")


def test_gate_commit_raises_diff_error_when_git_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diff_module.shutil, "which", lambda _name: None)

    with pytest.raises(DiffError, match="git executable not found"):
        _gate_commit(Path.cwd())


def test_merge_base_raises_diff_error_when_git_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(diff_module.shutil, "which", lambda _name: None)

    with pytest.raises(DiffError, match="git executable not found"):
        _merge_base(Path.cwd(), "main", "feature/x")


def test_branch_diff_raises_diff_error_on_git_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.CalledProcessError(128, command, output="", stderr="fatal: bad revision")

    monkeypatch.setattr(diff_module.subprocess, "run", fake_run)

    with pytest.raises(DiffError, match="fatal: bad revision"):
        diff_module._branch_diff(Path.cwd(), "main", "feature/x")


@pytest.mark.parametrize("bad_ref", ["-h", "--upload-pack=evil", "--exec"])
def test_resolve_sha_rejects_option_like_refs(bad_ref: str) -> None:
    """base/branch can be repo-controlled (Config.base_branch); passed as a standalone
    argv token to `git rev-parse`, a leading `-` would be read as an option, not a ref.
    """
    with pytest.raises(DiffError, match="looks like a command-line option"):
        _resolve_sha(Path.cwd(), bad_ref)


@pytest.mark.parametrize("bad_ref", ["-h", "--upload-pack=evil"])
def test_merge_base_rejects_option_like_refs(bad_ref: str) -> None:
    with pytest.raises(DiffError, match="looks like a command-line option"):
        _merge_base(Path.cwd(), bad_ref, "HEAD")
    with pytest.raises(DiffError, match="looks like a command-line option"):
        _merge_base(Path.cwd(), "HEAD", bad_ref)


def test_branch_diff_rejects_an_option_like_base(tmp_path: Path) -> None:
    """Regression test: base comes from repo-controlled Config.base_branch. Before this
    guard, `base = "--output=<path>...branch"` made `git diff` write an arbitrary file
    (verified empirically: `git diff --no-ext-diff --output=/tmp/x...HEAD --` really does
    create /tmp/x...HEAD). base/branch are one combined argv token here, unlike
    `_resolve_sha`/`_merge_base`, so this needed its own guard call.
    """
    target = tmp_path / "should-not-be-created"

    with pytest.raises(DiffError, match="looks like a command-line option"):
        _branch_diff(Path.cwd(), f"--output={target}", "HEAD")

    assert not target.exists()


def test_branch_diff_rejects_an_option_like_branch() -> None:
    with pytest.raises(DiffError, match="looks like a command-line option"):
        _branch_diff(Path.cwd(), "HEAD", "--upload-pack=evil")
