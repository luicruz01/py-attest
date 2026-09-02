import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from py_attest.review import secrets_gate
from py_attest.review.postfilter import filter_findings


@pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks is not installed")
def test_reviewed_repo_cannot_disable_the_firewall_with_its_own_gitleaks_config(
    tmp_path: Path,
) -> None:
    """A malicious PR must not be able to ship a `.gitleaks.toml`/`.gitleaksignore` that
    silently disables secret detection -- the whole diff would then reach the LLM
    provider with the secret still in it. Regression test for a real bypass found in
    review: gitleaks auto-discovers config from its cwd, and `repo_root` (the reviewed
    repo) used to be that cwd.
    """
    (tmp_path / ".gitleaks.toml").write_text(
        "[allowlist]\nregexes = ['''.*''']\n", encoding="utf-8"
    )
    (tmp_path / ".gitleaksignore").write_text("*:aws-access-token:*\n", encoding="utf-8")
    diff = (
        "diff --git a/app/config.py b/app/config.py\n"
        "--- a/app/config.py\n"
        "+++ b/app/config.py\n"
        "@@ -0,0 +1,1 @@\n"
        '+AWS_ACCESS_KEY_ID = "AKIAABCDEFGHIJKLMNOP"\n'
    )

    findings = secrets_gate.findings_for_diff(diff, tmp_path)

    assert len(findings) == 1
    assert findings[0]["rule"] == "5-secrets"


def test_gitleaks_receives_exact_diff_and_only_redacted_fields_survive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = (
        "diff --git a/app/config.py b/app/config.py\n"
        "--- a/app/config.py\n"
        "+++ b/app/config.py\n"
        "@@ -1 +1 @@\n"
        "-TOKEN = None\n"
        "+TOKEN = 'do-not-report-this-text'\n"
    )
    captured: dict[str, Any] = {}
    report = [
        {
            "RuleID": "generic-api-key",
            "StartLine": 6,
            "File": "",
            "Match": "TOKEN = 'REDACTED'",
            "Secret": "REDACTED",
        }
    ]

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = command
        captured.update(kwargs)
        return subprocess.CompletedProcess(command, 1, json.dumps(report), "")

    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(secrets_gate.subprocess, "run", fake_run)

    findings = secrets_gate.findings_for_diff(diff, tmp_path)

    assert captured["input"] == diff
    assert "--redact=100" in captured["command"]
    assert findings[0]["file"] == "app/config.py"
    assert findings[0]["line"] == 1
    assert findings[0]["rule"] == "5-secrets"
    assert findings[0]["severity"] == "S1"
    assert findings[0]["confidence"] == "high"
    assert findings[0]["evidence"] == "TOKEN"
    assert "do-not-report-this-text" not in json.dumps(findings)


def test_bare_secret_uses_minimal_grounded_evidence_without_losing_block(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bare_value = "do-not-report-this-bare-value"
    diff = (
        "diff --git a/app/config.py b/app/config.py\n"
        "--- /dev/null\n"
        "+++ b/app/config.py\n"
        "@@ -0,0 +1 @@\n"
        f"+{bare_value}\n"
    )
    report = [{"RuleID": "generic-api-key", "StartLine": 5, "Secret": "REDACTED"}]

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, json.dumps(report), "")

    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(secrets_gate.subprocess, "run", fake_run)

    findings = secrets_gate.findings_for_diff(diff, tmp_path)
    filtered = filter_findings({"findings": findings, "summary": "secret"}, diff)

    assert findings[0]["evidence"] == bare_value[0]
    assert bare_value not in json.dumps(findings)
    assert len(filtered["findings"]) == 1
    assert filtered["filtered_out"] == []


def test_findings_for_diff_raises_when_gitleaks_binary_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: None)

    with pytest.raises(secrets_gate.SecretsGateError, match="gitleaks executable not found"):
        secrets_gate.findings_for_diff("diff", tmp_path)


def test_findings_for_diff_raises_on_unexpected_return_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(
        secrets_gate.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 2, "", "boom"),
    )

    with pytest.raises(secrets_gate.SecretsGateError, match="exit code 2"):
        secrets_gate.findings_for_diff("diff", tmp_path)


