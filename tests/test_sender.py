from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models import Message
from app.douyin import PageOperationError
from app.sender import (
    OUTGOING_MESSAGES,
    DeliveryProbe,
    DeliveryUnconfirmedError,
    LATEST_OUTGOING_MESSAGE,
    SEND_BUTTONS,
    _click_and_confirm_sticker,
    _confirm_outgoing_message,
    _confirm_sticker_sent,
    _latest_outgoing_message_identity,
    _publish_ready,
    _restore_composer,
    _send_control_ready,
    _sticker_resource_key,
    _trigger_send,
    _wait_for_composer_cleared,
    confirm_delivery_persisted,
    confirm_delivery_settled,
    send_message,
    send_text,
)


@pytest.mark.asyncio
async def test_random_message_delegates_to_selected_choice(monkeypatch) -> None:
    editor = AsyncMock()
    page = MagicMock()
    message_items = MagicMock()
    message_items.count = AsyncMock(return_value=0)
    missing_first = MagicMock()
    missing_first.count = AsyncMock(return_value=0)
    message_items.first = missing_first
    page.locator.return_value = message_items
    page.keyboard.insert_text = AsyncMock()
    page.keyboard.press = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    editor.page = page
    chat = AsyncMock()
    chat.message_input.return_value = editor
    text = Message(type="text", content="你好")
    message = Message(type="random", choices=(text,))
    monkeypatch.setattr("app.sender.random.choice", lambda choices: choices[0])
    monkeypatch.setattr("app.sender._latest_outgoing_message_identity", AsyncMock(return_value="previous-id"))
    monkeypatch.setattr("app.sender._mark_latest_outgoing_message", AsyncMock(return_value=("anchor", "")))
    monkeypatch.setattr("app.sender._wait_for_composer_cleared", AsyncMock())
    monkeypatch.setattr("app.sender._confirm_outgoing_message", AsyncMock())

    probe = await send_message(page, chat, message, {})

    assert probe == DeliveryProbe(expected_text="你好", previous_message_id="previous-id")
    page.keyboard.insert_text.assert_awaited_once_with("你好")
    page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_trigger_send_clicks_publish_button_when_visible() -> None:
    page = MagicMock()
    button = MagicMock()
    button.count = AsyncMock(return_value=1)
    button.is_visible = AsyncMock(return_value=True)
    button.is_enabled = AsyncMock(return_value=True)
    button.get_attribute = AsyncMock(return_value=None)
    button.click = AsyncMock()
    publish = MagicMock()
    publish.first = button
    missing_loc = MagicMock()
    missing_first = MagicMock()
    missing_first.count = AsyncMock(return_value=0)
    missing_loc.first = missing_first
    page.locator.side_effect = lambda selector: publish if selector == SEND_BUTTONS[0] else missing_loc

    await _trigger_send(page)

    button.click.assert_awaited_once_with()
    page.keyboard.press.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_send_falls_back_to_enter() -> None:
    page = MagicMock()
    missing = MagicMock()
    missing.first = MagicMock()
    missing.first.count = AsyncMock(return_value=0)
    page.locator.return_value = missing
    page.keyboard.press = AsyncMock()

    await _trigger_send(page)

    page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_trigger_send_ignores_disabled_button() -> None:
    page = MagicMock()
    button = MagicMock()
    button.count = AsyncMock(return_value=1)
    button.is_visible = AsyncMock(return_value=True)
    button.is_enabled = AsyncMock(return_value=False)
    publish = MagicMock()
    publish.first = button
    missing = MagicMock()
    missing.first = MagicMock()
    missing.first.count = AsyncMock(return_value=0)
    page.locator.side_effect = lambda selector: publish if selector == SEND_BUTTONS[0] else missing
    page.keyboard.press = AsyncMock()

    await _trigger_send(page)

    button.click.assert_not_called()
    page.keyboard.press.assert_awaited_once_with("Enter")


@pytest.mark.asyncio
async def test_publish_ready_true_when_button_visible() -> None:
    page = MagicMock()
    button = MagicMock()
    button.count = AsyncMock(return_value=1)
    button.is_visible = AsyncMock(return_value=True)
    button.is_enabled = AsyncMock(return_value=True)
    button.get_attribute = AsyncMock(return_value=None)
    publish = MagicMock()
    publish.first = button
    missing = MagicMock()
    missing.first = MagicMock()
    missing.first.count = AsyncMock(return_value=0)
    page.locator.side_effect = lambda selector: publish if selector == SEND_BUTTONS[0] else missing

    assert await _publish_ready(page) is True


