"""One-time-ish generator: Seed B's quality_gate/review_rules.json -> core/domain.standards.yml.

Not wired into the CLI. Reads Seed B's public rule catalog and Seed A's TEAM-STANDARDS.md
sections 1/2/3/4/5 (rescued as prose below, since the two catalogs don't share wording) and
emits the core (code-quality/testing/secrets) and domain (pii/retention) standards.yml text,
plus the legacy Seed-B-string -> new-id table (ADR-001's ADR-004 amendment).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LEGACY_RULE_IDS: dict[str, str] = {
    "EXTERNAL_INPUT_VALIDATION": "code-quality-3",
    "EXPLICIT_ERROR_HANDLING": "code-quality-4",
    "TODO_TICKET_REFERENCE": "code-quality-5",
    "INCORRECT_DATA_LOGIC": "code-quality-6",
    "LOGIC_TEST_REQUIRED": "testing-2",
    "TESTS_EFFECTIVE": "testing-3",
    "COMMITTED_SECRET": "secrets-1",
    "LOG_PII": "pii-1",
    "MINOR_DATA_EGRESS": "pii-2",
    "DATASET_RETENTION_DECLARED": "retention-1",
    "MINOR_RETENTION_MAX_90_DAYS": "retention-2",
    "SECONDARY_PII_MINIMIZATION": "retention-3",
}

# (new_id, title, severity_or_None_for_contextual, description) -- deterministic core rules
# (code-quality-1/2, testing-1, secrets-1's tree-scan twin) already exist in check/runner.py;
# their ids/severities/checks are transcribed here, not invented.
_CORE_DETERMINISTIC: tuple[tuple[str, str, str, str, str], ...] = (
    (
        "code-quality-1",
        "ruff check passes",
        "S3",
        "ruff-check",
        "ruff check must report no violations.",
    ),
    (
        "code-quality-2",
        "ruff format passes",
        "S3",
        "ruff-format",
        "ruff format --check must report no files needing reformatting.",
    ),
    (
        "testing-1",
        "Untested core logic fails CI",
        "S2",
        "coverage-gate",
        "Every logic change includes tests that fail if the behavior breaks, enforced by the "
        "coverage gate.",
    ),
    (
        "secrets-1",
        "No committed secrets",
        "S1",
        "gitleaks",
        "Secrets are provided through environment variables only, never committed to the "
        "repository.",
    ),
)


def _core_deterministic_rules() -> list[dict[str, Any]]:
    return [
        {
            "id": rule_id,
            "title": title,
            "severity": severity,
            "mode": "deterministic",
            "check": check,
            "description": description,
        }
        for rule_id, title, severity, check, description in _CORE_DETERMINISTIC
    ]


def _by_legacy(catalog: dict[str, Any], legacy_id: str) -> dict[str, Any]:
    return next(rule for rule in catalog["rules"] if rule["rule_id"] == legacy_id)


def _llm_rule(catalog: dict[str, Any], legacy_id: str, *, mode: str = "llm") -> dict[str, Any]:
    source = _by_legacy(catalog, legacy_id)
    new_id = LEGACY_RULE_IDS[legacy_id]
    rule: dict[str, Any] = {
        "id": new_id,
        "title": source["title"],
        "mode": mode,
        "description": source["description"],
        "evidence_required": source["evidence_required"],
        "non_examples": source["non_examples"],
    }
    if "severity" in source:
        rule["severity"] = source["severity"]
    else:
        rule["severity_policy"] = source["severity_policy"]
    if mode == "deterministic":
        rule["check"] = "todo-ticket-ref"
    return rule


def _dump(document: dict[str, Any]) -> str:
    import yaml

    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def migrate(review_rules_path: Path) -> tuple[str, str, dict[str, str]]:
    catalog = json.loads(review_rules_path.read_text(encoding="utf-8"))

    code_quality_rules = _core_deterministic_rules()[:2]
    code_quality_rules.append(_llm_rule(catalog, "EXTERNAL_INPUT_VALIDATION"))
    code_quality_rules.append(_llm_rule(catalog, "EXPLICIT_ERROR_HANDLING"))
    code_quality_rules.append(_llm_rule(catalog, "TODO_TICKET_REFERENCE", mode="deterministic"))
    code_quality_rules.append(_llm_rule(catalog, "INCORRECT_DATA_LOGIC"))

    testing_rules = [_core_deterministic_rules()[2]]
    testing_rules.append(_llm_rule(catalog, "LOGIC_TEST_REQUIRED"))
    testing_rules.append(_llm_rule(catalog, "TESTS_EFFECTIVE"))

    secrets_rules = [_core_deterministic_rules()[3]]

    core_document = {
        "version": 1,
        "sections": [
            {"slug": "code-quality", "title": "Code quality", "rules": code_quality_rules},
            {"slug": "testing", "title": "Testing", "rules": testing_rules},
            {"slug": "secrets", "title": "Secrets", "rules": secrets_rules},
        ],
    }

    pii_rules = [_llm_rule(catalog, "LOG_PII"), _llm_rule(catalog, "MINOR_DATA_EGRESS")]
    retention_rules = [
        _llm_rule(catalog, "DATASET_RETENTION_DECLARED"),
        _llm_rule(catalog, "MINOR_RETENTION_MAX_90_DAYS"),
        _llm_rule(catalog, "SECONDARY_PII_MINIMIZATION"),
    ]
    domain_document = {
        "version": 1,
        "sections": [
            {
                "slug": "pii",
                "title": "PII and logging (example -- edit or delete this section)",
                "rules": pii_rules,
            },
            {
                "slug": "retention",
                "title": "Data retention (example -- edit or delete this section)",
                "rules": retention_rules,
            },
        ],
    }

    return _dump(core_document), _dump(domain_document), dict(LEGACY_RULE_IDS)


def _main() -> None:
    review_rules_path = Path("../seed-b/quality_gate/review_rules.json")
    core_yaml, domain_yaml, legacy_ids = migrate(review_rules_path)
    defaults = Path(__file__).with_name("defaults")
    defaults.mkdir(exist_ok=True)
    (defaults / "core.standards.yml").write_text(core_yaml, encoding="utf-8")
    (defaults / "domain.standards.yml").write_text(domain_yaml, encoding="utf-8")
    legacy_path = Path(__file__).parents[1] / "eval" / "legacy_rule_ids.json"
    legacy_path.parent.mkdir(exist_ok=True)
    legacy_path.write_text(
        json.dumps(legacy_ids, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    _main()
