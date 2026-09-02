# Design: golden-set eval harness (F0.5)

**Branch:** `wp/f0.5` · **Depends on:** F0.3 (merged, `9f4149b`), F0.4 (merged, `dbfd1e1`)
**Governing docs:** `docs/adr/004-seed-b-base.md` §6 (anti-leakage), `docs/trd.md` v0.3 §9, `docs/prd.md` G3, `docs/plan-cc.md` Paso 4 / P4

## 1. Problem

`py_attest/eval/metrics.py` is still Seed A's `eval_metrics.py`, byte-migrated in Paso 2 (`8daf199`) with only paths rewritten: it matches findings by `(file, leading-digit rule-section)` and knows nothing about `rule_id`, `path`/`side`/`line_start`/`line_end`, or egress mode. There is no `eval/golden/` fixture set, no recorder, and no CI job. F0.5 builds all of it: recorded fixtures for the 8 seed PRs, a rewritten `metrics.py` with three readings, a recorder CLI, the weekly live-eval workflow, and `EVAL.md`.

Two things make this WP harder than "migrate and rename": (a) the golden set's ground truth has to be re-expressed in the new `rule_id` vocabulary, and the two available sources of that ground truth — Seed A's `ground_truth.yml` and Seed B's `ground_truth.json` — disagree on some branches; (b) provider recordings need a real API key this session doesn't have, so the harness must be fully buildable and testable without ever making a network call, leaving the actual 8-branch recordings as a follow-up the user runs.

## 2. Ground truth reconciliation