@pytest.mark.asyncio
async def test_send_control_rejects_aria_disabled() -> None:
    control = MagicMock()
    control.count = AsyncMock(return_value=1)
    control.is_visible = AsyncMock(return_value=True)
    control.is_enabled = AsyncMock(return_value=True)
    control.get_attribute = AsyncMock(return_value="true")

    assert await _send_control_ready(control) is False


@pytest.mark.asyncio
async def test_confirm_delivery_persisted_requires_latest_matching_message() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock()
    probe = DeliveryProbe(expected_text="睡觉", previous_message_id="previous-id")

    await confirm_delivery_persisted(page, probe)

    assert page.wait_for_function.await_args.kwargs["arg"] == [
        OUTGOING_MESSAGES,
        "睡觉",
        "text",
        "previous-id",
    ]
    assert "currentMessageId === previousMessageId" in page.wait_for_function.await_args.args[0]
    assert page.wait_for_function.await_args.kwargs["timeout"] == 30_000


@pytest.mark.asyncio
async def test_confirm_delivery_persisted_reports_unconfirmed() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock(side_effect=TimeoutError)

    with pytest.raises(DeliveryUnconfirmedError, match="发送结果待确认"):
        await confirm_delivery_persisted(page, DeliveryProbe(expected_text="睡觉"))


@pytest.mark.asyncio
async def test_confirm_delivery_settled_rechecks_after_stability_delay() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock()
    probe = DeliveryProbe(expected_text="睡觉", previous_message_id="previous-id")

    await confirm_delivery_settled(page, probe)

    assert page.wait_for_function.await_args.kwargs["arg"] == [
        OUTGOING_MESSAGES,
        "睡觉",
        "text",
        "previous-id",
    ]
    assert page.wait_for_function.await_args.kwargs["timeout"] == 5_000


@pytest.mark.asyncio
async def test_latest_outgoing_message_identity_reads_virtual_item_id() -> None:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value="message-id")

    assert await _latest_outgoing_message_identity(page) == "message-id"
    assert page.evaluate.await_args.args[1] == OUTGOING_MESSAGES


@pytest.mark.asyncio
async def test_latest_outgoing_message_identity_requires_existing_message() -> None:
    page = MagicMock()
    page.evaluate = AsyncMock(return_value="")

    assert await _latest_outgoing_message_identity(page) == ""


@pytest.mark.asyncio
async def test_sticker_click_retries_via_publish_when_staged(monkeypatch) -> None:
    item = MagicMock()
    item.get_attribute = AsyncMock(return_value=None)
    item.click = AsyncMock()
    img_first = MagicMock()
    img_first.count = AsyncMock(return_value=0)
    img_loc = MagicMock()
    img_loc.first = img_first
    item.locator.return_value = img_loc
    page = MagicMock()
    calls = {"confirm": 0, "publish": 0}

    async def fake_confirm(_page, _before, _name, _key=""):
        calls["confirm"] += 1
        if calls["confirm"] == 1:
            raise PageOperationError("未检测到新的已发送消息")
        return None

    async def fake_trigger(_page):
        calls["publish"] += 1

    async def fake_ready(_page):
        return True

    monkeypatch.setattr("app.sender._confirm_sticker_sent", fake_confirm)
    monkeypatch.setattr("app.sender._trigger_send", fake_trigger)
    monkeypatch.setattr("app.sender._publish_ready", fake_ready)

    await _click_and_confirm_sticker(page, item, ("anchor", "old"), "比心")

    assert calls["confirm"] == 2
    assert calls["publish"] == 1


@pytest.mark.asyncio
async def test_sticker_click_raises_when_not_staged(monkeypatch) -> None:
    item = MagicMock()
    item.get_attribute = AsyncMock(return_value=None)
    item.click = AsyncMock()
    img_first = MagicMock()
    img_first.count = AsyncMock(return_value=0)
    img_loc = MagicMock()
    img_loc.first = img_first
    item.locator.return_value = img_loc
    page = MagicMock()

    async def fake_confirm(_page, _before, _name, _key=""):
        raise PageOperationError("未检测到新的已发送消息")

    async def fake_trigger(_page):
        raise AssertionError("不应触发发送")

    async def fake_ready(_page):
        return False

    monkeypatch.setattr("app.sender._confirm_sticker_sent", fake_confirm)
    monkeypatch.setattr("app.sender._trigger_send", fake_trigger)
    monkeypatch.setattr("app.sender._publish_ready", fake_ready)

    with pytest.raises(PageOperationError):
        await _click_and_confirm_sticker(page, item, ("anchor", "old"), "比心")


