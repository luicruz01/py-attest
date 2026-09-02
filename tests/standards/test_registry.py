from pathlib import Path

import pytest

from py_attest.standards.registry import Registry, RegistryError, load_registry

CORE_YAML = """
version: 1
sections:
  - slug: code-quality
    title: Code quality
    rules:
      - id: code-quality-1
        title: ruff check passes
        severity: S3
        mode: deterministic
        check: ruff-check
        description: ruff check must report no violations.
      - id: code-quality-3
        title: External input validated
        severity: S2
        mode: llm
        description: All external input is validated before use.
        evidence_required: Require a changed input boundary.
        non_examples:
          - Typed FastAPI parameters whose framework validation runs first.
"""

DOMAIN_YAML = """
version: 1
sections:
  - slug: pii
    title: PII and logging
    rules:
      - id: pii-1
        title: PII must not reach logs
        severity: S1
        mode: llm
        description: PII must not be written to logs.
      - id: retention-1
        title: Every dataset declares a retention category
        severity_policy:
          minor_data: S1
          minors_demonstrably_excluded: human_classification_required_based_on_impact
        mode: llm
        description: Every persisted or copied dataset declares its retention category.
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_load_registry_merges_core_and_domain(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    registry = load_registry(core, domain)

    assert isinstance(registry, Registry)
    assert "code-quality-1" in registry
    assert "pii-1" in registry
    assert "does-not-exist-1" not in registry


def test_fixed_severity_resolves_a_normal_rule(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, "core.standards.yml", CORE_YAML),
        _write(tmp_path, "domain.standards.yml", DOMAIN_YAML),
    )

    assert registry.fixed_severity("code-quality-1") == "S3"
    assert registry.is_contextual("code-quality-1") is False


def test_fixed_severity_is_none_for_a_contextual_rule(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, "core.standards.yml", CORE_YAML),
        _write(tmp_path, "domain.standards.yml", DOMAIN_YAML),
    )

    assert registry.fixed_severity("retention-1") is None
    assert registry.is_contextual("retention-1") is True


def test_unknown_rule_id_raises(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, "core.standards.yml", CORE_YAML),
        _write(tmp_path, "domain.standards.yml", DOMAIN_YAML),
    )

    with pytest.raises(RegistryError, match="unknown rule id"):
        registry.rule("does-not-exist-1")


def test_llm_rules_excludes_deterministic_rules(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, "core.standards.yml", CORE_YAML),
        _write(tmp_path, "domain.standards.yml", DOMAIN_YAML),
    )

    assert {rule.id for rule in registry.llm_rules()} == {"code-quality-3", "pii-1", "retention-1"}


def test_deterministic_rules_carries_the_check_field(tmp_path: Path) -> None:
    registry = load_registry(
        _write(tmp_path, "core.standards.yml", CORE_YAML),
        _write(tmp_path, "domain.standards.yml", DOMAIN_YAML),
    )

    [rule] = registry.deterministic_rules()
    assert rule.id == "code-quality-1"
    assert rule.check == "ruff-check"


def test_duplicate_id_across_core_and_domain_raises(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    colliding_domain = DOMAIN_YAML.replace("pii-1", "code-quality-1")
    domain = _write(tmp_path, "domain.standards.yml", colliding_domain)

    with pytest.raises(RegistryError, match="duplicate rule id"):
        load_registry(core, domain)


@pytest.mark.parametrize(
    ("core_yaml", "case_id"),
    [
        pytest.param(CORE_YAML.replace("        check: ruff-check\n", ""), "no-check"),
        pytest.param(
            CORE_YAML.replace(
                "        severity: S3\n", "        severity: S3\n        severity_policy: {x: S1}\n"
            ),
            "both-severities",
        ),
        pytest.param(
            CORE_YAML.replace("id: code-quality-1", "id: Code_Quality_1"), "bad-id-pattern"
        ),
    ],
    ids=["deterministic-without-check", "both-severity-and-severity-policy", "bad-id-pattern"],
)
def test_invalid_core_yaml_is_rejected(tmp_path: Path, core_yaml: str, case_id: str) -> None:  # noqa: ARG001
    core = _write(tmp_path, "core.standards.yml", core_yaml)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    with pytest.raises(RegistryError, match="schema violation"):
        load_registry(core, domain)
