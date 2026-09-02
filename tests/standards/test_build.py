from pathlib import Path

import pytest

from py_attest.errors import StandardsDriftError
from py_attest.standards.build import build
from tests.standards.test_registry import CORE_YAML, DOMAIN_YAML, _write


def test_build_writes_markdown_readable_like_seed_as_hand_written_file(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)
    output = tmp_path / "TEAM-STANDARDS.md"

    rendered = build(core, domain, output)

    assert output.read_text(encoding="utf-8") == rendered
    assert "GENERATED" in rendered
    assert "## 1. Code quality" in rendered
    assert "## 2. PII and logging" in rendered
    assert "code-quality-1" in rendered
    assert "External input validated" in rendered
    assert "S1 -- blocks merge" in rendered
    assert "```yaml" not in rendered  # reads like prose, not a YAML dump


def test_build_check_passes_when_output_matches(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)
    output = tmp_path / "TEAM-STANDARDS.md"
    build(core, domain, output)

    result = build(core, domain, output, check=True)

    assert result == output.read_text(encoding="utf-8")


def test_build_check_raises_on_drift(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)
    output = tmp_path / "TEAM-STANDARDS.md"
    output.write_text("stale content\n", encoding="utf-8")

    with pytest.raises(StandardsDriftError):
        build(core, domain, output, check=True)


def test_build_check_raises_when_output_is_missing(tmp_path: Path) -> None:
    core = _write(tmp_path, "core.standards.yml", CORE_YAML)
    domain = _write(tmp_path, "domain.standards.yml", DOMAIN_YAML)

    with pytest.raises(StandardsDriftError):
        build(core, domain, tmp_path / "TEAM-STANDARDS.md", check=True)
