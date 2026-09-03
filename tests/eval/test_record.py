"""Tests for the golden-set recorder CLI. Exercises --provider fake only -- this WP
never calls a real provider (CLAUDE.md: no network calls in tests)."""

import json
import shutil
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
# A fresh, clearly-fake AWS-access-key-shaped fixture -- same detector/convention as
# tests/review/fixtures/secret.patch and tests/review/test_secrets_gate.py, but its own
# distinct value (never the real email-reminders SendGrid key) so it needs its own
# .gitleaksignore entry rather than piggybacking on a line-pinned one elsewhere.
# noqa: S105 below - a fake test fixture diff, not a credential
_SECRET_DIFF = (
    "diff --git a/app/config.py b/app/config.py\n"  # noqa: S105
    "--- a/app/config.py\n"
    "+++ b/app/config.py\n"
    "@@ -1 +1,2 @@\n"
    " EXISTING = 1\n"
    '+AWS_ACCESS_KEY_ID = "AKIAZYXWVUTSRQPONMLK"\n'
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


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_record_response_never_calls_the_provider_when_a_secret_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mirrors reviewer.py's own context-scan pattern: the assembled egress payload is
    scanned for secrets before the provider is ever constructed/called. Regression test
    for the finding that record.py had no secrets-firewall check anywhere -- without this,
    recording a branch like feature/email-reminders would spend a real API call and
    transmit a secret-bearing payload, even though the real pipeline (run_review) never
    calls the provider for it (its deterministic-secret-detection branch fires first)."""

    def _explode(*_args: object, **_kwargs: object) -> None:
        pytest.fail("run_with_policy must never be called once a secret is detected")

    monkeypatch.setattr("py_attest.eval.record.run_with_policy", _explode)

    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(_SECRET_DIFF, encoding="utf-8")
    out_path = tmp_path / "provider_response.raw.json"

    with pytest.raises(RecordError, match="secrets firewall"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=out_path,
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )

    assert not out_path.exists()


def test_record_response_wraps_a_secrets_gate_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing gitleaks binary must be a loud RecordError, never a silent skip of the
    firewall (CLAUDE.md: "a missing gitleaks binary is exit 4, never a silent skip")."""
    diff_path = _write_diff(tmp_path)
    monkeypatch.setattr("py_attest.review.secrets_gate.shutil.which", lambda _name: None)

    with pytest.raises(RecordError, match="gitleaks executable not found"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_wraps_a_registry_error(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)
    # Malformed YAML, so it's used in place of the packaged default core standards and
    # load_registry() raises RegistryError before any egress/provider work happens.
    (tmp_path / "core.standards.yml").write_text("sections: [", encoding="utf-8")

    with pytest.raises(RecordError, match="invalid YAML"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
        )


def test_record_response_wraps_a_click_usage_error_for_an_unregistered_provider(
    tmp_path: Path,
) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="unknown provider"):
        record_response(
            diff_path=diff_path,
            provider_name="does-not-exist",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            repo_root=tmp_path,
        )


def test_record_response_wraps_a_click_usage_error_for_a_missing_fake_response(
    tmp_path: Path,
) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="--fake-response is required"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            repo_root=tmp_path,
        )


def test_record_response_wraps_a_prompt_error(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="unknown prompt version"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(FIXTURES / "record_response.json"),
            repo_root=tmp_path,
            prompt_version="does-not-exist",
        )


def test_record_response_wraps_a_provider_failure(tmp_path: Path) -> None:
    diff_path = _write_diff(tmp_path)

    with pytest.raises(RecordError, match="provider call failed"):
        record_response(
            diff_path=diff_path,
            provider_name="fake",
            egress_mode="raw",
            out_path=tmp_path / "out.json",
            config=Config(),
            fake_response=str(tmp_path / "missing-fixture.json"),
            repo_root=tmp_path,
        )
