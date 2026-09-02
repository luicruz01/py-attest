# Decisions — mini-ADRs

## 1. Deterministic-first, severity-aligned enforcement
50 years of tooling solve most of this problem without an LLM. Gitleaks
(secrets, S1), pytest + a 100% coverage gate on app/ (S2 proxy: new
untested code fails CI), Ruff (S3), pip-audit (advisory). The LLM is
reserved for what only it can judge: indirect PII flows, retention
semantics, logic-vs-intent, test effectiveness. CI enforcement mirrors
TEAM-STANDARDS §6: S1 (secrets) and S2 (tests) jobs block PRs; S3 (lint)
is advisory on PRs and enforcing on main. Trigger: the streaks PR
initially failed CI for formatting — a wrong-reason block that
contradicted the standard the gate exists to apply.

## 2. CLI-first, CI-wrapped
The reviewer is a local CLI (make gate BRANCH=x) wrapped by a GitHub
Actions job — one engine, two modes. Rationale: the evaluators must
reproduce in <15 min without our infrastructure, and the live session
requires reviewing an unseen PR on demand. PR comments + artifacts in
CI; markdown + JSON reports locally.

## 3. Secrets firewall before the LLM
The exact diff is scanned by gitleaks BEFORE any LLM call. On a leak,
the LLM is skipped, an S1 finding is synthesized (redacted), the verdict
blocks, and the report states the diff was not transmitted. The
deterministic layer is not only cheaper — it is the privacy firewall of
the semantic layer: a committed secret never leaves the machine. Cost:
other findings in that diff are unreachable by the LLM (measured and
reported separately in EVAL.md). We accept that trade-off deliberately.

## 4. The model never decides the verdict
The LLM outputs findings only (schema-enforced; verdict smuggling is
rejected by tests). The verdict is computed by gating.py from a policy
TABLE (data, not scattered ifs). Basis: published evidence that LLM
self-assessment of its own findings is unreliable; our policy is instead
justified by measured precision/recall per tier (EVAL.md).

## 5. Evidence grounding — and degrade-not-drop
Findings must quote the added lines they indict; quotes are verified
deterministically against the diff (fragment-aware, whitespace
normalized). This killed the context-line FP class. First implementation
dropped unverified findings and thereby silently deleted two true S2s
(multi-fragment quotes); redesigned so unverified findings survive at
confidence=low, visible but never auto-blocking. Principle: a
deterministic guard may demote, never silently delete.

## 6. Freeze by ablation, with stop rules
Prompt and model were iterated as isolated variables (v1→v2→v3 ×
mini/gpt-5-mini), each arm measured against the golden set. Frozen
config: prompt v3 + gpt-5-mini. Declared stop rules: prompt iteration
ends at v3; variance documented from cross-run evidence instead of
dedicated N-run batches. Timebox honesty over completeness.

## Deliberately out of scope
- Mutation testing: the deterministic proxy for "tests that cannot fail"
  (it would catch the streaks test-theater without an LLM). Left out for
  timebox; first candidate for the next iteration.
- Presidio/PII scanners: text-oriented, best-effort; the LLM covers the
  semantic cases better in this codebase.
- Reviewer feedback loop (suppression memory from accepted/rejected
  comments) — the long-term FP strategy.
- Bilingual (ES/EN) reviewer instruction for Spanish docstrings.
- Branch rulesets exported as code (docs/rulesets/) — blocking is
  design-complete; org-level enforcement is a platform-plan toggle.