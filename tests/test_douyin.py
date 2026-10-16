from unittest.mock import AsyncMock, MagicMock

import pytest

from app.douyin import AmbiguousTargetError, DouyinChat, PageOperationError, _group_count_suffix_matches
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


def _locator_group(items: list[MagicMock]) -> MagicMock:
    group = MagicMock()
    group.count = AsyncMock(return_value=len(items))
    group.nth.side_effect = lambda index: items[index]
    if items:
        group.first = items[0]
    else:
        empty = MagicMock()
        empty.count = AsyncMock(return_value=0)
        empty.is_visible = AsyncMock(return_value=False)
        group.first = empty
    return group


def _search_page(names: list[str]) -> tuple[MagicMock, list[MagicMock]]:
    page = MagicMock()
    empty = _locator_group([])
    items: list[MagicMock] = []
    buttons: list[MagicMock] = []

    for displayed_name in names:
        name_node = MagicMock()
        name_node.inner_text = AsyncMock(return_value=f" {displayed_name} ")
        name_node.is_visible = AsyncMock(return_value=True)
        exact_names = _locator_group([name_node])
        button = MagicMock(name=f"message-{displayed_name}")
        button.count = AsyncMock(return_value=1)
        button.is_visible = AsyncMock(return_value=True)
        button_group = _locator_group([button])
        item = MagicMock()
        item.is_visible = AsyncMock(return_value=True)

        def item_locator(
            selector: str,
            *,
            button_group=button_group,
            exact_names=exact_names,
        ):
            if selector == '[class*="SearchPanelitemchat_btn"]':
                return button_group
            if selector == '[class*="SearchPanelitemname"]':
                return exact_names
            return empty

        item.locator.side_effect = item_locator
        items.append(item)
        buttons.append(button)

    search_items = _locator_group(items)

    def page_locator(selector: str):
        if selector == '[class*="SearchPanelitembox"], [class*="SearchPanelitem-box"], [class*="SearchPanelitem_box"]':
            return search_items
        return empty

    page.locator.side_effect = page_locator
    page.get_by_text.return_value = empty
    return page, buttons


@pytest.mark.asyncio
async def test_search_result_selects_exact_name_when_one_name_contains_another() -> None:
    page, buttons = _search_page(["test1", "test"])

    result = await DouyinChat(page)._search_result("test")

    assert result is buttons[1]


@pytest.mark.asyncio
async def test_search_result_selects_longer_exact_name() -> None:
    page, buttons = _search_page(["test1", "test"])

    result = await DouyinChat(page)._search_result("test1")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_keeps_normal_exact_match_working() -> None:
    page, buttons = _search_page(["好友A"])

    result = await DouyinChat(page)._search_result("好友A")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_accepts_group_count_suffix() -> None:
    # Group chats render as "<name>(<member count>)" in the search panel, e.g.
    # target "4161" is displayed as "4161(7)". The strict exact match alone would
    # reject this and break group sending.
    page, buttons = _search_page(["4161(7)"])

    result = await DouyinChat(page)._search_result("4161")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_accepts_fullwidth_group_count_suffix() -> None:
    page, buttons = _search_page(["4161（7）"])

    result = await DouyinChat(page)._search_result("4161")

    assert result is buttons[0]


@pytest.mark.asyncio
async def test_search_result_prefers_exact_name_over_group_suffix() -> None:
    # When both an exact "test" and a group-suffixed "test(7)" exist, the exact
    # friend must win even though "test(7)" sorts first. A naive single-pass
    # suffix check would wrongly return the group row.
    page, buttons = _search_page(["test(7)", "test"])

    result = await DouyinChat(page)._search_result("test")

    assert result is buttons[1]


@pytest.mark.asyncio
async def test_search_result_rejects_non_digit_group_suffix() -> None:
    # "(abc)" is not a member count; must not match target "test".
    page, _buttons = _search_page(["test(abc)"])

    result = await DouyinChat(page)._search_result("test")

    assert result is None


@pytest.mark.asyncio
async def test_search_result_rejects_containing_name_for_group_rule() -> None:
    # The group-suffix rule must not reintroduce the test/test1 mis-routing:
    # "test1" has no trailing member-count brackets, so it must be rejected.
    page, _buttons = _search_page(["test1"])

    result = await DouyinChat(page)._search_result("test")

    assert result is None


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


def _chat_page(
    header_name: str,
    *,
    input_count: int = 1,
    header_selector: str = CHAT_HEADER_TITLES[0],
    header_visible: bool = True,
    name_visible: bool = True,
    stale_name: str | None = None,
) -> MagicMock:
    page = MagicMock()
    empty = _locator_group([])
    header_name_node = MagicMock()
    header_name_node.inner_text = AsyncMock(return_value=f" {header_name} ")
    header_name_node.is_visible = AsyncMock(return_value=name_visible)
    nodes = [header_name_node]
    if stale_name is not None:
        stale_node = MagicMock()
        stale_node.inner_text = AsyncMock(return_value=f" {stale_name} ")
        stale_node.is_visible = AsyncMock(return_value=False)
        nodes.append(stale_node)
    if not header_visible:
        for node in nodes:
            node.is_visible = AsyncMock(return_value=False)
    header_group = _locator_group(nodes)

    composer_target = MagicMock()
    composer_target.count = AsyncMock(return_value=input_count)
    composer_target.is_visible = AsyncMock(return_value=bool(input_count))
    composer = MagicMock()
    composer.first = composer_target

    def locator_router(selector: str):
        if selector == header_selector:
            return header_group
        if selector in MESSAGE_INPUTS:
            return composer
        return empty

    page.locator.side_effect = locator_router
    return page