@pytest.mark.asyncio
async def test_missing_sticker_mapping_fails() -> None:
    with pytest.raises(Exception, match="没有原生表情映射"):
        await send_message(AsyncMock(), AsyncMock(), Message(type="douyin_sticker", sticker="比心"), {})


@pytest.mark.asyncio
async def test_image_message_requires_path() -> None:
    with pytest.raises(Exception, match="缺少文件路径"):
        await send_message(AsyncMock(), AsyncMock(), Message(type="image", path=None), {})


@pytest.mark.asyncio
async def test_sticker_confirmation_waits_for_new_matching_outgoing_message() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    latest_group = MagicMock()
    latest = MagicMock()
    latest_group.first = latest
    marker_group = MagicMock()
    marker = MagicMock()
    marker_group.first = marker
    marker.count = AsyncMock(return_value=0)
    latest.locator.return_value = marker_group
    anchors = MagicMock()
    anchors.evaluate_all = AsyncMock()
    page.locator.side_effect = lambda selector: latest_group if selector == LATEST_OUTGOING_MESSAGE else anchors

    await _confirm_sticker_sent(page, ("anchor", "old-content"), "比心", "resource-key")

    assert page.wait_for_function.await_args.kwargs["arg"] == [
        LATEST_OUTGOING_MESSAGE,
        "anchor",
        "old-content",
        "resource-key",
        "",
    ]
    page.wait_for_timeout.assert_awaited_once_with(5_000)


@pytest.mark.asyncio
async def test_sticker_confirmation_reports_page_send_failure() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    latest_group = MagicMock()
    latest = MagicMock()
    latest_group.first = latest
    marker_group = MagicMock()
    marker = MagicMock()
    marker_group.first = marker
    marker.count = AsyncMock(return_value=1)
    marker.is_visible = AsyncMock(return_value=True)
    latest.locator.return_value = marker_group
    anchors = MagicMock()
    anchors.evaluate_all = AsyncMock()
    page.locator.side_effect = lambda selector: latest_group if selector == LATEST_OUTGOING_MESSAGE else anchors

    with pytest.raises(PageOperationError, match="发送失败"):
        await _confirm_sticker_sent(page, ("anchor", "old-content"), "比心")


@pytest.mark.asyncio
async def test_sticker_confirmation_reports_missing_new_message() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock(side_effect=TimeoutError)
    anchors = MagicMock()
    anchors.evaluate_all = AsyncMock()
    page.locator.return_value = anchors

    with pytest.raises(PageOperationError, match="没有检测到新的已发送消息"):
        await _confirm_sticker_sent(page, ("anchor", "old-content"), "比心")


@pytest.mark.asyncio
async def test_sticker_resource_key_ignores_signed_query_string() -> None:
    item = MagicMock()
    item.get_attribute = AsyncMock(
        return_value="https://p26-sign.douyinpic.com/obj/im-resource/sticker-key?x-signature=temporary"
    )

    assert await _sticker_resource_key(item) == "sticker-key"


@pytest.mark.asyncio
async def test_confirm_outgoing_message_waits_for_expected_text() -> None:
    page = MagicMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    latest_group = MagicMock()
    latest = MagicMock()
    latest_group.first = latest
    marker_group = MagicMock()
    marker = MagicMock()
    marker_group.first = marker
    marker.count = AsyncMock(return_value=0)
    latest.locator.return_value = marker_group
    anchors = MagicMock()
    anchors.evaluate_all = AsyncMock()
    page.locator.side_effect = lambda selector: latest_group if selector == LATEST_OUTGOING_MESSAGE else anchors

    await _confirm_outgoing_message(page, ("anchor", "old-content"), "文字", expected_text="测试文字")

    assert page.wait_for_function.await_args.kwargs["arg"] == [
        LATEST_OUTGOING_MESSAGE,
        "anchor",
        "old-content",
        "",
        "测试文字",
    ]


