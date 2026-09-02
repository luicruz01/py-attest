# Golden-set eval harness (F0.5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the F0.5 golden-set eval harness: 8 recorded-fixture branches with reconciled ground truth, a `metrics.py` rewrite with three readings (strict/adjudicated/severity-exact) across two egress modes, a `record.py` recorder, offline-passing tests, the weekly live-eval workflow, and `EVAL.md`.

**Architecture:** `eval/golden/<branch>/{diff.patch, expected.json}` are real, committed, network-free data (git diffs + reconciled ground truth). `provider_response.<egress>.json` per branch is deliberately left unrecorded this WP (needs a real API key) — `metrics.py`'s `evaluate()` skips branches whose recording is absent rather than failing, so the suite is green today and becomes a real regression gate once recordings land. `record.py` and `metrics.py` both reuse the exact request-building internals `review/reviewer.py` already uses (`_build_egress`, `_standards_paths`, `_build_provider`), so a recording is provably built from the same `ProviderRequest` the real pipeline sends, and metrics replay real recordings through `reviewer.run_review` end to end (validation, postfilter, policy, report — not just a JSON diff).

**Tech Stack:** Python 3.11+, pytest, click/argparse (metrics.py and record.py stay plain-argparse, matching the existing `eval/metrics.py` convention — no new console-script entry point), PyYAML, existing `py_attest` internals.

**Spec:** `docs/superpowers/specs/2026-09-02-golden-set-eval-design.md`

## Global Constraints

- `uv sync --all-extras && uv run pytest` and `ruff check .` / `ruff format --check .` must pass after every task (CLAUDE.md).
- `--cov-fail-under=95` (pyproject.toml) — every new module needs real test coverage, not just happy-path.
- No network calls anywhere in `tests/` (CLAUDE.md, DONE WHEN). `record.py` itself calls a provider, but its own tests use `--provider fake` only.
- API keys only from environment variables, never fixtures (CLAUDE.md) — not applicable to this WP's own tests (fake provider only), but `record.py`'s docstring/CLI help must not suggest otherwise.
- Anti-leakage (ADR-004 §6): `py_attest/` (excluding `py_attest/eval/`, which *is* the eval tooling) must never import or read `eval/`. `py_attest/eval/` and top-level `eval/` are allowed to reference each other freely.
- Golden-set ground truth is regression, never tuning (ADR-004 §6): no task in this plan may adjust a rule's severity, a matcher's leniency, or a finding's expected outcome to make a number look better — `eval/golden/*/expected.json` is fixed data, authored once from the reconciliation in spec §2, not iterated against a real run.
- `score-validation`'s expected verdict is **BLOCK** (registry-fixed S2 `code-quality-3`), not Seed A's original APPROVE — resolved in brainstorming, spec §2. Do not "fix" this back to APPROVE.
- Neither `raw` nor `minimized` inherits Seed A's 6/6-recall/87.5%-accuracy numbers as a pytest target (spec §6/§8, corrected after review) — no task may hardcode those numbers as an assertion.

---

## Task 1: Golden fixture data — `diff.patch` + `manifest.json` for the 8 seed branches

**Files:**
- Create: `eval/golden/manifest.json`
- Create: `eval/golden/feature/analytics-archive/diff.patch`
- Create: `eval/golden/feature/email-reminders/diff.patch`
- Create: `eval/golden/feature/lessons-pagination/diff.patch`
- Create: `eval/golden/feature/score-validation/diff.patch`
- Create: `eval/golden/feature/streaks/diff.patch`
- Create: `eval/golden/feature/support-context/diff.patch`
- Create: `eval/golden/fix/mobile-sync-visibility/diff.patch`
- Create: `eval/golden/fix/progress-percentage/diff.patch`
- Test: `tests/eval/test_golden_manifest.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `eval/golden/manifest.json` — `{"dataset_version": "1.0.0", "base_sha": str, "branches": {<branch>: {"head_sha": str, "merge_base_sha": str, "patch_sha256": str}}}`. Task 2 reads this to populate each `expected.json`'s `source` block. Task 5/8 read it to discover which branches exist.

- [ ] **Step 1: Write the failing integrity test**

```python
# tests/eval/test_golden_manifest.py
"""manifest.json must match Seed B's frozen benchmark manifest exactly, and every
committed diff.patch must hash to the patch_sha256 it records (ADR-004 SS6, seed-b's
eval/README.md "Integrity validation")."""

import hashlib
import json
from pathlib import Path

GOLDEN_DIR = Path(__file__).parents[2] / "eval" / "golden"

EXPECTED_BASE_SHA = "fbd4e09643ea61027165fdbfafbb2c3e5edd0153"

EXPECTED_BRANCHES = {
    "feature/analytics-archive": (
        "d5ecfb126399ae9b214500ab71e75e5707a2264d",
        "d406de699c4fc42c3a1cad2a02f49a2e811b8835c13ca33bbffbfb2c37d32207",
    ),
    "feature/email-reminders": (
        "e1732cb7b95d42ad36f1a5b00583fb61bea8c119",
        "4fa76a4edb931b92e5c9eb21a28db8d1d1228db1037013b9f2214ff08a8bfa3a",
    ),
    "feature/lessons-pagination": (
        "386b2e1d2882820c82977cbfd7361d3aea6b6865",
        "0682eebedbc2d3b840b4ce5846c1dc1bbf8e7c31cd0b44be6192b3e12a41909e",
    ),
    "feature/score-validation": (
        "60a6090693bc327d90838943f13890ca803f37a0",
        "edef156d10b2bda7628f4cf54bea09fea4f317978b2d5b3a3122ff48c172a8cb",
    ),
    "feature/streaks": (
        "b5133c29895d6a98ceb2e595b10c4e89093ac71f",
        "5c40733a254dec924ae0545d03f5c6aa7b9642d2968d4da80374edfe4dd4cac9",
    ),
    "feature/support-context": (
        "dfabcaeb1fedc65330928a29271b00efb40c5bce",
        "72380ff6bfde72feaf1cbb307d8d594abe7ef804d75df8625d51ecd92d5be85b",
    ),
    "fix/mobile-sync-visibility": (
        "fa726eb00be931ad67a4b11f1282f1838563975f",
        "4a25d0d6af8cf37eb8ca08def2ac6dca15cb995b49d62e3fa975b867a0ec095f",
    ),
    "fix/progress-percentage": (
        "a620c3832d9a587624814a2f9c0dd9a566345c92",
        "6eae85ee1c133808f8cce0cbbfcee9b2d51dbd3581a26b484da57702d04552e1",
    ),
}


def test_manifest_matches_the_frozen_seed_b_benchmark() -> None:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))

    assert manifest["dataset_version"] == "1.0.0"
    assert manifest["base_sha"] == EXPECTED_BASE_SHA
    assert set(manifest["branches"]) == set(EXPECTED_BRANCHES)
    for branch, (head_sha, patch_sha256) in EXPECTED_BRANCHES.items():
        entry = manifest["branches"][branch]
        assert entry["head_sha"] == head_sha
        assert entry["merge_base_sha"] == EXPECTED_BASE_SHA
        assert entry["patch_sha256"] == patch_sha256


def test_every_diff_patch_hashes_to_its_manifest_patch_sha256() -> None:
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    for branch, entry in manifest["branches"].items():
        diff_path = GOLDEN_DIR / branch / "diff.patch"
        digest = hashlib.sha256(diff_path.read_bytes()).hexdigest()
        assert digest == entry["patch_sha256"], f"{branch}: diff.patch does not match manifest"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/eval/test_golden_manifest.py -v`
Expected: FAIL — `eval/golden/manifest.json` doesn't exist yet (`FileNotFoundError`).

- [ ] **Step 3: Generate `manifest.json` and the 8 `diff.patch` files from the seed repo**

The 8 branches are read-only reference data in `../student-progress-seed` (CLAUDE.md: "Seed A... Read-only"). `git diff`/`git rev-parse`/`git merge-base` are non-mutating reads — no checkout, no branch modification. Run this once from the `py-attest` repo root:

```bash
mkdir -p eval/golden/feature eval/golden/fix

python3 - <<'PYEOF'
import hashlib
import json
import subprocess
from pathlib import Path

SEED = Path("../student-progress-seed").resolve()
GOLDEN = Path("eval/golden")
BASE_SHA = "fbd4e09643ea61027165fdbfafbb2c3e5edd0153"

BRANCHES = [
    "feature/analytics-archive",
    "feature/email-reminders",
    "feature/lessons-pagination",
    "feature/score-validation",
    "feature/streaks",
    "feature/support-context",
    "fix/mobile-sync-visibility",
    "fix/progress-percentage",
]

manifest = {"dataset_version": "1.0.0", "base_sha": BASE_SHA, "branches": {}}

