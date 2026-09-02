import importlib.metadata
from pathlib import Path

import pytest

from py_attest.doctor import _compat


def test_load_copier_answers_rejects_a_non_mapping_document(tmp_path: Path) -> None:
    (tmp_path / ".copier-answers.yml").write_text("- just\n- a\n- list\n")

    with pytest.raises(_compat.CompatDataError, match="mapping"):
        _compat.load_copier_answers(tmp_path)


def test_engine_range_from_pyproject_rejects_malformed_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("not valid [ toml")

    with pytest.raises(_compat.CompatDataError, match="TOML"):
        _compat.engine_range_from_pyproject(tmp_path)


def test_engine_range_from_pyproject_rejects_a_non_list_attest_extra(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        '[project.optional-dependencies]\nattest = "not-a-list"\n'
    )

    with pytest.raises(_compat.CompatDataError, match="must be a list"):
        _compat.engine_range_from_pyproject(tmp_path)


def test_engine_range_from_pyproject_skips_unparseable_and_unrelated_entries(
    tmp_path: Path,
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project.optional-dependencies]\n"
        'attest = [1, "not a valid requirement !!!", '
        '"other-package>=1", "py-attest>=1.3,<2"]\n'
    )

    engine_range = _compat.engine_range_from_pyproject(tmp_path)

    assert str(engine_range.specifier) == str(_compat.SpecifierSet(">=1.3,<2"))


def test_installed_engine_version_wraps_package_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _raise(_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(_compat.importlib.metadata, "version", _raise)

    with pytest.raises(_compat.CompatDataError, match="not installed"):
        _compat.installed_engine_version()


def test_installed_engine_version_wraps_an_invalid_version_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(_compat.importlib.metadata, "version", lambda _name: "not-a-version")

    with pytest.raises(_compat.CompatDataError, match="invalid"):
        _compat.installed_engine_version()
