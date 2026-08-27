from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import scripts.login as login_script
from scripts.login import _click_first_visible, _save_storage_state, _wait_for_login


def test_login_cmd_uses_project_virtual_environment() -> None:
    launcher = Path(__file__).resolve().parents[1] / "login.cmd"
    content = launcher.read_text(encoding="utf-8")

    assert ".venv\\Scripts\\python.exe" in content
    assert "scripts\\login.py" in content
    assert "if not \"%LOGIN_EXIT%\"==\"0\" pause" in content


@pytest.mark.asyncio
async def test_click_first_visible_skips_hidden_candidate() -> None:
    hidden = MagicMock()
    hidden.is_visible = AsyncMock(return_value=False)
    visible = MagicMock()
    visible.is_visible = AsyncMock(return_value=True)
    visible.click = AsyncMock()
    group = MagicMock()
    group.count = AsyncMock(return_value=2)
    group.nth.side_effect = [hidden, visible]

    assert await _click_first_visible(group, timeout_ms=5_000) is True
    visible.click.assert_awaited_once_with(timeout=5_000)


@pytest.mark.asyncio
async def test_wait_for_login_verifies_chat_after_auth_cookie(monkeypatch) -> None:
    context = MagicMock()
    context.cookies = AsyncMock(return_value=[{"name": "sessionid", "value": "token"}])
    page = MagicMock()
    page.wait_for_timeout = AsyncMock()
    open_messages = AsyncMock()
    monkeypatch.setattr(login_script, "open_private_messages", open_messages)

    await _wait_for_login(context, page, timeout_seconds=30)

    page.wait_for_timeout.assert_awaited_once_with(2_000)
    open_messages.assert_awaited_once_with(page)


@pytest.mark.asyncio
async def test_save_storage_state_replaces_existing_file_atomically(tmp_path: Path) -> None:
    output = tmp_path / "storage-state.json"
    output.write_text("old", encoding="utf-8")
    context = MagicMock()

    async def write_state(*, path: str) -> None:
        Path(path).write_text('{"cookies": []}', encoding="utf-8")

    context.storage_state = AsyncMock(side_effect=write_state)

    await _save_storage_state(context, output)

    assert output.read_text(encoding="utf-8") == '{"cookies": []}'
    assert not (tmp_path / "storage-state.json.tmp").exists()
