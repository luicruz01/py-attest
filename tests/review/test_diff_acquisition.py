"""Ported from Seed B's tests/quality_gate/test_diff.py (bounded acquisition, ADR-004
§2(d)). Import paths only change: `quality_gate.diff`/`quality_gate.config.Limits` ->
`py_attest.review.diff`/`py_attest.config.Limits`; `PatchError` -> `DiffError` (this port
keeps one exception base rather than introducing a parallel name for the same thing).
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from py_attest.config import Limits
from py_attest.review.diff import (
    DiffError,
    GitTimeout,
    PatchTooLarge,
    _read_bounded_process,
    acquire_patch,
    parse_unified_diff,
    resolve_commit,
)


def git(repo: Path, *args: str) -> str:
    git_executable = shutil.which("git")
    assert git_executable is not None
    result = subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
        [git_executable, *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


@pytest.fixture
def synthetic_repo(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "synthetic"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Synthetic Reviewer")
    git(repo, "config", "user.email", "reviewer@example.test")
    (repo / "sample.py").write_text("value = 1\n", encoding="utf-8")
    git(repo, "add", "sample.py")
    git(repo, "commit", "-qm", "initial")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "sample.py").write_text("value = 1\nresult = value + 1\n", encoding="utf-8")
    git(repo, "add", "sample.py")
    git(repo, "commit", "-qm", "logic")
    return repo, base, git(repo, "rev-parse", "HEAD")


def test_parser_supports_change_types_hunks_spaces_and_no_newline() -> None:
    text = """diff --git a/new.py b/new.py
new file mode 100644
--- /dev/null
+++ b/new.py
@@ -0,0 +1,2 @@
+one
+two
\\ No newline at end of file
diff --git a/old.py b/old.py
deleted file mode 100644
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
-gone
diff --git a/name.py b/renamed.py
similarity index 80%
rename from name.py
rename to renamed.py
@@ -1 +1 @@
-old
+new
diff --git "a/path with spaces.py" "b/path with spaces.py"
--- "a/path with spaces.py"
+++ "b/path with spaces.py"
@@ -2,2 +2,4 @@
 same
+first
 second
+third
"""
    files = parse_unified_diff(text)
    assert [item.change_type for item in files] == ["added", "deleted", "renamed", "modified"]
    assert files[3].path == "path with spaces.py"
    assert [line.number for line in files[3].added_lines] == [3, 5]
    assert [(line.number, line.content) for line in files[1].deleted_lines] == [(1, "gone")]
    assert [(line.number, line.content) for line in files[2].deleted_lines] == [(1, "old")]


def test_parser_supports_empty_and_binary_patches() -> None:
    assert parse_unified_diff("") == ()
    files = parse_unified_diff(
        "diff --git a/picture.bin b/picture.bin\n"
        "Binary files a/picture.bin and b/picture.bin differ\n"
    )
    assert files[0].binary is True


def test_no_newline_marker_does_not_change_old_or_new_line_numbers() -> None:
    files = parse_unified_diff(
        """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -4 +4 @@
