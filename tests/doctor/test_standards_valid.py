from pathlib import Path

from py_attest.config import load_config
from py_attest.doctor.check import CheckStatus, DoctorContext
from py_attest.doctor.checks.standards_valid import StandardsValidCheck

FIXTURES = Path(__file__).parent / "fixtures" / "standards_valid"


def _ctx(repo_root: Path) -> DoctorContext:
    return DoctorContext(repo_root=repo_root, offline=False, config=load_config(repo_root))


def test_no_standards_files_is_skip_not_fail(tmp_path: Path) -> None:
    check = StandardsValidCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.SKIP


def test_pass_fixture_is_pass() -> None:
    check = StandardsValidCheck()

    result = check.run(_ctx(FIXTURES / "pass"))

    assert result.status == CheckStatus.PASS


def test_fail_fixture_is_fail_and_names_the_duplicate_rule_id() -> None:
    check = StandardsValidCheck()

    result = check.run(_ctx(FIXTURES / "fail"))

    assert result.status == CheckStatus.FAIL
    assert "testing-1" in result.message
    assert result.remedy == "run `attest standards lint` for the full list of problems"


def test_a_deterministic_rule_with_an_unknown_check_id_is_fail(tmp_path: Path) -> None:
    (tmp_path / "core.standards.yml").write_text(
        "version: 1\n"
        "sections:\n"
        "  - slug: testing\n"
        "    title: Testing\n"
        "    rules:\n"
        "      - id: testing-1\n"
        "        title: Untested core logic fails CI\n"
        "        severity: S2\n"
        "        mode: deterministic\n"
        "        check: not-a-real-check\n"
        "        description: placeholder\n"
    )
    (tmp_path / "domain.standards.yml").write_text("version: 1\nsections: []\n")
    check = StandardsValidCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.FAIL
    assert "not-a-real-check" in result.message
