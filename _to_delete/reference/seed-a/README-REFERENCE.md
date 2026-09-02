# Seed A — frozen reference (read-only)

This is the first implementation of the Open English AI Quality Gate ("Seed A", `tools/quality_gate/`), kept here
only so that F0 can port three pieces into py-attest (see docs/adr/004-seed-b-base.md):

1. `tools/quality_gate/prompts/reviewer_v3.md` — the measured prompt (egress `raw`).
2. `tools/quality_gate/context_pack.py` + `secrets_gate.py` — egress `raw`: context pack + gitleaks on the diff via stdin.
3. `tools/quality_gate/postfilter.py` (+ `tests/quality_gate/test_postfilter.py`) — fragment-aware evidence matching,
   degrade-not-drop (`evidence_policy = "degrade"`).

`EVAL.md` and `eval/` hold the baseline for the `raw` mode (6/6 block recall, 87.5% verdict accuracy, F1 72 strict).

Rules: never import from here; excluded from ruff, pytest, coverage and the wheel; delete this directory when F0 closes.
The code base of py-attest is Seed B (`../student-progress-seed`), not this.
