"""eval-live.yml must be valid YAML with the shape the weekly job needs (workflow_dispatch
+ cron trigger, a raw/minimized egress matrix, no secrets available to fork PRs)."""

from pathlib import Path

import yaml

WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "eval-live.yml"


def test_eval_live_workflow_is_valid_yaml_with_the_expected_triggers() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))

    assert "workflow_dispatch" in workflow["on"]
    assert "schedule" in workflow["on"]
    assert workflow["on"]["schedule"][0]["cron"]


def test_eval_live_workflow_has_a_raw_minimized_egress_matrix() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    record_job = workflow["jobs"]["record-and-score"]

    assert set(record_job["strategy"]["matrix"]["egress"]) == {"raw", "minimized"}


def test_eval_live_workflow_needs_a_provider_key_secret() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    record_job = workflow["jobs"]["record-and-score"]
    rendered_steps = str(record_job["steps"])

    assert "OPENAI_API_KEY" in rendered_steps
    assert "secrets." in rendered_steps
