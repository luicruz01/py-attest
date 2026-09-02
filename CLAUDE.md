# py-attest

CLI + quality-gate engine for Python repos. PyPI package `py-attest`, import `py_attest`, command `attest`.
Companion template: github.com/luicruz01/py-attest-template (created after v1.0.0; see docs/adr/003-compatibility.md).

## Before touching code
- Read `docs/trd.md` §3 (module layout) and §4 (CLI contracts). Exit codes are a contract:
  `0` ok / APPROVE / COMMENT · `2` BLOCK · `3` engine↔template incompatibility · `4` execution error · `64` usage error.
- Closed decisions live in `docs/adr/`. If your work package needs to contradict an ADR: do NOT implement a
  workaround. Leave a comment in the PR and propose a change to the ADR instead.
- The verdict is computed by `py_attest/gate/gating.py` from a policy table. Never by the model. Do not change this.
- Findings cite `rule_id`; severity is resolved from the standards registry (ADR-001), never trusted from model output.
- The secrets firewall (gitleaks) runs before any LLM call. A detected secret blocks and the diff is never transmitted.
  A missing gitleaks binary is exit 4, never a silent skip.
- `attest review` (and the CI job that holds secrets) must never execute code from the reviewed repository — no pytest,
  no imports, no hooks, no checkout of the PR head. Only `attest check` executes code, and it runs without secrets.
- Fail closed: a technical failure or an incomplete review is exit 4 (INCONCLUSIVE) and a red check — never an approval.

## How to work
- One work package per branch (`wp/f0.3`). Prompts and DoD per work package: `docs/plan-cc.md` §4 and §6.
- TDD: tests first. The tests migrated from the seed are the safety net for phase F0.
- `uv sync --all-extras && uv run pytest` before every commit. `ruff check` and `ruff format --check` must pass.
- No telemetry. No network calls except the configured LLM provider (and git/PyPI/GitHub on explicit user action).
- API keys only from environment variables. Never in files, never in fixtures.
- Provider tests use recorded fixtures; nothing in the PR test suite touches the network.

## Map (TRD v0.3 §3.1)
- `py_attest/check/`     the ONLY code that executes the reviewed repo (ruff, pytest+cov, gitleaks on the tree). Runs without secrets.
- `py_attest/review/`    never executes repo code: diff as data → deterministic → gitleaks firewall → egress (raw | minimized)
                          → provider → validation → policy → report.
- `py_attest/llm/`       provider interface (ADR-002): fake, openai, anthropic; prompts/
- `py_attest/standards/` standards.yml → TEAM-STANDARDS.md (ADR-001 + ADR-004 fields): schema, registry, build, lint
- `py_attest/doctor/`    check catalog (TRD §6), runner, report
- `py_attest/cli/`       click commands (check, review, gate, doctor, new, upgrade, standards, calibrate); `main.py` maps exit codes
- `eval/`                golden set = REGRESSION only, never tuning (anti-leakage, ADR-004 §6). Recorded fixtures; the weekly job uses real providers.
- `docs/`                prd.md · trd.md · plan-cc.md · adr/

## Seeds (read docs/adr/004-seed-b-base.md before F0 work)
- **Seed A** = the code base: `../student-progress-seed` on branch `main` (`tools/quality_gate/`, `tests/quality_gate/`, `eval/`,
  `EVAL.md`). Read-only. Its eight benchmark branches are frozen fixtures: never modify them, never run the reviewer against
  them outside the eval harness.
- **Seed B** = branch `fix/quality-gate-safety` of the same repo, checked out read-only at `../seed-b`. Only the pieces named in
  ADR-004 §2 are rescued (catalog fields, provider Protocol + fake, egress minimized, bounded git, side old/new, optional
  pull_request_target job) — each one together with its tests. Never merge seed branches.
- Migrate first, change later, in separate PRs. Never "improve" behavior while moving code.
