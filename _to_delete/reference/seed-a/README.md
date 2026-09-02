# student-progress + AI Quality Gate

The seed LMS service plus an AI Quality Gate: deterministic CI checks and an LLM reviewer that audits every PR against `TEAM-STANDARDS.md`, backed by an eval harness that measures the reviewer instead of trusting it. Everything below is reproducible from a clean clone; the full quickstart was last verified end-to-end in 66 seconds, well inside the 15-minute budget.

## How the gate works

Every PR diff flows through layers ordered so that cheap, deterministic, high-precision checks run first and the LLM only judges what tools cannot:

    PR diff
      │
      ├─ ruff lint + format          (S3: advisory on PRs, enforcing on main)
      ├─ pytest + 100% coverage gate (S2 proxy: untested code fails CI)
      ├─ gitleaks on the exact diff  (S1: BLOCK, and a firewall: on a leak the
      │                               LLM is skipped, the diff never leaves CI)
      ▼
      LLM reviewer (prompt v3, gpt-5-mini, structured findings only)
      │
      ├─ schema validation            (findings + summary; a verdict from the
      │                               model is rejected, never trusted)
      ├─ evidence postfilter          (findings must quote added lines; failed
      │                               verification demotes to low confidence,
      │                               never silently deletes)
      ▼
      gating.py policy table  →  VERDICT: BLOCK (exit 2) / COMMENT / APPROVE

The verdict is computed by code from a data table, not by the model. The policy and the measured precision/recall behind it are in `EVAL.md`; the reasoning behind each layer is in `DECISIONS.md`.

## Quickstart

Prereqs: Python 3.11+, git. Optional: gitleaks (`brew install gitleaks`) for local secret scans; an OpenAI API key for the LLM reviewer.

    make setup          # venv + deps (fails fast below Python 3.11)
    make test           # pytest, 100% coverage gate on app/
    make lint           # ruff check + format
    make hooks          # optional: pre-commit + commit-msg hooks

Without an API key every deterministic layer still runs and the reviewer exits with a clear message instead of a stack trace.

## Review any branch (including one you have never seen)

The reviewer is a local CLI wrapped by CI: one engine, two modes.

    # local, against any branch:
    make gate BRANCH=feature/streaks

    # hosted, on demand, against any branch:
    gh workflow run ci.yml -f branch=feature/streaks

`make gate` runs lint, tests, the secrets preflight on the exact target diff, and then the LLM review. Reports land in `reports/` as markdown and JSON, both stamped with prompt version, model, temperature, and gate commit, so every artifact self-describes the configuration that produced it. A committed secret in the target diff is caught before any LLM call and the diff is never transmitted.

## What a review looks like

From the CI run on `feature/streaks` (a seeded off-by-one shielded by tests that cannot fail):

> Reviewed with prompt v3 · gpt-5-mini · temp model-default · gate 699f43d
>
> **VERDICT: BLOCK**
>
> | Severity | Rule | File:line | Title | Confidence |
> | --- | --- | --- | --- | --- |
> | S2 | 6-S2-logic-bug | app/streaks.py:10 | Streak calculation omits today | high |
> | S2 | 2-testing | tests/test_streaks.py:5 | Insufficient tests, core logic not asserted | high |
>
> Suggested fix: [...] assert current_streak([today], today=today) == 1 [...] These tests will detect the current implementation bug and protect against regressions.

The suggested tests fail on the buggy implementation, which is the point: the gate does not just object, it hands the author the regression test.

## Reproducing the eval

    make eval-run VERSION=final PROMPT=v3   # runs the gate on all 8 seed branches
    make eval VERSION=final                 # metrics against ground truth

Ground truth lives in `eval/ground_truth.yml`, labeled before any reviewer run. All ablation arms (v1 through v3-big) are committed under `eval/` for byte-for-byte comparison, plus the harvested CI artifacts (`eval/runs_ci_final`) for the hosted runs. Full analysis, including strict vs adjudicated readings and failure analysis: `EVAL.md`.

## CI

Five jobs on every PR: `lint` (advisory on PRs, enforcing on main, per TEAM-STANDARDS §6: style is S3 and must not block), `test`, `secrets` (gitleaks), `audit` (pip-audit, warn-only on pinned seed deps), and `ai-review` (posts the review as a PR comment, uploads JSON/markdown artifacts, and its exit code blocks the merge). Branch protection requires `test`, `secrets`, and `ai-review` to pass; `lint` and `audit` are deliberately not required. The `ai-review` job also accepts `workflow_dispatch` with a branch input for on-demand reviews.

## Repo map

    app/, tests/            seed service (untouched, protected)
    TEAM-STANDARDS.md       the rules the gate enforces
    tools/quality_gate/     reviewer CLI, schema, postfilters, gating policy,
                            versioned prompts (v1/v2/v3), eval metrics
    eval/                   ground truth, per-arm runs and metrics, CI harvest
    EVAL.md                 ground truth, metrics, failure analysis, trust policy
    DECISIONS.md            six mini-ADRs and what was deliberately left out
    AI-USAGE.md             how AI built this, and where it was wrong
    CONTEXT.md              the agents' working memory, kept as the build record

---

## Seed service (original docs)

Open English LMS service that tracks students' lesson progress.
**Some students are minors** — read `TEAM-STANDARDS.md` before making any changes.

## Running locally

Requires **Python 3.11+** (a virtual environment is recommended):

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```

## Endpoints

- `GET /health`
- `GET /lessons`
- `GET /students/{id}/progress`
- `POST /students/{id}/progress` — body: `{"lesson_id": "...", "score": 0-100}`

Data is held in memory (see `app/store.py`). There is no database: the focus of this repository is the review process, not persistence.