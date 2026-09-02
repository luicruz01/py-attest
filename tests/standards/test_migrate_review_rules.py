import json
from pathlib import Path

import yaml

from py_attest.standards.migrate_review_rules import LEGACY_RULE_IDS, migrate
from py_attest.standards.registry import Registry, _sections_from

FIXTURES = Path(__file__).parent / "fixtures"


def test_legacy_rule_ids_maps_every_seed_b_rule() -> None:
    catalog = json.loads((FIXTURES / "seed_b_review_rules.json").read_text(encoding="utf-8"))
    seed_b_ids = {rule["rule_id"] for rule in catalog["rules"]}

    assert set(LEGACY_RULE_IDS) == seed_b_ids
    assert LEGACY_RULE_IDS["EXTERNAL_INPUT_VALIDATION"] == "code-quality-3"
    assert LEGACY_RULE_IDS["EXPLICIT_ERROR_HANDLING"] == "code-quality-4"
    assert LEGACY_RULE_IDS["TODO_TICKET_REFERENCE"] == "code-quality-5"
    assert LEGACY_RULE_IDS["INCORRECT_DATA_LOGIC"] == "code-quality-6"
    assert LEGACY_RULE_IDS["LOGIC_TEST_REQUIRED"] == "testing-2"
    assert LEGACY_RULE_IDS["TESTS_EFFECTIVE"] == "testing-3"
    assert LEGACY_RULE_IDS["COMMITTED_SECRET"] == "secrets-1"  # noqa: S105 - rule id, not a secret
    assert LEGACY_RULE_IDS["LOG_PII"] == "pii-1"
    assert LEGACY_RULE_IDS["MINOR_DATA_EGRESS"] == "pii-2"
    assert LEGACY_RULE_IDS["DATASET_RETENTION_DECLARED"] == "retention-1"
    assert LEGACY_RULE_IDS["MINOR_RETENTION_MAX_90_DAYS"] == "retention-2"
    assert LEGACY_RULE_IDS["SECONDARY_PII_MINIMIZATION"] == "retention-3"


def test_migrate_produces_valid_core_and_domain_yaml() -> None:
    core_yaml, domain_yaml, legacy_ids = migrate(FIXTURES / "seed_b_review_rules.json")

    core_doc = yaml.safe_load(core_yaml)
    domain_doc = yaml.safe_load(domain_yaml)
    core_sections = _sections_from(core_doc)
    domain_sections = _sections_from(domain_doc)
    registry = Registry(core_sections=core_sections, domain_sections=domain_sections)

    assert legacy_ids == LEGACY_RULE_IDS
    assert {section.slug for section in core_sections} == {"code-quality", "testing", "secrets"}
    assert {section.slug for section in domain_sections} == {"pii", "retention"}
    assert registry.fixed_severity("code-quality-3") == "S2"
    assert registry.rule("code-quality-3").evidence_required is not None
    assert registry.is_contextual("retention-1") is True
    assert registry.fixed_severity("code-quality-1") == "S3"  # deterministic, from check/runner.py
    assert registry.rule("code-quality-1").check == "ruff-check"
    assert registry.rule("code-quality-5").mode == "deterministic"
    assert registry.rule("code-quality-5").check == "todo-ticket-ref"


def test_migrate_output_matches_the_committed_defaults() -> None:
    """Regression test: catches drift between the migration transform and the committed
    defaults/*.yml without depending on the ../seed-b worktree being checked out.
    """
    core_yaml, domain_yaml, _legacy_ids = migrate(FIXTURES / "seed_b_review_rules.json")
    defaults = Path(__file__).parents[2] / "py_attest" / "standards" / "defaults"

    assert core_yaml == (defaults / "core.standards.yml").read_text(encoding="utf-8")
    assert domain_yaml == (defaults / "domain.standards.yml").read_text(encoding="utf-8")


def test_eval_legacy_rule_ids_json_matches() -> None:
    legacy_path = Path(__file__).parents[2] / "py_attest" / "eval" / "legacy_rule_ids.json"

    assert json.loads(legacy_path.read_text(encoding="utf-8")) == LEGACY_RULE_IDS
