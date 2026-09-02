from pathlib import Path

from py_attest.config import load_config
from py_attest.doctor.check import CheckStatus, DoctorContext
from py_attest.doctor.checks.compat_engine_range import CompatEngineRangeCheck

FIXTURES = Path(__file__).parent / "fixtures" / "compat_engine_range"


def _ctx(repo_root: Path) -> DoctorContext:
    return DoctorContext(repo_root=repo_root, offline=False, config=load_config(repo_root))


def test_pass_fixture_is_pass_because_installed_version_is_inside_the_wide_range() -> None:
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(FIXTURES / "pass"))

    assert result.status == CheckStatus.PASS
    assert result.remedy is None


def test_fail_fixture_is_fail_with_the_exact_pip_install_remedy() -> None:
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(FIXTURES / "fail"))

    assert result.status == CheckStatus.FAIL
    assert result.remedy == 'pip install -U "py-attest>=97,<98"'


def test_no_copier_answers_file_is_skip_not_fail(tmp_path: Path) -> None:
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.SKIP


def test_malformed_answers_file_is_error(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("not: [valid, yaml:\n")
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.ERROR


def test_missing_attest_engine_range_key_is_error(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("_commit: v1.0.0\n")
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.ERROR


def test_invalid_specifier_is_error(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("attest_engine_range: 'not a specifier'\n")
    check = CompatEngineRangeCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.ERROR
