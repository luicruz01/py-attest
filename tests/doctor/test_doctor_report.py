from pathlib import Path

from py_attest.doctor.check import Check, CheckResult, CheckStatus
from py_attest.doctor.report import to_json, to_markdown
from py_attest.doctor.runner import DoctorReport


class _Fake(Check):
    id = "fake_check"
    severity = "S1"

    def run(self, ctx: object) -> CheckResult:  # pragma: no cover - not exercised here
        raise NotImplementedError


def _report(results: list[tuple[Check, CheckResult]], **kwargs: object) -> DoctorReport:
    return DoctorReport(
        target=Path("/repo"),
        strict=kwargs.get("strict", False),
        compat=kwargs.get("compat", False),
        results=results,
    )


def test_to_json_reports_schema_version_and_target() -> None:
    report = _report([])

    payload = to_json(report)

    assert payload["schema_version"] == 1
    assert payload["target"] == "/repo"
    assert payload["strict"] is False
    assert payload["compat"] is False


def test_to_json_includes_one_row_per_check_result() -> None:
    check = _Fake()
    result = CheckResult(
        status=CheckStatus.FAIL,
        message="engine out of range",
        remedy='pip install -U "py-attest>=1.3,<2"',
        rule_id=None,
    )

    payload = to_json(_report([(check, result)]))

    assert payload["checks"] == [
        {
            "id": "fake_check",
            "severity": "S1",
            "status": "fail",
            "message": "engine out of range",
            "remedy": 'pip install -U "py-attest>=1.3,<2"',
            "rule_id": None,
        }
    ]


def test_to_json_summarizes_status_counts() -> None:
    check = _Fake()
    pass_result = CheckResult(status=CheckStatus.PASS, message="ok")
    skip_result = CheckResult(status=CheckStatus.SKIP, message="not applicable")

    payload = to_json(_report([(check, pass_result), (check, skip_result)]))

    assert payload["summary"] == {"pass": 1, "fail": 0, "skip": 1, "error": 0}


def test_to_json_meta_has_engine_version_and_generated_at() -> None:
    payload = to_json(_report([]))

    assert "engine_version" in payload["meta"]
    assert "generated_at" in payload["meta"]


def test_to_markdown_renders_a_row_per_check_with_remedy() -> None:
    check = _Fake()
    result = CheckResult(
        status=CheckStatus.FAIL,
        message="engine out of range",
        remedy='pip install -U "py-attest>=1.3,<2"',
    )

    markdown = to_markdown(_report([(check, result)]))

    assert "fake_check" in markdown
    assert "S1" in markdown
    assert "fail" in markdown
    assert "engine out of range" in markdown
    assert 'pip install -U "py-attest>=1.3,<2"' in markdown


def test_to_markdown_with_no_results_says_no_checks_ran() -> None:
    markdown = to_markdown(_report([]))

    assert "no checks" in markdown.lower()
