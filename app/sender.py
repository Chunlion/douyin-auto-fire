from __future__ import annotations

import random
import secrets
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Page

from app.douyin import DouyinChat, PageOperationError, first_visible
from app.models import Message, Sticker
from app.selectors import IMAGE_INPUTS, MESSAGE_INPUTS, STICKER_BUTTONS, STICKER_PANELS


SEND_BUTTONS = (
    '[class*="messageMsgInputpublishBtn"]',
    '.e2e-send-msg-bt',
    'button[aria-label*="发送"]',
    '[role="button"][aria-label*="发送"]',
)


async def _trigger_send(page: Page) -> None:
    button = None
    for selector in SEND_BUTTONS:
        candidate = page.locator(selector).first
        try:
            if await _send_control_ready(candidate):
                button = candidate
                break
        except Exception:
            continue
    if button is not None:
        await button.click()
    else:
        await page.keyboard.press("Enter")


async def _publish_ready(page: Page) -> bool:
    for selector in SEND_BUTTONS:
        candidate = page.locator(selector).first
        try:
            if await _send_control_ready(candidate):
                return True
        except Exception:
            continue
    return False


async def _send_control_ready(control) -> bool:
    if not await control.count() or not await control.is_visible() or not await control.is_enabled():
        return False
    return await control.get_attribute("aria-disabled") != "true"


LATEST_OUTGOING_MESSAGE = (
    '.messageMessageListlist [data-index="0"] '
    '.messageMessageBoxmessageBox:has(.messageMessageBoxcontentBox.messageMessageBoxisFromMe)'
)
OUTGOING_MESSAGES = (
    '.messageMessageListlist [data-index] '
    '.messageMessageBoxmessageBox:has(.messageMessageBoxcontentBox.messageMessageBoxisFromMe)'
)
MESSAGE_CONFIRM_ANCHOR = "data-douyin-sender-anchor"
SEND_FAILURE_MARKERS = (
    "text=发送失败",
    '[aria-label*="重试"]',
    '[title*="重试"]',
    '[class*="sendFailed"]',
    '[class*="SendFailed"]',
)


class DeliveryUnconfirmedError(PageOperationError):
    pass


@dataclass(frozen=True)
class DeliveryProbe:
    expected_text: str
    before_count: int
    kind: str = "text"


async def send_message(
    page: Page,
    chat: DouyinChat,
    message: Message,
    stickers: dict[str, Sticker],
) -> DeliveryProbe:
    if message.type == "random":
        return await send_message(page, chat, random.choice(message.choices), stickers)
    if message.type == "text":
        probe = await _capture_delivery_probe(page, message.content or "", kind="text")
        await send_text(chat, message.content or "")
        return probe
    if message.type == "image":
        if message.path is None:
            raise PageOperationError("图片消息缺少文件路径")
        probe = await _capture_delivery_probe(page, kind="media")
        await send_image(page, message.path.as_posix())
        return probe
    if message.type == "douyin_sticker":
        sticker = stickers.get(message.sticker or "")
        if sticker is None:
            raise PageOperationError(f"没有原生表情映射: {message.sticker}")
        probe = await _capture_delivery_probe(page, kind="media")
        await send_douyin_sticker(page, sticker)
        return probe
    raise PageOperationError(f"不支持的消息类型: {message.type}")


async def _capture_delivery_probe(page: Page, expected_text: str = "", kind: str = "text") -> DeliveryProbe:
    counts: list[int] = []
    for sample in range(3):
        counts.append(await _count_outgoing_messages(page, expected_text, kind))
        if sample < 2:
            await page.wait_for_timeout(500)
    return DeliveryProbe(
        expected_text=expected_text,
        before_count=max(counts),
        kind=kind,
    )


async def _count_outgoing_messages(page: Page, expected_text: str = "", kind: str = "text") -> int:
    return await page.locator(OUTGOING_MESSAGES).evaluate_all(
        """(messages, [expected, kind]) => {
            const normalize = value => (value || '').replace(/[\\s\\u200B\\u200C\\u200D\\uFEFF]+/g, ' ').trim();
            return messages.filter(message => {
                const content = message.querySelector('[data-e2e="msg-item-content"]') || message;
                const failed = normalize(message.innerText).includes('发送失败') ||
                    !!message.querySelector('[aria-label*="重试"], [title*="重试"], [class*="sendFailed"], [class*="SendFailed"]');
                if (failed) return false;
                if (kind === 'media') return !!content.querySelector('img, video');
                return normalize(content.innerText) === normalize(expected);
            }).length;
        }""",
        [expected_text, kind],
    )


