import base64
import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.config import ConfigError, load_settings
from app.models import TargetResult
from app.notifier import (
    WECOM_MAX_MARKDOWN_BYTES,
    _signed_webhook_url,
    _validated_wecom_webhook_url,
    build_dingtalk_markdown,
    send_wecom_notification,
)


def test_signed_webhook_url_uses_dingtalk_hmac() -> None:
    timestamp = 1700000000123
    secret = "SEC-test-secret"
    url = _signed_webhook_url(
        "https://oapi.dingtalk.com/robot/send?access_token=token",
        secret,
        timestamp_ms=timestamp,
    )

    query = parse_qs(urlsplit(url).query)
    expected = base64.b64encode(
        hmac.new(secret.encode(), f"{timestamp}\n{secret}".encode(), hashlib.sha256).digest()
    ).decode()
    assert query["access_token"] == ["token"]
    assert query["timestamp"] == [str(timestamp)]
    assert query["sign"] == [expected]


@pytest.mark.parametrize(
    "webhook",
    [
        "http://oapi.dingtalk.com/robot/send?access_token=token",
        "https://example.com/robot/send?access_token=token",
        "file:///tmp/webhook",
    ],
)
def test_signed_webhook_url_rejects_untrusted_destinations(webhook: str) -> None:
    with pytest.raises(ValueError, match="oapi.dingtalk.com"):
        _signed_webhook_url(webhook, "SEC-test-secret")


def test_validates_wecom_webhook() -> None:
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"

    assert _validated_wecom_webhook_url(webhook) == webhook


@pytest.mark.parametrize(
    "webhook",
    [
        "http://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key",
        "https://example.com/cgi-bin/webhook/send?key=test-key",
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send",
        "https://qyapi.weixin.qq.com/other?key=test-key",
    ],
)
def test_rejects_untrusted_wecom_webhook(webhook: str) -> None:
    with pytest.raises(ValueError, match="企业微信官方群机器人地址"):
        _validated_wecom_webhook_url(webhook)


@pytest.mark.asyncio
async def test_sends_wecom_markdown_within_size_limit(monkeypatch) -> None:
    to_thread = AsyncMock()
    monkeypatch.setattr("app.notifier.asyncio.to_thread", to_thread)
    webhook = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=test-key"
    results = [TargetResult(target=f"好友{index}", status="failed", error="失败" * 500) for index in range(20)]

    await send_wecom_notification(webhook, "daily-streak", False, results, [])

    _, called_webhook, payload, provider = to_thread.await_args.args
    assert called_webhook == webhook
    assert provider == "企业微信"
    assert payload["msgtype"] == "markdown"
    assert len(payload["markdown"]["content"].encode("utf-8")) <= WECOM_MAX_MARKDOWN_BYTES


def test_markdown_lists_successes_failures_and_screenshots(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.setenv("UPLOAD_SENSITIVE_DIAGNOSTICS", "true")
    results = [
        TargetResult(target="好友A", status="success", sent=2),
        TargetResult(target="好友B", status="failed", sent=1, error="发送失败\n请重试"),
    ]

    title, markdown = build_dingtalk_markdown(
        "daily-streak",
        False,
        results,
        [Path("artifacts/screenshots/friend-b.png")],
        finished_at=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
    )

    assert title == "抖音自动发送：存在失败"
    assert "完成时间**：2026-08-09 16:00:00 +0800" in markdown
    assert "成功名单（1）" in markdown
    assert "**好友A** - 已确认发送 2 条" in markdown
    assert "失败名单（1）" in markdown
    assert "**好友B**，已触发 1 条" in markdown
    assert "发送失败 请重试" in markdown
    assert "`friend-b.png`" in markdown
    assert "https://github.com/owner/repo/actions/runs/123" in markdown


def test_markdown_marks_unverified_delivery_as_pending() -> None:
    title, markdown = build_dingtalk_markdown(
        "daily-streak",
        False,
        [TargetResult(target="好友A", status="unknown", sent=1)],
        [],
        finished_at=datetime(2026, 8, 9, 8, 0, tzinfo=timezone.utc),
    )

    assert title == "抖音自动发送：发送结果待确认"
    assert "结果**：成功 0 人，待确认 1 人，失败 0 人" in markdown
    assert "待确认名单（1）" in markdown
    assert "**好友A** - 已触发 1 条，送达未确认" in markdown
    assert "已发送" not in markdown


def test_markdown_does_not_link_sensitive_artifacts_by_default(monkeypatch) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_RUN_ID", "123")
    monkeypatch.delenv("UPLOAD_SENSITIVE_DIAGNOSTICS", raising=False)

    _, markdown = build_dingtalk_markdown(
        "daily-streak",
        False,
        [TargetResult(target="好友A", status="failed", error="发送失败")],
        [Path("artifacts/screenshots/friend-a.png")],
    )

    assert "https://github.com/owner/repo/actions/runs/123" not in markdown


def test_dingtalk_webhook_and_secret_must_be_configured_together(monkeypatch) -> None:
    monkeypatch.setenv("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=token")
    monkeypatch.delenv("DINGTALK_SECRET", raising=False)

    with pytest.raises(ConfigError, match="必须同时配置"):
        load_settings()


def test_markdown_shows_real_name_even_with_alias() -> None:
    results = [
        TargetResult(target="张三", status="success", sent=1, target_alias="好友01"),
        TargetResult(target="李四", status="failed", sent=0, error="搜索不到目标好友", target_alias="好友02"),
    ]

    _, markdown = build_dingtalk_markdown("daily-streak", False, results, [])

    assert "张三" in markdown
    assert "李四" in markdown
    assert "好友01" not in markdown
    assert "好友02" not in markdown


def test_markdown_escapes_dynamic_text_and_limits_large_lists() -> None:
    results = [
        TargetResult(target=f"好友*[{index}]", status="failed", error="`失败`" * 200)
        for index in range(100)
    ]

    _, markdown = build_dingtalk_markdown("task_*", False, results, [])

    assert r"task\_\*" in markdown
    assert r"好友\*\[0\]" in markdown
    assert "其余 85 人已省略" in markdown
    assert len(markdown.encode("utf-8")) <= 18_000