@pytest.mark.asyncio
async def test_chat_open_error_accepts_exact_name_in_each_header_fallback() -> None:
    for header_selector in CHAT_HEADER_TITLES[:3]:
        page = _chat_page("好友A", header_selector=header_selector)

        error = await DouyinChat(page)._chat_open_error("好友A")

        assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_exact_header_name() -> None:
    page = _chat_page("test", header_visible=False)

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_containing_header_name() -> None:
    page = _chat_page("test1")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认目标会话" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_stale_name_in_visible_header() -> None:
    # Visible current chat is `test1`, but the header retains a hidden stale name
    # node equal to the requested `test`. The hidden stale node must not confirm
    # the wrong recipient; only a visible exact title node may.
    page = _chat_page("test1", stale_name="test")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认目标会话" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_accepts_group_count_suffix_in_header() -> None:
    # Right-side group chat header shows "4161(7)" while the configured target
    # is bare "4161". Confirmation must succeed so group chats can be sent.
    page = _chat_page("4161(7)")

    error = await DouyinChat(page)._chat_open_error("4161")

    assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_accepts_fullwidth_group_count_suffix_in_header() -> None:
    page = _chat_page("4161（7）")

    error = await DouyinChat(page)._chat_open_error("4161")

    assert error is None


@pytest.mark.asyncio
async def test_chat_open_error_still_rejects_containing_header_name() -> None:
    # The group rule must not weaken the test/test1 guard: a header "test1" must
    # not confirm target "test" (no trailing member-count brackets).
    page = _chat_page("test1")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_hidden_stale_group_name_in_visible_header() -> None:
    # Visible current chat is "test1" but the header retains a hidden stale
    # node "test(7)". The hidden stale node must not confirm target "test";
    # only a visible title node may confirm. This preserves the stale-header
    # safety check under the new group-suffix logic.
    page = _chat_page("test1", stale_name="test(7)")

    error = await DouyinChat(page)._chat_open_error("test")

    assert isinstance(error, PageOperationError)
    assert "无法确认目标会话" in str(error)


@pytest.mark.asyncio
async def test_chat_open_error_rejects_when_header_name_absent() -> None:
    page = _chat_page("其他好友", input_count=0)

    error = await DouyinChat(page)._chat_open_error("好友A")

    assert isinstance(error, PageOperationError)
    assert "无法确认目标会话" in str(error)


def test_group_count_suffix_matches_accepts_bare_name() -> None:
    assert _group_count_suffix_matches("4161", "4161")


def test_group_count_suffix_matches_accepts_halfwidth_suffix() -> None:
    assert _group_count_suffix_matches("4161(7)", "4161")


def test_group_count_suffix_matches_accepts_fullwidth_suffix() -> None:
    assert _group_count_suffix_matches("4161（123）", "4161")


def test_group_count_suffix_matches_accepts_internal_spaces() -> None:
    assert _group_count_suffix_matches("4161 ( 7 )", "4161")


def test_group_count_suffix_matches_rejects_non_digit_suffix() -> None:
    assert not _group_count_suffix_matches("4161(abc)", "4161")


def test_group_count_suffix_matches_rejects_empty_suffix() -> None:
    assert not _group_count_suffix_matches("4161()", "4161")


def test_group_count_suffix_matches_rejects_trailing_chars() -> None:
    assert not _group_count_suffix_matches("4161(7)abc", "4161")


def test_group_count_suffix_matches_rejects_prefix() -> None:
    assert not _group_count_suffix_matches("abc4161(7)", "4161")


def test_group_count_suffix_matches_rejects_longer_name() -> None:
    # The core test/test1 safety property: expected "test" must not match the
    # longer bare name "test1" (no member-count brackets to legitimize it).
    assert not _group_count_suffix_matches("test1", "test")


def test_group_count_suffix_matches_escapes_expected_regex_meta() -> None:
    # re.escape must be used so a name like "a.b" is literal, not "any char".
    assert _group_count_suffix_matches("a.b(7)", "a.b")
    assert not _group_count_suffix_matches("aXb(7)", "a.b")


@pytest.mark.asyncio
async def test_search_result_accepts_single_visible_exact_text() -> None:
    page = MagicMock()
    rows = MagicMock()
    page.locator.return_value = rows
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
    page.locator.return_value = rows
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


def _routed_page(*, header_text: str | None, selected_name: str | None, composer_visible: bool) -> MagicMock:
    page = MagicMock()
    header = MagicMock()
    header.is_visible = AsyncMock(return_value=True)
    header.inner_text = AsyncMock(return_value=header_text or "")
    header_group = _locator_group([header]) if header_text is not None else _locator_group([])

    current = MagicMock()
    current.is_visible = AsyncMock(return_value=True)
    current.locator.return_value = _locator_group([])
    selected = MagicMock()
    selected.is_visible = AsyncMock(return_value=True)
    current.get_by_text.return_value = _locator_group([selected]) if selected_name == "好友A" else _locator_group([])
    current_group = _locator_group([current]) if selected_name is not None else _locator_group([])

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
        return _locator_group([])

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


@pytest.mark.asyncio
@pytest.mark.parametrize("names", [["好友", "好友"], ["好友(7)", "好友（8）"]])
async def test_search_panel_rejects_multiple_matching_targets(names) -> None:
    page, _buttons = _search_page(names)

    with pytest.raises(AmbiguousTargetError, match="多个同名"):
        await DouyinChat(page)._search_result("好友")


@pytest.mark.asyncio
async def test_chat_open_error_requires_visible_composer() -> None:
    page = _chat_page("好友A", input_count=0)

    assert isinstance(await DouyinChat(page)._chat_open_error("好友A"), PageOperationError)
