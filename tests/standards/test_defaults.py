from pathlib import Path

import pytest

from py_attest.errors import StandardsDriftError
from py_attest.standards.build import build
from py_attest.standards.lint import lint

DEFAULTS = Path(__file__).parents[2] / "py_attest" / "standards" / "defaults"


def test_defaults_lint_clean() -> None:
    assert lint(DEFAULTS / "core.standards.yml", DEFAULTS / "domain.standards.yml") == []


def test_defaults_build_check_matches_committed_team_standards() -> None:
    build(
        DEFAULTS / "core.standards.yml",
        DEFAULTS / "domain.standards.yml",
        DEFAULTS / "TEAM-STANDARDS.md",
        check=True,
    )  # raises StandardsDriftError if this ever needs re-running


def test_defaults_build_check_catches_real_drift(tmp_path: Path) -> None:
    stale = tmp_path / "TEAM-STANDARDS.md"
    stale.write_text("stale\n", encoding="utf-8")

    with pytest.raises(StandardsDriftError):
        build(DEFAULTS / "core.standards.yml", DEFAULTS / "domain.standards.yml", stale, check=True)
