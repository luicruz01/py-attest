from pathlib import Path

import pytest

from py_attest.config import load_config
from py_attest.doctor import _standards_adapter
from py_attest.doctor.check import CheckStatus, DoctorContext
from py_attest.doctor.checks.standards_valid import StandardsValidCheck

FIXTURES = Path(__file__).parent / "fixtures" / "standards_valid"


def _ctx(repo_root: Path) -> DoctorContext:
    return DoctorContext(repo_root=repo_root, offline=False, config=load_config(repo_root))


def test_run_is_skip_with_the_f0_4_pending_message_while_registry_is_unavailable(
    tmp_path: Path,
) -> None:
    assert not _standards_adapter.is_available(), "F0.4 landed: un-skip the tests below"
    check = StandardsValidCheck()

    result = check.run(_ctx(tmp_path))

    assert result.status == CheckStatus.SKIP
    assert result.message == _standards_adapter.F0_4_PENDING_MESSAGE


@pytest.mark.skip(reason="waiting for F0.4")
def test_pass_fixture_is_pass() -> None:
    check = StandardsValidCheck()

    result = check.run(_ctx(FIXTURES / "pass"))

    assert result.status == CheckStatus.PASS


@pytest.mark.skip(reason="waiting for F0.4")
def test_fail_fixture_is_fail_and_names_the_offending_rule() -> None:
    check = StandardsValidCheck()

    result = check.run(_ctx(FIXTURES / "fail"))

    assert result.status == CheckStatus.FAIL
    assert result.rule_id is not None