-old
\\ No newline at end of file
+new
\\ No newline at end of file
"""
    )

    assert [(line.number, line.content) for line in files[0].deleted_lines] == [(4, "old")]
    assert [(line.number, line.content) for line in files[0].added_lines] == [(4, "new")]


def test_resolve_commit_rejects_option_injection(synthetic_repo: tuple[Path, str, str]) -> None:
    repo, _, _ = synthetic_repo
    with pytest.raises(DiffError, match="invalid ref"):
        resolve_commit(repo, "--help", 1)


def producer(script: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


@pytest.mark.parametrize(
    ("size", "limit", "succeeds"),
    [(9, 10, True), (10, 10, True), (11, 10, False)],
    ids=("below-limit", "exact-limit", "one-byte-over"),
)
def test_bounded_reader_enforces_exact_byte_limit(size: int, limit: int, succeeds: bool) -> None:
    process = producer(f"import sys; sys.stdout.buffer.write(b'x' * {size})")

    if succeeds:
        assert (
            _read_bounded_process(
                process,
                timeout=1,
                max_output_bytes=limit,
                output_limit_error=PatchTooLarge("patch byte limit exceeded"),
            )
            == b"x" * size
        )
    else:
        with pytest.raises(PatchTooLarge, match="patch byte limit exceeded"):
            _read_bounded_process(
                process,
                timeout=1,
                max_output_bytes=limit,
                output_limit_error=PatchTooLarge("patch byte limit exceeded"),
            )
    assert process.poll() is not None


def test_bounded_reader_terminates_producer_that_continues_after_limit() -> None:
    process = producer(
        "import sys,time\n"
        "while True:\n"
        " sys.stdout.buffer.write(b'x' * 1024); sys.stdout.buffer.flush(); time.sleep(0.001)"
    )

    with pytest.raises(PatchTooLarge, match="patch byte limit exceeded"):
        _read_bounded_process(
            process,
            timeout=1,
            max_output_bytes=10,
            output_limit_error=PatchTooLarge("patch byte limit exceeded"),
        )

    assert process.poll() is not None


def test_bounded_reader_timeout_is_sanitized_and_reaps_child() -> None:
    process = producer("import time; time.sleep(2)")

    with pytest.raises(GitTimeout, match="timed out") as captured:
        _read_bounded_process(
            process,
            timeout=0.01,
            max_output_bytes=10,
            output_limit_error=PatchTooLarge("patch byte limit exceeded"),
        )

    assert "sleep" not in str(captured.value)
    assert process.poll() is not None


def test_bounded_reader_drains_stderr_without_exposing_it() -> None:
    sensitive = "never expose synthetic stderr"
    process = producer(
        f"import sys; sys.stderr.write({sensitive!r} * 10000); sys.stdout.buffer.write(b'ok')"
    )

    output = _read_bounded_process(
        process,
        timeout=2,
        max_output_bytes=2,
        output_limit_error=PatchTooLarge("patch byte limit exceeded"),
    )

    assert output == b"ok"


def test_nonzero_git_exit_does_not_expose_stderr(synthetic_repo: tuple[Path, str, str]) -> None:
    repo, _, _ = synthetic_repo
    sensitive_ref = "missing-sensitive-ref"

    with pytest.raises(DiffError) as captured:
        resolve_commit(repo, sensitive_ref, 1)

    assert sensitive_ref not in str(captured.value)


def test_acquisition_builds_index_and_provenance(synthetic_repo: tuple[Path, str, str]) -> None:
    repo, base, head = synthetic_repo
    result = acquire_patch(repo, base, head, Limits())
    assert result.resolved_base == base
    assert result.resolved_head == head
    assert result.merge_base == base
    assert result.new_line_index == {"sample.py": {2}}
    assert result.old_line_index == {"sample.py": set()}
    assert len(result.sha256) == 64


def test_git_execution_preserves_safe_argument_and_environment_controls(
    synthetic_repo: tuple[Path, str, str],
) -> None:
    repo, base, head = synthetic_repo
    with patch("py_attest.review.diff.subprocess.Popen", wraps=subprocess.Popen) as spawn:
        acquire_patch(repo, base, head, Limits())

    for call in spawn.call_args_list:
        command = call.args[0]
        assert isinstance(command, list)
        assert command[0].endswith("git") or command[0] == "git"
        assert call.kwargs["shell"] is False
        assert call.kwargs["env"] == {
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
    diff_command = next(call.args[0] for call in spawn.call_args_list if "diff" in call.args[0])
    assert "--no-ext-diff" in diff_command
    assert "--no-textconv" in diff_command
    assert "--full-index" in diff_command
    assert diff_command[1:3] == ["-c", "core.quotepath=false"]


def test_resolution_merge_base_and_diff_have_independent_hard_caps(tmp_path: Path) -> None:
    calls: list[tuple[list[str], int, DiffError | None]] = []
    resolved = iter((b"a" * 40 + b"\n", b"b" * 40 + b"\n"))

    def fake_git(
        repo: Path,
        args: list[str],
        timeout: float,
        *,
        max_output_bytes: int,
        output_limit_error: DiffError | None = None,
    ) -> bytes:
        del repo, timeout
        calls.append((args, max_output_bytes, output_limit_error))
        if args[0] == "rev-parse":
            return next(resolved)
        if args[0] == "merge-base":
            return b"a" * 40 + b"\n"
        return b""

    with patch("py_attest.review.diff._git", side_effect=fake_git):
        acquire_patch(tmp_path, "base", "head", Limits(max_patch_bytes=123))

    assert [maximum for _, maximum, _ in calls] == [41, 41, 41, 123]
    assert isinstance(calls[-1][2], PatchTooLarge)


def test_acquisition_hashes_the_full_index_patch_sent_to_review(
    synthetic_repo: tuple[Path, str, str],
) -> None:
    repo, base, head = synthetic_repo
    result = acquire_patch(repo, base, head, Limits())
    index_line = next(line for line in result.raw_text.splitlines() if line.startswith("index "))
    assert re.fullmatch(r"index [0-9a-f]{40}\.\.[0-9a-f]{40} 100644", index_line)
    git_executable = shutil.which("git")
    assert git_executable is not None
    expected = subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
        [
            git_executable,
            "-c",
            "core.quotepath=false",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--full-index",
            "--find-renames",
            "--unified=3",
            base,
            head,
            "--",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    ).stdout
    assert result.raw_text.encode() == expected
    assert result.sha256 == hashlib.sha256(expected).hexdigest()


def test_patch_limit_is_enforced_during_acquisition(synthetic_repo: tuple[Path, str, str]) -> None:
    repo, base, head = synthetic_repo
    expected_size = acquire_patch(repo, base, head, Limits()).byte_count

    assert (
        acquire_patch(repo, base, head, Limits(max_patch_bytes=expected_size + 1)).byte_count
        == expected_size
    )
    assert (
        acquire_patch(repo, base, head, Limits(max_patch_bytes=expected_size)).byte_count
        == expected_size
    )
    with pytest.raises(PatchTooLarge, match="patch byte limit exceeded"):
        acquire_patch(repo, base, head, Limits(max_patch_bytes=expected_size - 1))


def test_binary_requires_human_review(tmp_path: Path) -> None:
    repo = tmp_path / "binary"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Synthetic")
    git(repo, "config", "user.email", "synthetic@example.test")
    (repo / "readme.txt").write_text("base\n", encoding="utf-8")
    git(repo, "add", "readme.txt")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "picture.bin").write_bytes(bytes(range(256)) * 4)
    git(repo, "add", "picture.bin")
    git(repo, "commit", "-qm", "binary")
    result = acquire_patch(repo, base, "HEAD", Limits())
    assert result.binary_count == 1
    assert result.complete is False


def test_representable_deletion_builds_old_index_without_forcing_incomplete(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "deletion"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Synthetic")
    git(repo, "config", "user.email", "synthetic@example.test")
    (repo / "module.py").write_text("keep = 1\nremove = 2\n", encoding="utf-8")
    git(repo, "add", "module.py")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    (repo / "module.py").write_text("keep = 1\n", encoding="utf-8")
    git(repo, "add", "module.py")
    git(repo, "commit", "-qm", "delete line")

    result = acquire_patch(repo, base, "HEAD", Limits())

    assert result.deleted_line_count == 1
    assert result.stats()["deleted_lines"] == 1
    assert result.old_line_index == {"module.py": {2}}
    assert result.new_line_index == {"module.py": set()}
    assert result.complete is True
    assert result.warnings == ()


def test_parser_rejects_unrepresentable_hunk_counts() -> None:
    malformed = """diff --git a/module.py b/module.py
--- a/module.py
+++ b/module.py
@@ -1,2 +1 @@
-removed
"""

    with pytest.raises(DiffError, match="unrepresentable"):
        parse_unified_diff(malformed)