@pytest.mark.asyncio
async def test_send_text_confirms_outgoing_message_without_retry(monkeypatch) -> None:
    page = MagicMock()
    page.keyboard.insert_text = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    editor = MagicMock()
    editor.click = AsyncMock()
    editor.page = page
    chat = MagicMock()
    chat.message_input = AsyncMock(return_value=editor)
    calls = {"trigger": 0, "composer": 0, "confirm": 0}

    async def fake_mark(_page):
        return ("anchor", "old-content")

    async def fake_trigger(_page):
        calls["trigger"] += 1

    async def fake_composer(editor_arg, content):
        calls["composer"] += 1
        assert editor_arg is editor
        assert content == "你好"

    async def fake_confirm(_page, before, label, resource_key="", expected_text=""):
        calls["confirm"] += 1
        assert before == ("anchor", "old-content")
        assert label == "文字"
        assert expected_text == "你好"

    monkeypatch.setattr("app.sender._mark_latest_outgoing_message", fake_mark)
    monkeypatch.setattr("app.sender._trigger_send", fake_trigger)
    monkeypatch.setattr("app.sender._wait_for_composer_cleared", fake_composer)
    monkeypatch.setattr("app.sender._confirm_outgoing_message", fake_confirm)

    await send_text(chat, "你好")

    assert calls["trigger"] == 1
    assert calls["composer"] == 1
    assert calls["confirm"] == 1


@pytest.mark.asyncio
async def test_wait_for_composer_cleared_requires_text_to_disappear() -> None:
    editor = MagicMock()
    editor.evaluate = AsyncMock(side_effect=["你好", ""])
    editor.page = MagicMock()
    editor.page.wait_for_timeout = AsyncMock()

    await _wait_for_composer_cleared(editor, "你好", timeout_ms=200)

    assert editor.evaluate.await_count == 2


@pytest.mark.asyncio
async def test_wait_for_composer_cleared_rejects_unsent_text() -> None:
    editor = MagicMock()
    editor.evaluate = AsyncMock(return_value="你好")
    editor.page = MagicMock()
    editor.page.wait_for_timeout = AsyncMock()

    with pytest.raises(PageOperationError, match="输入框未清空"):
        await _wait_for_composer_cleared(editor, "你好", timeout_ms=200)


@pytest.mark.asyncio
async def test_send_text_does_not_confirm_when_composer_stays_filled(monkeypatch) -> None:
    page = MagicMock()
    page.keyboard.insert_text = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    editor = MagicMock()
    editor.click = AsyncMock()
    editor.page = page
    chat = MagicMock()
    chat.message_input = AsyncMock(return_value=editor)
    confirm = AsyncMock()

    monkeypatch.setattr("app.sender._mark_latest_outgoing_message", AsyncMock(return_value=("anchor", "old")))
    monkeypatch.setattr("app.sender._trigger_send", AsyncMock())
    monkeypatch.setattr(
        "app.sender._wait_for_composer_cleared",
        AsyncMock(side_effect=PageOperationError("点击发送后输入框未清空，消息未发送")),
    )
    monkeypatch.setattr("app.sender._confirm_outgoing_message", confirm)

    with pytest.raises(PageOperationError, match="消息未发送"):
        await send_text(chat, "你好")

    confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_text_raises_when_confirmation_fails(monkeypatch) -> None:
    page = MagicMock()
    page.keyboard.insert_text = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.wait_for_timeout = AsyncMock()
    editor = MagicMock()
    editor.click = AsyncMock()
    editor.page = page
    chat = MagicMock()
    chat.message_input = AsyncMock(return_value=editor)

    monkeypatch.setattr("app.sender._mark_latest_outgoing_message", AsyncMock(return_value=("anchor", "")))
    monkeypatch.setattr("app.sender._trigger_send", AsyncMock())
    monkeypatch.setattr("app.sender._wait_for_composer_cleared", AsyncMock())

    async def fail(_page, *_args, **_kwargs):
        raise PageOperationError("文字已发送，但没有检测到新的已发送消息")

    monkeypatch.setattr("app.sender._confirm_outgoing_message", fail)

    with pytest.raises(PageOperationError, match="没有检测到新的已发送消息"):
        await send_text(chat, "你好")


@pytest.mark.asyncio
async def test_restore_composer_presses_escape_and_focuses(monkeypatch) -> None:
    page = MagicMock()
    page.keyboard.press = AsyncMock()
    editor = MagicMock()
    editor.click = AsyncMock()
    editor.focus = AsyncMock()
    monkeypatch.setattr("app.sender.first_visible", AsyncMock(return_value=editor))

    await _restore_composer(page)

    page.keyboard.press.assert_awaited_once_with("Escape")
    editor.click.assert_awaited_once()
    editor.focus.assert_awaited_once()
