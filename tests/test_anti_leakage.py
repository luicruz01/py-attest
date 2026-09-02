"""The installable package must never import or read the top-level eval/ golden set
(CLAUDE.md, ADR-004 SS6). py_attest/eval/ is the eval tooling itself and is exempt --
record.py and metrics.py legitimately take eval/golden/ paths as CLI arguments; nothing
in py_attest/review, /llm, /check, /standards, /cli, or /doctor may reference it."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "py_attest"
SCANNED_SUBPACKAGES = ("review", "llm", "check", "standards", "cli", "doctor")
PROTECTED_MARKERS = ("eval/golden", "ground_" + "truth", "expected.json", "adjudications.yml")


def test_the_core_engine_never_references_the_golden_set() -> None:
    offenders = []
    for subpackage in SCANNED_SUBPACKAGES:
        for path in (PACKAGE_ROOT / subpackage).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            hits = [marker for marker in PROTECTED_MARKERS if marker in source]
            if hits:
                offenders.append((path, hits))

    assert offenders == [], f"py_attest core engine files reference eval/golden data: {offenders}"


def test_py_attest_eval_is_the_only_subpackage_allowed_to_mention_the_golden_set() -> None:
    # Sanity check that the exemption is real and this test isn't accidentally vacuous.
    record_source = (PACKAGE_ROOT / "eval" / "record.py").read_text(encoding="utf-8")
    assert "diff_path" in record_source  # eval/ itself does take golden-set-shaped paths
