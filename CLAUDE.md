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

## How to work
- One work package per branch (`wp/f0.3`). Prompts and DoD per work package: `docs/plan-cc.md` §4 and §6.
- TDD: tests first. The tests migrated from the seed are the safety net for phase F0.
- `uv sync --all-extras && uv run pytest` before every commit. `ruff check` and `ruff format --check` must pass.
- No telemetry. No network calls except the configured LLM provider (and git/PyPI/GitHub on explicit user action).
- API keys only from environment variables. Never in files, never in fixtures.
- Provider tests use recorded fixtures; nothing in the PR test suite touches the network.

## Map
- `py_attest/gate/`      pipeline by layers: lint → tests+cov → secrets firewall → llm → schema → postfilter → gating → report
- `py_attest/llm/`       provider interface (ADR-002): types, retry policy, entry-point registry, providers/
- `py_attest/standards/` standards.yml → TEAM-STANDARDS.md (ADR-001): schema, registry, build, lint
- `py_attest/doctor/`    check catalog (TRD §6), runner, report
- `py_attest/cli/`       click commands; `main.py` owns the exit-code mapping
- `eval/`                golden set (recorded fixtures); the weekly job uses real providers and regenerates EVAL.md
- `docs/`                prd.md · trd.md · plan-cc.md · adr/

## Seed
The original engine lives in the read-only seed repo `../student-progress-seed` (`tools/quality_gate/`, `tests/quality_gate/`,
`eval/`). Phase F0 migrates it; do not "improve" behavior while migrating — move first, change later, in separate PRs.
