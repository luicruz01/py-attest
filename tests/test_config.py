from pathlib import Path

import click
import pytest

from py_attest.config import Config, Limits, StandardsPaths, load_config


def test_load_config_defaults_when_no_pyproject_file(tmp_path: Path) -> None:
    config = load_config(tmp_path)

    assert config == Config()


def test_load_config_defaults_when_no_attest_section(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")

    config = load_config(tmp_path)

    assert config == Config()


def test_load_config_reads_declared_top_level_values(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.attest]\n"
        "provider = 'anthropic'\n"
        "model = 'claude-x'\n"
        "base_branch = 'develop'\n"
        "reports_dir = 'out/'\n"
    )

    config = load_config(tmp_path)

    assert config.provider == "anthropic"
    assert config.model == "claude-x"
    assert config.base_branch == "develop"
    assert config.reports_dir == "out/"


def test_load_config_reads_nested_limits(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.attest.limits]\nmax_files = 5\n")

    config = load_config(tmp_path)

    assert config.limits.max_files == 5
    assert config.limits.max_patch_bytes == Limits().max_patch_bytes


def test_load_config_reads_nested_standards(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.attest.standards]\ncore = 'my-core.yml'\n")

    config = load_config(tmp_path)

    assert config.standards.core == "my-core.yml"
    assert config.standards.output == StandardsPaths().output


def test_load_config_reads_context_files_list(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.attest]\ncontext_files = ['README.md', 'ARCH.md']\n"
    )

    config = load_config(tmp_path)

    assert config.context_files == ("README.md", "ARCH.md")


@pytest.mark.parametrize(
    ("env_var", "attr"),
    [
        ("ATTEST_PROVIDER", "provider"),
        ("ATTEST_MODEL", "model"),
        ("ATTEST_EGRESS", "egress"),
        ("ATTEST_BASE_BRANCH", "base_branch"),
    ],
)
def test_env_override_wins_over_pyproject_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    env_var: str,
    attr: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.attest]\n"
        "provider = 'openai'\n"
        "model = 'gpt-5-mini'\n"
        "egress = 'raw'\n"
        "base_branch = 'main'\n"
    )
    monkeypatch.setenv(env_var, "overridden")

    config = load_config(tmp_path)

    assert getattr(config, attr) == "overridden"


def test_env_override_applies_even_without_pyproject_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ATTEST_PROVIDER", "fake")

    config = load_config(tmp_path)

    assert config.provider == "fake"


def test_unknown_top_level_key_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.attest]\nnot_a_real_key = 1\n")

    with pytest.raises(click.UsageError, match="not_a_real_key"):
        load_config(tmp_path)


def test_non_table_attest_value_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[tool]\nattest = ""\n')

    with pytest.raises(click.UsageError, match="tool.attest"):
        load_config(tmp_path)


def test_invalid_toml_syntax_is_a_usage_error(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.attest\nprovider = 'openai'\n")

    with pytest.raises(click.UsageError, match="pyproject.toml"):
        load_config(tmp_path)


def test_load_config_reads_non_ascii_values_as_utf8(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[tool.attest]\nbase_branch = 'función'\n", encoding="utf-8"
    )

    config = load_config(tmp_path)

    assert config.base_branch == "función"
