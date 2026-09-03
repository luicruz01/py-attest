"""Two tiers (spec SS6): (1) an always-on synthetic replay proving the recorder ->
pipeline -> metrics chain works fully offline, reusing an existing review/ fixture
pair so this doesn't invent a second copy of the same data; (2) a golden-set
integration pass over the real eval/golden/ branches that skips (not fails) whatever
egress recordings don't exist yet -- honest today, becomes a real regression gate once
a human records them (spec SS6/SS8, corrected after review: neither raw nor minimized
inherits Seed A's original numbers as a hardcoded target)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from py_attest.eval.metrics import evaluate

GOLDEN_DIR = Path(__file__).parents[2] / "eval" / "golden"
REVIEW_FIXTURES = Path(__file__).parents[1] / "review" / "fixtures"


def _init_git_repo(root: Path) -> None:
    """run_review's _gate_commit unconditionally runs `git rev-parse HEAD` in
    repo_root (even for a provider="fake" replay) -- give evaluate()'s fixtures a
    real, hermetic git ancestor rather than mocking that away, so this test actually
    exercises the real pipeline end to end. Same pattern as
    tests/eval/test_metrics.py's _init_git_repo."""
    git_executable = shutil.which("git")
    assert git_executable is not None
    for args in (
        ["init", "-q"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
    ):
        subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
            [git_executable, *args], cwd=root, check=True
        )
    (root / ".gitkeep").write_text("", encoding="utf-8")
    for args in (["add", "."], ["commit", "-q", "-m", "init"]):
        subprocess.run(  # noqa: S603 - resolved executable, fixed arguments, no shell
            [git_executable, *args], cwd=root, check=True
        )


def test_synthetic_streaks_recording_replays_through_the_full_pipeline(tmp_path: Path) -> None:
    golden_dir = tmp_path / "golden"
    golden_dir.mkdir(parents=True)
    _init_git_repo(golden_dir)

    branch_dir = golden_dir / "feature" / "streaks"
    branch_dir.mkdir(parents=True)

    diff = (REVIEW_FIXTURES / "streaks.patch").read_text(encoding="utf-8")
    (branch_dir / "diff.patch").write_text(diff, encoding="utf-8")

    recording = json.loads(
        (REVIEW_FIXTURES / "pr2_streaks_findings.json").read_text(encoding="utf-8")
    )
    (branch_dir / "provider_response.raw.json").write_text(json.dumps(recording), encoding="utf-8")

    expected = {
        "branch": "feature/streaks",
        "source": {
            "base_sha": "a" * 40,
            "head_sha": "b" * 40,
            "merge_base_sha": "a" * 40,
            "patch_sha256": "c" * 64,
        },
        "verdict": "BLOCK",
        "findings": [
            {
                "rule_id": "code-quality-6",
                "severity": "S2",
                "path": "app/streaks.py",
                "line_start": 10,
                "line_end": 10,
                "llm_reachable": True,
            },
            {
                "rule_id": "testing-3",
                "severity": "S2",
                "path": "app/streaks.py",
                "line_start": 5,
                "line_end": 5,
                "llm_reachable": True,
            },
        ],
    }
    (branch_dir / "expected.json").write_text(json.dumps(expected), encoding="utf-8")

    results = evaluate(golden_dir, "raw", require_all=False)

    assert results.skipped == []
    assert len(results.branches) == 1
    branch = results.branches[0]
    assert branch.predicted_verdict == "BLOCK"
    assert branch.expected_verdict == "BLOCK"
    # both recorded findings match their expected counterpart exactly (same
    # rule_id/path/line) -- proves validation.py + postfilter.py + policy.py all ran
    # for real on the replayed recording, not a stub.
    assert len(branch.readings["strict"].true_positives) == 2
    assert branch.readings["strict"].false_positives == []
    assert branch.readings["strict"].false_negatives == []


@pytest.mark.parametrize("egress", ["raw", "minimized"])
def test_the_real_golden_set_runs_offline_and_skips_unrecorded_branches(egress: str) -> None:
    """This is the test that keeps `uv run pytest -q tests/eval` green today, with zero
    recordings committed, and turns into the real 8-branch regression check the moment
    a human records and commits provider_response.<egress>.json for every branch --
    with no code change required here."""
    manifest = json.loads((GOLDEN_DIR / "manifest.json").read_text(encoding="utf-8"))
    all_branches = set(manifest["branches"])

    results = evaluate(GOLDEN_DIR, egress, require_all=False)

    scored = {b.branch for b in results.branches}
    assert scored | set(results.skipped) == all_branches
    assert scored.isdisjoint(results.skipped)

    if not results.skipped:
        # All 8 recordings exist -- print the real numbers for a human to review and
        # seal into EVAL.md (spec SS6/SS8). No hardcoded target: Seed A's original
        # 6/6-recall/87.5%-accuracy numbers were measured against a ground truth this
        # golden set no longer uses (score-validation's BLOCK reclassification, spec
        # SS2), so they cannot be this assertion's target.
        print(f"\n{egress} block recall: {results.block_recall:.1%}")  # noqa: T201
        print(f"{egress} verdict accuracy: {results.accuracy:.1%}")  # noqa: T201
        for name, reading in results.readings.items():
            print(f"{egress} {name} F1: {reading.f1:.1%}")  # noqa: T201
