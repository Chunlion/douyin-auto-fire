from pathlib import Path
import subprocess
import os
import shutil

import pytest

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
        "DOUYIN_PREVENT_DUPLICATES",
        "DINGTALK_WEBHOOK",
        "DINGTALK_SECRET",
        "WECOM_WEBHOOK",
        "WEBHOOK_URL",
        "WEBHOOK_HEADERS",
        "WEBHOOK_TEMPLATE",
    }
    assert cleanup_step["if"] == "always()"
    assert steps.index(cleanup_step) < steps.index(named_steps["Upload redacted diagnostics"])


def test_send_workflow_has_configurable_recovery_schedule() -> None:
    content = WORKFLOW_PATH.read_text(encoding="utf-8")
    workflow = yaml.safe_load(content)

    assert 'cron: "8-53/15 * * * *"' in content
    assert "vars.DOUYIN_SCHEDULE_TIME || '05:24'" in content
    assert "vars.DOUYIN_SCHEDULE_TIMEZONE || 'Asia/Shanghai'" in content

    guard = workflow["jobs"]["guard"]
    send = workflow["jobs"]["send"]
    assert send["needs"] == "guard"
    assert send["if"] == "needs.guard.outputs.should_run == 'true'"
    assert "actions/cache/restore@55cc8345863c7cc4c66a329aec7e433d2d1c52a9" in content
    assert "actions/cache/save@55cc8345863c7cc4c66a329aec7e433d2d1c52a9" in content
    assert "douyin-sent-${{ needs.guard.outputs.run_date }}" in content
    assert "douyin-history-v2-${{ needs.guard.outputs.run_date }}-${{ github.run_id }}" in content


@pytest.mark.parametrize(
    ("due", "already_sent", "skip_date", "expected"),
    [
        ("true", "false", "2026-10-16", "false"),
        ("true", "false", "2026-10-15", "true"),
        ("true", "false", "", "true"),
        ("false", "false", "", "false"),
        ("true", "true", "", "false"),
    ],
)
def test_schedule_decision_respects_skip_date(tmp_path, due, already_sent, skip_date, expected):
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["guard"]["steps"] if step.get("id") == "decision")
    bash = str(Path(shutil.which("git")).resolve().parents[1] / "bin" / "bash.exe") if os.name == "nt" else "bash"
    output = tmp_path / "output"
    subprocess.run(
        [bash, "-c", step["run"]],
        check=True,
        capture_output=True,
        env={**os.environ, "EVENT_NAME": "schedule", "DUE": due, "ALREADY_SENT": already_sent,
             "RUN_DATE": "2026-10-16", "SKIP_DATE": skip_date, "GITHUB_OUTPUT": output.as_posix()},
    )
    assert output.read_text().strip() == f"should_run={expected}"
