# AI Usage: how this was built

This repository was built agentic-first, and the build process is itself the thing the challenge asks the gate to be: an AI pipeline whose output is not trusted until a separate layer verifies it. Three roles, explicit governance, and a paper trail for every claim.

## The setup: three roles, separated on purpose

- **OpenAI Codex, implementer.** All code was written by Codex working in scoped work packets: each packet carries an allowed-file list, acceptance criteria, and a standing order to stop and ask on any scope ambiguity rather than improvise. It stopped five times; each stop is logged, and each resolution was an explicit scope amendment by the architect, so scope creep had to happen out loud or not at all.
- **OpenAI Codex, fresh sessions, adversarial reviewer.** A reviewer with a refute-first mandate ("assume this packet fails its acceptance criteria and hunt for evidence"), no authority to edit code, and a fresh context per review so it cannot inherit the implementer's assumptions. Generator/reviewer separation here is context isolation, not branding.
- **Claude, architect.** Specs, scope adjudications, verification of agent claims against artifacts, and these documents. No code.

Governance lives in two files kept in-repo: `AGENTS.md` (the constitution: risk tiers, protected paths, stop rules) and `CONTEXT.md` (shared working memory: state, decisions, review findings, and a log of every discarded AI output). Low-risk packets merged on green checks; high-risk packets required an adversarial review round plus human sign-off before push.

## By the numbers

18 scoped work packets plus two micro-fixes. Five scope stops, all resolved by explicit amendment. Four adversarial review rounds before pushes, which surfaced 9 findings including two high-severity catches that would have surfaced during the live demo instead: a Python-floor bug (`make setup` accepted Python 3.9, where the streaks branch crashes on `date | None` syntax) and a secrets-ordering flaw where `make gate` could transmit a committed secret to the LLM provider before the deterministic scan ran. Total LLM spend for the entire exercise, build and eval included: $0.20 USD of a $10 budget.

## The five prompts that mattered most

1. The adversarial reviewer role prompt: "assume this packet fails its acceptance criteria and hunt for evidence." Found 4 valid issues in phase 1 alone, including the Python-floor bug above.
2. The WP2a spec: JSON schema for findings, the verdict-smuggling prohibition (the model may never output a verdict; tests enforce it), and the runtime context pack. This is the reviewer engine's contract.
3. The v2 reviewer prompt: the full-standard checklist plus the evidence requirement. Moved verdict recall from 66.7% to 100% (EVAL.md, ablation).
4. The v3 precision guard: "name the exact sentence of the standard or do not emit the finding."
5. The scope-amendment pattern: the architect authorizes file-list changes explicitly, in writing, in CONTEXT.md. Five ambiguities never became silent scope creep.

## Discarded or corrected AI output (selection)

- The gitleaks target Codex first generated scanned all local refs; from `main` it "found" the seed branch's intentional leak. Corrected to scanning only the current branch's history, with the seed leak verified separately by explicit diff.
- pip-audit's default ephemeral-venv mode aborts on macOS (`ensurepip` SIGABRT); the generated Make target was replaced with environment-mode auditing against the project venv.
- The implementer's completion message misreported the v3-mini metrics by quoting the v3-big numbers. Caught by architect verification against the committed `metrics_v3.md`. Agent claims are checked against artifacts, not accepted from summaries.
- The evidence postfilter, an AI-designed false-positive guard, silently dropped two true S2 findings whose evidence was quoted as multi-fragment strings. Detected by a human reading the contradiction between a report's APPROVE verdict and its own summary describing two blockers. Redesigned to degrade-not-drop; the triggering pair is now a regression fixture (EVAL.md, evidence-guard incident).
- Two CI evidence harvests were discarded after forensic checks showed reviewer runs had executed against stale configurations (GitHub merge-ref refresh races). Fixed by stamping every artifact with prompt version, model, temperature, and gate commit, so evidence self-describes its configuration and staleness is detectable by inspection.
- A harvest spot-check initially paired PRs to branches by assuming PR-number ordering; `prs.json` showed the mapping was wrong, and the comparison was discarded and redone keyed by branch name.

The complete, timestamped record, including every smaller correction, lives in `CONTEXT.md`, kept in-repo deliberately as the build record.