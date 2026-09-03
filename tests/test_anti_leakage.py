"""The installable package must never import or read the top-level eval/ golden set
(CLAUDE.md, ADR-004 SS6). py_attest/eval/ is the eval tooling itself and is exempt --
record.py and metrics.py legitimately take eval/golden/ paths as CLI arguments; nothing
else under py_attest/ may reference it.

Deny-by-default (not an allowlist of subpackages): every .py file under py_attest/ is
scanned except py_attest/eval/ itself. A hardcoded allowlist of subpackage names would
silently stop covering a future subpackage (e.g. py_attest/gate/, described in
CLAUDE.md's module map as coming later) unless someone remembered to add it here.
"""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "py_attest"
_EXEMPT_SUBPACKAGE = "eval"
PROTECTED_MARKERS = (
    "eval/golden",
    "ground_" + "truth",
    "expected.json",
    "adjudications.yml",
    # Path/filename markers above don't catch an import-style leak (`import
    # py_attest.eval` / `from py_attest import eval`) that never spells out a literal
    # eval/golden path. Split the same way the markers above are, so this guard's own
    # source never contains the literal substring it's watching for.
    "py_attest" + ".eval",
    "from py_attest import" + " eval",
)


def test_the_core_engine_never_references_the_golden_set() -> None:
    offenders = []
    for path in PACKAGE_ROOT.rglob("*.py"):
        if path.relative_to(PACKAGE_ROOT).parts[0] == _EXEMPT_SUBPACKAGE:
            continue
        source = path.read_text(encoding="utf-8")
        hits = [marker for marker in PROTECTED_MARKERS if marker in source]
        if hits:
            offenders.append((path, hits))

    assert offenders == [], f"py_attest core engine files reference eval/golden data: {offenders}"


def test_the_scanner_actually_flags_a_protected_marker_when_present() -> None:
    # Positive control: proves the matching logic above isn't vacuously always-passing.
    # (The old version of this test only asserted "diff_path" in record.py's source --
    # true regardless of whether the scanner's own hit-detection worked at all.)
    synthetic_source = 'path = "eval/golden/some-branch/expected.json"'

    hits = [marker for marker in PROTECTED_MARKERS if marker in synthetic_source]

    assert hits, "the scanner's own matching logic failed to flag a known-bad synthetic source"


def test_the_scanner_flags_an_eval_import_style_leak() -> None:
    # Positive control for the import-style markers specifically -- a core-engine file
    # could leak-import py_attest.eval without ever spelling out a literal
    # "eval/golden"-shaped path string.
    synthetic_source = "import py_attest.eval"

    hits = [marker for marker in PROTECTED_MARKERS if marker in synthetic_source]

    assert hits, "the scanner failed to flag an `import py_attest.eval`-style leak"
