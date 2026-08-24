from unittest.mock import AsyncMock, MagicMock

import pytest

from app.douyin import AmbiguousTargetError, DouyinChat, PageOperationError
from app.selectors import CHAT_HEADER_TITLES, CURRENT_CONVERSATIONS, MESSAGE_INPUTS


@pytest.mark.asyncio
async def test_search_failure_raises_without_page_text_or_real_name(monkeypatch) -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    search = MagicMock()
    search.click = AsyncMock()
    search.fill = AsyncMock()
    monkeypatch.setattr("app.douyin.first_visible", AsyncMock(return_value=search))
    chat = DouyinChat(page)
    chat._search_result = AsyncMock(return_value=None)

    with pytest.raises(PageOperationError, match="搜索不到目标好友") as exc_info:
        await chat._open_target_once("张三")

    message = str(exc_info.value)
    assert "当前页面文字" not in message
    assert "张三" not in message


@pytest.mark.asyncio
async def test_search_result_accepts_single_visible_exact_text() -> None:
    page = MagicMock()
    rows = MagicMock()
    page.locator.return_value.filter.return_value = rows
    rows.count = AsyncMock(return_value=0)
    exact = MagicMock()
    page.get_by_text.return_value = exact
    exact.count = AsyncMock(return_value=1)
    candidate = MagicMock()
    candidate.is_visible = AsyncMock(return_value=True)
    exact.nth.return_value = candidate

    result = await DouyinChat(page)._search_result("好友")

    assert result is candidate
    page.get_by_text.assert_called_once_with("好友", exact=True)


@pytest.mark.asyncio
async def test_search_result_rejects_multiple_visible_exact_matches() -> None:
    page = MagicMock()
    rows = MagicMock()
    page.locator.return_value.filter.return_value = rows
    rows.count = AsyncMock(return_value=0)
    exact = MagicMock()
    page.get_by_text.return_value = exact
    exact.count = AsyncMock(return_value=2)
    first = MagicMock()
    first.is_visible = AsyncMock(return_value=True)
    second = MagicMock()
    second.is_visible = AsyncMock(return_value=True)
    exact.nth.side_effect = [first, second]

    with pytest.raises(AmbiguousTargetError, match="多个同名"):
        await DouyinChat(page)._search_result("好友")


@pytest.mark.asyncio
async def test_search_panel_rejects_multiple_exact_friends(monkeypatch) -> None:
    page = MagicMock()
    search_items = MagicMock()
    search_items.count = AsyncMock(return_value=2)
    items = []
    for _ in range(2):
        button = MagicMock()
        button.count = AsyncMock(return_value=1)
        button.is_visible = AsyncMock(return_value=True)
        button_group = MagicMock()
        button_group.first = button
        item = MagicMock()
        item.locator.return_value = button_group
        items.append(item)
    search_items.nth.side_effect = lambda index: items[index]
    root = MagicMock()
    root.filter.return_value = search_items
    page.locator.return_value = root
    monkeypatch.setattr("app.douyin._contains_visible_exact_text", AsyncMock(return_value=True))

    with pytest.raises(AmbiguousTargetError, match="多个同名"):
        await DouyinChat(page)._search_result("好友")


@pytest.mark.asyncio
async def test_open_target_retries_after_failed_first_attempt() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)
    calls = {"n": 0}

    async def flaky(name: str) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise PageOperationError("首次失败")

    chat._open_target_once = flaky

    await chat.open_target("好友A", retries=1)

    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_open_target_raises_after_retries_exhausted() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page)

    async def fail(name: str) -> None:
        raise PageOperationError("始终失败")

    chat._open_target_once = fail

    with pytest.raises(PageOperationError, match="始终失败"):
        await chat.open_target("好友A", retries=1)

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_open_target_succeeds_without_retry() -> None:
    page = MagicMock()
    chat = DouyinChat(page)

    async def ok(name: str) -> None:
        return None

    chat._open_target_once = ok

    await chat.open_target("好友A", retries=1)

    page.wait_for_timeout.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_opened_polls_until_confirmed() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=5_000)
    results = iter([PageOperationError("未就绪"), None])

    async def checker(name: str):
        return next(results, None)

    chat._chat_open_error = checker

    await chat._confirm_opened("好友A")

    assert page.wait_for_timeout.await_count == 1


@pytest.mark.asyncio
async def test_confirm_opened_raises_on_timeout() -> None:
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    chat = DouyinChat(page, confirm_timeout_ms=100)

    async def checker(name: str):
        return PageOperationError("一直失败")

    chat._chat_open_error = checker

    with pytest.raises(PageOperationError, match="一直失败"):
        await chat._confirm_opened("好友A")


def _locator_group(*nodes) -> MagicMock:
    group = MagicMock()
    group.count = AsyncMock(return_value=len(nodes))
    group.nth.side_effect = lambda index: nodes[index]
    return group


def _routed_page(*, header_text: str | None, selected_name: str | None, composer_visible: bool) -> MagicMock:
    page = MagicMock()
    header = MagicMock()
    header.is_visible = AsyncMock(return_value=True)
    header.inner_text = AsyncMock(return_value=header_text or "")
    header_group = _locator_group(header) if header_text is not None else _locator_group()

    current = MagicMock()
    current.is_visible = AsyncMock(return_value=True)
    selected = MagicMock()
    selected.is_visible = AsyncMock(return_value=True)
    current.get_by_text.return_value = _locator_group(selected) if selected_name == "好友A" else _locator_group()
    current_group = _locator_group(current) if selected_name is not None else _locator_group()

    editor = MagicMock()
    editor.count = AsyncMock(return_value=1 if composer_visible else 0)
    editor.is_visible = AsyncMock(return_value=composer_visible)
    composer_group = MagicMock()
    composer_group.first = editor

    def locator_router(selector: str):
        if selector in CHAT_HEADER_TITLES:
            return header_group
        if selector in CURRENT_CONVERSATIONS:
            return current_group
        if selector in MESSAGE_INPUTS:
            return composer_group
        return _locator_group()

    page.locator.side_effect = locator_router
    return page


@pytest.mark.asyncio
async def test_chat_open_error_accepts_header_composer_and_selected_target() -> None:
    page = _routed_page(header_text="好友A", selected_name="好友A", composer_visible=True)

    chat = DouyinChat(page)

    assert await chat._chat_open_error("好友A") is None


@pytest.mark.asyncio
async def test_chat_open_accepts_selected_remark_when_header_uses_another_name() -> None:
    page = _routed_page(header_text="抖音昵称", selected_name="好友A", composer_visible=True)

    assert await DouyinChat(page)._chat_open_error("好友A") is None


@pytest.mark.asyncio
async def test_chat_open_error_rejects_name_outside_header() -> None:
    page = _routed_page(header_text=None, selected_name=None, composer_visible=True)

    chat = DouyinChat(page)

    error = await chat._chat_open_error("好友A")

    assert isinstance(error, PageOperationError)
    assert "无法确认目标会话" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_wrong_selected_conversation() -> None:
    page = _routed_page(header_text="好友A", selected_name="好友B", composer_visible=True)

    error = await DouyinChat(page)._chat_open_error("好友A")

    assert isinstance(error, PageOperationError)
    assert "选中会话: 不匹配" in str(error)
