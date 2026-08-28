from pathlib import Path

import yaml


WORKFLOW_PATH = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "send.yml"


def test_send_workflow_scopes_and_removes_secrets() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    job = workflow["jobs"]["send"]
    assert all("secrets." not in str(value) for value in job.get("env", {}).values())

    steps = job["steps"]
    named_steps = {step.get("name"): step for step in steps if step.get("name")}
    write_step = named_steps["Write protected configuration"]
    run_step = named_steps["Run"]
    cleanup_step = named_steps["Remove protected configuration"]

    assert set(write_step["env"]) == {
        "DOUYIN_CONFIG",
        "DOUYIN_STORAGE_STATE",
        "DOUYIN_STORAGE_STATE_GZIP_BASE64",
    }
    assert set(run_step["env"]) == {
        "DOUYIN_COOKIE",
        "DINGTALK_WEBHOOK",
        "DINGTALK_SECRET",
        "WECOM_WEBHOOK",
    }
    assert cleanup_step["if"] == "always()"
    assert steps.index(cleanup_step) < steps.index(named_steps["Upload redacted diagnostics"])


def test_send_workflow_has_guarded_fallback_schedules() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(content)

    assert content.count('timezone: "Asia/Shanghai"') == 5
    for hour in (5, 6, 8, 10, 12):
        assert f'cron: "24 {hour} * * *"' in content

    guard = workflow["jobs"]["guard"]
    send = workflow["jobs"]["send"]
    assert guard["permissions"] == {"actions": "read", "contents": "read"}
    assert send["needs"] == "guard"
    assert send["if"] == "needs.guard.outputs.should_run == 'true'"
    assert 'run["status"] == "completed"' in content
    assert 'run["conclusion"] != "cancelled"' in content