`py_attest/eval/legacy_rule_ids.json` (added in F0.4) is keyed exactly to **Seed B's** rule catalog IDs (`COMMITTED_SECRET`, `LOG_PII`, ...), not to Seed A's coarse section numbers (`rule: "3"`). Seed B's `ground_truth.json` already labels the same 8 branches at `rule_id`/`path`/`line_start`/`line_end` precision. So `expected.json` is built primarily from **Seed B's ground truth, remapped through `legacy_rule_ids.json`**, not by eyeballing Seed A's one-line notes. Seed A's `ground_truth.yml` and `EVAL.md` stay the cross-check and the narrative source (they're what "raw = EVAL of A" in ADR-004 §6 refers to).

Full per-branch mapping (`seed rule_id → legacy_rule_ids.json → new rule_id`), confirmed against both `core.standards.yml` and `domain.standards.yml`:

| Branch | Seed B finding(s) | New `rule_id` | Severity (registry-fixed) | `mode` |
|---|---|---|---|---|
| `feature/lessons-pagination` | none | — | — | — |
| `feature/score-validation` | `EXTERNAL_INPUT_VALIDATION` @ `app/main.py:52` | `code-quality-3` | S2 | llm |
| `fix/mobile-sync-visibility` | `LOG_PII` @ `app/main.py:57-60` | `pii-1` | S1 | llm |
| `feature/support-context` | `LOG_PII` @ `app/main.py:37` | `pii-1` | S1 | llm |
| `feature/email-reminders` | `COMMITTED_SECRET` @ `app/notifications.py:7`; `LOG_PII` @ `:13`; `TODO_TICKET_REFERENCE` @ `:6` | `secrets-1`; `pii-1`; `code-quality-5` | S1; S1; S3 | deterministic; llm; deterministic |
| `feature/streaks` | `INCORRECT_DATA_LOGIC` @ `app/streaks.py:10`; `TESTS_EFFECTIVE` @ `:10-13` | `code-quality-6`; `testing-3` | S2; S2 | llm; llm |
| `feature/analytics-archive` | `MINOR_RETENTION_MAX_90_DAYS` @ `app/archive.py:4-8`; `SECONDARY_PII_MINIMIZATION` @ `:15-16`; `LOGIC_TEST_REQUIRED` @ `app/main.py:58` | `retention-2`; `retention-3`; `testing-2` | S1; S1; S2 | llm; llm; llm |
| `fix/progress-percentage` | `TESTS_EFFECTIVE` @ `app/main.py:38` | `testing-3` | S2 | llm |

`llm_reachable` per finding is **computed, not copied**: a `deterministic`-mode rule is always reachable (it runs in `review/deterministic.py` regardless of the secrets firewall); an `llm`-mode rule is reachable only if no `secrets-1` finding fires anywhere in that branch's diff (the firewall skips the LLM call entirely — `reviewer.py` §"Deterministic findings ... common to all three branches"). Concretely: for `email-reminders`, `secrets-1` fires, so `pii-1` (llm mode) is unreachable but `code-quality-5` (deterministic) stays reachable — this differs from Seed A's original marking, which predates the deterministic/LLM split and had marked both unreachable.

### Two resolved divergences from Seed A's ground truth (approved above)

1. **`feature/score-validation`**: Seed A's `ground_truth.yml`/`EVAL.md` frames this as APPROVE with an S3 "severity inflation" case study. Both Seed B's ground truth and the new registry fix `code-quality-3` at **S2/blocking**. `expected.json` follows the registry: **verdict BLOCK**, one `code-quality-3` finding. `EVAL.md` documents this explicitly as a consequence of "severity resolved from the registry, never the model" (CLAUDE.md, ADR-001) — not a bug, and not comparable to Seed A's narrative of this branch as a false positive.
2. **`feature/support-context`** and **`fix/progress-percentage`**: Seed A's ground truth lists 2 findings each; Seed B's lists 1 each (it treats what Seed A splits as two aspects of one root cause). `expected.json` follows Seed B (1 finding each). Both are flagged in the REPORT below as branches to sanity-check once real recordings exist — if the new prompt's output naturally wants to describe these as two findings, that's a matching-policy question (Seed B's own `SCORING-POLICY.md` "substantially equivalent root cause" language exists for exactly this), not a ground-truth error.

## 3. `eval/golden/` layout

```
eval/golden/
  manifest.json                          # dataset_version, base_sha, per-branch head_sha (+ patch_sha256, mirrored into each expected.json for a single source of truth check)
  feature/
    lessons-pagination/
      diff.patch                         # git diff --binary --full-index <base>...<head>, verified sha256 == Seed B's patch_sha256
      expected.json                      # {source: {base_sha, head_sha, merge_base_sha, patch_sha256}, verdict, findings: [...]}
      # no provider_response.*.json yet — recorded later with a real key
    score-validation/
      ...
  fix/
    mobile-sync-visibility/
      ...
  adjudications.yml                      # empty scaffold; schema documented, populated once a real run needs one
```

Branch dirs mirror the branch name (`feature/`, `fix/` subdirectories), same convention Seed A's `eval/runs_final/` already uses. `expected.json` finding shape matches the schema_version 3 report's finding shape minus provider-only fields (`confidence`, `evidence_verified`, `title`, `evidence`, `explanation`, `suggested_fix`, `fingerprint` don't exist in ground truth):

```jsonc
{
  "source": {"base_sha": "fbd4e09643ea61027165fdbfafbb2c3e5edd0153", "head_sha": "d5ecfb...", "merge_base_sha": "fbd4e09...", "patch_sha256": "d406de69..."},
  "verdict": "BLOCK",
  "findings": [
    {"rule_id": "retention-2", "severity": "S1", "path": "app/archive.py", "line_start": 4, "line_end": 8, "llm_reachable": true},
    {"rule_id": "retention-3", "severity": "S1", "path": "app/archive.py", "line_start": 15, "line_end": 16, "llm_reachable": true},
    {"rule_id": "testing-2", "severity": "S2", "path": "app/main.py", "line_start": 58, "line_end": 58, "llm_reachable": true}
  ]
}
```

`diff.patch` and `expected.json` for all 8 branches are produced and committed in this WP (no network required — confirmed by reproducing `feature/analytics-archive`'s hash locally, matches Seed B's frozen `d406de69...` exactly). `provider_response.raw.json` / `provider_response.minimized.json` are **not** produced in this WP; see §7.

## 4. `py_attest/eval/record.py`

```
attest-eval-record --branch feature/streaks --provider openai --egress raw \
    --diff eval/golden/feature/streaks/diff.patch \
    --out eval/golden/feature/streaks/provider_response.raw.json
```

Thin wrapper around the existing pipeline pieces (`review/egress`, `llm/registry.load_provider`, `llm/policy.run_with_policy`) — **not** `reviewer.run_review`, because recording must call the provider exactly once and write only `ProviderResponse.raw_json` (the model's raw structured output), not a full assembled report. Reuses `context_pack.render_rules_block` + the registry + the egress builder (raw or minimized) to build the exact `ProviderRequest` `reviewer.py` would build, then calls the resolved provider and writes `raw_json` verbatim to `--out`. Refuses to overwrite an existing recording without `--force` (a recording is a sealed artifact once committed — accidental re-recording would silently change a baseline).

`--provider fake` (pointed at a fixture file via `--fake-response`) is how this WP's own tests exercise `record.py`'s CLI mechanics — argument parsing, output path handling, `--force` refusal — without a key. The user runs it for real per branch × egress mode (16 calls total) once F0.5 lands.

## 5. `py_attest/eval/metrics.py` rewrite

Replaces the Seed-A-shaped matcher entirely (no more `findings_match` on `(file, rule-section-prefix)`). New matching keys off the schema-3 finding shape: `rule_id` (exact) + `path` (exact) + line-range overlap with the expected `[line_start, line_end]` (adapting Seed B's `SCORING-POLICY.md` §"One-to-one finding matching" to line ranges instead of Seed B's raw diff-anchor rules, since our findings already carry `line_start`/`line_end`).

Three readings, computed from the same match set:

- **`strict`**: detection-only one-to-one match (rule_id + path + line overlap), severity ignored. This is what today's file effectively does, minus the old file/rule-section keying.
- **`adjudicated`**: `strict` plus manual overrides from `eval/golden/adjudications.yml` — a list of `{branch, expected: {rule_id, path}, predicted: {rule_id, path}, reason}` entries that credit a specific documented mismatch as a match. **Starts empty.** Seed A's own two adjudications (streaks off-by-one filed under the wrong section; progress-percentage test-enshrinement filed under the wrong section) were about a run this WP has no equivalent recording for yet under the new prompt/schema — they aren't ported mechanically. The mechanism ships with unit tests using synthetic cases; real entries get added once a real run needs one (see §7's REPORT obligation for future sessions).
- **`severity_exact`** (Seed B's reading, `SCORING-POLICY.md` §"Severity treatment"): a `strict` match additionally requires equal severity to count as TP; a rule/path/line match with unequal severity is one FN (expected severity) + one FP (predicted severity), never a hidden TP. Since expected severity is always the registry's fixed severity, this reading only differs from `strict` when a `severity_policy` (contextual) rule's actual classification differs, or (pre-registry-fix world) when a model mis-grades — worth keeping as its own column because it's the more rigorous of the two upstream policies.

`evaluate()` gains an `egress` axis: `render_markdown` produces one table block per (egress mode × reading), consistent with TRD §10(a) "cada combinación necesita su fila en EVAL.md." Loading shifts from Seed A's `prs.json`/`runs_root` PR-artifact lookup (GitHub-PR-shaped, doesn't apply here) to reading `eval/golden/<branch>/provider_response.<egress>.json` directly and replaying it through `reviewer.run_review(..., provider="fake", fake_response=<path>, egress=<mode>)` to get a real schema-3 report — this is what "replays recordings through the full pipeline" means: the recording only stands in for the network call, everything downstream (validation, postfilter, policy, report) runs for real.

## 6. Tests

- **`tests/eval/test_metrics.py`** (rewrite): unit tests for the new matcher and all three readings against small synthetic fixtures (2-3 branches, hand-built) — never touches `eval/golden/`. Covers: rule_id+path+line-range matching, non-overlapping ranges don't match, `llm_reachable: false` exclusion, adjudication override changes `adjudicated` but not `strict`, severity mismatch produces FN+FP under `severity_exact` but TP under `strict`.
- **`tests/eval/test_record.py`** (new): drives `record.py`'s CLI with `--provider fake`, asserts output path/content, asserts `--force` refusal on an existing file, asserts a bad `--egress` value fails cleanly.
- **`tests/eval/test_golden.py`** (new): two tiers.
  1. Always-on: a couple of synthetic branches (own fixtures under `tests/eval/fixtures/`, not `eval/golden/`) recorded with the fake provider, replayed through `reviewer.run_review`, scored with all three readings — proves the recorder → pipeline → metrics chain works end to end, fully offline.
  2. Golden-set integration: iterates the real `eval/golden/*/` directories. For each branch × egress mode, if `provider_response.<egress>.json` exists, replay it and include it in that mode's aggregate; if absent, skip it with a clear reason (`pytest.skip`, not a failure). Once **all 8** recordings for a given egress mode are present, a dedicated test computes that mode's metrics against the *reconciled* `expected.json` (§2 — not Seed A's original ground truth) and prints the table; it does not assert a hardcoded target for either mode. **Neither `raw` nor `minimized` has a pre-existing sealed baseline against the reconciled ground truth** — `score-validation`'s BLOCK reclassification (§2) changed the must-block set from 6/8 to 7/8, so Seed A's 6/6-recall, 87.5%-accuracy numbers were measured against a ground truth this WP no longer uses and cannot be the pytest target. The first complete real run under the reconciled ground truth is what a human reviews and seals into `EVAL.md`, for *both* egress modes symmetrically (F0.5 doesn't auto-write that; ADR-004 §6 requires the "no empeorar" comparison to be against a value a human has looked at). Future regression runs (the weekly `eval-live.yml` job, §7) then assert non-regression against that sealed number, not against Seed A's.
- **`tests/test_anti_leakage.py`** (new, package-root — the currently-nonexistent top-level `tests/` sibling to `tests/eval/`, matching CLAUDE.md's "the installable package neither imports nor reads eval/"): ports Seed B's pattern — scans `py_attest/**/*.py` source text for `eval/`, `ground_truth`, ADR-file markers; asserts none appear. This is about `py_attest/` (the installable package), not `eval/` itself (which is allowed to import `py_attest` freely — `record.py` and `metrics.py` do).

## 7. `.github/workflows/eval-live.yml`

`workflow_dispatch` (manual) + weekly `schedule: cron`. Matrix over `egress: [raw, minimized]`. Needs `OPENAI_API_KEY` (or the configured provider's secret) — not available to fork PRs, consistent with `attest review`'s own no-secrets-to-forks stance (ADR-004 §4). Steps: checkout, `uv sync --all-extras`, install gitleaks (same pin as `ci.yml`), run `record.py` for all 8 branches × the matrix egress mode, run `metrics.py` to regenerate `EVAL.md`'s tables, open a PR with the updated recordings + `EVAL.md` (`peter-evans/create-pull-request` or `gh pr create` from a bot branch — mechanical, not a design decision). This WP ships the workflow file (valid YAML, checked with `yaml.safe_load` in a test) but does not — cannot — trigger a real run.

## 8. `EVAL.md`

Repo root (Seed A's convention). Contents: (a) Seed A's sealed `raw` table (6/6 block recall, 87.5% verdict accuracy, F1 72 strict), reproduced verbatim, labeled **historical citation, not the target this system is measured against** — it was measured against Seed A's pre-reconciliation ground truth (§2's `score-validation` divergence changed the must-block set from 6/8 to 7/8), so it documents where the golden set came from, not a number the new pipeline has to reproduce; (b) a `raw` table and a `minimized` table for the reconciled ground truth, both marked "pending first sealed run" until the user records all 8 branches for that mode and a human seals the result — symmetric treatment, neither mode inherits Seed A's number as its bar; (c) methodology section explaining the three readings, the egress axis, and why raw's historical and reconciled numbers aren't comparable; (d) explicit anti-leakage rule restated: comparing prompts/rules/models requires a new sealed holdout (F2), this golden set is regression-only; (e) reproduction instructions (`uv run python -m py_attest.eval.record ...` then `uv run python -m py_attest.eval.metrics ...`).

## Open questions for the REPORT (not blocking this WP)

- `support-context` / `progress-percentage`: once real recordings exist, check whether the model naturally produces 1 or 2 findings for these and whether Seed B's 1-finding ground truth or Seed A's 2-finding framing is the better fit — may need an `adjudications.yml` entry either way.
- `minimized`'s baseline is not established until someone runs `record.py --egress minimized` for real and a human seals the resulting number into `EVAL.md` — that sealing step is explicitly a human action per ADR-004 §6, not something `metrics.py` should do unattended.