def test_findings_for_diff_raises_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(
        secrets_gate.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 1, "{not json", ""),
    )

    with pytest.raises(secrets_gate.SecretsGateError, match="invalid JSON report"):
        secrets_gate.findings_for_diff("diff", tmp_path)


def test_findings_for_diff_raises_when_report_is_not_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(
        secrets_gate.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 1, json.dumps({}), ""),
    )

    with pytest.raises(secrets_gate.SecretsGateError, match="invalid JSON report"):
        secrets_gate.findings_for_diff("diff", tmp_path)


def test_findings_for_diff_raises_when_a_leak_entry_is_not_an_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(
        secrets_gate.subprocess,
        "run",
        lambda command, **_kw: subprocess.CompletedProcess(command, 1, json.dumps(["oops"]), ""),
    )

    with pytest.raises(secrets_gate.SecretsGateError, match="invalid leak entry"):
        secrets_gate.findings_for_diff("diff", tmp_path)


@pytest.mark.parametrize(
    ("target_line", "diff", "expected"),
    [
        (None, "+x\n", "<redacted secret evidence>"),
        (5, "+x\n", "<redacted secret evidence>"),
        (1, "-removed\n", "<redacted secret evidence>"),
        (1, "+++ b/f\n", "<redacted secret evidence>"),
        (1, "+TOKEN=value\n", "TOKEN"),
        (1, "+1=2\n", "="),
        (1, "+1:2\n", ":"),
        (1, "+   \n", "<redacted secret evidence>"),
    ],
)
def test_safe_evidence_for_diff_line_edge_cases(
    target_line: int | None, diff: str, expected: str
) -> None:
    assert secrets_gate._safe_evidence_for_diff_line(diff, target_line) == expected


def test_fallback_file_prefers_the_gitleaks_reported_file() -> None:
    assert secrets_gate._fallback_file("diff --git a/x b/x\n", "a/x") == "x"


def test_fallback_file_falls_back_to_the_first_file_in_the_diff() -> None:
    diff = "diff --git a/z.py b/z.py\n--- a/z.py\n+++ b/z.py\n"
    assert secrets_gate._fallback_file(diff, None) == "z.py"


def test_fallback_file_returns_a_placeholder_when_nothing_is_known() -> None:
    assert secrets_gate._fallback_file("", None) == "<diff>"


def test_location_for_diff_line_returns_none_for_none_target() -> None:
    assert secrets_gate._location_for_diff_line("+x\n", None) == (None, None)


def test_location_for_diff_line_resolves_a_deleted_line() -> None:
    diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,1 @@\n-old\n context\n"
    file_name, line = secrets_gate._location_for_diff_line(diff, 4)
    assert file_name == "f"
    assert line == 1


def test_location_for_diff_line_resolves_a_context_line() -> None:
    diff = "--- a/f\n+++ b/f\n@@ -1,2 +1,2 @@\n context\n+added\n"
    file_name, line = secrets_gate._location_for_diff_line(diff, 4)
    assert file_name == "f"
    assert line == 1


def test_location_for_diff_line_beyond_the_diff_falls_back_to_last_known_file() -> None:
    diff = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    assert secrets_gate._location_for_diff_line(diff, 99) == ("f", None)


def test_location_for_diff_line_pointing_at_a_header_line_has_no_source_line() -> None:
    diff = "--- a/f\n+++ b/f\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    assert secrets_gate._location_for_diff_line(diff, 1) == ("f", None)


def test_positive_int_rejects_non_positive_and_non_int_values() -> None:
    assert secrets_gate._positive_int(0) is None
    assert secrets_gate._positive_int(-1) is None
    assert secrets_gate._positive_int(True) is None
    assert secrets_gate._positive_int("5") is None


def test_findings_for_diff_falls_back_to_file_in_diff_when_start_line_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    diff = "diff --git a/app/config.py b/app/config.py\n--- a/app/config.py\n+++ b/app/config.py\n"
    report = [{"RuleID": "generic-api-key"}]

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, json.dumps(report), "")

    monkeypatch.setattr(secrets_gate.shutil, "which", lambda _name: "/usr/bin/gitleaks")
    monkeypatch.setattr(secrets_gate.subprocess, "run", fake_run)

    findings = secrets_gate.findings_for_diff(diff, tmp_path)

    assert findings[0]["file"] == "app/config.py"
    assert findings[0]["line"] is None
