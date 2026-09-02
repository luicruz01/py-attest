from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import click

_ENV_OVERRIDES = {
    "ATTEST_PROVIDER": "provider",
    "ATTEST_MODEL": "model",
    "ATTEST_EGRESS": "egress",
    "ATTEST_BASE_BRANCH": "base_branch",
}

_KNOWN_KEYS = {
    "provider",
    "model",
    "egress",
    "evidence_policy",
    "base_branch",
    "context_files",
    "standards",
    "reports_dir",
    "limits",
}


@dataclass(frozen=True)
class Limits:
    max_patch_bytes: int = 1_000_000
    max_files: int = 200
    max_added_lines: int = 10_000
    max_line_length: int = 10_000
    git_timeout: float = 15.0
    provider_timeout: float = 30.0


@dataclass(frozen=True)
class StandardsPaths:
    core: str = "core.standards.yml"
    domain: str = "domain.standards.yml"
    output: str = "TEAM-STANDARDS.md"


@dataclass(frozen=True)
class Config:
    provider: str = "openai"
    model: str = "gpt-5-mini"
    egress: str = "raw"
    evidence_policy: str = "degrade"
    base_branch: str = "main"
    context_files: tuple[str, ...] = ()
    standards: StandardsPaths = field(default_factory=StandardsPaths)
    reports_dir: str = "reports/"
    limits: Limits = field(default_factory=Limits)


def load_config(cwd: Path | None = None) -> Config:
    """Load [tool.attest] from pyproject.toml, applying ATTEST_* env overrides."""
    cwd = cwd or Path.cwd()
    pyproject_path = cwd / "pyproject.toml"

    raw: dict = {}
    if pyproject_path.is_file():
        try:
            with pyproject_path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise click.UsageError(f"invalid TOML in {pyproject_path}: {exc}") from exc
        raw = data.get("tool", {}).get("attest", {})
        if not isinstance(raw, dict):
            raise click.UsageError(f"[tool.attest] must be a table, got {type(raw).__name__}")

    unknown_keys = sorted(set(raw) - _KNOWN_KEYS)
    if unknown_keys:
        raise click.UsageError(f"unknown key in [tool.attest]: {unknown_keys[0]}")

    values = dict(raw)
    limits_raw = values.pop("limits", {})
    standards_raw = values.pop("standards", {})

    if "context_files" in values:
        values["context_files"] = tuple(values["context_files"])

    for env_var, key in _ENV_OVERRIDES.items():
        if env_var in os.environ:
            values[key] = os.environ[env_var]

    return Config(
        **values,
        standards=StandardsPaths(**standards_raw),
        limits=Limits(**limits_raw),
    )
