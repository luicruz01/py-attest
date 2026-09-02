"""Tests for the golden-set recorder CLI. Exercises --provider fake only -- this WP
never calls a real provider (CLAUDE.md: no network calls in tests)."""

import json
from pathlib import Path

import pytest

from py_attest.config import Config
from py_attest.eval.record import RecordError, main, record_response

FIXTURES = Path(__file__).parent / "fixtures"
DIFF = (
    "diff --git a/app/main.py b/app/main.py\n"
    "--- a/app/main.py\n"
    "+++ b/app/main.py\n"
    "@@ -1,1 +1,2 @@\n"
    " x\n"
    "+y\n"
)


def _write_diff(tmp_path: Path) -> Path:
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(DIFF, encoding="utf-8")
    return diff_path


def test_record_response_writes_the_provider_raw_json_verbatim(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"

    record_response(
        diff_path=diff_path,
        provider_name="fake",
        egress_mode="raw",
        out_path=out_path,
        config=Config(),
        fake_response=str(FIXTURES / "record_response.json"),
        repo_root=tmp_path,
        branch="feature/example",
    )

    assert json.loads(out_path.read_text(encoding="utf-8")) == {"findings": [], "summary": "clean"}


def test_record_response_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"
    out_path.write_text("{}", encoding="utf-8")

    with pytest.raises(RecordError, match="already exists"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=out_path,
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_overwrites_when_forced(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"
    out_path.write_text("{}", encoding="utf-8")

    record_response(
        diff_path=diff_path,
        provider_name="fake",
        egress_mode="raw",
        out_path=out_path,
        config=Config(),
        fake_response=str(FIXTURES / "record_response.json"),
        repo_root=tmp_path,
        force=True,
    )

    assert json.loads(out_path.read_text(encoding="utf-8"))["summary"] == "clean"


def test_record_response_rejects_an_unknown_egress_mode(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="egress"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="bogus",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_raises_when_the_diff_file_is_missing(tmp_path: Path) -> None:
    with pytest.raises(RecordError, match="cannot read diff"):
        record_response(
            diff_path=tmp_path / "missing.patch",
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_main_writes_the_recording_and_returns_zero(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    out_path = tmp_path / "provider_response.raw.json"

    exit_code = main(
        [
            "--diff",
            str(diff_path),
            "--provider",
            "fake",
            "--fake-response",
            str(FIXTURES / "record_response.json"),
            "--egress",
            "raw",
            "--out",
            str(out_path),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    assert out_path.is_file()


def test_main_returns_two_on_a_record_error(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--diff",
            str(tmp_path / "missing.patch"),
            "--provider",
            "fake",
            "--fake-response",
            str(FIXTURES / "record_response.json"),
            "--egress",
            "raw",
            "--out",
            str(tmp_path / "out.json"),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert exit_code == 2
