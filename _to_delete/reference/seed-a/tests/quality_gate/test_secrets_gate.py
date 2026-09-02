import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tools.quality_gate import secrets_gate
from tools.quality_gate.postfilter import filter_findings


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
