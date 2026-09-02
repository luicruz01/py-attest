from pathlib import Path

from py_attest.config import load_config
from py_attest.doctor.check import CheckStatus, DoctorContext
from py_attest.doctor.checks.compat_pin_consistent import CompatPinConsistentCheck

FIXTURES = Path(__file__).parent / "fixtures" / "compat_pin_consistent"


def _ctx(repo_root: Path) -> DoctorContext:
    return DoctorContext(repo_root=repo_root, offline=False, config=load_config(repo_root))


def test_pass_fixture_is_pass_when_pyproject_and_answers_ranges_match() -> None:
    check = CompatPinConsistentCheck()

    result = check.run(_ctx(FIXTURES / "pass"))

    assert result.status == CheckStatus.PASS
    assert result.remedy is None


def test_fail_fixture_is_fail_with_an_upgrade_remedy_when_ranges_diverge() -> None:
    check = CompatPinConsistentCheck()

    result = check.run(_ctx(FIXTURES / "fail"))

    assert result.status == CheckStatus.FAIL
    assert result.remedy is not None
    assert "attest upgrade" in result.remedy


def test_equivalent_but_differently_formatted_ranges_still_pass(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text('attest_engine_range: ">=1.3,<2"\n')
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\nattest = ["py-attest[openai]>=1.3, <2"]\n'
    )
    check = CompatPinConsistentCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.PASS


def test_no_copier_answers_file_is_skip_not_fail(tmp_path: Path) -> None:
    check = CompatPinConsistentCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.SKIP


def test_answers_present_but_no_pyproject_attest_entry_is_error(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text('attest_engine_range: ">=1.3,<2"\n')
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    check = CompatPinConsistentCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.ERROR
