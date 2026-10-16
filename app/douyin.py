from __future__ import annotations

import asyncio
import re

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
        #
        # Identity must be resolved from the per-result name node, never from the
        # collection container: `[class*="SearchPanelitem"]` also matches an outer
        # `SearchPanelitems` wrapper, whose descendants would then contain the
        # target name while `.first` returns another row's button. Scope to result
        # rows and require the matched name node and its button to be visible here.
        search_items = self.page.locator('[class*="SearchPanelitembox"], [class*="SearchPanelitem-box"], [class*="SearchPanelitem_box"]')
        name_selectors = (
            '[class*="SearchPanelitemtitle"]',
            '[class*="SearchPanelitemTitle"]',
            '[class*="SearchPanelitem_title"]',
            '[class*="SearchPanelitem-title"]',
            '[class*="SearchPanelitemname"]',
            '[class*="SearchPanelitemName"]',
            '[class*="SearchPanelitem_name"]',
            '[class*="SearchPanelitem-name"]',
        )

        # Two-phase priority: an exact friend name always wins over a group whose
        # display name happens to start with it. Pass 1 scans every search row for
        # an exact name; only if none is found does pass 2 accept a group member
        # count suffix like "4161(7)" for target "4161". This ordering guarantees
        # "test" never returns "test(7)" or "test1".
        for matcher in (_visible_exact_text_locator, _visible_group_text_locator):
            search_buttons: list[Locator] = []
            for index in range(await search_items.count()):
                item = search_items.nth(index)
                if await matcher(item, name_selectors, name) is None:
                    continue
                button = item.locator('[class*="SearchPanelitemchat_btn"]').first
                try:
                    if await button.count() and await button.is_visible():
                        search_buttons.append(button)
                except Exception:
                    continue
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
        title_selectors = (
            '[class*="conversationConversationItemtitle"]',
            '[class*="ConversationItemtitle"]',
            '[class*="ConversationItemTitle"]',
            '[class*="conversation-item-title"]',
            '[class*="conversation-item-Title"]',
        )
        for matcher in (_visible_exact_text_locator, _visible_group_text_locator):
            for selector in row_selectors:
                rows = self.page.locator(selector)
                matching_rows: list[Locator] = []
                for index in range(await rows.count()):
                    row = rows.nth(index)
                    if await matcher(row, title_selectors, name) is None:
                        continue
                    try:
                        class_name = await row.get_attribute("class") or ""
                        is_row = "wrapper" in class_name or await row.get_attribute("data-e2e") == "conversation-item"
                        if is_row and await row.is_visible():
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
        # This hidden-title fallback stays STRICT exact only: a hidden stale name
        # node (group or plain) must never be trusted to resolve the recipient.
        hidden_titles = self.page.locator('[class*="conversationConversationItemtitle"]')
        for index in range(await hidden_titles.count()):
            title = hidden_titles.nth(index)
            if not await _text_equals(title, name):
                continue
            row = title.locator(
                "xpath=ancestor::*[contains(@class, 'conversationConversationItem')][1]"
            )
            if await row.count() and await row.is_visible():
                return row

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
            [await _locator_has_visible_exact_or_group_text(self.page.locator(selector), name) for selector in CHAT_HEADER_TITLES]
        )
        current_rows_seen = False
        current_matches = False
        title_selectors = (
            '[class*="conversationConversationItemtitle"]',
            '[class*="ConversationItemtitle"]',
            '[class*="ConversationItemTitle"]',
            '[class*="conversation-item-title"]',
            '[class*="conversation-item-Title"]',
        )
        for selector in CURRENT_CONVERSATIONS:
            visible_rows = await _visible_locators(self.page.locator(selector))
            if visible_rows:
                current_rows_seen = True
            for row in visible_rows:
                if await _contains_visible_exact_text(row, name) or await _visible_exact_or_group_text_in(row, title_selectors, name):
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


