import os
import unittest

from src.browser.driver import MODE_HEADED, MODE_HEADLESS, BrowserDriver


@unittest.skipUnless(
    os.environ.get("RUN_BROWSER_SMOKE") == "1",
    "set RUN_BROWSER_SMOKE=1 to run (needs Chromium installed)",
)
class BrowserSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_headless_launch_opens_page(self) -> None:
        async with BrowserDriver(mode=MODE_HEADLESS) as driver:
            page = driver.page
            self.assertIsNotNone(page)
            await page.goto("about:blank")
            self.assertEqual(page.url, "about:blank")


@unittest.skipUnless(
    os.environ.get("RUN_BROWSER_SMOKE_HEADED") == "1",
    "set RUN_BROWSER_SMOKE_HEADED=1 to run (needs Chromium and a display; "
    "CI uses xvfb-run)",
)
class HeadedBrowserSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_headed_launch_opens_page(self) -> None:
        async with BrowserDriver(mode=MODE_HEADED) as driver:
            page = driver.page
            self.assertIsNotNone(page)
            await page.goto("about:blank")
            self.assertEqual(page.url, "about:blank")