async def confirm_delivery_persisted(page: Page, probe: DeliveryProbe, timeout_ms: int = 30_000) -> None:
    try:
        await page.wait_for_function(
            """([selector, expected, kind]) => {
                const normalize = value => (value || '').replace(/[\\s\\u200B\\u200C\\u200D\\uFEFF]+/g, ' ').trim();
                const message = document.querySelector(selector);
                if (!message) return false;
                const content = message.querySelector('[data-e2e="msg-item-content"]') || message;
                const failed = normalize(message.innerText).includes('发送失败') ||
                    !!message.querySelector('[aria-label*="重试"], [title*="重试"], [class*="sendFailed"], [class*="SendFailed"]');
                if (failed) return false;
                if (kind === 'media') return !!content.querySelector('img, video');
                return normalize(content.innerText) === normalize(expected);
            }""",
            arg=[OUTGOING_MESSAGES, probe.expected_text, probe.kind],
            timeout=timeout_ms,
        )
    except Exception as exc:
        raise DeliveryUnconfirmedError("重新加载会话后未检测到服务器保存的新增消息，发送结果待确认") from exc


async def send_text(chat: DouyinChat, content: str) -> None:
    editor = await chat.message_input()
    page = editor.page
    await editor.click()
    await page.keyboard.insert_text(content)
    try:
        await page.wait_for_function(
            """([txt]) => {
                const es = [...document.querySelectorAll('[class*=messageEditor] [contenteditable=true], .messageEditorinputArea')];
                return es.some(e => (e.innerText || '').includes(txt));
            }""",
            arg=[content],
            timeout=5_000,
        )
    except Exception as exc:
        raise PageOperationError("文字未能写入聊天输入框") from exc

    before = await _mark_latest_outgoing_message(page)
    await page.wait_for_timeout(300)
    await _trigger_send(page)
    await _wait_for_composer_cleared(editor, content)
    await _confirm_outgoing_message(page, before, label="文字", expected_text=content)


