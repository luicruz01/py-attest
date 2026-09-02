from pathlib import Path

from py_attest.standards.lint import lint
from tests.standards.test_registry import CORE_YAML, DOMAIN_YAML, _write


def test_lint_passes_on_valid_standards(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    assert lint(core, domain) == []


def test_lint_reports_schema_violations_without_raising(tmp_path: Path) -> None:
    core = _write(
        tmp_path, "core.standards.yml", CORE_YAML.replace("        check: ruff-check\n", "")
    )
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    errors = lint(core, domain)

    assert len(errors) == 1
    assert "schema violation" in errors[0].message


def test_lint_reports_an_unknown_check_id(tmp_path: Path) -> None:
    core = _write(
        tmp_path,
        "core.standards.yml",
        CORE_YAML.replace("check: ruff-check", "check: not-a-real-check"),
    )
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    errors = lint(core, domain)

    assert len(errors) == 1
    assert "code-quality-1" in errors[0].message
    assert "not-a-real-check" in errors[0].message


def test_lint_reports_every_unknown_check_id_not_just_the_first(tmp_path: Path) -> None:
    two_bad_checks = CORE_YAML.replace("check: ruff-check", "check: bogus-one") + (
        "  - slug: testing\n"
        "    title: Testing\n"
        "    rules:\n"
        "      - id: testing-1\n"
        "        title: Untested core logic fails CI\n"
        "        severity: S2\n"
        "        mode: deterministic\n"
        "        check: bogus-two\n"
        "        description: Every logic change includes a test that would fail if it broke.\n"
    )
    core = _write(tmp_path, "core.standards.yml", two_bad_checks)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    errors = lint(core, domain)

    assert {error.message.split(": ")[0] for error in errors} == {"code-quality-1", "testing-1"}


def test_lint_handles_nonexistent_core_file_without_raising(tmp_path: Path) -> None:
    core = tmp_path / "nonexistent.yml"
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    errors = lint(core, domain)

    assert len(errors) == 1
    assert "cannot read file" in errors[0].message
