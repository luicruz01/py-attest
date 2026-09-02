"""Load, validate, and merge standards.yml files into a Registry."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import jsonschema
import yaml

Severity = Literal["S1", "S2", "S3"]
Mode = Literal["deterministic", "llm", "human"]

_SCHEMA_PATH = Path(__file__).with_name("schema.json")


class RegistryError(ValueError):
    """Raised when standards.yml files fail schema validation or contain duplicate ids."""


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    mode: Mode
    description: str
    severity: Severity | None = None
    severity_policy: dict[str, Any] | None = None
    check: str | None = None
    rationale: str | None = None
    evidence_required: str | None = None
    non_examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class Section:
    slug: str
    title: str
    rules: tuple[Rule, ...]


def _load_schema() -> dict[str, Any]:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _load_document(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path}: invalid YAML: {exc}") from exc
    except OSError as exc:
        raise RegistryError(f"{path}: cannot read file: {exc}") from exc
    if not isinstance(raw, dict):
        raise RegistryError(f"{path}: document must be a mapping")
    try:
        jsonschema.validate(raw, _load_schema())
    except jsonschema.ValidationError as exc:
        raise RegistryError(f"{path}: schema violation: {exc.message}") from exc
    return raw


def _sections_from(document: dict[str, Any]) -> tuple[Section, ...]:
    sections = []
    for section_raw in document["sections"]:
        rules = tuple(
            Rule(
                id=rule_raw["id"],
                title=rule_raw["title"],
                mode=rule_raw["mode"],
                description=rule_raw["description"],
                severity=rule_raw.get("severity"),
                severity_policy=rule_raw.get("severity_policy"),
                check=rule_raw.get("check"),
                rationale=rule_raw.get("rationale"),
                evidence_required=rule_raw.get("evidence_required"),
                non_examples=tuple(rule_raw.get("non_examples", ())),
            )
            for rule_raw in section_raw["rules"]
        )
        sections.append(Section(slug=section_raw["slug"], title=section_raw["title"], rules=rules))
    return tuple(sections)


class Registry:
    """The merged, validated core+domain rule set. Rule ids are globally unique."""

    def __init__(
        self, core_sections: tuple[Section, ...], domain_sections: tuple[Section, ...]
    ) -> None:
        self.core_sections = core_sections
        self.domain_sections = domain_sections
        self._rules_by_id: dict[str, Rule] = {}
        for section in (*core_sections, *domain_sections):
            for rule in section.rules:
                if rule.id in self._rules_by_id:
                    raise RegistryError(f"duplicate rule id across core/domain: {rule.id}")
                self._rules_by_id[rule.id] = rule

    def __contains__(self, rule_id: str) -> bool:
        return rule_id in self._rules_by_id

    def rule(self, rule_id: str) -> Rule:
        try:
            return self._rules_by_id[rule_id]
        except KeyError as exc:
            raise RegistryError(f"unknown rule id: {rule_id}") from exc

    def fixed_severity(self, rule_id: str) -> Severity | None:
        return self.rule(rule_id).severity

    def is_contextual(self, rule_id: str) -> bool:
        return self.rule(rule_id).severity_policy is not None

    def llm_rules(self) -> list[Rule]:
        return [
            rule
            for section in (*self.core_sections, *self.domain_sections)
            for rule in section.rules
            if rule.mode == "llm"
        ]

    def deterministic_rules(self) -> list[Rule]:
        return [
            rule
            for section in (*self.core_sections, *self.domain_sections)
            for rule in section.rules
            if rule.mode == "deterministic"
        ]


def load_registry(core_path: Path, domain_path: Path) -> Registry:
    core_sections = _sections_from(_load_document(core_path))
    domain_sections = _sections_from(_load_document(domain_path))
    return Registry(core_sections=core_sections, domain_sections=domain_sections)
