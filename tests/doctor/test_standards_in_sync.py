from pathlib import Path

from py_attest.config import load_config
from py_attest.doctor.check import CheckStatus, DoctorContext
from py_attest.doctor.checks.standards_in_sync import StandardsInSyncCheck

FIXTURES = Path(__file__).parent / "fixtures" / "standards_in_sync"


def _ctx(repo_root: Path) -> DoctorContext:
    return DoctorContext(repo_root=repo_root, offline=False, config=load_config(repo_root))


def test_no_standards_files_is_skip_not_fail(tmp_path: Path) -> None:
    check = StandardsInSyncCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.SKIP


def test_pass_fixture_is_pass_when_team_standards_matches_the_generated_output() -> None:
    check = StandardsInSyncCheck()

    result = check.run(_ctx(FIXTURES / "pass"))

    assert result.status == CheckStatus.PASS


def test_fail_fixture_is_fail_with_an_attest_standards_build_remedy() -> None:
    check = StandardsInSyncCheck()

    result = check.run(_ctx(FIXTURES / "fail"))

    assert result.status == CheckStatus.FAIL
    assert result.remedy == "run `attest standards build` to regenerate TEAM-STANDARDS.md"


def test_an_invalid_registry_is_error_not_fail(tmp_path: Path) -> None:
    (tmp_path / "core.standards.yml").write_text("not: [valid\n")
    (tmp_path / "domain.standards.yml").write_text("version: 1\nsections: []\n")
    check = StandardsInSyncCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.ERROR
