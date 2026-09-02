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
