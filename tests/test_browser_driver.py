from __future__ import annotations

import asyncio
import time
import unittest
from typing import Any

from src.browser.driver import (
    DEFAULT_MODE,
    MODE_HEADED,
    MODE_HEADLESS,
    BrowserDriver,
    BrowserLaunchError,
    build_launch_args,
    build_proxy_settings,
    headless_flag,
)


class FakePage:
    def __init__(self, log: list[str], close_delay: float = 0.0) -> None:
        self._log = log
        self._close_delay = close_delay
        self.closed = False

    async def close(self) -> None:
        if self._close_delay:
            await asyncio.sleep(self._close_delay)
        self.closed = True
        self._log.append("page")


class FakeContext:
    def __init__(self, log: list[str], close_delay: float = 0.0) -> None:
        self._log = log
        self._close_delay = close_delay
        self.proxy: Any = "UNSET"
        self.page: FakePage | None = None
        self.closed = False

    async def new_page(self) -> FakePage:
        self.page = FakePage(self._log, self._close_delay)
        return self.page

    async def close(self) -> None:
        if self._close_delay:
            await asyncio.sleep(self._close_delay)
        self.closed = True
        self._log.append("context")


class FakeBrowser:
    def __init__(self, log: list[str], close_delay: float = 0.0) -> None:
        self._log = log
        self._close_delay = close_delay
        self.context: FakeContext | None = None
        self.closed = False

    async def new_context(self, proxy: Any = None) -> FakeContext:
        self.context = FakeContext(self._log, self._close_delay)
        self.context.proxy = proxy
        return self.context

    async def close(self) -> None:
        if self._close_delay:
            await asyncio.sleep(self._close_delay)
        self.closed = True
        self._log.append("browser")


class FakeChromium:
    def __init__(
        self,
        log: list[str],
        close_delay: float = 0.0,
        launch_error: Exception | None = None,
    ) -> None:
        self._log = log
        self._close_delay = close_delay
        self._launch_error = launch_error
        self.launch_calls: list[dict[str, Any]] = []
        self.browser: FakeBrowser | None = None

    async def launch(self, *, headless: bool, args: list[str]) -> FakeBrowser:
        self.launch_calls.append({"headless": headless, "args": args})
        if self._launch_error is not None:
            raise self._launch_error
        self.browser = FakeBrowser(self._log, self._close_delay)
        return self.browser


class FakePlaywright:
    def __init__(
        self,
        log: list[str],
        close_delay: float = 0.0,
        launch_error: Exception | None = None,
    ) -> None:
        self._log = log
        self.chromium = FakeChromium(log, close_delay, launch_error)
        self.stopped = False

    async def stop(self) -> None:
        self.stopped = True
        self._log.append("playwright")


class FakePlaywrightCM:
    def __init__(
        self,
        log: list[str],
        close_delay: float = 0.0,
        launch_error: Exception | None = None,
    ) -> None:
        self._pw = FakePlaywright(log, close_delay, launch_error)

    async def start(self) -> FakePlaywright:
        return self._pw


def make_driver(
    *,
    mode: str = DEFAULT_MODE,
    proxy: str | None = None,
    timeout: float = 30.0,
    close_delay: float = 0.0,
    launch_error: Exception | None = None,
) -> tuple[BrowserDriver, list[str], list[Any]]:
    close_log: list[str] = []
    stealthed: list[Any] = []

    cm = FakePlaywrightCM(close_log, close_delay, launch_error)

    async def fake_stealth(page: Any) -> None:
        stealthed.append(page)

    driver = BrowserDriver(
        mode=mode,
        proxy=proxy,
        timeout=timeout,
        playwright_factory=lambda: cm,
        stealth=fake_stealth,
    )
    return driver, close_log, stealthed


class HelperTests(unittest.TestCase):
    def test_headless_flag_mapping(self) -> None:
        self.assertTrue(headless_flag(MODE_HEADLESS))
        self.assertFalse(headless_flag(MODE_HEADED))

    def test_headless_flag_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            headless_flag("invisible")

    def test_launch_args_include_automation_flag(self) -> None:
        args = build_launch_args()
        self.assertIn("--disable-blink-features=AutomationControlled", args)

    def test_build_proxy_settings_none_when_absent(self) -> None:
        self.assertIsNone(build_proxy_settings(None))
        self.assertIsNone(build_proxy_settings(""))

    def test_build_proxy_settings_wraps_server(self) -> None:
        self.assertEqual(
            build_proxy_settings("http://127.0.0.1:8080"),
            {"server": "http://127.0.0.1:8080"},
        )