async def _wait_for_composer_cleared(editor, expected_text: str, timeout_ms: int = 5_000) -> None:
    attempts = max(1, timeout_ms // 100)
    normalized_expected = _normalize_text(expected_text)
    for _ in range(attempts):
        try:
            current = await editor.evaluate("element => element.innerText || element.textContent || ''")
            if normalized_expected not in _normalize_text(current):
                return
        except Exception:
            pass
        await editor.page.wait_for_timeout(100)
    raise PageOperationError("点击发送后输入框未清空，消息未发送")


def _normalize_text(value: str | None) -> str:
    return " ".join((value or "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").split())


async def send_image(page: Page, image_path: str) -> None:
    message_items = page.locator('[data-e2e="msg-item-content"]')
    before = await message_items.count()
    file_input = None
    for selector in IMAGE_INPUTS:
        candidate = page.locator(selector).first
        if await candidate.count():
            file_input = candidate
            break
    if file_input is None:
        raise PageOperationError("找不到图片上传控件")
    await file_input.set_input_files(image_path)
    await page.wait_for_timeout(1_500)

    await _trigger_send(page)
    try:
        await page.wait_for_function(
            """([selector, count]) => document.querySelectorAll(selector).length > count""",
            arg=['[data-e2e="msg-item-content"]', before],
            timeout=15_000,
        )
    except Exception as exc:
        raise PageOperationError("图片消息已触发发送，但无法确认是否发送成功；为避免重复不会自动重试") from exc


async def _restore_composer(page: Page, timeout_ms: int = 10_000) -> None:
    try:
        await page.keyboard.press("Escape")
    except Exception:
        pass
    try:
        editor = await first_visible(page, MESSAGE_INPUTS, timeout_ms)
    except Exception:
        return
    try:
        await editor.click(timeout=timeout_ms)
        await editor.focus()
    except Exception:
        pass


async def send_douyin_sticker(page: Page, sticker: Sticker) -> None:
    before = await _mark_latest_outgoing_message(page)
    try:
        button = await first_visible(page, STICKER_BUTTONS)
        await button.click(force=True)
        panel = await first_visible(page, STICKER_PANELS)

        if sticker.category:
            category = panel.get_by_text(sticker.category, exact=True)
            if await category.count() and await category.first.is_visible():
                await category.first.click()

        name = sticker.accessible_name or sticker.name
        item = panel.locator('.emojiEmojiItememojiItem').filter(has_text=name)
        for index in range(await item.count()):
            candidate = item.nth(index)
            description = candidate.locator('.emojiEmojiItememojiItemDesc')
            if await description.count() and (await description.first.inner_text()).strip() == name:
                await _click_and_confirm_sticker(page, candidate, before, name)
                return

        candidates = (
            panel.get_by_role("img", name=name, exact=True),
            panel.get_by_role("button", name=name, exact=True),
            panel.locator(f'[aria-label="{_css_escape(name)}"]'),
            panel.locator(f'[title="{_css_escape(name)}"]'),
            panel.locator(f'[alt="{_css_escape(name)}"]'),
        )
        for candidate in candidates:
            if await candidate.count() and await candidate.first.is_visible():
                await _click_and_confirm_sticker(page, candidate.first, before, name)
                return

        if sticker.fallback_index is not None:
            items = panel.locator('[role="button"], img, [aria-label], [title]')
            if await items.count() > sticker.fallback_index:
                await _click_and_confirm_sticker(page, items.nth(sticker.fallback_index), before, name)
                return
        raise PageOperationError(f"在抖音表情面板中找不到原生表情: {sticker.name}")
    finally:
        await _restore_composer(page)


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def _mark_latest_outgoing_message(page: Page) -> tuple[str, str]:
    anchor = secrets.token_hex(8)
    latest = page.locator(LATEST_OUTGOING_MESSAGE).first
    if not await latest.count():
        return anchor, ""

    content = latest.locator('[data-e2e="msg-item-content"]').first
    before_content = await content.inner_html() if await content.count() else await latest.inner_html()
    await latest.evaluate(
        "(element, value) => element.setAttribute('data-douyin-sender-anchor', value)",
        anchor,
    )
    return anchor, before_content


async def _click_and_confirm_sticker(page: Page, item, before: tuple[str, str], name: str) -> None:
    resource_key = await _sticker_resource_key(item)
    await item.click(force=True)
    try:
        await _confirm_sticker_sent(page, before, name, resource_key)
    except PageOperationError:
        if await _publish_ready(page):
            await _trigger_send(page)
            await _confirm_sticker_sent(page, before, name, resource_key)
        else:
            raise


async def _sticker_resource_key(item) -> str:
    src = await item.get_attribute("src")
    if not src:
        image = item.locator("img").first
        if await image.count():
            src = await image.get_attribute("src")
    if not src:
        return ""
    return urlsplit(src).path.rsplit("/", 1)[-1]


async def _confirm_sticker_sent(
    page: Page,
    before: tuple[str, str],
    name: str,
    resource_key: str = "",
) -> None:
    await _confirm_outgoing_message(page, before, f"原生表情“{name}”", resource_key=resource_key)


async def _confirm_outgoing_message(
    page: Page,
    before: tuple[str, str],
    label: str,
    resource_key: str = "",
    expected_text: str = "",
) -> None:
    anchor, before_content = before
    try:
        await page.wait_for_function(
            """([selector, anchor, previousContent, expectedResource, expectedText]) => {
                const message = document.querySelector(selector);
                if (!message) return false;
                const content = message.querySelector('[data-e2e="msg-item-content"]') || message;
                const markerChanged = message.getAttribute('data-douyin-sender-anchor') !== anchor;
                const contentChanged = content.innerHTML !== previousContent;
                const isNewMessage = markerChanged && (expectedText || expectedResource || contentChanged);
                if (!isNewMessage) return false;
                if (expectedText) {
                    const normalize = value => (value || '').replace(/[\\s\\u200B\\u200C\\u200D\\uFEFF]+/g, ' ').trim();
                    return normalize(content.innerText).includes(normalize(expectedText));
                }
                if (!expectedResource) return true;
                const images = [...content.querySelectorAll('img')];
                return images.some(image => (image.src || '').includes(expectedResource)) || images.length > 0;
            }""",
            arg=[LATEST_OUTGOING_MESSAGE, anchor, before_content, resource_key, expected_text],
            timeout=15_000,
        )
        await page.wait_for_timeout(5_000)
        latest = page.locator(LATEST_OUTGOING_MESSAGE).first
        for selector in SEND_FAILURE_MARKERS:
            marker = latest.locator(selector).first
            if await marker.count() and await marker.is_visible():
                raise PageOperationError(f"{label}发送失败，页面提示可以重试")
    except PageOperationError:
        raise
    except Exception as exc:
        raise PageOperationError(f"未确认{label}已发送：没有检测到新的已发送消息") from exc
    finally:
        anchors = page.locator(f"[{MESSAGE_CONFIRM_ANCHOR}]")
        try:
            await anchors.evaluate_all(
                "elements => elements.forEach(element => element.removeAttribute('data-douyin-sender-anchor'))"
            )
        except Exception:
            pass
