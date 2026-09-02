"""Acquire a git diff and repo commit metadata as data (never executes repo code)."""

import hashlib
import shutil
import subprocess
from pathlib import Path


class DiffError(RuntimeError):
    """Raised when the diff or repo metadata cannot be acquired from git."""


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


def _branch_diff(repo_root: Path, base: str, branch: str) -> str:
    _reject_option_like_ref(base)
    _reject_option_like_ref(branch)
    git_executable = shutil.which("git")
    if git_executable is None:
        raise DiffError("cannot create branch diff: git executable not found")
    try:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            [
                git_executable,
                "-c",
                "core.quotepath=false",
                "diff",
                "--no-ext-diff",
                f"{base}...{branch}",
                "--",
            ],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "git diff failed"
        raise DiffError(f"cannot diff {base}...{branch}: {detail}") from exc
    return result.stdout


def _gate_commit(repo_root: Path) -> str:
    return _rev_parse(repo_root, "HEAD", short=True)


def _resolve_sha(repo_root: Path, ref: str) -> str:
    return _rev_parse(repo_root, ref, short=False)


def _merge_base(repo_root: Path, base: str, branch: str) -> str:
    _reject_option_like_ref(base)
    _reject_option_like_ref(branch)
    git_executable = shutil.which("git")
    if git_executable is None:
        raise DiffError("cannot resolve merge base: git executable not found")
    try:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            [git_executable, "merge-base", base, branch],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "git merge-base failed"
        raise DiffError(f"cannot resolve merge base of {base}...{branch}: {detail}") from exc
    return result.stdout.strip()


def _rev_parse(repo_root: Path, ref: str, *, short: bool) -> str:
    _reject_option_like_ref(ref)
    git_executable = shutil.which("git")
    if git_executable is None:
        raise DiffError("cannot resolve commit: git executable not found")
    args = [git_executable, "rev-parse"]
    if short:
        args.append("--short")
    args.append(ref)
    try:
        result = subprocess.run(  # noqa: S603 - absolute executable and argument list, no shell
            args,
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or "git rev-parse failed"
        raise DiffError(f"cannot resolve {ref}: {detail}") from exc
    return result.stdout.strip()


def patch_sha256(diff: str) -> str:
    """Return the hex digest of the diff text, for report provenance."""
    return hashlib.sha256(diff.encode("utf-8")).hexdigest()