async def _visible_exact_text_in(container: Locator, selectors: tuple[str, ...], expected: str) -> bool:
    return await _visible_exact_text_locator(container, selectors, expected) is not None


async def _visible_exact_text_locator(
    container: Locator, selectors: tuple[str, ...], expected: str
) -> Locator | None:
    for selector in selectors:
        nodes = container.locator(selector)
        for index in range(await nodes.count()):
            node = nodes.nth(index)
            if await _text_equals(node, expected):
                try:
                    if await node.is_visible():
                        return node
                except Exception:
                    continue
    return None


async def _visible_group_text_locator(
    container: Locator, selectors: tuple[str, ...], expected: str
) -> Locator | None:
    # Second-phase match for group chats: accepts a trailing "(N)"/"（N）"
    # member count. Only reached after the exact pass found nothing, so a bare
    # "test" never reaches here when an exact "test" row exists.
    for selector in selectors:
        nodes = container.locator(selector)
        for index in range(await nodes.count()):
            node = nodes.nth(index)
            if await _group_name_matches(node, expected):
                try:
                    if await node.is_visible():
                        return node
                except Exception:
                    continue
    return None


async def _visible_exact_or_group_text_in(
    container: Locator, selectors: tuple[str, ...], expected: str
) -> bool:
    # Chat-header confirmation: an exact title wins; otherwise a group member
    # count suffix also confirms. The node must be visible in both cases, so a
    # hidden stale title node can never confirm the wrong recipient.
    if await _visible_exact_text_locator(container, selectors, expected) is not None:
        return True
    return await _visible_group_text_locator(container, selectors, expected) is not None


async def _has_exact_text_in(container: Locator, selectors: tuple[str, ...], expected: str) -> bool:
    for selector in selectors:
        if await _has_exact_text(container.locator(selector), expected):
            return True
    return False


async def _has_exact_text(locators: Locator, expected: str) -> bool:
    for index in range(await locators.count()):
        if await _text_equals(locators.nth(index), expected):
            return True
    return False


async def _text_equals(locator: Locator, expected: str) -> bool:
    try:
        return (await locator.inner_text(timeout=500)).strip() == expected
    except Exception:
        return False


# Matches a group chat display name: the configured target name optionally
# followed by exactly one pair of brackets containing a pure member count,
# e.g. "4161" / "4161(7)" / "4161（123）". This is an INDEPENDENT helper kept
# separate from _text_equals so the friend exact-match semantics stay strict:
# it must never let "test" match "test1" (no trailing brackets to legitimize a
# longer name). re.fullmatch anchors both ends; re.escape makes the name literal.
_GROUP_COUNT_SUFFIX_RE_TEMPLATE = r"{name}\s*[\(（]\s*\d+\s*[\)）]"


def _group_count_suffix_matches(actual: str, expected: str) -> bool:
    actual = actual.strip()
    expected = expected.strip()
    if actual == expected:
        return True
    pattern = _GROUP_COUNT_SUFFIX_RE_TEMPLATE.format(name=re.escape(expected))
    return re.fullmatch(pattern, actual) is not None


async def _group_name_matches(locator: Locator, expected: str) -> bool:
    try:
        return _group_count_suffix_matches(
            await locator.inner_text(timeout=500), expected
        )
    except Exception:
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


async def _locator_has_visible_exact_or_group_text(group: Locator, expected: str) -> bool:
    normalized = _normalize_text(expected)
    for candidate in await _visible_locators(group):
        try:
            if _group_count_suffix_matches(_normalize_text(await candidate.inner_text()), normalized):
                return True
        except Exception:
            continue
    return False


async def _contains_visible_exact_text(container: Locator, expected: str) -> bool:
    exact = container.get_by_text(expected, exact=True)
    return bool(await _visible_locators(exact))


def _normalize_text(value: str) -> str:
    return " ".join(value.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "").split())
