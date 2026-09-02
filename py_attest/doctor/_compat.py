"""Shared helpers for the ADR-003 compatibility checks (engine range, pin consistency)."""

from __future__ import annotations

import importlib.metadata
import tomllib
from dataclasses import dataclass
from pathlib import Path

import yaml
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

ENGINE_DISTRIBUTION = "py-attest"
ANSWERS_FILENAME = ".copier-answers.yml"


class CompatDataError(ValueError):
    """A compat data source (answers file, pyproject entry, installed version) is unusable."""


@dataclass(frozen=True)
class EngineRange:
    """A parsed attest_engine_range, keeping the original text for display/remedy strings.

    SpecifierSet.__str__ doesn't preserve clause order (it's backed by a frozenset), so a
    remedy like `pip install -U "py-attest>=1.3,<2"` must be built from ``raw``, never from
    ``str(specifier)``.
    """

    raw: str
    specifier: SpecifierSet

    def __str__(self) -> str:
        return self.raw

    def __contains__(self, version: Version) -> bool:
        return version in self.specifier


def load_copier_answers(repo_root: Path) -> dict[str, object] | None:
    """Return the parsed .copier-answers.yml, or None if the repo wasn't template-generated."""
    answers_path = repo_root / ANSWERS_FILENAME
    if not answers_path.is_file():
        return None
    try:
        data = yaml.safe_load(answers_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise CompatDataError(f"{ANSWERS_FILENAME} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise CompatDataError(f"{ANSWERS_FILENAME} must contain a YAML mapping")
    return data


def engine_range_from_answers(answers: dict[str, object]) -> EngineRange:
    """Parse the attest_engine_range field the template computed into an EngineRange."""
    raw_range = answers.get("attest_engine_range")
    if not isinstance(raw_range, str) or not raw_range.strip():
        raise CompatDataError(f"{ANSWERS_FILENAME} has no attest_engine_range field")
    try:
        return EngineRange(raw=raw_range, specifier=SpecifierSet(raw_range))
    except InvalidSpecifier as exc:
        raise CompatDataError(
            f"attest_engine_range {raw_range!r} is not a valid specifier"
        ) from exc


def installed_engine_version() -> Version:
    """Return the installed py-attest version as a packaging.version.Version."""
    try:
        raw_version = importlib.metadata.version(ENGINE_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise CompatDataError(
            f"{ENGINE_DISTRIBUTION} is not installed in this environment"
        ) from exc
    try:
        return Version(raw_version)
    except InvalidVersion as exc:
        raise CompatDataError(
            f"installed {ENGINE_DISTRIBUTION} version {raw_version!r} is invalid"
        ) from exc


def engine_range_from_pyproject(repo_root: Path) -> EngineRange:
    """Parse the py-attest specifier out of [project.optional-dependencies].attest."""
    pyproject_path = repo_root / "pyproject.toml"
    if not pyproject_path.is_file():
        raise CompatDataError("pyproject.toml not found")
    try:
        with pyproject_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise CompatDataError(f"pyproject.toml is not valid TOML: {exc}") from exc

    attest_extra = data.get("project", {}).get("optional-dependencies", {}).get("attest", [])
    if not isinstance(attest_extra, list):
        raise CompatDataError("[project.optional-dependencies].attest must be a list")

    for entry in attest_extra:
        if not isinstance(entry, str):
            continue
        try:
            requirement = Requirement(entry)
        except InvalidRequirement:
            continue
        if requirement.name.lower() == ENGINE_DISTRIBUTION:
            return EngineRange(raw=str(requirement.specifier), specifier=requirement.specifier)
    raise CompatDataError(
        f"no {ENGINE_DISTRIBUTION} entry found in [project.optional-dependencies].attest"
    )
