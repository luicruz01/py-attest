# Design: `standards/` subsystem + `review/` rule_id validation (F0.4)

**Branch:** `wp/f0.4` · **Depends on:** F0.2 (merged) · **Coordinates with:** F0.3 (`wp/f0.3`, "4a"), merge order per `docs/plan-cc.md` §3 is 3b (this WP) → 3a (F0.3) → 3c
**Governing docs:** `docs/adr/001-standards-yml.md` (+ its ADR-004 amendment), `docs/adr/004-seed-b-base.md` §2(a)/§7, `docs/trd.md` v0.3 §3.1/§4.3/§5 rows 6-7

## 1. Problem

`py_attest/review/` currently trusts the LLM's own `severity` and free-text `rule` label (`review/models.py` `REVIEW_SCHEMA`), and locates findings by re-anchoring a quoted evidence fragment against the diff's added lines (`review/postfilter.py`). ADR-001 requires severity to be resolved from a validated rule registry, never trusted from model output, and ADR-004 rescues Seed B's `rule_id`/`side`/line-range contract to replace prose-based location. Neither `standards.yml` nor its registry/build/lint tooling exist yet.

## 2. `py_attest/standards/` subsystem

### 2.1 `schema.json`

JSON Schema for a `standards.yml` document:

```yaml
version: 1
sections:
  - slug: kebab-case
    title: string
    rules:
      - id: "^[a-z0-9]+(-[a-z0-9]+)*-[0-9]+$"   # e.g. code-quality-3, testing-2, pii-1
        title: string
        severity: S1 | S2 | S3            # exactly one of severity / severity_policy
        severity_policy: {object}         # contextual — provider can't classify it
        mode: deterministic | llm | human
        check: string                     # REQUIRED iff mode == deterministic
        description: string               # human-readable; injected into the LLM prompt when mode == llm
        rationale: string                 # optional
        evidence_required: string         # optional (★ Seed B)
        non_examples: [string]            # optional (★ Seed B)
```

`registry.py` validates every loaded file against this schema before building the `Registry`.

### 2.2 `registry.py`

