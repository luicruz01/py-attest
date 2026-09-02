# Evaluation: AI Quality Gate

The 8 seed PRs are the golden set. The reviewer is treated as a system to be measured, not assumed: every number in this document is reproducible with `make eval-run VERSION=final PROMPT=v3 && make eval VERSION=final`, and every claim points at a committed artifact.

## Ground truth

Labeled before any reviewer run (`eval/ground_truth.yml`): per branch, the expected verdict and the expected findings (standard section, severity, file). Two labels on email-reminders are marked `llm_reachable: false`: they sit behind the secrets firewall (DECISIONS #3), which blocks that PR before any LLM call, so no semantic reviewer can be graded on them. They are excluded from LLM denominators and reported separately.

| Branch | Expected | Expected findings | Frozen gate (local and CI agree) |
|---|---|---|---|
| lessons-pagination | APPROVE | none | APPROVE. The true negative: the gate stays quiet on a clean PR |
| score-validation | APPROVE | §1 S3: `int(score)` raises an unhandled 500 on non-numeric input | BLOCK. The documented false positive: real issue found, severity inflated S3 to S2 |
| mobile-sync-visibility | BLOCK | §3 S1: full_name and email logged, bypassing `redact()` | BLOCK, S1 verified, 1 of 1 findings |
| support-context | BLOCK | §3 S1 x2: helper returns PII incl. birthdate; minors' data reaches support tooling without minimization | BLOCK, 1 of 2 findings (the minimization miss is the one genuine FN, see below) |
| email-reminders | BLOCK | §5 S1: hardcoded SendGrid key (+2 findings behind the firewall) | BLOCK by the deterministic firewall; the diff was never transmitted to the LLM |
| streaks | BLOCK | §2 S2 x2: off-by-one (today never counted, contradicting the docstring); tests that cannot fail | BLOCK, both issues reported with the exact missing tests prescribed |
| analytics-archive | BLOCK | §4 S1 indefinite retention; §3 S1 unminimized PII copy; §2 S2 untested logic | BLOCK, 3 of 3 findings, including the retention issue evidenced by a Spanish-language docstring |
| progress-percentage | BLOCK | §2 S2 x2: zero-lessons edge returns 100%; new test enshrines the bug | BLOCK, both issues described, one filed under a neighboring section (adjudicated below) |

## Methodology

Reviewer outputs are matched to ground truth one-to-one by (file, standard-section prefix), computed by `tools/quality_gate/eval_metrics.py`. Severity is compared but is not part of the matching identity. Two readings are reported where they differ: STRICT, the matcher exactly as implemented, and ADJUDICATED, where a documented manual pairing credits a finding that describes a real labeled issue but was filed under a different section or file. Strict numbers are never inflated; every adjudication is listed explicitly in this document.

## Results: two variables, isolated

Denominators for all arms: 8 PRs (6 must block, 2 must pass), 12 LLM-reachable ground-truth findings.

| Arm | Prompt | Model | Verdict P / R / Acc | Findings P / R / F1 |
|---|---|---|---|---|
| v1 | v1 (privacy-focused) | gpt-4o-mini | 100 / 66.7 / 75 | 100 / 33.3 / 50 |
| v2 | v2 (full checklist + evidence) | gpt-4o-mini | 75 / 100 / 75 | 61.5 / 66.7 / 64 |
| v3 | v3 (v2 + precision guard) | gpt-4o-mini | 75 / 100 / 75 | 60 / 50 / 54.5 |
| v3-big | v3 | gpt-5-mini | 85.7 / 100 / 87.5 | 58.3 / 58.3 / 58.3 |
| **final** | v3 | gpt-5-mini + postfilter redesign | **85.7 / 100 / 87.5** | **69.2 / 75.0 / 72.0** |

In absolute terms, the frozen configuration blocks 6 of 6 PRs that must block, wrongly blocks 1 of 2 that must pass (score-validation), and gets 7 of 8 verdicts right. At the finding level it emits 13 findings: 9 true positives, 4 false positives, 3 misses.

What each variable moved. The prompt iteration moved recall: v1's privacy focus made the model self-limit its mandate (its own streaks summary read "No findings related to PII exposure..."), and the v2 full-standard checklist closed both S2 correctness blind spots, taking verdict recall from 66.7% (4 of 6) to 100% (6 of 6). The model upgrade moved precision and depth: verdict accuracy 75 to 87.5, and the streaks off-by-one class, unreachable for gpt-4o-mini across three prompt versions, was caught with a prescriptive fix. The v3 precision guard measurably helped only on the larger model, an interaction effect we measured rather than assumed. gpt-5-family models reject `temperature=0`, so the final configuration runs at model-default temperature; a provider constraint, stamped into every artifact.

## Strict vs adjudicated

Two of the 4 strict FPs and 2 of the 3 strict FNs are the same finding counted twice: the model described a labeled issue but filed it under a neighboring section, and the one-to-one matcher charges that as one FP plus one FN.

| Adjudication | Strict charge | Evidence |
|---|---|---|
| streaks off-by-one filed under §1 (docstring contradiction) instead of §2 | FP + FN | Finding title: "Docstring claims streak 'terminando hoy' but implementation excludes today", anchored at `app/streaks.py` |
| percentage test-enshrinement filed under §1 instead of §2 | FP + FN | Anchored at the correct file `tests/test_progress.py`, describes the new test locking in the wrong behavior |

| Reading | Findings P / R / F1 | Interpretation |
|---|---|---|
| STRICT | 69.2 / 75.0 / 72.0 (9 TP, 4 FP, 3 FN) | What the matcher can defend automatically |
| ADJUDICATED | 84.6 / 91.7 / 88.0 (11 TP, 2 FP, 1 FN) | What the reviewer actually caught |

After adjudication, one genuine miss remains (support-context's missing-minimization label) and two genuine FPs (score-validation's extra testing finding and support-context's S2). Verdict metrics are identical under both readings.

## Failure analysis: the frozen configuration

FALSE POSITIVE (score-validation, the 1-in-8 wrong verdict). The reviewer found a real defect: `int(score)` raises an unhandled exception, returning a 500 where the API contract expects a 422. Ground truth grades it §1 S3 (minor); the reviewer graded it S2 with high confidence, verified evidence, and the trust policy did what S2/high must do: block. Root cause is severity inflation, not hallucination; the finding itself is legitimate and its suggested fix is correct. This is the failure mode our trust policy is designed to buy: with asymmetric costs (below), we accept an occasional over-blocked minor issue rather than tune toward letting an S2 through. The fix direction is severity calibration (anchor severity language to the standard's own S1/S2/S3 definitions in the prompt), listed as future work rather than iterated past the declared stop rule.

FALSE NEGATIVE (support-context, the one genuine miss). Ground truth labels two S1s: the PII-returning helper (caught) and the fact that minors' data reaches support tooling without minimization (missed). The model consistently folds the second concern into the first finding's narrative instead of emitting it separately; a one-to-one matcher cannot credit a second label to a single finding, and in this case the separation is substantive: redacting the log line would fix finding one but not the data-minimization design flaw. The 3 strict FNs share this shape (single findings absorbing adjacent labeled issues), which is why the adjudicated recall is 91.7%: the reviewer's blind spot is more about finding granularity than about detection.

## Failure analysis: what the iteration eliminated

Kept in compressed form because these failures shaped the design; full detail is reconstructable from the committed per-arm runs (`eval/runs_v1` through `eval/runs_v3-big`).

The v1 context-line FP: the reviewer flagged S1 PII-logging on `logger.info(... redact(...))`, an unchanged line that uses the sanctioned redaction helper. Fix: evidence grounding, findings must quote the added lines they indict, verified deterministically against the diff.

The v1/v2 streaks FN: an off-by-one shielded by tests that cannot fail, invisible to a privacy-only prompt and to the smaller model under every prompt. Closed by the checklist prompt plus the model upgrade; the frozen gate now reports both S2s with the exact missing test cases prescribed.

The evidence-guard incident: the FP-killer killed TPs. The model quoted evidence as fragments joined by "..."; the whole-string matcher failed and silently dropped two true S2s while the report's own summary still described them. A human caught the verdict/summary contradiction; the postfilter's `filtered_out` audit trail plus provenance stamps made the diagnosis take minutes. Redesign: fragment-aware matching plus degrade-not-drop, where a finding with unverifiable evidence survives at `confidence=low`, visible but never auto-blocking. Deterministic guards must fail visible, not silent. The exact CI pair that triggered the incident is now a regression fixture.

## Variance

gpt-5-family models accept no explicit temperature, so run-to-run variance is a fact to manage, not a bug to fix. Measured across the frozen configuration's local runs and the hosted CI harvest (`eval/runs_final`, `eval/runs_ci_final`):

- Verdict level: 8 of 8 verdicts agree between the local frozen run and CI. Verdicts are stable.
- Finding level: variance concentrates in finding count and anchoring, not detection. support-context and progress-percentage emitted 2 findings locally vs 1 in CI, where a second finding anchored outside the diff and was structurally filtered (visible in `filtered_out` as `file_not_in_diff`, never silently). The analytics-archive retention finding survives some runs only through degrade-not-drop, at `confidence=low` with `evidence_verified=false`, because its supporting evidence is a Spanish-language docstring the matcher verifies imperfectly.
- One caveat on CI provenance: in CI the stamped `gate_commit` is the PR merge commit (unique per PR), while local runs stamp the actual gate commit. Same code, different ref semantics.

Implication: merge-blocking must tolerate variance. The trust policy does, by blocking only on high or medium-confidence verified findings; a finding that flips to low-confidence across runs flips between BLOCK and COMMENT, never between visible and gone.

## Trust policy, justified by the numbers above

| Signal | Action |
|---|---|
| S1/S2, confidence high or medium, evidence verified | BLOCK (exit 2) |
| S1/S2 at low confidence, or evidence unverified | COMMENT, flagged for human review |
| S3 (style) | COMMENT only, per TEAM-STANDARDS §6 |
| Secrets (gitleaks, deterministic) | BLOCK unconditionally; the LLM never sees the diff |

The rationale is asymmetric cost. In a minors'-privacy context, a false block costs minutes of human review; a false approve can cost a legal violation. We therefore optimize S1/S2 recall first (100% block recall, 6 of 6, in the frozen configuration) and recover precision second (85.7% block precision, 6 of 7), keeping every uncertain signal visible but non-blocking. The deterministic layer is exempt from this trade-off: gitleaks precision is effectively 1, so it blocks without a confidence tier, and it runs before the LLM so a committed secret is never transmitted.

## Known limitations (accepted under the declared stop rules)

- Severity inflation (S3 graded as S2) caused the single wrong verdict; prompt-level severity calibration is the first candidate fix.
- Finding granularity: adjacent labeled issues get absorbed into one finding (all 3 strict FNs). A many-to-one matcher or a "one finding per issue" prompt instruction are both viable; neither was iterated past the stop rule.
- The retention-finding evidence is a Spanish-language docstring; a bilingual reviewer instruction is listed as future work.
- Evidence matching is substring-based; adversarial paraphrase could evade it. Acceptable for a review gate, not a security boundary.
- Prompt iteration stopped at v3 by declared stop rule; remaining ideas live in DECISIONS.md.