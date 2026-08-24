from __future__ import annotations

import asyncio

from playwright.async_api import Locator, Page

from app.selectors import CHAT_HEADER_TITLES, CURRENT_CONVERSATIONS, MESSAGE_INPUTS, SEARCH_INPUTS


class PageOperationError(RuntimeError):
    pass


class AmbiguousTargetError(PageOperationError):
    pass


RETRY_DELAY_MS = 3_000


class DouyinChat:
    def __init__(
        self,
        page: Page,
        timeout_ms: int = 15_000,
        confirm_timeout_ms: int = 15_000,
    ) -> None:
        self.page = page
        self.timeout_ms = timeout_ms
        self.confirm_timeout_ms = confirm_timeout_ms

    async def open_target(self, name: str, retries: int = 1) -> None:
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                await self._open_target_once(name)
                return
            except Exception as exc:
                last_error = exc
                if attempt < retries:
                    await self.page.wait_for_timeout(RETRY_DELAY_MS)
        if last_error is not None:
            raise last_error
        raise PageOperationError("打开聊天失败")

    async def _open_target_once(self, name: str) -> None:
        search = await first_visible(self.page, SEARCH_INPUTS, self.timeout_ms)
        await search.click()
        await search.fill("")
        await search.fill(name)
        await self.page.wait_for_timeout(1_500)

        result = await self._search_result(name)
        if result is None:
            raise PageOperationError("搜索不到目标好友")
        await result.click(force=True)
        await self._confirm_opened(name)

    async def _search_result(self, name: str) -> Locator | None:
        # Search mode renders a separate SearchPanel. Its "发消息" action is the
        # correct control; clicking the hidden conversation cache does not mount
        # the composer.
        search_items = self.page.locator('[class*="SearchPanelitem"]').filter(has_text=name)
        search_buttons: list[Locator] = []
        for index in range(await search_items.count()):
            item = search_items.nth(index)
            if not await _contains_visible_exact_text(item, name):
                continue
            button = item.locator('[class*="SearchPanelitemchat_btn"]').first
            if await button.count() and await button.is_visible():
                search_buttons.append(button)
        if len(search_buttons) > 1:
            raise AmbiguousTargetError("搜索结果存在多个同名好友，无法安全选择")
        if search_buttons:
            return search_buttons[0]

        # The nickname node can be hidden while its conversation row is visible.
        # Locate and click the complete row instead of relying on text visibility.
        row_selectors = (
            '[data-e2e="conversation-item"]',
            '[class*="conversationConversationItem"]',
            '[class*="conversation-item"]',
            '[class*="ConversationItem"]',
        )
        for selector in row_selectors:
            rows = self.page.locator(selector).filter(has_text=name)
            matching_rows: list[Locator] = []
            for index in range(await rows.count()):
                row = rows.nth(index)
                try:
                    class_name = await row.get_attribute("class") or ""
                    is_row = "wrapper" in class_name or await row.get_attribute("data-e2e") == "conversation-item"
                    if is_row and await row.is_visible() and await _contains_visible_exact_text(row, name):
                        matching_rows.append(row)
                except Exception:
                    continue
            if len(matching_rows) > 1:
                raise AmbiguousTargetError("会话列表存在多个同名好友，无法安全选择")
            if matching_rows:
                return matching_rows[0]

        exact = self.page.get_by_text(name, exact=True)
        visible = await _visible_locators(exact)
        if len(visible) > 1:
            raise AmbiguousTargetError("页面存在多个同名候选项，无法安全选择")
        if visible:
            return visible[0]

        # Some Douyin builds render the title itself as hidden, but keep a visible
        # ancestor as the actionable result. Find that ancestor from the hidden title.
        hidden_titles = self.page.locator('[class*="conversationConversationItemtitle"]').filter(has_text=name)
        for index in range(await hidden_titles.count()):
            row = hidden_titles.nth(index).locator(
                "xpath=ancestor::*[contains(@class, 'conversationConversationItem')][1]"
            )
            if await row.count() and await row.is_visible():
                return row

        for selector in (f'[title="{_css_escape(name)}"]', f'[aria-label="{_css_escape(name)}"]'):
            candidate = self.page.locator(selector).first
            if await candidate.count() and await candidate.is_visible():
                return candidate
        return None

    async def message_input(self) -> Locator:
        return await first_visible(self.page, MESSAGE_INPUTS, self.timeout_ms)

    async def _confirm_opened(self, name: str, timeout_ms: int | None = None) -> None:
        timeout = timeout_ms if timeout_ms is not None else self.confirm_timeout_ms
        deadline = asyncio.get_running_loop().time() + timeout / 1000
        while True:
            last_error = await self._chat_open_error(name)
            if last_error is None:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise last_error
            await self.page.wait_for_timeout(500)

    async def _chat_open_error(self, name: str) -> PageOperationError | None:
        composer_visible = await self._composer_visible()
        header_matches = any(
            [await _locator_has_visible_exact_text(self.page.locator(selector), name) for selector in CHAT_HEADER_TITLES]
        )
        current_rows_seen = False
        current_matches = False
        for selector in CURRENT_CONVERSATIONS:
            rows = self.page.locator(selector)
            visible_rows = await _visible_locators(rows)
            if visible_rows:
                current_rows_seen = True
            for row in visible_rows:
                if await _contains_visible_exact_text(row, name):
                    current_matches = True
                    break
            if current_matches:
                break
        identity_matches = current_matches if current_rows_seen else header_matches
        if composer_visible and identity_matches:
            return None
        current_status = "匹配" if current_matches else "不匹配" if current_rows_seen else "未检测"
        return PageOperationError(
            "点击搜索结果后无法确认目标会话"
            f"（输入框: {'有' if composer_visible else '无'}，"
            f"会话标题: {'匹配' if header_matches else '不匹配'}，"
            f"选中会话: {current_status}）"
        )

    async def _composer_visible(self) -> bool:
        for selector in MESSAGE_INPUTS:
            locator = self.page.locator(selector).first
            try:
                if await locator.count() and await locator.is_visible():
                    return True
            except Exception:
                continue
        return False


async def first_visible(page: Page, selectors: tuple[str, ...], timeout_ms: int = 15_000) -> Locator:
    per_selector = max(500, timeout_ms // max(1, len(selectors)))
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=per_selector)
            return locator
        except Exception:
            continue
    raise PageOperationError(f"找不到页面元素，已尝试: {', '.join(selectors)}")


def _css_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


async def _visible_locators(group: Locator) -> list[Locator]:
    visible: list[Locator] = []
    for index in range(await group.count()):
        candidate = group.nth(index)
        try:
            if await candidate.is_visible():
                visible.append(candidate)
        except Exception:
            continue
    return visible


async def _locator_has_visible_exact_text(group: Locator, expected: str) -> bool:
    normalized = _normalize_text(expected)
    for candidate in await _visible_locators(group):
        try:
            if _normalize_text(await candidate.inner_text()) == normalized:
                return True
        except Exception:
            continue
    return False


async def _contains_visible_exact_text(container: Locator, expected: str) -> bool:
    exact = container.get_by_text(expected, exact=True)
    return bool(await _visible_locators(exact))


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").split())
