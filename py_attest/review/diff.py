"""Acquire a git diff and repo commit metadata as data (never executes repo code).

Bounded acquisition (ADR-004 SS2(d), ported from Seed B's ``quality_gate/diff.py``):
full 40-char SHAs, merge-base, streaming byte/time limits from ``[tool.attest.limits]``,
``--no-textconv --full-index``, and a restricted subprocess environment. Seed A's
``--branch``/``--base`` entry point (``_branch_diff``) sits on top of it unchanged in
spirit, now routed through the bounded primitives instead of a plain, unbounded
``subprocess.run``.

The diff-structure dataclasses (``Patch``/``ChangedFile``/``Hunk``/``AddedLine``/
``DeletedLine``) live here, not in ``review/models.py`` -- that module is Seed A's
*LLM-output* Finding schema (a different concern, owned by F0.4) and is never touched by
this port.
"""

from __future__ import annotations

import hashlib
import os
import re
import selectors
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from py_attest.config import Limits

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_COMMIT_OUTPUT_BYTES = 41
_READ_CHUNK_BYTES = 64 * 1024
_REAP_TIMEOUT_SECONDS = 1.0
_GIT_ENV = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_NOSYSTEM": "1"}
_REMOVED_CONTROL_PATTERNS = (
    re.compile(r"\b(?:redact|mask|sanitize)\s*\(", re.IGNORECASE),
    re.compile(
        r"\b(?:authorize|authorization|is_authorized|check_permission|require_auth|permission)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:validate|validation|validator|is_valid)\b", re.IGNORECASE),
    re.compile(r"\b(?:retention(?:_days)?|expires_at|expiry|time_to_live|ttl)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:getenv|environ|secret_manager|verify_signature|compare_digest)\b", re.IGNORECASE
    ),
)

_DEFAULT_LIMITS = Limits()


class DiffError(RuntimeError):
    """Raised when the diff or repo metadata cannot be acquired from git."""


class GitTimeout(DiffError):
    """Raised when a git subprocess exceeds its bounded timeout."""


class PatchTooLarge(DiffError):
    """Raised when acquired output exceeds ``limits.max_patch_bytes``."""


# --- diff-structure dataclasses (ADR-004 §2(d), ported from Seed B's models.py) -------


@dataclass(frozen=True)
class AddedLine:
    number: int
    content: str


@dataclass(frozen=True)
class DeletedLine:
    number: int
    content: str


@dataclass(frozen=True)
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    added_lines: tuple[AddedLine, ...] = ()
    deleted_lines: tuple[DeletedLine, ...] = ()


@dataclass(frozen=True)
class ChangedFile:
    path: str
    old_path: str | None
    change_type: Literal["added", "modified", "deleted", "renamed"]
    hunks: tuple[Hunk, ...] = ()
    binary: bool = False

    @property
    def added_lines(self) -> tuple[AddedLine, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.added_lines)

    @property
    def deleted_lines(self) -> tuple[DeletedLine, ...]:
        return tuple(line for hunk in self.hunks for line in hunk.deleted_lines)


@dataclass(frozen=True)
class Patch:
    requested_base: str
    resolved_base: str
    resolved_head: str
    merge_base: str
    sha256: str
    files: tuple[ChangedFile, ...]
    byte_count: int
    added_line_count: int
    binary_count: int
    deleted_line_count: int = 0
    complete: bool = True
    warnings: tuple[str, ...] = ()
    raw_text: str = field(default="", repr=False, compare=False)

    @property
    def line_indexes(self) -> dict[str, dict[str, set[int]]]:
        indexes: dict[str, dict[str, set[int]]] = {"old": {}, "new": {}}
        for item in self.files:
            old_path = item.old_path or item.path
            indexes["old"].setdefault(old_path, set()).update(
                line.number for line in item.deleted_lines
            )
            indexes["new"].setdefault(item.path, set()).update(
                line.number for line in item.added_lines
            )
        return indexes

    @property
    def old_line_index(self) -> dict[str, set[int]]:
        return self.line_indexes["old"]

    @property
    def new_line_index(self) -> dict[str, set[int]]:
        return self.line_indexes["new"]

    def stats(self) -> dict[str, int]:
        return {
            "files": len(self.files),
            "added_lines": self.added_line_count,
            "deleted_lines": self.deleted_line_count,
            "binary_files": self.binary_count,
            "patch_bytes": self.byte_count,
        }


