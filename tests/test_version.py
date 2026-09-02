import importlib
from importlib.metadata import PackageNotFoundError

import pytest

import py_attest


def test_falls_back_to_0_0_0_when_package_metadata_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_not_found(name: str) -> str:
        raise PackageNotFoundError(name)

    monkeypatch.setattr("importlib.metadata.version", raise_not_found)
    importlib.reload(py_attest)
    assert py_attest.__version__ == "0.0.0"

    monkeypatch.undo()
    importlib.reload(py_attest)
