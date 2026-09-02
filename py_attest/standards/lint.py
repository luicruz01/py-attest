"""Collect standards.yml problems without raising on the first one found."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from py_attest.standards.registry import RegistryError, load_registry

# Doctor's check catalog doesn't exist yet (TRD §6, out of scope for this WP) --
# this is a static list grounded in what check/runner.py already runs, plus the
# one check F0.3's review/deterministic.py adds (code-quality-5, todo-ticket-ref).
KNOWN_CHECK_IDS = {"ruff-check", "ruff-format", "coverage-gate", "gitleaks", "todo-ticket-ref"}


@dataclass(frozen=True)
class LintError:
    message: str


def lint(core_path: Path, domain_path: Path) -> list[LintError]:
    try:
        registry = load_registry(core_path, domain_path)
    except RegistryError as exc:
        return [LintError(str(exc))]

    return [
        LintError(f"{rule.id}: unknown check id: {rule.check}")
        for rule in registry.deterministic_rules()
        if rule.check not in KNOWN_CHECK_IDS
    ]
