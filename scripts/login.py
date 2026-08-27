from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from playwright.async_api import async_playwright

from app.browser import open_private_messages


DOUYIN_URL = "https://www.douyin.com/"
DEFAULT_STORAGE_PATH = PROJECT_ROOT / "storage-state.json"
AUTH_COOKIE_NAMES = {"sessionid", "sessionid_ss", "sid_guard"}
LOGIN_BUTTON_SELECTORS = (
    'button:has-text("登录")',
    '[role="button"]:has-text("登录")',
    '[data-e2e*="login"]',
    '[class*="login"] button',
    '[class*="Login"] button',
)


async def login(storage_path: Path = DEFAULT_STORAGE_PATH, *, timeout_seconds: int = 240) -> None:
    storage_path = storage_path.resolve()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=False)
        try:
            context = await browser.new_context(locale="zh-CN")
            page = await context.new_page()
            await page.goto(DOUYIN_URL, wait_until="domcontentloaded", timeout=45_000)
            await _open_login(page)
            print("请在浏览器中扫码并完成手机确认，登录状态会自动保存。")
            await _wait_for_login(context, page, timeout_seconds)
            await _save_storage_state(context, storage_path)
            print(f"登录状态已保存: {storage_path}")
        finally:
            await browser.close()


async def _open_login(page, timeout_ms: int = 20_000) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
    while True:
        for selector in LOGIN_BUTTON_SELECTORS:
            if await _click_first_visible(page.locator(selector), timeout_ms=5_000):
                await page.wait_for_timeout(500)
                await _click_first_visible(page.get_by_text("扫码登录", exact=True), timeout_ms=5_000)
                return
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError("未找到登录按钮，请检查网络后重试")
        await page.wait_for_timeout(250)


async def _click_first_visible(group, timeout_ms: int) -> bool:
    for index in range(await group.count()):
        candidate = group.nth(index)
        try:
            if await candidate.is_visible():
                await candidate.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


async def _wait_for_login(context, page, timeout_seconds: int) -> None:
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while asyncio.get_running_loop().time() < deadline:
        cookies = await context.cookies()
        if any(cookie.get("name") in AUTH_COOKIE_NAMES and cookie.get("value") for cookie in cookies):
            await page.wait_for_timeout(2_000)
            await open_private_messages(page)
            return
        await page.wait_for_timeout(1_000)
    raise RuntimeError(f"等待扫码登录超时（{timeout_seconds} 秒）")


async def _save_storage_state(context, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp")
    try:
        await context.storage_state(path=str(temporary))
        temporary.replace(path)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="扫码登录抖音并保存 Storage State")
    parser.add_argument("--storage-state", type=Path, default=DEFAULT_STORAGE_PATH, help="Storage State 输出路径")
    parser.add_argument("--timeout", type=int, default=240, help="扫码等待秒数")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(login(args.storage_state, timeout_seconds=args.timeout))
    except KeyboardInterrupt:
        print("登录已取消")
    except Exception as exc:
        raise SystemExit(f"错误: {exc}") from exc