# --- bounded, streaming git execution (ADR-004 §2(d)) ---------------------------------


def _close_process_pipes(process: subprocess.Popen[bytes]) -> None:
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _terminate_and_reap(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=_REAP_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        process.wait()
    finally:
        _close_process_pipes(process)


def _read_bounded_process(
    process: subprocess.Popen[bytes],
    *,
    timeout: float,
    max_output_bytes: int,
    output_limit_error: DiffError,
) -> bytes:
    """Read stdout up to ``max_output_bytes``, aborting the process at the first byte
    over the limit rather than buffering an unbounded amount of output in memory.
    """
    if process.stdout is None or process.stderr is None:
        _terminate_and_reap(process)
        raise DiffError("Git could not be executed")
    deadline = time.monotonic() + timeout
    output = bytearray()
    selector = selectors.DefaultSelector()
    try:
        for stream, name in ((process.stdout, "stdout"), (process.stderr, "stderr")):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _terminate_and_reap(process)
                raise GitTimeout("Git operation timed out")
            events = selector.select(remaining)
            if not events:
                _terminate_and_reap(process)
                raise GitTimeout("Git operation timed out")
            for key, _ in events:
                try:
                    chunk = os.read(key.fd, _READ_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                if key.data == "stdout":
                    remaining_capacity = max_output_bytes + 1 - len(output)
                    if remaining_capacity > 0:
                        output.extend(chunk[:remaining_capacity])
                    if len(output) > max_output_bytes or len(chunk) > remaining_capacity:
                        _terminate_and_reap(process)
                        raise output_limit_error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_and_reap(process)
            raise GitTimeout("Git operation timed out")
        try:
            returncode = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            _terminate_and_reap(process)
            raise GitTimeout("Git operation timed out") from exc
        _close_process_pipes(process)
    except (GitTimeout, DiffError):
        raise
    except OSError as exc:
        _terminate_and_reap(process)
        raise DiffError("Git could not be executed") from exc
    finally:
        selector.close()
    if returncode != 0:
        raise DiffError("Git could not resolve or compare the requested commits")
    return bytes(output)


def _git(
    repo: Path,
    args: list[str],
    timeout: float,
    *,
    max_output_bytes: int,
    output_limit_error: DiffError | None = None,
) -> bytes:
    git_executable = shutil.which("git")
    if git_executable is None:
        raise DiffError("cannot run git: git executable not found")
    started = time.monotonic()
    try:
        process = subprocess.Popen(  # noqa: S603 - absolute executable, list argv, no shell
            [git_executable, *args],
            cwd=repo,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=dict(_GIT_ENV),
        )
    except OSError as exc:
        raise DiffError("Git could not be executed") from exc
    remaining = timeout - (time.monotonic() - started)
    if remaining <= 0:
        _terminate_and_reap(process)
        raise GitTimeout("Git operation timed out")
    return _read_bounded_process(
        process,
        timeout=remaining,
        max_output_bytes=max_output_bytes,
        output_limit_error=output_limit_error or DiffError("Git returned excessive output"),
    )


def _reject_option_like_ref(ref: str) -> None:
    """Reject a ref that would be parsed as a git command-line option.

    `base`/`branch` come from repo-controlled config (Config.base_branch, or a
    reviewed repo's own [tool.attest]) or a CLI flag. A leading `-` would let git read
    the value as an option instead of a ref -- e.g. `base = "--output=/tmp/x"` makes
    `git diff --no-ext-diff --output=/tmp/x...branch --` write an arbitrary file outside
    the repo (verified empirically). Refs are validated explicitly rather than relying
    on `--`/`--end-of-options`, which are easy to place incorrectly relative to other
    flags and don't cover every git subcommand the same way.
    """
    if ref.startswith("-"):
        raise DiffError(f"invalid ref: {ref!r} looks like a command-line option")


def resolve_commit(repo: Path, ref: str, timeout: float) -> str:
    """Resolve ``ref`` to its full 40-char SHA, rejecting anything that isn't a ref."""
    if not isinstance(ref, str) or not ref or "\x00" in ref:
        raise DiffError("invalid commit reference")
    _reject_option_like_ref(ref)
    raw = _git(
        repo,
        ["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        timeout,
        max_output_bytes=_COMMIT_OUTPUT_BYTES,
    )
    sha = raw.decode("ascii", "strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise DiffError("Git returned an invalid commit identifier")
    return sha


# --- unified diff parsing (ADR-004 §2(d)) ----------------------------------------------


def _strip_prefix(path: str) -> str:
    return path[2:] if path.startswith(("a/", "b/")) else path


def parse_unified_diff(text: str) -> tuple[ChangedFile, ...]:
    files: list[ChangedFile] = []
    current: dict[str, object] | None = None
    hunks: list[Hunk] = []
    hunk_data: dict[str, object] | None = None
    old_seen = new_seen = 0

    def finish_hunk() -> None:
        nonlocal hunk_data, old_seen, new_seen
        if hunk_data is not None:
            if old_seen != hunk_data["old_count"] or new_seen != hunk_data["new_count"]:
                raise DiffError("malformed or unrepresentable diff hunk")
            hunks.append(Hunk(**hunk_data))
            hunk_data = None
            old_seen = new_seen = 0

    def finish_file() -> None:
        nonlocal current, hunks
        if current is not None:
            finish_hunk()
            current["hunks"] = tuple(hunks)
            files.append(ChangedFile(**current))
        current = None
        hunks = []

    old_line = new_line = 0
    for line in text.splitlines():
        if line.startswith("diff --git "):
            finish_file()
            try:
                parts = shlex.split(line[len("diff --git ") :])
            except ValueError as exc:
                raise DiffError("malformed diff path header") from exc
            if len(parts) != 2:
                raise DiffError("malformed diff path header")
            current = {
                "old_path": _strip_prefix(parts[0]),
                "path": _strip_prefix(parts[1]),
                "change_type": "modified",
                "binary": False,
            }
            continue
        if current is None:
            continue
        if line.startswith("new file mode "):
            current["change_type"] = "added"
        elif line.startswith("deleted file mode "):
            current["change_type"] = "deleted"
        elif line.startswith("rename from "):
            current["change_type"] = "renamed"
            current["old_path"] = line[len("rename from ") :]
        elif line.startswith("rename to "):
            current["path"] = line[len("rename to ") :]
        elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            current["binary"] = True
        elif match := _HUNK.match(line):
            finish_hunk()
            old_line, new_line = int(match[1]), int(match[3])
            hunk_data = {
                "old_start": old_line,
                "old_count": int(match[2] or 1),
                "new_start": new_line,
                "new_count": int(match[4] or 1),
                "added_lines": (),
                "deleted_lines": (),
            }
            old_seen = new_seen = 0
        elif hunk_data is not None:
            added = list(hunk_data["added_lines"])
            deleted = list(hunk_data["deleted_lines"])
            if line.startswith("+"):
                added.append(AddedLine(new_line, line[1:]))
                new_line += 1
                new_seen += 1
            elif line.startswith("-"):
                deleted.append(DeletedLine(old_line, line[1:]))
                old_line += 1
                old_seen += 1
            elif line.startswith(" "):
                old_line += 1
                new_line += 1
                old_seen += 1
                new_seen += 1
            elif line == "\\ No newline at end of file":
                pass
            else:
                raise DiffError("malformed or unrepresentable diff hunk")
            hunk_data["added_lines"] = tuple(added)
            hunk_data["deleted_lines"] = tuple(deleted)
    finish_file()
    return tuple(files)


def _has_unresolved_removed_control(item: ChangedFile) -> bool:
    deleted = "\n".join(line.content for line in item.deleted_lines)
    added = "\n".join(line.content for line in item.added_lines)
    return any(
        pattern.search(deleted) and not pattern.search(added)
        for pattern in _REMOVED_CONTROL_PATTERNS
    )


def acquire_patch(
    repo: str | Path, base: str, head: str, limits: Limits = _DEFAULT_LIMITS
) -> Patch:
    """Bounded, streaming acquisition of the diff between ``base`` and ``head``.

    Aborts at the first byte over ``limits.max_patch_bytes`` instead of buffering an
    unbounded ``git diff`` in memory; resolves full 40-char SHAs and the merge-base so
    the report's `source` block is unambiguous.
    """
    root = Path(repo).resolve()
    if not root.is_dir():
        raise DiffError("repository path is not a directory")
    base_sha = resolve_commit(root, base, limits.git_timeout)
    head_sha = resolve_commit(root, head, limits.git_timeout)
    merge_base_raw = _git(
        root,
        ["merge-base", base_sha, head_sha],
        limits.git_timeout,
        max_output_bytes=_COMMIT_OUTPUT_BYTES,
    )
    merge_base = merge_base_raw.decode("ascii", "strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", merge_base):
        raise DiffError("Git returned an invalid merge base")
    raw = _git(
        root,
        [
            "-c",
            "core.quotepath=false",
            "diff",
            "--no-ext-diff",
            "--no-textconv",
            "--full-index",
            "--find-renames",
            "--unified=3",
            merge_base,
            head_sha,
            "--",
        ],
        limits.git_timeout,
        max_output_bytes=limits.max_patch_bytes,
        output_limit_error=PatchTooLarge("patch byte limit exceeded"),
    )
    text = raw.decode("utf-8", "replace")
    files = parse_unified_diff(text)
    added = sum(len(item.added_lines) for item in files)
    deleted = sum(len(item.deleted_lines) for item in files)
    warnings: list[str] = []
    if len(files) > limits.max_files:
        warnings.append("changed file limit exceeded")
    if added > limits.max_added_lines:
        warnings.append("added line limit exceeded")
    if any(item.change_type == "deleted" for item in files):
        warnings.append("entire-file deletion requires human review")
    if any(_has_unresolved_removed_control(item) for item in files):
        warnings.append("removed safety control requires human review")
    if any(
        len(line.content) > limits.max_line_length
        for item in files
        for line in (*item.added_lines, *item.deleted_lines)
    ):
        warnings.append("line length limit exceeded")
    binaries = sum(item.binary for item in files)
    if binaries:
        warnings.append("binary files require human review")
    return Patch(
        requested_base=base,
        resolved_base=base_sha,
        resolved_head=head_sha,
        merge_base=merge_base,
        sha256=hashlib.sha256(raw).hexdigest(),
        files=files,
        byte_count=len(raw),
        added_line_count=added,
        binary_count=binaries,
        deleted_line_count=deleted,
        complete=not warnings,
        warnings=tuple(warnings),
        raw_text=text,
    )


# --- Seed A's --branch/--base CLI entry points, now on top of the bounded machinery ---


def _branch_diff(repo_root: Path, base: str, branch: str, limits: Limits = _DEFAULT_LIMITS) -> str:
    return acquire_patch(repo_root, base, branch, limits).raw_text


def _gate_commit(repo_root: Path, *, timeout: float = _DEFAULT_LIMITS.git_timeout) -> str:
    raw = _git(
        repo_root,
        ["rev-parse", "--short", "--end-of-options", "HEAD"],
        timeout,
        max_output_bytes=_COMMIT_OUTPUT_BYTES,
    )
    return raw.decode("ascii", "strict").strip()


def _resolve_sha(repo_root: Path, ref: str, *, timeout: float = _DEFAULT_LIMITS.git_timeout) -> str:
    return resolve_commit(repo_root, ref, timeout)


def _merge_base(
    repo_root: Path, base: str, branch: str, *, timeout: float = _DEFAULT_LIMITS.git_timeout
) -> str:
    _reject_option_like_ref(base)
    _reject_option_like_ref(branch)
    raw = _git(
        repo_root, ["merge-base", base, branch], timeout, max_output_bytes=_COMMIT_OUTPUT_BYTES
    )
    sha = raw.decode("ascii", "strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise DiffError("Git returned an invalid merge base")
    return sha


def patch_sha256(diff: str) -> str:
    """Return the hex digest of the diff text, for report provenance."""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()
