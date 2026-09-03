"""Every expected.json must (a) match manifest.json's source block, (b) cite only
rule_ids that exist in the shipped registry, (c) carry the registry's fixed severity
for each rule_id (never a hand-typed value that could drift), (d) mark BLOCK iff any
llm_reachable-independent S1/S2 finding exists (S1/S2 always block per TRD's trust
policy; S3-only or contextual-without-classification never does)."""

import json
from pathlib import Path

import pytest

from py_attest.standards.registry import load_registry

GOLDEN_DIR = Path(__file__).parents[2] / "eval" / "golden"
DEFAULTS_DIR = Path(__file__).parents[2] / "py_attest" / "standards" / "defaults"


def _branches() -> list[str]:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    return sorted(manifest["branches"])


@pytest.fixture(scope="module")
def registry():
    return load_registry(DEFAULTS_DIR / "core.standards.yml", DEFAULTS_DIR / "domain.standards.yml")


@pytest.mark.parametrize("branch", _branches())
def test_expected_json_matches_manifest_source(branch: str) -> None:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    expected = json.loads((GOLDEN_DIR / branch / "expected.json").read_text(encoding="utf-8"))

    assert expected["branch"] == branch
    manifest_entry = manifest["branches"][branch]
    assert expected["source"] == {
        "base_sha": manifest["base_sha"],
        "head_sha": manifest_entry["head_sha"],
        "merge_base_sha": manifest_entry["merge_base_sha"],
        "patch_sha256": manifest_entry["patch_sha256"],
    }


@pytest.mark.parametrize("branch", _branches())
def test_expected_json_findings_cite_real_registry_severities(branch: str, registry) -> None:
    expected = json.loads((GOLDEN_DIR / branch / "expected.json").read_text(encoding="utf-8"))
    for finding in expected["findings"]:
        assert finding["rule_id"] in registry
        assert finding["severity"] == registry.fixed_severity(finding["rule_id"])


@pytest.mark.parametrize("branch", _branches())
def test_expected_json_verdict_matches_blocking_findings(branch: str) -> None:
    expected = json.loads((GOLDEN_DIR / branch / "expected.json").read_text(encoding="utf-8"))
    has_blocking = any(f["severity"] in {"S1", "S2"} for f in expected["findings"])
    assert expected["verdict"] == ("BLOCK" if has_blocking else "APPROVE")


def test_email_reminders_pii_finding_is_the_only_unreachable_one() -> None:
    expected = json.loads(
        (GOLDEN_DIR / "feature/email-reminders" / "expected.json").read_text(encoding="utf-8")
    )
    unreachable = [f["rule_id"] for f in expected["findings"] if not f["llm_reachable"]]
    assert unreachable == ["pii-1"]