class ConstructionTests(unittest.TestCase):
    def test_default_mode_is_headed(self) -> None:
        driver = BrowserDriver()
        self.assertEqual(driver.mode, MODE_HEADED)
        self.assertFalse(driver.headless)

    def test_default_mode_constant_is_headed(self) -> None:
        self.assertEqual(DEFAULT_MODE, MODE_HEADED)

    def test_headed_mode_is_not_headless(self) -> None:
        driver = BrowserDriver(mode=MODE_HEADED)
        self.assertFalse(driver.headless)

    def test_unknown_mode_rejected(self) -> None:
        with self.assertRaises(ValueError):
            BrowserDriver(mode="ghost")


class LaunchTests(unittest.IsolatedAsyncioTestCase):
    async def test_headless_launch_passes_headless_true(self) -> None:
        driver, _log, stealthed = make_driver(mode=MODE_HEADLESS)
        page = await driver.launch()
        chromium = driver._playwright.chromium  # type: ignore[union-attr]
        self.assertEqual(chromium.launch_calls[0]["headless"], True)
        self.assertIn(
            "--disable-blink-features=AutomationControlled",
            chromium.launch_calls[0]["args"],
        )

        self.assertEqual(stealthed, [page])
        await driver.aclose()

    async def test_headed_launch_passes_headless_false(self) -> None:
        driver, _log, stealthed = make_driver(mode=MODE_HEADED)
        page = await driver.launch()
        chromium = driver._playwright.chromium  # type: ignore[union-attr]
        self.assertEqual(chromium.launch_calls[0]["headless"], False)

        self.assertEqual(stealthed, [page])
        await driver.aclose()

    async def test_proxy_settings_applied_to_context(self) -> None:
        driver, _log, _stealthed = make_driver(proxy="http://10.0.0.1:3128")
        await driver.launch()
        context = driver._context  # type: ignore[union-attr]
        self.assertEqual(context.proxy, {"server": "http://10.0.0.1:3128"})
        await driver.aclose()

    async def test_no_proxy_passes_none_to_context(self) -> None:
        driver, _log, _stealthed = make_driver(proxy=None)
        await driver.launch()
        context = driver._context  # type: ignore[union-attr]
        self.assertIsNone(context.proxy)
        await driver.aclose()

    async def test_launch_returns_page_and_records_it(self) -> None:
        driver, _log, _stealthed = make_driver()
        page = await driver.launch()
        self.assertIs(driver.page, page)
        await driver.aclose()

    async def test_context_manager_launches_and_closes(self) -> None:
        driver, close_log, stealthed = make_driver()
        async with driver as d:
            self.assertIsNotNone(d.page)
            self.assertEqual(len(stealthed), 1)

        self.assertEqual(close_log, ["page", "context", "browser", "playwright"])


class LaunchFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_headed_launch_failure_raises_without_fallback(self) -> None:
        driver, _log, _stealthed = make_driver(
            mode=MODE_HEADED, launch_error=RuntimeError("no display")
        )
        with self.assertRaises(BrowserLaunchError) as ctx:
            await driver.launch()
        self.assertIn("headed", str(ctx.exception))

        chromium = driver._playwright is None
        self.assertTrue(chromium)

    async def test_headless_launch_failure_raises(self) -> None:
        driver, _log, _stealthed = make_driver(
            mode=MODE_HEADLESS, launch_error=RuntimeError("boom")
        )
        with self.assertRaises(BrowserLaunchError):
            await driver.launch()


class CleanupTests(unittest.IsolatedAsyncioTestCase):
    async def test_aclose_closes_in_order(self) -> None:
        driver, close_log, _stealthed = make_driver()
        await driver.launch()
        await driver.aclose()
        self.assertEqual(close_log, ["page", "context", "browser", "playwright"])

    async def test_aclose_resets_resources(self) -> None:
        driver, _log, _stealthed = make_driver()
        await driver.launch()
        await driver.aclose()
        self.assertIsNone(driver.page)
        self.assertIsNone(driver._browser)
        self.assertIsNone(driver._context)
        self.assertIsNone(driver._playwright)

    async def test_aclose_is_idempotent(self) -> None:
        driver, _log, _stealthed = make_driver()
        await driver.launch()
        await driver.aclose()

        await driver.aclose()

    async def test_each_close_is_bounded_by_timeout(self) -> None:

        timeout = 0.05
        hang = 5.0
        driver, _log, _stealthed = make_driver(timeout=timeout, close_delay=hang)
        await driver.launch()

        start = time.monotonic()
        await driver.aclose()
        elapsed = time.monotonic() - start

        self.assertLess(elapsed, hang)
        self.assertLess(elapsed, 2.0)

        self.assertIsNone(driver.page)
        self.assertIsNone(driver._browser)


if __name__ == "__main__":
    unittest.main()