for branch in BRANCHES:
    head_sha = subprocess.run(
        ["git", "-C", str(SEED), "rev-parse", branch],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    merge_base_sha = subprocess.run(
        ["git", "-C", str(SEED), "merge-base", BASE_SHA, head_sha],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert merge_base_sha == BASE_SHA, f"{branch}: merge-base {merge_base_sha} != {BASE_SHA}"

    diff = subprocess.run(
        ["git", "-C", str(SEED), "diff", "--binary", "--full-index", f"{BASE_SHA}...{head_sha}"],
        capture_output=True, check=True,
    ).stdout

    branch_dir = GOLDEN / branch
    branch_dir.mkdir(parents=True, exist_ok=True)
    (branch_dir / "diff.patch").write_bytes(diff)

    manifest["branches"][branch] = {
        "head_sha": head_sha,
        "merge_base_sha": merge_base_sha,
        "patch_sha256": hashlib.sha256(diff).hexdigest(),
    }

(GOLDEN / "manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print("wrote", GOLDEN / "manifest.json")
PYEOF
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/eval/test_golden_manifest.py -v`
Expected: PASS — both tests green, confirming every generated `diff.patch` hashes to Seed B's frozen `patch_sha256` and `manifest.json` matches the hardcoded table above exactly.

- [ ] **Step 5: Commit**

```bash
git add eval/golden/manifest.json eval/golden/feature eval/golden/fix tests/eval/test_golden_manifest.py
git commit -m "$(cat <<'EOF'
eval: golden-set diff.patch + manifest.json for the 8 seed branches

git diff --binary --full-index against Seed B's frozen base/head SHAs
(../seed-b/eval/README.md), sha256-verified against Seed B's ground_truth.json
patch_sha256 values. Read-only against ../student-progress-seed (no checkout,
no branch mutation).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 2: Golden fixture data — `expected.json` for the 8 branches + `adjudications.yml` scaffold

**Files:**
- Create: `eval/golden/feature/analytics-archive/expected.json`
- Create: `eval/golden/feature/email-reminders/expected.json`
- Create: `eval/golden/feature/lessons-pagination/expected.json`
- Create: `eval/golden/feature/score-validation/expected.json`
- Create: `eval/golden/feature/streaks/expected.json`
- Create: `eval/golden/feature/support-context/expected.json`
- Create: `eval/golden/fix/mobile-sync-visibility/expected.json`
- Create: `eval/golden/fix/progress-percentage/expected.json`
- Create: `eval/golden/adjudications.yml`
- Test: `tests/eval/test_golden_expected.py`

**Interfaces:**
- Consumes: `eval/golden/manifest.json` (Task 1), `py_attest.standards.registry.load_registry` + `py_attest/standards/defaults/{core,domain}.standards.yml`, `py_attest/eval/legacy_rule_ids.json`.
- Produces: `expected.json` shape `{"branch": str, "source": {"base_sha", "head_sha", "merge_base_sha", "patch_sha256"}, "verdict": "APPROVE"|"BLOCK", "findings": [{"rule_id", "severity", "path", "line_start", "line_end", "llm_reachable"}]}`. Task 5/8's `metrics.py`/`test_golden.py` read this as the expected side of matching.

**Ground truth** (spec §2 — Seed B's `ground_truth.json` findings remapped through `legacy_rule_ids.json`, cross-checked against Seed A's `ground_truth.yml`, with the two brainstormed divergences resolved: `score-validation` follows the registry's fixed S2/BLOCK, not Seed A's original APPROVE; `support-context`/`progress-percentage` follow Seed B's 1-finding-per-branch shape). `llm_reachable` is computed, not copied: `deterministic`-mode rules are always reachable; `llm`-mode rules are unreachable only when `secrets-1` fires anywhere in the same branch (only `email-reminders`).

| Branch | Verdict | Findings (`rule_id`, `severity`, `path`, `line_start`-`line_end`, `llm_reachable`) |
|---|---|---|
| `feature/lessons-pagination` | APPROVE | none |
| `feature/score-validation` | BLOCK | `code-quality-3`, S2, `app/main.py`, 52-52, true |
| `fix/mobile-sync-visibility` | BLOCK | `pii-1`, S1, `app/main.py`, 57-60, true |
| `feature/support-context` | BLOCK | `pii-1`, S1, `app/main.py`, 37-37, true |
| `feature/email-reminders` | BLOCK | `secrets-1`, S1, `app/notifications.py`, 7-7, true · `pii-1`, S1, `app/notifications.py`, 13-13, **false** · `code-quality-5`, S3, `app/notifications.py`, 6-6, true |
| `feature/streaks` | BLOCK | `code-quality-6`, S2, `app/streaks.py`, 10-10, true · `testing-3`, S2, `app/streaks.py`, 10-13, true |
| `feature/analytics-archive` | BLOCK | `retention-2`, S1, `app/archive.py`, 4-8, true · `retention-3`, S1, `app/archive.py`, 15-16, true · `testing-2`, S2, `app/main.py`, 58-58, true |
| `fix/progress-percentage` | BLOCK | `testing-3`, S2, `app/main.py`, 38-38, true |

- [ ] **Step 1: Write the failing consistency test**

```python
# tests/eval/test_golden_expected.py
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/eval/test_golden_expected.py -v`
Expected: FAIL — no `expected.json` files exist yet.

- [ ] **Step 3: Write the 8 `expected.json` files**

`eval/golden/feature/lessons-pagination/expected.json`:
```json
{
  "branch": "feature/lessons-pagination",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "386b2e1d2882820c82977cbfd7361d3aea6b6865",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "0682eebedbc2d3b840b4ce5846c1dc1bbf8e7c31cd0b44be6192b3e12a41909e"
  },
  "verdict": "APPROVE",
  "findings": []
}
```

`eval/golden/feature/score-validation/expected.json`:
```json
{
  "branch": "feature/score-validation",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "60a6090693bc327d90838943f13890ca803f37a0",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "edef156d10b2bda7628f4cf54bea09fea4f317978b2d5b3a3122ff48c172a8cb"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "code-quality-3", "severity": "S2", "path": "app/main.py", "line_start": 52, "line_end": 52, "llm_reachable": true}
  ]
}
```

`eval/golden/fix/mobile-sync-visibility/expected.json`:
```json
{
  "branch": "fix/mobile-sync-visibility",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "fa726eb00be931ad67a4b11f1282f1838563975f",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "4a25d0d6af8cf37eb8ca08def2ac6dca15cb995b49d62e3fa975b867a0ec095f"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "pii-1", "severity": "S1", "path": "app/main.py", "line_start": 57, "line_end": 60, "llm_reachable": true}
  ]
}
```

`eval/golden/feature/support-context/expected.json`:
```json
{
  "branch": "feature/support-context",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "dfabcaeb1fedc65330928a29271b00efb40c5bce",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "72380ff6bfde72feaf1cbb307d8d594abe7ef804d75df8625d51ecd92d5be85b"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "pii-1", "severity": "S1", "path": "app/main.py", "line_start": 37, "line_end": 37, "llm_reachable": true}
  ]
}
```

`eval/golden/feature/email-reminders/expected.json`:
```json
{
  "branch": "feature/email-reminders",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "e1732cb7b95d42ad36f1a5b00583fb61bea8c119",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "4fa76a4edb931b92e5c9eb21a28db8d1d1228db1037013b9f2214ff08a8bfa3a"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "secrets-1", "severity": "S1", "path": "app/notifications.py", "line_start": 7, "line_end": 7, "llm_reachable": true},
    {"rule_id": "pii-1", "severity": "S1", "path": "app/notifications.py", "line_start": 13, "line_end": 13, "llm_reachable": false},
    {"rule_id": "code-quality-5", "severity": "S3", "path": "app/notifications.py", "line_start": 6, "line_end": 6, "llm_reachable": true}
  ]
}
```

`eval/golden/feature/streaks/expected.json`:
```json
{
  "branch": "feature/streaks",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "b5133c29895d6a98ceb2e595b10c4e89093ac71f",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "5c40733a254dec924ae0545d03f5c6aa7b9642d2968d4da80374edfe4dd4cac9"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "code-quality-6", "severity": "S2", "path": "app/streaks.py", "line_start": 10, "line_end": 10, "llm_reachable": true},
    {"rule_id": "testing-3", "severity": "S2", "path": "app/streaks.py", "line_start": 10, "line_end": 13, "llm_reachable": true}
  ]
}
```

`eval/golden/feature/analytics-archive/expected.json`:
```json
{
  "branch": "feature/analytics-archive",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "d5ecfb126399ae9b214500ab71e75e5707a2264d",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "d406de699c4fc42c3a1cad2a02f49a2e811b8835c13ca33bbffbfb2c37d32207"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "retention-2", "severity": "S1", "path": "app/archive.py", "line_start": 4, "line_end": 8, "llm_reachable": true},
    {"rule_id": "retention-3", "severity": "S1", "path": "app/archive.py", "line_start": 15, "line_end": 16, "llm_reachable": true},
    {"rule_id": "testing-2", "severity": "S2", "path": "app/main.py", "line_start": 58, "line_end": 58, "llm_reachable": true}
  ]
}
```

`eval/golden/fix/progress-percentage/expected.json`:
```json
{
  "branch": "fix/progress-percentage",
  "source": {
    "base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "head_sha": "a620c3832d9a587624814a2f9c0dd9a566345c92",
    "merge_base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153",
    "patch_sha256": "6eae85ee1c133808f8cce0cbbfcee9b2d51dbd3581a26b484da57702d04552e1"
  },
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "testing-3", "severity": "S2", "path": "app/main.py", "line_start": 38, "line_end": 38, "llm_reachable": true}
  ]
}
```

`eval/golden/adjudications.yml` (empty scaffold — populated later, once a real run needs one; spec §5):
```yaml
# Manual overrides for the `adjudicated` reading (py_attest/eval/metrics.py).
#
# Each entry credits one documented, human-reviewed mismatch between a predicted
# finding and an expected finding as a match, without changing `strict`'s count.
# This file starts empty: F0.5 ships the mechanism, not pre-loaded entries. Seed A's
# own two historical adjudications (streaks off-by-one and progress-percentage
# test-enshrinement, both filed under the wrong section) described mismatches in a run
# under the *old* prompt/schema and are not ported mechanically — add an entry here
# only after reviewing a real recording under the new prompt/schema and confirming the
# same mismatch shape recurs (ADR-004 SS6: never tune the golden set from outcomes,
# only document what a specific real run actually did).
#
# Schema:
# adjudications:
#   - branch: feature/streaks
#     expected: {rule_id: code-quality-6, path: app/streaks.py}
#     predicted: {rule_id: code-quality-6, path: app/main.py}
#     reason: "human-reviewed: predicted finding describes the same root cause, filed under a neighboring path"

adjudications: []
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/eval/test_golden_expected.py -v`
Expected: PASS — all 8 branches consistent with `manifest.json`, every `rule_id` real, every severity matches the registry, every verdict matches its findings' severities, and `email-reminders`'s `pii-1` is the only `llm_reachable: false` finding.

- [ ] **Step 5: Commit**

```bash
git add eval/golden/*/expected.json eval/golden/*/*/expected.json eval/golden/adjudications.yml tests/eval/test_golden_expected.py
git commit -m "$(cat <<'EOF'
eval: golden-set expected.json (reconciled ground truth) + adjudications.yml scaffold

Ground truth is Seed B's ground_truth.json findings remapped through
legacy_rule_ids.json (rule_id/path/line precision), cross-checked against Seed
A's ground_truth.yml, with two brainstormed divergences resolved: score-
validation follows the registry's fixed S2 severity for code-quality-3 (BLOCK,
not Seed A's original APPROVE/S3 framing), and support-context/progress-
percentage follow Seed B's one-finding-per-branch shape. llm_reachable is
computed from rule mode + whether secrets-1 fires in the same branch, not
copied from Seed A's pre-deterministic/LLM-split marking.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 3: `metrics.py` — new matcher + `strict` reading

**Files:**
- Modify: `py_attest/eval/metrics.py` (full rewrite — the current file is Seed A's unmodified `eval_metrics.py`; every function in it is replaced across this and the next two tasks)
- Modify: `tests/eval/test_metrics.py` (full rewrite)

**Interfaces:**
- Consumes: nothing from other tasks (pure data-structure logic, tested with inline synthetic dicts).
- Produces: `FindingRecord`, `FindingResults` (`true_positives`/`false_positives`/`false_negatives` + `precision`/`recall`/`f1` properties, same names as today), `findings_match(expected: dict, predicted: dict) -> bool`, `match_findings(branch: str, expected: list[dict], predicted: list[dict]) -> FindingResults` — all consumed by Task 4 (adjudicated/severity_exact build on `match_findings`'s output) and Task 5 (`evaluate()` calls `match_findings` per branch per reading).

Old `findings_match`/`match_findings`/`EvaluationResults`/`evaluate`/`render_markdown`/`main`/loader helpers (`_load_pr_numbers`, `_load_review`, `_load_branch_review`, `_verdict_class`, `_confusion`, `_branch_row`, etc.) are **replaced in this and the next two tasks**, not kept alongside the new logic — Seed A's PR-artifact-lookup shape (`prs.json`, `runs_root`) doesn't apply to a golden-set-of-recordings design.

- [ ] **Step 1: Write the failing tests**

```python
# tests/eval/test_metrics.py (new file content — replaces the old one entirely)
"""Tests for the golden-set matcher and finding-level readings."""

from py_attest.eval.metrics import FindingResults, findings_match, match_findings


def _finding(rule_id: str, path: str, line_start: int, line_end: int, **extra) -> dict:
    return {"rule_id": rule_id, "path": path, "line_start": line_start, "line_end": line_end, **extra}


def test_findings_match_requires_rule_id_and_path_and_overlapping_lines() -> None:
    expected = _finding("code-quality-6", "app/streaks.py", 10, 10)

    assert findings_match(expected, _finding("code-quality-6", "app/streaks.py", 10, 10))
    assert findings_match(expected, _finding("code-quality-6", "app/streaks.py", 8, 12))  # overlap
    assert not findings_match(expected, _finding("code-quality-6", "app/other.py", 10, 10))
    assert not findings_match(expected, _finding("testing-3", "app/streaks.py", 10, 10))
    assert not findings_match(expected, _finding("code-quality-6", "app/streaks.py", 20, 25))


def test_findings_match_tolerates_a_missing_predicted_line_range() -> None:
    expected = _finding("pii-1", "app/main.py", 37, 37)
    predicted = {"rule_id": "pii-1", "path": "app/main.py", "line_start": None, "line_end": None}

    assert not findings_match(expected, predicted)


def test_match_findings_is_one_to_one() -> None:
    expected = [_finding("testing-3", "app/streaks.py", 10, 13)]
    predicted = [
        _finding("testing-3", "app/streaks.py", 10, 13, title="first"),
        _finding("testing-3", "app/streaks.py", 10, 13, title="duplicate"),
    ]

    results = match_findings("feature/streaks", expected, predicted)

    assert len(results.true_positives) == 1
    assert [record.finding["title"] for record in results.false_positives] == ["duplicate"]
    assert results.false_negatives == []


def test_match_findings_reports_a_miss_as_a_false_negative() -> None:
    expected = [_finding("retention-2", "app/archive.py", 4, 8)]

    results = match_findings("feature/analytics-archive", expected, [])

    assert results.true_positives == []
    assert len(results.false_negatives) == 1
    assert results.false_negatives[0].finding["rule_id"] == "retention-2"


def test_unreachable_findings_are_excluded_from_the_recall_denominator() -> None:
    expected = [
        _finding("code-quality-5", "app/notifications.py", 6, 6, llm_reachable=True),
        _finding("pii-1", "app/notifications.py", 13, 13, llm_reachable=False),
    ]
    predicted = [_finding("code-quality-5", "app/notifications.py", 6, 6)]

    results = match_findings("feature/email-reminders", expected, predicted)

    assert len(results.true_positives) == 1
    assert results.false_negatives == []  # the unreachable pii-1 never counts as a miss
    assert results.recall == 1.0


def test_finding_results_precision_recall_f1() -> None:
    results = FindingResults(
        true_positives=[object(), object()],  # 2 TP
        false_positives=[object()],  # 1 FP
        false_negatives=[object()],  # 1 FN
    )

    assert results.precision == 2 / 3
    assert results.recall == 2 / 3
    assert round(results.f1, 4) == round(2 * (2 / 3) * (2 / 3) / ((2 / 3) + (2 / 3)), 4)


def test_finding_results_ratios_are_zero_not_a_crash_on_empty_input() -> None:
    results = FindingResults(true_positives=[], false_positives=[], false_negatives=[])

    assert results.precision == 0.0
    assert results.recall == 0.0
    assert results.f1 == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: FAIL — `findings_match`/`match_findings`/`FindingResults` in `py_attest/eval/metrics.py` still use the old `(file, rule-section)` shape and reject/mis-handle these new-shape dicts.

- [ ] **Step 3: Replace the matcher and reading in `py_attest/eval/metrics.py`**

**Replace the entire contents of `py_attest/eval/metrics.py`** with the code block below — every function and class from the current Seed-A-shaped file (`EvaluationResults`, `BranchResults`, `rule_section`, the old `findings_match`/`match_findings`, `evaluate`, `render_markdown`, `main`, `_parser`, `_load_ground_truth`, `_load_pr_numbers`, `_load_review`, `_load_branch_review`, `_verdict_class`, `_combine_findings`, `_confusion`, `_branch_row`, `_append_matches`, `_append_records`, `_finding_json`, `_markdown_cell`, and the trailing `if __name__ == "__main__":` block) is deleted, not left in place. This matters beyond tidiness: Task 5 appends new `evaluate`/`render_markdown`/`main` functions to this same file, and if the old same-named functions are still sitting in it, that's a duplicate top-level definition — ruff's `F811` (redefinition of unused name, part of the `F` category this project selects) will fail Task 5's own ruff step. Leave nothing below what's shown here; Tasks 4 and 5 append to the end of *this* file.

```python
"""Measure reviewer verdicts and findings against the golden set (F0.5).

Matching follows Seed B's SCORING-POLICY.md "One-to-one finding matching": same
rule_id, same path, overlapping [line_start, line_end] range. No finding text
(title/evidence/explanation) affects matching -- only rule_id/path/line identify a
finding, matching the schema_version 3 report shape (TRD SS4.3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class EvaluationError(ValueError):
    """Raised when evaluation inputs do not have the expected structure."""


@dataclass(frozen=True)
class FindingRecord:
    """A finding together with its source branch."""

    branch: str
    finding: dict[str, Any]


@dataclass(frozen=True)
class FindingMatch:
    """A one-to-one match between a golden and predicted finding."""

    expected: FindingRecord
    predicted: FindingRecord


@dataclass
class FindingResults:
    """Finding-level results for one reading (strict / adjudicated / severity_exact)."""

    true_positives: list[Any] = field(default_factory=list)
    false_positives: list[Any] = field(default_factory=list)
    false_negatives: list[Any] = field(default_factory=list)

    @property
    def precision(self) -> float:
        denominator = len(self.true_positives) + len(self.false_positives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def recall(self) -> float:
        denominator = len(self.true_positives) + len(self.false_negatives)
        return _ratio(len(self.true_positives), denominator)

    @property
    def f1(self) -> float:
        return _ratio(2 * self.precision * self.recall, self.precision + self.recall)


def _ranges_overlap(a_start: int, a_end: int, b_start: int | None, b_end: int | None) -> bool:
    if b_start is None or b_end is None:
        return False
    return a_start <= b_end and b_start <= a_end


def findings_match(expected: dict[str, Any], predicted: dict[str, Any]) -> bool:
    """Match findings by exact rule_id, exact path, and overlapping line range."""
    return (
        expected.get("rule_id") is not None
        and expected.get("rule_id") == predicted.get("rule_id")
        and expected.get("path") == predicted.get("path")
        and _ranges_overlap(
            expected["line_start"],
            expected["line_end"],
            predicted.get("line_start"),
            predicted.get("line_end"),
        )
    )


def match_findings(
    branch: str,
    expected: list[dict[str, Any]],
    predicted: list[dict[str, Any]],
) -> FindingResults:
    """Perform deterministic one-to-one finding matching for one branch (the `strict`
    reading). llm_reachable: false findings are excluded entirely -- they sit behind the
    secrets firewall and no LLM-graded reviewer can be scored on them (TRD SS9)."""
    reachable = [finding for finding in expected if finding.get("llm_reachable", True)]
    remaining_predictions = list(predicted)
    true_positives: list[FindingMatch] = []
    false_negatives: list[FindingRecord] = []

    for expected_finding in reachable:
        match_index = _first_match(expected_finding, remaining_predictions)
        expected_record = FindingRecord(branch, expected_finding)
        if match_index is None:
            false_negatives.append(expected_record)
            continue
        predicted_finding = remaining_predictions.pop(match_index)
        true_positives.append(
            FindingMatch(expected_record, FindingRecord(branch, predicted_finding))
        )

    return FindingResults(
        true_positives=true_positives,
        false_positives=[FindingRecord(branch, finding) for finding in remaining_predictions],
        false_negatives=false_negatives,
    )


def _first_match(expected: dict[str, Any], predicted: list[dict[str, Any]]) -> int | None:
    return next(
        (
            index
            for index, predicted_finding in enumerate(predicted)
            if findings_match(expected, predicted_finding)
        ),
        None,
    )


def _ratio(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check py_attest/eval/metrics.py tests/eval/test_metrics.py && uv run ruff format --check py_attest/eval/metrics.py tests/eval/test_metrics.py`
Expected: clean (fix any `ARG`/`S101`/import-order violations before proceeding).

- [ ] **Step 6: Commit**

```bash
git add py_attest/eval/metrics.py tests/eval/test_metrics.py
git commit -m "$(cat <<'EOF'
eval: metrics.py matcher rewrite for rule_id/path/line-range findings (F0.5)

Replaces Seed A's (file, leading-rule-section-digit) matcher -- eval_metrics.py's
original shape, byte-migrated in Paso 2 -- with rule_id + path + overlapping
[line_start, line_end] matching (Seed B's SCORING-POLICY.md "One-to-one finding
matching"), matching the schema_version 3 report's finding shape (TRD SS4.3).
This is the `strict` reading; adjudicated and severity_exact land in the next
commits.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 4: `metrics.py` — `adjudicated` and `severity_exact` readings

**Files:**
- Modify: `py_attest/eval/metrics.py`
- Modify: `tests/eval/test_metrics.py`

**Interfaces:**
- Consumes: `FindingRecord`, `FindingMatch`, `FindingResults`, `match_findings` (Task 3).
- Produces: `load_adjudications(path: Path) -> list[dict[str, Any]]`, `apply_adjudications(branch: str, strict: FindingResults, predicted: list[dict], adjudications: list[dict]) -> FindingResults`, `severity_exact_results(strict: FindingResults) -> FindingResults`. Task 5's `evaluate()` calls all three per branch to build the three per-egress reading aggregates.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/eval/test_metrics.py

from py_attest.eval.metrics import apply_adjudications, severity_exact_results


def test_severity_exact_demotes_a_mismatched_severity_to_fn_plus_fp() -> None:
    expected = _finding("code-quality-3", "app/main.py", 52, 52, severity="S2")
    predicted = _finding("code-quality-3", "app/main.py", 52, 52, severity="S3")
    strict = match_findings("feature/score-validation", [expected], [predicted])
    assert len(strict.true_positives) == 1  # strict ignores severity entirely

    exact = severity_exact_results(strict)

    assert exact.true_positives == []
    assert len(exact.false_negatives) == 1  # expected S2 never matched
    assert len(exact.false_positives) == 1  # predicted S3 never matched


def test_severity_exact_keeps_a_matching_severity_as_tp() -> None:
    expected = _finding("pii-1", "app/main.py", 37, 37, severity="S1")
    predicted = _finding("pii-1", "app/main.py", 37, 37, severity="S1")
    strict = match_findings("feature/support-context", [expected], [predicted])

    exact = severity_exact_results(strict)

    assert len(exact.true_positives) == 1
    assert exact.false_positives == []
    assert exact.false_negatives == []


def test_severity_exact_carries_over_unmatched_findings_unchanged() -> None:
    expected = [_finding("retention-2", "app/archive.py", 4, 8, severity="S1")]
    strict = match_findings("feature/analytics-archive", expected, [])  # no prediction -> 1 FN

    exact = severity_exact_results(strict)

    assert len(exact.false_negatives) == 1
    assert exact.true_positives == []
    assert exact.false_positives == []


def test_adjudications_credit_a_documented_mismatch_without_changing_strict() -> None:
    expected = [_finding("code-quality-6", "app/streaks.py", 10, 10)]
    predicted = [_finding("code-quality-6", "app/main.py", 5, 5, title="filed under the wrong path")]
    strict = match_findings("feature/streaks", expected, predicted)
    assert strict.true_positives == []
    assert len(strict.false_negatives) == 1
    assert len(strict.false_positives) == 1

    adjudications = [
        {
            "branch": "feature/streaks",
            "expected": {"rule_id": "code-quality-6", "path": "app/streaks.py"},
            "predicted": {"rule_id": "code-quality-6", "path": "app/main.py"},
            "reason": "same root cause, filed under a neighboring path",
        }
    ]

    adjudicated = apply_adjudications("feature/streaks", strict, predicted, adjudications)

    assert len(adjudicated.true_positives) == 1
    assert adjudicated.false_negatives == []
    assert adjudicated.false_positives == []
    # strict itself is untouched
    assert len(strict.false_negatives) == 1
    assert len(strict.false_positives) == 1


def test_adjudications_only_apply_to_their_own_branch() -> None:
    expected = [_finding("code-quality-6", "app/streaks.py", 10, 10)]
    predicted = [_finding("code-quality-6", "app/main.py", 5, 5)]
    strict = match_findings("feature/other-branch", expected, predicted)

    adjudications = [
        {
            "branch": "feature/streaks",  # different branch
            "expected": {"rule_id": "code-quality-6", "path": "app/streaks.py"},
            "predicted": {"rule_id": "code-quality-6", "path": "app/main.py"},
            "reason": "n/a",
        }
    ]

    adjudicated = apply_adjudications("feature/other-branch", strict, predicted, adjudications)

    assert adjudicated.true_positives == []
    assert len(adjudicated.false_negatives) == 1
    assert len(adjudicated.false_positives) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: FAIL — `apply_adjudications`/`severity_exact_results` don't exist yet (`ImportError`).

- [ ] **Step 3: Implement both readings**

Append to `py_attest/eval/metrics.py`:

```python
def severity_exact_results(strict: FindingResults) -> FindingResults:
    """Seed B's SCORING-POLICY.md "Severity treatment": a strict match with unequal
    severity is one FN (expected severity) + one FP (predicted severity), never a
    hidden TP. Unmatched findings carry over unchanged."""
    true_positives: list[FindingMatch] = []
    false_negatives: list[FindingRecord] = list(strict.false_negatives)
    false_positives: list[FindingRecord] = list(strict.false_positives)

    for match in strict.true_positives:
        if match.expected.finding.get("severity") == match.predicted.finding.get("severity"):
            true_positives.append(match)
        else:
            false_negatives.append(match.expected)
            false_positives.append(match.predicted)

    return FindingResults(
        true_positives=true_positives,
        false_positives=false_positives,
        false_negatives=false_negatives,
    )


def load_adjudications(path: Path) -> list[dict[str, Any]]:
    """Load eval/golden/adjudications.yml. Missing file -> no adjudications (the
    mechanism must work before any entry is ever added)."""
    if not path.is_file():
        return []
    document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    entries = document.get("adjudications", [])
    if not isinstance(entries, list):
        raise EvaluationError(f"{path}: 'adjudications' must be a list")
    return entries


def apply_adjudications(
    branch: str,
    strict: FindingResults,
    predicted: list[dict[str, Any]],
    adjudications: list[dict[str, Any]],
) -> FindingResults:
    """Credit documented mismatches (spec SS5) as matches, without mutating `strict`."""
    true_positives = list(strict.true_positives)
    remaining_fn = list(strict.false_negatives)
    remaining_fp = list(strict.false_positives)

    for entry in adjudications:
        if entry.get("branch") != branch:
            continue
        expected_key = entry["expected"]
        predicted_key = entry["predicted"]

        fn_index = next(
            (
                i
                for i, record in enumerate(remaining_fn)
                if record.finding.get("rule_id") == expected_key["rule_id"]
                and record.finding.get("path") == expected_key["path"]
            ),
            None,
        )
        fp_index = next(
            (
                i
                for i, record in enumerate(remaining_fp)
                if record.finding.get("rule_id") == predicted_key["rule_id"]
                and record.finding.get("path") == predicted_key["path"]
            ),
            None,
        )
        if fn_index is None or fp_index is None:
            continue  # the documented mismatch didn't recur in this run -- not an error

        expected_record = remaining_fn.pop(fn_index)
        predicted_record = remaining_fp.pop(fp_index)
        true_positives.append(FindingMatch(expected_record, predicted_record))

    return FindingResults(
        true_positives=true_positives,
        false_positives=remaining_fp,
        false_negatives=remaining_fn,
    )
```

Add the two new imports at the top of the file:

```python
from pathlib import Path

import yaml
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: PASS — all tests green, including the earlier Task 3 tests (no regressions).

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check py_attest/eval/metrics.py tests/eval/test_metrics.py && uv run ruff format --check py_attest/eval/metrics.py tests/eval/test_metrics.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add py_attest/eval/metrics.py tests/eval/test_metrics.py
git commit -m "$(cat <<'EOF'
eval: metrics.py adjudicated + severity_exact readings (F0.5)

severity_exact ports Seed B's SCORING-POLICY.md "Severity treatment": a
rule/path/line match with unequal severity contributes one FN + one FP, never
a hidden TP. adjudicated overlays eval/golden/adjudications.yml (still empty)
onto the strict match set without mutating strict itself -- the mechanism
ships now; entries get added once a real recording needs one.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 5: `metrics.py` — egress axis, `evaluate()`/`render_markdown()` via `run_review` replay, CLI

**Files:**
- Modify: `py_attest/eval/metrics.py`
- Modify: `tests/eval/test_metrics.py`

**Interfaces:**
- Consumes: `match_findings`, `severity_exact_results`, `apply_adjudications`, `load_adjudications` (Tasks 3-4); `py_attest.review.reviewer.run_review`; `py_attest.config.Config`.
- Produces: `BranchResult` (`branch`, `expected_verdict`, `predicted_verdict: str | None`, `readings: dict[str, FindingResults]`), `EgressResults` (`egress: str`, `branches: list[BranchResult]`, `skipped: list[str]`, `readings: dict[str, FindingResults]` aggregated, plus `block_recall`/`block_precision`/`accuracy` properties over `branches`), `evaluate(golden_dir: Path, egress: str, *, require_all: bool = False) -> EgressResults`, `render_markdown(results: EgressResults) -> str`, `main(argv) -> int`. Task 8's `test_golden.py` calls `evaluate(..., require_all=False)` directly.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/eval/test_metrics.py

import json

import pytest

from py_attest.config import Config
from py_attest.eval.metrics import EvaluationError, evaluate, render_markdown


def _write_branch(
    tmp_path, branch: str, *, verdict: str, findings: list[dict], recording: dict | None
) -> None:
    branch_dir = tmp_path / branch
    branch_dir.mkdir(parents=True)
    (branch_dir / "diff.patch").write_text(
        "diff --git a/app/main.py b/app/main.py\n"
        "--- a/app/main.py\n+++ b/app/main.py\n@@ -1,1 +1,2 @@\n x\n+y\n",
        encoding="utf-8",
    )
    (branch_dir / "expected.json").write_text(
        json.dumps(
            {
                "branch": branch,
                "source": {
                    "base_sha": "a" * 40,
                    "head_sha": "b" * 40,
                    "merge_base_sha": "a" * 40,
                    "patch_sha256": "c" * 64,
                },
                "verdict": verdict,
                "findings": findings,
            }
        ),
        encoding="utf-8",
    )
    if recording is not None:
        (branch_dir / "provider_response.raw.json").write_text(
            json.dumps(recording), encoding="utf-8"
        )


def test_evaluate_skips_branches_with_no_recording_when_require_all_is_false(tmp_path) -> None:
    golden_dir = tmp_path / "golden"
    _write_branch(golden_dir, "feature/clean", verdict="APPROVE", findings=[], recording=None)

    results = evaluate(golden_dir, "raw", require_all=False)

    assert results.branches == []
    assert results.skipped == ["feature/clean"]


def test_evaluate_replays_a_recording_through_the_full_pipeline(tmp_path) -> None:
    golden_dir = tmp_path / "golden"
    _write_branch(
        golden_dir,
        "feature/clean",
        verdict="APPROVE",
        findings=[],
        recording={"findings": [], "summary": "nothing to report"},
    )

    results = evaluate(golden_dir, "raw", require_all=False)

    assert results.skipped == []
    assert len(results.branches) == 1
    branch = results.branches[0]
    assert branch.branch == "feature/clean"
    assert branch.expected_verdict == "APPROVE"
    assert branch.predicted_verdict == "APPROVE"
    assert branch.readings["strict"].true_positives == []


def test_evaluate_raises_when_require_all_and_a_recording_is_missing(tmp_path) -> None:
    golden_dir = tmp_path / "golden"
    _write_branch(golden_dir, "feature/clean", verdict="APPROVE", findings=[], recording=None)

    with pytest.raises(EvaluationError, match="feature/clean"):
        evaluate(golden_dir, "raw", require_all=True)


def test_render_markdown_includes_all_three_readings(tmp_path) -> None:
    golden_dir = tmp_path / "golden"
    _write_branch(
        golden_dir,
        "feature/clean",
        verdict="APPROVE",
        findings=[],
        recording={"findings": [], "summary": "nothing to report"},
    )
    results = evaluate(golden_dir, "raw", require_all=False)

    report = render_markdown(results)

    assert "strict" in report
    assert "adjudicated" in report
    assert "severity_exact" in report
    assert "raw" in report
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: FAIL — `evaluate`/`render_markdown`/`EgressResults`/`BranchResult` don't exist in the new shape yet.

- [ ] **Step 3: Implement `evaluate()`, `render_markdown()`, `main()`**

Append to `py_attest/eval/metrics.py` (and add `import argparse`, `import json`, `import sys`, `import tempfile`, `from py_attest.config import Config`, `from py_attest.review.reviewer import run_review` to the top):

```python
_READING_NAMES = ("strict", "adjudicated", "severity_exact")


@dataclass(frozen=True)
class BranchResult:
    branch: str
    expected_verdict: str
    predicted_verdict: str | None
    readings: dict[str, FindingResults]


@dataclass
class EgressResults:
    egress: str
    branches: list[BranchResult] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def readings(self) -> dict[str, FindingResults]:
        combined: dict[str, FindingResults] = {name: FindingResults() for name in _READING_NAMES}
        for branch in self.branches:
            for name, result in branch.readings.items():
                combined[name].true_positives.extend(result.true_positives)
                combined[name].false_positives.extend(result.false_positives)
                combined[name].false_negatives.extend(result.false_negatives)
        return combined

    @property
    def accuracy(self) -> float:
        correct = sum(
            b.predicted_verdict is not None and b.predicted_verdict == b.expected_verdict
            for b in self.branches
        )
        return _ratio(correct, len(self.branches))

    @property
    def block_recall(self) -> float:
        expected_blocks = [b for b in self.branches if b.expected_verdict == "BLOCK"]
        true_blocks = sum(b.predicted_verdict == "BLOCK" for b in expected_blocks)
        return _ratio(true_blocks, len(expected_blocks))

    @property
    def block_precision(self) -> float:
        predicted_blocks = [b for b in self.branches if b.predicted_verdict == "BLOCK"]
        true_blocks = sum(b.expected_verdict == "BLOCK" for b in predicted_blocks)
        return _ratio(true_blocks, len(predicted_blocks))


def evaluate(golden_dir: Path, egress: str, *, require_all: bool = False) -> EgressResults:
    """Replay each branch's provider_response.<egress>.json through the real pipeline
    (reviewer.run_review with provider="fake") and score it under all three readings.
    A branch with no recording for this egress mode is skipped unless require_all."""
    if egress not in {"raw", "minimized"}:
        raise EvaluationError(f"unknown egress mode: {egress!r}")

    adjudications = load_adjudications(golden_dir / "adjudications.yml")
    results = EgressResults(egress=egress)

    for expected_path in sorted(golden_dir.glob("*/*/expected.json")):
        branch_dir = expected_path.parent
        branch = json.loads(expected_path.read_text(encoding="utf-8"))
        recording_path = branch_dir / f"provider_response.{egress}.json"

        if not recording_path.is_file():
            if require_all:
                raise EvaluationError(
                    f"missing provider_response.{egress}.json for {branch['branch']}"
                )
            results.skipped.append(branch["branch"])
            continue

        diff = (branch_dir / "diff.patch").read_text(encoding="utf-8")
        # run_review always writes a JSON+MD report under out_dir -- golden_dir is a
        # real, committed directory (eval/golden/), so that report must land in a
        # scratch location, never alongside the fixtures themselves.
        with tempfile.TemporaryDirectory() as scratch_dir:
            outcome = run_review(
                diff=diff,
                source_name=branch["branch"].replace("/", "-"),
                repo_root=branch_dir,
                config=Config(),
                out_dir=Path(scratch_dir),
                provider="fake",
                fake_response=str(recording_path),
                egress=egress,
                as_json=True,
            )
        predicted_findings = outcome.json_report["findings"]

        strict = match_findings(branch["branch"], branch["findings"], predicted_findings)
        readings = {
            "strict": strict,
            "adjudicated": apply_adjudications(
                branch["branch"], strict, predicted_findings, adjudications
            ),
            "severity_exact": severity_exact_results(strict),
        }
        results.branches.append(
            BranchResult(
                branch=branch["branch"],
                expected_verdict=branch["verdict"],
                predicted_verdict=outcome.json_report["verdict"],
                readings=readings,
            )
        )

    return results


def render_markdown(results: EgressResults) -> str:
    lines = [
        f"# Reviewer evaluation -- egress={results.egress}",
        "",
        f"- Branches scored: {len(results.branches)}",
        f"- Branches skipped (no recording yet): {len(results.skipped)}"
        + (f" ({', '.join(results.skipped)})" if results.skipped else ""),
        f"- Block recall: {_percent(results.block_recall)}",
        f"- Block precision: {_percent(results.block_precision)}",
        f"- Verdict accuracy: {_percent(results.accuracy)}",
        "",
    ]
    for name in _READING_NAMES:
        reading = results.readings[name]
        lines.extend(
            [
                f"## Findings -- {name}",
                "",
                f"- Precision: {_percent(reading.precision)}",
                f"- Recall: {_percent(reading.recall)}",
                f"- F1: {_percent(reading.f1)}",
                f"- TP: {len(reading.true_positives)} / FP: {len(reading.false_positives)} "
                f"/ FN: {len(reading.false_negatives)}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _percent(value: float) -> str:
    return f"{value:.1%}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--golden-dir", type=Path, default=Path.cwd() / "eval" / "golden")
    parser.add_argument("--egress", choices=["raw", "minimized"], required=True)
    parser.add_argument("--require-all", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    try:
        results = evaluate(args.golden_dir, args.egress, require_all=args.require_all)
    except EvaluationError as exc:
        sys.stderr.write(f"evaluation failed: {exc}\n")
        return 2

    report = render_markdown(results)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Task 3 already removed Seed A's old `evaluate`/`render_markdown`/`main`/loader helpers, so this is purely additive — the file should now end with the `if __name__ == "__main__":` block shown here, exactly once.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/eval/test_metrics.py -v`
Expected: PASS — all tests in the file green.

- [ ] **Step 5: Run ruff and the full suite**

Run: `uv run ruff check py_attest/eval/metrics.py tests/eval/test_metrics.py && uv run ruff format --check py_attest/eval/metrics.py tests/eval/test_metrics.py`
Run: `uv run pytest tests/eval -v`
Expected: both clean; every test from Tasks 1-5 passes together.

- [ ] **Step 6: Commit**

```bash
git add py_attest/eval/metrics.py tests/eval/test_metrics.py
git commit -m "$(cat <<'EOF'
eval: metrics.py egress axis + full-pipeline replay + CLI (F0.5)

evaluate(golden_dir, egress) replaces Seed A's PR-artifact-lookup shape
(prs.json/runs_root, GitHub-PR-shaped) with a direct eval/golden/ scan, and
replays each provider_response.<egress>.json through reviewer.run_review
(provider="fake") -- validation.py, postfilter.py, and policy.py all run for
real, not just a JSON diff against the recording. A branch with no recording
yet is skipped (require_all=False, the offline-test default) rather than
failing, since this WP ships the harness without real recordings (spec SS7).
render_markdown() now prints one block per reading (strict/adjudicated/
severity_exact) for the given egress mode.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 6: `py_attest/eval/record.py` — the recorder

**Files:**
- Create: `py_attest/eval/record.py`
- Create: `tests/eval/test_record.py`
- Create: `tests/eval/fixtures/record_response.json` (a small valid `REVIEW_SCHEMA` fixture for `--provider fake`)

**Interfaces:**
- Consumes: `py_attest.review.reviewer._build_egress`, `_standards_paths`, `_build_provider` (reused directly — spec §4: "reuses the exact request-building internals reviewer.py already uses"); `py_attest.review.context_pack.render_rules_block`; `py_attest.standards.registry.load_registry`; `py_attest.llm.prompts.read_system_prompt`; `py_attest.llm.policy.run_with_policy`; `py_attest.llm.types.ProviderRequest`, `ProviderFailure`; `py_attest.review.models.REVIEW_SCHEMA`; `py_attest.config.Config`.
- Produces: `RecordError(ValueError)`, `record_response(*, diff_path: Path, provider_name: str, egress_mode: str, out_path: Path, config: Config, fake_response: str | None = None, prompt_version: str = "v3", repo_root: Path, branch: str | None = None, force: bool = False) -> None`, `main(argv) -> int`. Not consumed by other tasks in this plan (Task 8's tests build their own recordings directly, to keep that task's fixtures self-contained) — this is the tool the user runs later with a real key.

- [ ] **Step 1: Write the failing tests**

```python
# tests/eval/fixtures/record_response.json
{
  "findings": [],
  "summary": "clean"
}
```

```python
# tests/eval/test_record.py
"""Tests for the golden-set recorder CLI. Exercises --provider fake only -- this WP
never calls a real provider (CLAUDE.md: no network calls in tests)."""

import json
from pathlib import Path

import pytest

from py_attest.eval.record import RecordError, main, record_response
from py_attest.config import Config

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = "diff --git a/app/main.py b/app/main.py\n--- a/app/main.py\n+++ b/app/main.py\n@@ -1,1 +1,2 @@\n x\n+y\n"


def _write_diff(tmp_path: Path) -> Path:
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(DIFF, encoding="utf-8")
    return diff_path


def test_record_response_writes_the_provider_raw_json_verbatim(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"

    record_response(
        diff_path=diff_path,
        provider_name="fake",
        egress_mode="raw",
        out_path=out_path,
        config=Config(),
        fake_response=str(FIXTURES / "record_response.json"),
        repo_root=tmp_path,
        branch="feature/example",
    )

    assert json.loads(out_path.read_text(encoding="utf-8")) == {"findings": [], "summary": "clean"}


def test_record_response_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"
    out_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RecordError, match="already exists"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=out_path,
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_overwrites_when_forced(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"
    out_path.write_text("{}", encoding="utf-8")

    record_response(
        diff_path=diff_path,
        provider_name="fake",
        egress_mode="raw",
        out_path=out_path,
        config=Config(),
        fake_response=str(FIXTURES / "record_response.json"),
        repo_root=tmp_path,
        force=True,
    )

    assert json.loads(out_path.read_text(encoding="utf-8"))["summary"] == "clean"


def test_record_response_rejects_an_unknown_egress_mode(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="egress"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="bogus",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_raises_when_the_diff_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RecordError, match="cannot read diff"):
        record_response(
            diff_path=tmp_path / "missing.patch",
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_main_writes_the_recording_and_returns_zero(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"

    exit_code = main(
        [
            "--diff",
            str(diff_path),
            "--provider",
            "fake",
            "--fake-response",
            str(FIXTURES / "record_response.json"),
            "--egress",
            "raw",
            "--out",
            str(out_path),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert out_path.is_file()


def test_main_returns_two_on_a_record_error(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--diff",
            str(tmp_path / "missing.patch"),
            "--provider",
            "fake",
            "--fake-response",
            str(FIXTURES / "record_response.json"),
            "--egress",
            "raw",
            "--out",
            str(tmp_path / "out.json"),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/eval/test_record.py -v`
Expected: FAIL — `py_attest/eval/record.py` doesn't exist yet (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `record.py`**

```python
# py_attest/eval/record.py
"""Record one real provider call per branch x egress mode into
eval/golden/<branch>/provider_response.<egress>.json (spec SS4). Reuses the exact
request-building internals reviewer.py uses for a live `attest review`, so a recording
is provably built from the same ProviderRequest the real pipeline sends -- everything
downstream of the network call (validation, postfilter, policy, report) then runs for
real when the recording is replayed by metrics.py's evaluate().

Tested here with --provider fake only. A real recording needs `uv run python -m
py_attest.eval.record --provider openai --egress raw ...` with a real API key --
run by a human, never from this package's own test suite (CLAUDE.md: no network calls
in tests; API keys only from environment variables).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import click

from py_attest.config import Config
from py_attest.llm.policy import run_with_policy
from py_attest.llm.prompts import PromptError, read_system_prompt
from py_attest.llm.types import ProviderFailure, ProviderRequest
from py_attest.review.context_pack import render_rules_block
from py_attest.review.models import REVIEW_SCHEMA
from py_attest.review.reviewer import _build_egress, _build_provider, _standards_paths
from py_attest.standards.registry import RegistryError, load_registry

_EGRESS_MODES = {"raw", "minimized"}
_REQUEST_TEMPERATURE = 0


class RecordError(ValueError):
    """Raised when a recording cannot be produced."""


def record_response(
    *,
    diff_path: Path,
    provider_name: str,
    egress_mode: str,
    out_path: Path,
    config: Config,
    repo_root: Path,
    fake_response: str | None = None,
    prompt_version: str = "v3",
    branch: str | None = None,
    force: bool = False,
) -> None:
    """Call `provider_name` exactly once and write its raw structured output to
    `out_path`, verbatim -- never decoded or validated (that happens on replay, in
    reviewer.run_review via metrics.py's evaluate(), so recording and replay can never
    silently disagree about what "valid" means)."""
    if out_path.exists() and not force:
        raise RecordError(
            f"{out_path} already exists; pass --force to overwrite a sealed recording"
        )
    if egress_mode not in _EGRESS_MODES:
        raise RecordError(f"unknown egress mode: {egress_mode!r}")

    try:
        diff = diff_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RecordError(f"cannot read diff: {exc}") from exc

    try:
        core_path, domain_path = _standards_paths(repo_root, config)
        registry = load_registry(core_path, domain_path)
    except RegistryError as exc:
        raise RecordError(str(exc)) from exc

    rules_block = render_rules_block(registry.llm_rules())
    source_name = branch or diff_path.stem
    egress_result = _build_egress(egress_mode, diff, repo_root, config, None, source_name, rules_block)

    try:
        provider_instance = _build_provider(provider_name, config=config, fake_response=fake_response)
    except click.UsageError as exc:
        # _build_provider raises click.UsageError for an unregistered provider name or a
        # missing --fake-response; record.py has no click.Group of its own to catch
        # this, so surface it uniformly as RecordError like every other failure here.
        raise RecordError(str(exc)) from exc

    try:
        system_prompt = read_system_prompt(prompt_version)
    except PromptError as exc:
        raise RecordError(str(exc)) from exc

    request = ProviderRequest(
        system_prompt=system_prompt,
        user_content=egress_result.user_content,
        output_schema=REVIEW_SCHEMA,
        model=config.model,
        temperature=_REQUEST_TEMPERATURE,
    )
    try:
        response = run_with_policy(provider_instance, request)
    except ProviderFailure as exc:
        raise RecordError(f"provider call failed: {exc}") from exc

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(response.raw_json, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diff", type=Path, required=True, dest="diff_path")
    parser.add_argument("--provider", required=True, dest="provider_name")
    parser.add_argument("--egress", required=True, choices=sorted(_EGRESS_MODES))
    parser.add_argument("--out", type=Path, required=True, dest="out_path")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), dest="repo_root")
    parser.add_argument("--fake-response")
    parser.add_argument("--branch")
    parser.add_argument("--prompt-version", default="v3")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    try:
        record_response(
            diff_path=args.diff_path,
            provider_name=args.provider_name,
            egress_mode=args.egress,
            out_path=args.out_path,
            config=Config(),
            repo_root=args.repo_root,
            fake_response=args.fake_response,
            prompt_version=args.prompt_version,
            branch=args.branch,
            force=args.force,
        )
    except RecordError as exc:
        sys.stderr.write(f"record failed: {exc}\n")
        return 2

    sys.stdout.write(f"wrote {args.out_path}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/eval/test_record.py -v`
Expected: PASS — all 7 tests green.

- [ ] **Step 5: Run ruff**

Run: `uv run ruff check py_attest/eval/record.py tests/eval/test_record.py && uv run ruff format --check py_attest/eval/record.py tests/eval/test_record.py`
Expected: clean. (`_build_egress`/`_build_provider`/`_standards_paths` are underscore-private in `reviewer.py`; ruff's `select` list here doesn't flag private cross-module imports, but if it does, add a narrowly-scoped `# noqa` on the import line with a one-line reason, not a blanket ignore.)

- [ ] **Step 6: Commit**

```bash
git add py_attest/eval/record.py tests/eval/test_record.py tests/eval/fixtures/record_response.json
git commit -m "$(cat <<'EOF'
eval: record.py -- golden-set provider recorder (F0.5)

Reuses reviewer.py's own _standards_paths/_build_egress/_build_provider so a
recording is built from the exact ProviderRequest a live `attest review` would
send. Writes response.raw_json verbatim, undecoded -- decoding/validation only
happens on replay (metrics.py's evaluate(), via reviewer.run_review), so
recording and replay can never quietly disagree about what "valid" means.
Tested with --provider fake only; a real recording needs a human running this
with a real provider key (no network call in this package's own tests).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 7: `tests/test_anti_leakage.py`

**Files:**
- Create: `tests/test_anti_leakage.py`

**Interfaces:**
- Consumes: nothing (pure source-text scan).
- Produces: nothing consumed by later tasks — a standalone regression guard.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_anti_leakage.py
"""The installable package must never import or read the top-level eval/ golden set
(CLAUDE.md, ADR-004 SS6). py_attest/eval/ is the eval tooling itself and is exempt --
record.py and metrics.py legitimately take eval/golden/ paths as CLI arguments; nothing
in py_attest/review, /llm, /check, /standards, /cli, or /doctor may reference it."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "py_attest"
SCANNED_SUBPACKAGES = ("review", "llm", "check", "standards", "cli", "doctor")
PROTECTED_MARKERS = ("eval/golden", "ground_" + "truth", "expected.json", "adjudications.yml")


def test_the_core_engine_never_references_the_golden_set() -> None:
    offenders = []
    for subpackage in SCANNED_SUBPACKAGES:
        for path in (PACKAGE_ROOT / subpackage).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            hits = [marker for marker in PROTECTED_MARKERS if marker in source]
            if hits:
                offenders.append((path, hits))

    assert offenders == [], f"py_attest core engine files reference eval/golden data: {offenders}"


def test_py_attest_eval_is_the_only_subpackage_allowed_to_mention_the_golden_set() -> None:
    # Sanity check that the exemption is real and this test isn't accidentally vacuous.
    record_source = (PACKAGE_ROOT / "eval" / "record.py").read_text(encoding="utf-8")
    assert "diff_path" in record_source  # eval/ itself does take golden-set-shaped paths
```

- [ ] **Step 2: Run it to verify it fails or passes for the right reason**

Run: `uv run pytest tests/test_anti_leakage.py -v`
Expected: PASS immediately (nothing in `review`/`llm`/`check`/`standards`/`cli`/`doctor` references the golden set today) — this is a regression guard, not new behavior, so there's no red-to-green step here. Confirm it would actually catch a violation: temporarily add a throwaway line like `# eval/golden/x` to `py_attest/review/reviewer.py`, rerun, confirm FAIL, then revert.

Run: `git diff py_attest/review/reviewer.py` after the revert
Expected: no changes — confirms the temporary edit was fully reverted.

- [ ] **Step 3: Commit**

```bash
git add tests/test_anti_leakage.py
git commit -m "$(cat <<'EOF'
test: anti-leakage guard -- core engine never reads eval/golden (F0.5)

Ports Seed B's tests/quality_gate/test_anti_leakage.py pattern (CLAUDE.md,
ADR-004 SS6: "the installable package neither imports nor reads eval/").
Scoped to exclude py_attest/eval/ itself, which is the eval tooling and
legitimately takes eval/golden/ paths as CLI arguments.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 8: `tests/eval/test_golden.py` — full-pipeline replay tests

**Files:**
- Create: `tests/eval/test_golden.py`

**Interfaces:**
- Consumes: `py_attest.eval.metrics.evaluate` (Task 5); `tests/review/fixtures/streaks.patch` + `pr2_streaks_findings.json` (already committed, F0.2/F0.4 — reused here rather than duplicated, per DRY); `eval/golden/manifest.json` (Task 1).
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the tests**

```python
# tests/eval/test_golden.py
"""Two tiers (spec SS6): (1) an always-on synthetic replay proving the recorder ->
pipeline -> metrics chain works fully offline, reusing an existing review/ fixture
pair so this doesn't invent a second copy of the same data; (2) a golden-set
integration pass over the real eval/golden/ branches that skips (not fails) whatever
egress recordings don't exist yet -- honest today, becomes a real regression gate once
a human records them (spec SS6/SS8, corrected after review: neither raw nor minimized
inherits Seed A's original numbers as a hardcoded target)."""

import json
from pathlib import Path

import pytest

from py_attest.eval.metrics import evaluate

GOLDEN_DIR = Path(__file__).parents[2] / "eval" / "golden"
REVIEW_FIXTURES = Path(__file__).parents[1] / "review" / "fixtures"


def test_synthetic_streaks_recording_replays_through_the_full_pipeline(tmp_path: Path) -> None:
    branch_dir = tmp_path / "golden" / "feature" / "streaks"
    branch_dir.mkdir(parents=True)

    diff = (REVIEW_FIXTURES / "streaks.patch").read_text(encoding="utf-8")
    (branch_dir / "diff.patch").write_text(diff, encoding="utf-8")

    recording = json.loads((REVIEW_FIXTURES / "pr2_streaks_findings.json").read_text(encoding="utf-8"))
    (branch_dir / "provider_response.raw.json").write_text(json.dumps(recording), encoding="utf-8")

    expected = {
        "branch": "feature/streaks",
        "source": {
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "merge_base_sha": "a" * 40,
            "patch_sha256": "c" * 64,
        },
        "verdict": "BLOCK",
        "findings": [
            {
                "rule_id": "code-quality-6",
                "severity": "S2",
                "path": "app/streaks.py",
                "line_start": 10,
                "line_end": 10,
                "llm_reachable": True,
            },
            {
                "rule_id": "testing-3",
                "severity": "S2",
                "path": "app/streaks.py",
                "line_start": 5,
                "line_end": 5,
                "llm_reachable": True,
            },
        ],
    }
    (branch_dir / "expected.json").write_text(json.dumps(expected), encoding="utf-8")

    results = evaluate(tmp_path / "golden", "raw", require_all=False)

    assert results.skipped == []
    assert len(results.branches) == 1
    branch = results.branches[0]
    assert branch.predicted_verdict == "BLOCK"
    assert branch.expected_verdict == "BLOCK"
    # both recorded findings match their expected counterpart exactly (same
    # rule_id/path/line) -- proves validation.py + postfilter.py + policy.py all ran
    # for real on the replayed recording, not a stub.
    assert len(branch.readings["strict"].true_positives) == 2
    assert branch.readings["strict"].false_positives == []
    assert branch.readings["strict"].false_negatives == []


@pytest.mark.parametrize("egress", ["raw", "minimized"])
def test_the_real_golden_set_runs_offline_and_skips_unrecorded_branches(egress: str) -> None:
    """This is the test that keeps `uv run pytest -q tests/eval` green today, with zero
    recordings committed, and turns into the real 8-branch regression check the moment
    a human records and commits provider_response.<egress>.json for every branch --
    with no code change required here."""
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    all_branches = set(manifest["branches"])

    results = evaluate(GOLDEN_DIR, egress, require_all=False)

    scored = {b.branch for b in results.branches}
    assert scored | set(results.skipped) == all_branches
    assert scored.isdisjoint(results.skipped)

    if not results.skipped:
        # All 8 recordings exist -- print the real numbers for a human to review and
        # seal into EVAL.md (spec SS6/SS8). No hardcoded target: Seed A's original
        # 6/6-recall/87.5%-accuracy numbers were measured against a ground truth this
        # golden set no longer uses (score-validation's BLOCK reclassification, spec
        # SS2), so they cannot be this assertion's target.
        print(f"\n{egress} block recall: {results.block_recall:.1%}")
        print(f"{egress} verdict accuracy: {results.accuracy:.1%}")
        for name, reading in results.readings.items():
            print(f"{egress} {name} F1: {reading.f1:.1%}")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/eval/test_golden.py -v`
Expected: PASS — `test_synthetic_streaks_recording_replays_through_the_full_pipeline` exercises the whole pipeline offline; `test_the_real_golden_set_runs_offline_and_skips_unrecorded_branches[raw]` and `[minimized]` both pass with `results.skipped` equal to all 8 branches (no recordings committed yet).

- [ ] **Step 3: Run the entire `tests/eval` + anti-leakage suite together**

Run: `uv run pytest -q tests/eval tests/test_anti_leakage.py`
Expected: all green, matching DONE WHEN's "`uv run pytest -q tests/eval` passes offline."

- [ ] **Step 4: Run ruff**

Run: `uv run ruff check tests/eval/test_golden.py && uv run ruff format --check tests/eval/test_golden.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/eval/test_golden.py
git commit -m "$(cat <<'EOF'
eval: test_golden.py -- full-pipeline replay, offline (F0.5)

Synthetic tier reuses tests/review/fixtures/streaks.patch +
pr2_streaks_findings.json (already committed) rather than duplicating a second
copy of the same fixture pair, and proves the recorder -> pipeline -> metrics
chain works end to end. Golden-set integration tier scans the real eval/golden/
branches, skipping (not failing) whatever recordings don't exist yet -- keeps
`pytest -q tests/eval` green with zero recordings committed, and becomes the
real 8-branch regression check with no code change once a human records and
commits them.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 9: `.github/workflows/eval-live.yml`

**Files:**
- Create: `.github/workflows/eval-live.yml`
- Create: `tests/test_eval_live_workflow.py`

**Interfaces:**
- Consumes: nothing from other tasks (YAML structure only).
- Produces: nothing consumed by other tasks.

- [ ] **Step 1: Write the failing YAML-validity test**

```python
# tests/test_eval_live_workflow.py
"""eval-live.yml must be valid YAML with the shape the weekly job needs (workflow_dispatch
+ cron trigger, a raw/minimized egress matrix, no secrets available to fork PRs)."""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "eval-live.yml"


def test_eval_live_workflow_is_valid_yaml_with_the_expected_triggers() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert "workflow_dispatch" in workflow["on"]
    assert "schedule" in workflow["on"]
    assert workflow["on"]["schedule"][0]["cron"]


def test_eval_live_workflow_has_a_raw_minimized_egress_matrix() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    record_job = workflow["jobs"]["record-and-score"]

    assert set(record_job["strategy"]["matrix"]["egress"]) == {"raw", "minimized"}


def test_eval_live_workflow_needs_a_provider_key_secret() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    record_job = workflow["jobs"]["record-and-score"]
    rendered_steps = str(record_job["steps"])

    assert "OPENAI_API_KEY" in rendered_steps
    assert "secrets." in rendered_steps
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_eval_live_workflow.py -v`
Expected: FAIL — `.github/workflows/eval-live.yml` doesn't exist yet.

- [ ] **Step 3: Write the workflow**

```yaml
# .github/workflows/eval-live.yml
name: eval-live

on:
  workflow_dispatch:
  schedule:
    - cron: "0 6 * * 1" # weekly, Monday 06:00 UTC

concurrency:
  group: eval-live
  cancel-in-progress: false

jobs:
  record-and-score:
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        egress: [raw, minimized]
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5
        with:
          enable-cache: true

      - name: Sync dependencies
        run: uv sync --all-extras

      - name: Install gitleaks
        run: |
          curl -sSL -o gitleaks.tar.gz \
            https://github.com/gitleaks/gitleaks/releases/download/v8.30.1/gitleaks_8.30.1_linux_x64.tar.gz
          tar -xzf gitleaks.tar.gz gitleaks
          sudo mv gitleaks /usr/local/bin/gitleaks

      - name: Record each branch
        env:
          OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
        run: |
          for expected in eval/golden/*/*/expected.json; do
            branch_dir=$(dirname "$expected")
            branch=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['branch'])" "$expected")
            uv run python -m py_attest.eval.record \
              --diff "$branch_dir/diff.patch" \
              --provider openai \
              --egress "${{ matrix.egress }}" \
              --out "$branch_dir/provider_response.${{ matrix.egress }}.json" \
              --branch "$branch" \
              --force
          done

      - name: Compute metrics
        run: |
          uv run python -m py_attest.eval.metrics \
            --egress "${{ matrix.egress }}" \
            --require-all \
            --output "eval/metrics_${{ matrix.egress }}.md"

      - uses: actions/upload-artifact@v4
        with:
          name: eval-live-${{ matrix.egress }}
          path: |
            eval/golden/*/*/provider_response.${{ matrix.egress }}.json
            eval/metrics_${{ matrix.egress }}.md

  open-pr:
    needs: record-and-score
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: eval-live-*
          path: eval/
          merge-multiple: true
      - name: Open a PR with the updated recordings
        uses: peter-evans/create-pull-request@v6
        with:
          commit-message: "eval: weekly live recording refresh"
          title: "eval: weekly live recording refresh"
          body: |
            Automated weekly run of `.github/workflows/eval-live.yml`. A human must
            review the updated `eval/metrics_*.md` tables and, if they're accepted,
            manually update `EVAL.md`'s sealed baseline (ADR-004 §6 -- sealing a new
            baseline is a human decision, this workflow only proposes the data).
          branch: eval-live-refresh
          add-paths: |
            eval/golden/*/*/provider_response.*.json
            eval/metrics_*.md
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_eval_live_workflow.py -v`
Expected: PASS — all 3 assertions green.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/eval-live.yml tests/test_eval_live_workflow.py
git commit -m "$(cat <<'EOF'
ci: eval-live.yml -- weekly live-provider eval job (F0.5)

workflow_dispatch + weekly cron, egress: [raw, minimized] matrix, records all
8 golden branches with the real OPENAI_API_KEY secret (unavailable to fork
PRs, same no-secrets-to-forks stance as attest review itself), computes
metrics with --require-all, and opens a PR with the updated recordings for a
human to review -- sealing a new baseline into EVAL.md stays a human action
(ADR-004 SS6), this workflow only proposes the data. Ships as valid YAML;
does not and cannot run for real from this session (no key, no network).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Task 10: `EVAL.md`

**Files:**
- Create: `EVAL.md` (repo root)

**Interfaces:**
- Consumes: nothing programmatically — cites Task 1/2's golden-set shape and Task 5/6/9's CLI commands in prose.
- Produces: nothing consumed by other tasks (documentation).

- [ ] **Step 1: Write `EVAL.md`**

```markdown
# Evaluation: py-attest reviewer

The golden set is 8 fixed PRs from `student-progress-seed`, frozen by Seed B's benchmark
manifest (`../seed-b/eval/README.md`, dataset version `1.0.0`) and re-expressed in
py-attest's `rule_id` vocabulary (`eval/golden/*/expected.json`; the reconciliation from
Seed A's and Seed B's original ground truths is documented in
`docs/superpowers/specs/2026-09-02-golden-set-eval-design.md` §2). Every number in this
document must be reproducible from a committed recording — no number here was hand-typed
without a `provider_response.<egress>.json` behind it.

## Anti-leakage (ADR-004 §6)

This golden set is regression, never tuning. It is never used to choose a prompt,
threshold, rule wording, or model — those comparisons require a new sealed holdout
(F2). `tests/test_anti_leakage.py` enforces that the installable package
(`py_attest/review`, `/llm`, `/check`, `/standards`, `/cli`, `/doctor`) never imports or
reads `eval/`.

## Historical citation: Seed A's original `raw` baseline

Seed A's own `EVAL.md` (the "final" configuration: prompt v3, gpt-5-mini, degrade-not-drop
postfilter) reported, against **its own, pre-reconciliation ground truth**:

| Arm | Verdict P / R / Acc | Findings P / R / F1 (strict) |
|---|---|---|
| Seed A "final" | 85.7 / 100 / 87.5 | 69.2 / 75.0 / 72.0 |

**This is a historical citation, not the number py-attest's pipeline is measured
against.** The reconciliation in `expected.json` changed `score-validation`'s expected
verdict from APPROVE to BLOCK (its `EXTERNAL_INPUT_VALIDATION`/`code-quality-3` finding is
S2 and blocking under both Seed B's ground truth and py-attest's registry-fixed severity —
never trusted from the model, per ADR-001/CLAUDE.md), which changes the must-block set
from 6/8 to 7/8. Comparing a new run's recall against "6/6" would be comparing against a
ground truth this golden set no longer uses.

## Current baselines: `raw` and `minimized`

| Egress | Block recall | Verdict accuracy | strict F1 | adjudicated F1 | severity-exact F1 | Status |
|---|---|---|---|---|---|---|
| `raw` | — | — | — | — | — | **Pending first sealed run** |
| `minimized` | — | — | — | — | — | **Pending first sealed run** |

Both modes are measured, and sealed as baselines, symmetrically — neither inherits Seed
A's historical number as its target. To produce these tables:

1. Record all 8 branches for one egress mode with a real provider key:
   ```bash
   for expected in eval/golden/*/*/expected.json; do
     branch_dir=$(dirname "$expected")
     branch=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['branch'])" "$expected")
     uv run python -m py_attest.eval.record \
       --diff "$branch_dir/diff.patch" --provider openai --egress raw \
       --out "$branch_dir/provider_response.raw.json" --branch "$branch"
   done
   ```
   (repeat with `--egress minimized` and `.minimized.json` for the other mode)
2. Compute metrics:
   ```bash
   uv run python -m py_attest.eval.metrics --egress raw --require-all --output eval/metrics_raw.md
   uv run python -m py_attest.eval.metrics --egress minimized --require-all --output eval/metrics_minimized.md
   ```
3. A human reviews `eval/metrics_raw.md` / `eval/metrics_minimized.md`, and if accepted,
   copies the numbers into the table above — sealing a baseline is a human decision
   (ADR-004 §6), never something `metrics.py` does unattended.
4. Commit the `provider_response.*.json` recordings alongside the updated table. Future
   runs (`.github/workflows/eval-live.yml`, weekly) are then a **non-regression** check
   against this sealed number, not against Seed A's.

## Methodology: three readings, per egress mode

`py_attest/eval/metrics.py` reports three readings per egress mode (TRD §10(a): "cada
combinación necesita su fila"):

- **strict** — one-to-one match by exact `rule_id`, exact `path`, and overlapping
  `[line_start, line_end]`. No finding text (title/evidence/explanation) affects
  matching.
- **adjudicated** — `strict` plus any manual overrides in `eval/golden/adjudications.yml`
  (empty until a real run documents a specific mismatch worth crediting — see that
  file's header for the schema and rationale).
- **severity_exact** — Seed B's `SCORING-POLICY.md` "Severity treatment": a `strict`
  match with unequal severity contributes one FN (expected severity) and one FP
  (predicted severity), never a hidden TP.

Every reading also excludes `llm_reachable: false` findings from its recall denominator
— currently only `email-reminders`'s `pii-1` finding, hidden behind the secrets firewall
before any LLM call happens (TRD §9).

## Reproducing this document

`uv run pytest -q tests/eval` replays every currently-committed recording through the
full review pipeline (`reviewer.run_review`) offline — no network call, no key required.
Recording new fixtures and sealing a baseline (the tables above) requires a real provider
key and is a human action, not part of `pytest`.
```

- [ ] **Step 2: Verify the reproduction commands actually match the shipped CLIs**

Run: `uv run python -m py_attest.eval.record --help`
Run: `uv run python -m py_attest.eval.metrics --help`
Expected: both print usage matching the flags used in `EVAL.md`'s reproduction steps (`--diff`, `--provider`, `--egress`, `--out`, `--branch` for `record`; `--egress`, `--require-all`, `--output` for `metrics`). Fix any drift in `EVAL.md`'s command examples before committing.

- [ ] **Step 3: Commit**

```bash
git add EVAL.md
git commit -m "$(cat <<'EOF'
docs: EVAL.md -- methodology, reproduction steps, pending baselines (F0.5)

Seed A's original raw table is kept as a historical citation, explicitly
labeled as not the target this pipeline is measured against (score-
validation's ground-truth reconciliation, spec SS2, changed the must-block
set from 6/8 to 7/8). Both raw and minimized are documented as pending their
first sealed run, symmetrically -- sealing a baseline is a human action per
ADR-004 SS6, not something this WP's tooling does unattended.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_011MsZuwQPCXyAhTVjBFnVqx
EOF
)"
```

---

## Final verification (after all 10 tasks)

- [ ] Run: `uv sync --all-extras && uv run pytest` — full suite green, `--cov-fail-under=95` satisfied.
- [ ] Run: `uv run ruff check . && uv run ruff format --check .` — clean.
- [ ] Run: `uv run pytest -q tests/eval` — passes offline (DONE WHEN).
- [ ] Confirm `eval/golden/*/*/provider_response.*.json` are **not** present in `git status` (they're deliberately unrecorded this WP; if any exist from local experimentation, remove them before the final commit — a committed placeholder recording would silently become a fake sealed baseline).
- [ ] Report to the user (per the original task's REPORT requirement): files touched, which of the 8 branches most need a second look once real recordings land (`support-context` and `progress-percentage` — spec §2's divergence #2), and that both `raw` and `minimized` baselines are pending the user's own `record.py --provider openai` run.