- `load_registry(core_path, domain_path) -> Registry`: loads and schema-validates both files, merges rules. Duplicate `id` across core+domain → `RegistryError` (global uniqueness, per ADR-001).
- `Registry` API: `__contains__(rule_id)`, `rule(rule_id) -> Rule`, `fixed_severity(rule_id) -> Severity | None` (`None` means contextual), `is_contextual(rule_id) -> bool`, `llm_rules() -> list[Rule]` (`mode == "llm"`, for prompt injection), `deterministic_rules() -> list[Rule]` (for `lint.py`'s check-id cross-reference).
- Unknown `rule_id` lookups raise `RegistryError` (callers — `validation.py` — treat this as "not a member," not a crash; see §4).

### 2.3 `build.py`

Jinja-renders core+domain sections (core sections first, in file order; domain sections after) into `TEAM-STANDARDS.md`, with a header stating it's generated and naming `domain.standards.yml` as the file to edit instead. `build(core, domain, output_path)` writes the file. `build(..., check=True)` renders to memory and diffs against the committed `output_path`; **on drift, raises `StandardsDriftError`** (see §6 exit codes) instead of writing.

The generated Markdown must read like Seed A's hand-written `TEAM-STANDARDS.md` (prose per rule under its section heading, plus the S1/S2/S3 severity legend) — not a YAML dump.

### 2.4 `lint.py`

`lint(core, domain) -> list[LintError]`:
- schema validation (via `registry.py`'s loader, which already schema-validates — `lint.py` wraps this to collect *all* errors rather than failing on the first);
- duplicate id (core vs domain, and within either file);
- every `mode: deterministic` rule's `check` is a member of a static known-check-id constant. Doctor doesn't exist yet (out of scope, per the work package's DO NOT), so this list is grounded directly in what `py_attest/check/runner.py` already runs, plus the one check F0.3 is adding in `review/deterministic.py`:
  ```python
  KNOWN_CHECK_IDS = {"ruff-check", "ruff-format", "coverage-gate", "gitleaks", "todo-ticket-ref"}
  ```
  (`ruff-check`/`ruff-format`/`coverage-gate`/`gitleaks` back `code-quality-1`/`code-quality-2`/`testing-1`/`secrets-1` respectively, already hardcoded in `check/runner.py`; `todo-ticket-ref` backs `code-quality-5`, which F0.3's `review/deterministic.py` implements — see §5.)

Any lint failure → CLI exits 64 (usage/config error, not a review verdict — see §6).

### 2.5 `migrate_review_rules.py`

One-time-ish generator, not wired into the CLI. Reads Seed B's `review_rules.json` (12 rules) and Seed A's `TEAM-STANDARDS.md` prose, and writes:
- `py_attest/standards/defaults/core.standards.yml` — sections `code-quality`, `testing`, `secrets`, from Seed A §1/§2/§5, enriched with matching B rules' `evidence_required`/`non_examples`.
- `py_attest/standards/defaults/domain.standards.yml` — sections `pii`, `retention`, from Seed A §3/§4, as the commented example (richer than today's single-rule stub).
- `py_attest/eval/legacy_rule_ids.json` — the B-string → new-id table (§3 below), for reading historical eval artifacts recorded with Seed B's IDs.

To avoid a CI dependency on the `../seed-b` worktree, a frozen copy of `review_rules.json` is committed as a test fixture (e.g. `tests/standards/fixtures/seed_b_review_rules.json`), and a regression test runs the migration transform against that fixture and asserts the output matches the committed `defaults/*.yml` — so drift in the migration logic is caught even without Seed B checked out.

## 3. Rule ID table

`check/runner.py` (already merged) hardcodes `rule: "code-quality-1"`/`"code-quality-2"`/`"testing-1"`/`"secrets-1"` with fixed severities S3/S3/S2/S1 — these are load-bearing (tests assert on them) and become the registry's `deterministic` entries unchanged. This also matches ADR-001's own worked example (`testing-1` deterministic/`coverage-gate`, `testing-2` llm) exactly.

### `core.standards.yml`

| id | title | severity | mode | check / source |
|---|---|---|---|---|
| code-quality-1 | ruff check passes | S3 | deterministic | `ruff-check` — already in check/runner.py |
| code-quality-2 | ruff format passes | S3 | deterministic | `ruff-format` — already in check/runner.py |
| code-quality-3 | External input validated | S2 | llm | B `EXTERNAL_INPUT_VALIDATION` (per ADR-001's ADR-004 amendment, verbatim example) |
| code-quality-4 | Errors handled explicitly | S2 | llm | B `EXPLICIT_ERROR_HANDLING` |
| code-quality-5 | TODOs need a ticket ref | S3 | **deterministic** | `todo-ticket-ref` — F0.3's `review/deterministic.py`; B `TODO_TICKET_REFERENCE` |
| code-quality-6 | Logic blocking incorrect data | S2 | llm | B `INCORRECT_DATA_LOGIC` |
| testing-1 | Untested core logic fails CI | S2 | deterministic | `coverage-gate` — already in check/runner.py |
| testing-2 | Logic changes need a failing-on-regression test | S2 | llm | B `LOGIC_TEST_REQUIRED` |
| testing-3 | Tests must be regression-sensitive (not trivial) | S2 | llm | B `TESTS_EFFECTIVE` |
| secrets-1 | No committed secrets | S1 | deterministic | `gitleaks` — check/runner.py's tree scan AND review's diff-scoped firewall (`secrets_gate.py`, currently `"5-secrets"`) share this one id |

### `domain.standards.yml` (commented example)

| id | title | severity | source |
|---|---|---|---|
| pii-1 | PII must not reach logs | S1 | B `LOG_PII` |
| pii-2 | Minors' data egress needs minimization + legal basis | S1 | B `MINOR_DATA_EGRESS` |
| retention-1 | Every dataset declares a retention category | **contextual** (`severity_policy`) | B `DATASET_RETENTION_DECLARED` — the `requires_human_classification=true` fixture |
| retention-2 | Minors' data ≤ 90 days unless legal basis documented | S1 | B `MINOR_RETENTION_MAX_90_DAYS` |
| retention-3 | Secondary PII copies need purpose + retention + minimization | S1 | B `SECONDARY_PII_MINIMIZATION` |

`py_attest/eval/legacy_rule_ids.json` records all 12 B-string → new-id mappings (the 10 above plus `COMMITTED_SECRET` → `secrets-1`; every B rule maps to exactly one new id).

Separately, already-migrated Seed A tests use ad-hoc placeholder strings (`"3-PII-logging"`, `"5-secrets"`, `"1-code-quality"`, `"2-testing"`, `"6-review-severity"`) that get updated in place to real ids from this table during implementation — mechanical, not a new design decision. Every changed test/fixture is listed in the final report.

## 4. `review/models.py` + new `review/validation.py`

### 4.1 LLM output schema (`review/models.py`)

The model no longer declares its own severity or a free-text rule label. `REVIEW_SCHEMA`'s finding properties become:

- **Dropped:** `rule`, `severity`, `file`, `line`.
- **Added:** `rule_id` (string — validated against the registry *after* schema validation, not as a JSON-Schema enum: `allowed_rule_ids` travels as prompt content per Seed B's actual approach, so `llm/providers/openai.py` doesn't need registry awareness), `path`, `side` (`"old"` | `"new"`), `line_start`, `line_end` (positive ints, `line_end >= line_start`, replacing single nullable `line`).
- **Unchanged:** `title`, `evidence`, `explanation`, `suggested_fix`, `confidence`.

**Behavior change, deliberate:** today's schema allows `line: null` for file-level findings, and it's actively used (`tests/review/test_models.py`'s null-line tests, `test_postfilter.py`'s file-level dedup tests, `test_reviewer.py:600`'s JSON-report assertion). `line_start`/`line_end` are now always required — every finding must anchor to a real line range within the changed lines for its declared side, no null escape hatch. This matches Seed B's contract and what `reviewer_v3.md` already instructs the model to do ("quote the closest added line being indicted" even for absence-findings — e.g. cite the new function/class definition instead of "the whole file"). All three test locations above need updating as part of this WP, not just id renames: the null-line assertions become "an absent line_start/line_end is a schema validation failure," and the file-level dedup test needs a real (path, side, line) fixture instead of `line=None`.

This matches the TRD §4.3 report schema's finding shape directly, so `report.py`'s `_finding_v3` translation shrinks to near-identity for LLM-origin findings.

**Scope refinement, found while planning:** "no null" above is scoped to diff-anchored findings (the LLM schema, and `secrets_gate.py`'s normal diff-firewall path once it's updated to the canonical shape — §5.3/§7). It does **not** extend to `reviewer.py`'s pre-existing `_blocked_review(..., anchor_to_diff=False)` case (`test_reviewer.py:598-604`): a secret found in `context_files`/`--description` isn't in the diff's coordinate system at all, so it has no `side` to assign — this is structurally different from a model being vague about which line in a real diff-scoped issue. That one narrow case keeps `path="<review context: context_files or --description>"`, `side=None`, `line_start=None`, `line_end=None` at the report-output level, unchanged from today. Every other diff-scoped finding requires real values.

No pydantic. Existing stdlib dict + manual validation, matching every other module in `review/` (TRD §3.2 explicitly defers this choice to F0.4; introducing pydantic now would mean dict↔model conversions at every existing boundary in `postfilter`/`policy`/`report` for no behavior benefit).

### 4.2 `review/validation.py` (new)

Given schema-valid raw findings + the loaded `Registry` + a per-side changed-line index built from the diff (same shape as Seed B's `Patch.line_indexes`; a new small function in this module, since it has no other consumer today):

- `rule_id` not in registry → invalid. **Narrowed by the citable set:** the registry membership check alone isn't enough — a `rule_id` must also satisfy `registry.rule(rule_id).mode == "llm"`, since `context_pack.render_rules_block` only injects `registry.llm_rules()` into the model's `<review-rules>` block; a deterministic-mode id (e.g. `secrets-1`) is a real registry member the model was never shown, so citing it is equally unverifiable and is rejected with the same `"unknown_rule_id"` reason.
- `[line_start, line_end]` not entirely within the changed lines for `(path, side)` → invalid. This **replaces** `postfilter.py`'s evidence-text-fragment re-anchoring (`_evidence_line`/`_trusted_short_evidence_line`) for LLM findings — no fallback to the old mechanism; keeping both would need reconciliation logic for two competing ways to locate a finding, for no real gain now that the model declares its location explicitly.
- A valid finding's severity is resolved via `registry.fixed_severity(rule_id)`; if `registry.is_contextual(rule_id)`, `severity = None` and `requires_human_classification = True`. The resolved finding's `evidence_verified: True` certifies only that this rule_id + line-range location was validated — it does **not** mean the quoted `evidence` text was matched against the diff's content (that comparison doesn't happen anywhere in this module).

`Config.evidence_policy`:
- **`degrade`** (default): invalid findings → `filtered_out` (visible, `reason: "unknown_rule_id"` or `"range_not_in_changed_lines"`); valid findings pass through with resolved severity. `review_complete` stays `True`. This preserves today's "evidence with unresolvable location survives visibly" philosophy, just with a crisper verification mechanism.
- **`fail_closed`**: any invalid finding invalidates the **entire** response — `validated_findings = []` for that LLM call (none of that response's findings are trusted, not even the individually-valid ones), `review_complete = False`.

**Audit trail under `fail_closed`:** the discarded findings do not appear in `filtered_out` — per TRD §4.3's own schema comment, that field is `degrade`-only ("`filtered_out` ... solo con evidence_policy=degrade"), and echoing an untrusted response's content into a structured, machine-parsed report field cuts against the whole point of `fail_closed` (nothing about that response is trusted enough to persist, not even which rule_ids it cited). What *is* recorded: `reviewer.py` sets `review["note"]` (the existing mechanism `_blocked_review` already uses for the secret-firewall case, rendered in both the JSON `note` field and the Markdown report's `> **{note}**` line) to a short counts-only message — e.g. `"LLM review invalidated: 2 of 5 findings failed validation (unknown_rule_id/range_not_in_changed_lines); response discarded (fail_closed)."` Counts and failure-reason categories only, never the discarded findings' `rule_id`/`title`/`evidence` content.

**Invariant (load-bearing for §5.3's policy design):** whenever `validation.py` returns `review_complete = False`, it must also return zero findings for that LLM call. `review_complete = False` only ever originates here (technical failures like a missing gitleaks binary already raise `InconclusiveError` directly, bypassing this path entirely); under `degrade`, `review_complete` is always `True`. This is what lets `policy.verdict()` treat "BLOCK present" and "review incomplete" as never being caused by the *same* untrustworthy source — see §5.3.

## 5. `policy.py` / `postfilter.py` / `reviewer.py` / `context_pack.py` / prompt

### 5.1 `policy.py`

`Verdict` gains `"INCONCLUSIVE"` (TRD §4.3 already lists it as a valid report verdict, exit code 4). `TRUST_POLICY_V1` is unchanged. Contextual findings (`severity is None`, `requires_human_classification=True`) bypass the table — forced to `("COMMENT", 0)`, never BLOCK on their own (ADR-004 §7).

```python
def verdict(findings, review_complete: bool = True) -> VerdictResult:
    outcomes = (
        ("COMMENT", 0) if finding.get("requires_human_classification")
        else TRUST_POLICY_V1[(finding["severity"], finding["confidence"])]
        for finding in findings
    )
    best = max(outcomes, key=lambda o: o[1], default=APPROVE_RESULT)
    if best[0] == "BLOCK":
        return best  # trusted S1/S2 wins over an incomplete review (Seed B decide() precedence)
    if not review_complete:
        return ("INCONCLUSIVE", 4)
    return best
```

This relies on §4.2's invariant: a `BLOCK` reaching this function while `review_complete=False` can only be deterministic-origin (secrets_gate / `review/deterministic.py`), never an untrusted LLM finding, because `validation.py` empties the LLM contribution whenever it sets `review_complete=False`. No `source`/provenance field is needed on findings for this to be safe — the guarantee lives in `validation.py`'s contract, not in `verdict()`'s inputs. Both files get an explicit comment stating this so it doesn't rot silently if either side changes independently.

`check/runner.py` keeps calling `verdict(findings)` unchanged (default `review_complete=True`).

### 5.2 `postfilter.py`

Drops `_evidence_line`/`_trusted_short_evidence_line` (superseded by `validation.py`). Keeps `files_in_diff` (still used by `secrets_gate.py`). The duplicate-merge logic is generalized into a single function:

```python
def merge_findings(findings: list[dict]) -> list[dict]:
    """Dedup by (rule_id, path, side, line_start, line_end); on a tie, the first-seen wins."""
```

One list, not Seed B's two-list `_deduplicate(deterministic, provider)` API — the existing tie-break already keeps the *first-seen* item on equal strength, so "deterministic findings always win a tie against an LLM duplicate" falls out for free as long as deterministic findings are placed first in the input list. This is the seam F0.3 uses (§5.3).

### 5.3 `reviewer.py`

New steps in `run_review()`:

1. Load `Registry` from `config.standards`, lazily inside the `else` branch (the one that actually builds context and calls the LLM) rather than unconditionally at the top — the `no_llm`/secret-firewall-blocked branches never need a registry, and loading it unconditionally would require every existing reviewer test (most of which use `tmp_path` or py-attest's own repo root as `repo_root`, neither of which has a `core.standards.yml`/`domain.standards.yml` today — py-attest doesn't self-host yet, §8) to grow standards.yml fixture boilerplate for no behavioral reason. **Found while planning, refining this section:** when `repo_root/config.standards.core` (or `.domain`) doesn't exist, fall back to the packaged `py_attest/standards/defaults/{core,domain}.standards.yml` — this is what makes `attest review` work out of the box on a repo that hasn't run `attest new`/`attest upgrade` yet, and is what keeps existing tests passing without per-test fixture setup. A file that exists but fails to parse/validate still raises `InconclusiveError` (exit 4) — never silently degrade against broken rules; the fallback is only for "not present," not for "present but broken."
2. Build the `<review-rules>` block from `registry.llm_rules()`, pass into `context_pack.build_context()`.
3. **Deterministic-findings seam (for F0.3's `review/deterministic.py`, not implemented on this branch):** compute `deterministic_findings` once, immediately after `diff`/`repo_root` are available — i.e. right before the existing `secret_findings = findings_for_diff(diff, repo_root)` call. `run_review()`'s branches (`_blocked_review` on a firewall hit, `filter_findings` on `no_llm`, `filter_findings` on a completed LLM call) each set `review["findings"]` independently; regardless of which branch ran, **immediately before** the existing `verdict_name, exit_code = verdict(review["findings"])` call, do:
   ```python
   review["findings"] = merge_findings(deterministic_findings + review["findings"])
   ```
   This branch does not exist on `wp/f0.4` (there is no `deterministic_findings` producer yet), so this WP does not add the call — only `merge_findings` (§5.2) and this exact insertion point, documented here for F0.3 to wire in on rebase. **Rebase instruction for F0.3:** switch `review/deterministic.py`'s finding shape from `{rule, severity, file, line, title, evidence, explanation, suggested_fix, confidence}` to `{rule_id, path, side, line_start, line_end, title, evidence, explanation, suggested_fix, confidence, severity, requires_human_classification, evidence_verified}`. Concretely: `rule` → `rule_id` (the TODO-without-ticket rule is now `code-quality-5`, `mode: deterministic`, `check: todo-ticket-ref` — coordinate naming if you'd chosen differently); `file` → `path`; single `line` → `side` (both of your checks scan added lines, so this is almost certainly always `"new"`) + `line_start`/`line_end` (both = the old `line` for a one-line finding); `severity` — resolve via `registry.fixed_severity(rule_id)` rather than a local constant, for consistency with the rest of `review/`; `requires_human_classification=False` (neither check targets a contextual rule); `evidence_verified=True` (deterministic findings are evidence by construction). If the high-confidence-secrets-in-added-lines check is a separate detector from `secrets_gate.py`'s gitleaks-diff scan, it should still cite `rule_id: "secrets-1"` — one id per violation type regardless of detection mechanism, same principle as check/runner.py's tree scan sharing `secrets-1` with the diff firewall.
4. After schema-validating the raw LLM response (`models.py`), run it through `validation.py` → `(validated_findings, filtered_out, review_complete)`.
5. Dedup via `postfilter.merge_findings`.
6. `policy.verdict(findings, review_complete)`.

### 5.4 `context_pack.py`

New `render_rules_block(rules: Sequence[Rule]) -> str` helper + optional `rules_block: str | None` param on `build_context()`, inserted as a `<review-rules>` tagged section (data, same pattern as `<reference>`/`<unified-diff>`) listing each `mode: llm` rule's id/title/description/`evidence_required`/`non_examples`.

### 5.5 Prompt

`reviewer_v3.md` only (**not** `code_review_v2.txt` — that belongs entirely to F0.3/`egress=minimized`; porting it now would duplicate F0.3's work and risk a merge conflict when they implement `egress/minimized.py`). Changes: stop asking for a free-text `rule` label + self-declared `severity`; ask the model to cite `rule_id` from the provided `<review-rules>` block, and `side` + `line_start`/`line_end` instead of `line`. Severity assignment is no longer the model's job.

## 6. CLI wiring and exit codes

`attest review` gains `--evidence-policy [degrade|fail_closed]`, overriding `config.evidence_policy`, for parity with the existing `--egress`/`--provider`/`--prompt-version` overrides (`Config` fields the CLI already lets you override per-invocation). The work package's own DONE WHEN text refers to it as a flag (`--evidence-policy degrade` / `fail_closed`), and today only the `pyproject.toml`/`Config` path exists.

`attest standards build [--check]` / `attest standards lint` read paths from `config.standards`, matching every other command's pattern.

- `lint` failure → `click.UsageError` → **exit 64** (config/usage error, same class as `Config`'s unknown-key rejection — not a review verdict).
- `build --check` drift → a new `StandardsDriftError` (mapped in `main.py`'s `exit_code_for`) → **exit 2**. This exit 2 is **not** accompanied by a schema-v3 JSON report (no `stage: "review"`, no `verdict: "BLOCK"` payload) — it's a plain CLI failure. A one-line note is added to `docs/trd.md` (near where `attest standards build|lint` is described) making this explicit, so nothing downstream assumes exit 2 always implies that report shape.

`docs/trd.md` §5 row 6 already updated (this session, ahead of implementation) to match §4.3's binary `filtered_out` mechanism instead of the retired text-anchoring "confidence=low" language — was inconsistent with its own §4.3 before this fix.

## 7. Out of scope for this WP (explicit boundaries, not silent gaps)

- **`code_review_v2.txt`** and anything under `review/egress/` — F0.3.
- **`review/deterministic.py`** itself — F0.3; this WP only prepares the seam (§5.3) and `merge_findings` (§5.2).
- **`check/runner.py`** stays on its current `rule`/`file`/`line` shape permanently for this WP. It's tree-scoped (no diff, so no `side` concept applies), and its JSON output is not schema-v3 / never flows through `build_json_report` or the registry's severity resolution. This is a deliberate, stated design boundary — not a temporary gap — though nothing here prevents a future WP from migrating it if `check/` ever wants registry-resolved severity.
- **`doctor/`** — not implemented (per this WP's DO NOT); `lint.py`'s known-check-id list is a static constant until it lands.

## 8. Testing

- Fixtures of invalid `standards.yml` (duplicate id, both `severity` and `severity_policy`, `deterministic` without `check`, unknown `check`, bad `id` pattern) → named lint errors.
- `migrate_review_rules.py` regression test against the committed `tests/standards/fixtures/seed_b_review_rules.json` copy.
- Contextual rule fixture (`retention-1`) → COMMENT with `requires_human_classification=true`.
- `--evidence-policy degrade`: a finding with an unknown `rule_id` or a range outside the changed lines for its declared side goes to `filtered_out` with its `reason` — it does **not** stay in `findings` at a degraded confidence. This is a binary outcome (kept as validated, or filtered out), not the old text-anchoring mechanism's three-way "verified / re-anchored / confidence=low" spectrum, which the line-range check retires. `fail_closed` on the same input yields INCONCLUSIVE (§4.2's whole-response invalidation).
- Seed A's golden fixtures (`streaks.patch` etc.) still produce 6/6 BLOCK offline with `rule_id`-shaped findings.
- Every already-migrated Seed A test file using the old `rule`/`file`/`line` shape (`tests/review/test_models.py`, `test_postfilter.py`, `test_reviewer.py`, `test_secrets_gate.py`, and the `tests/review/fixtures/*.json` finding fixtures) is updated to the new shape and real rule ids from §3's table, including the file-level → always-anchored behavior change in §4.1 (null-line tests in `test_models.py`/`test_postfilter.py`, and the JSON-report assertion at `test_reviewer.py:600`).
- `attest standards lint`/`build --check` exercised against `py_attest/standards/defaults/{core,domain}.standards.yml` directly (not through a self-hosted repo — py-attest doesn't self-host yet, that's F1.3).

## 9. Report deliverables (per the work package's REPORT section)

- Files touched/added.
- The legacy → new rule_id table (§3), including the full B-string mapping written to `py_attest/eval/legacy_rule_ids.json`.
- Every Seed-A ad-hoc test-fixture string → real rule_id mapping applied during implementation.
- Prompt diff for `reviewer_v3.md`.
- Open questions, if any surface during implementation.
