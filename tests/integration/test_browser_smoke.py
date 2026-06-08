"""Opt-in headless Chromium smoke test for ``BrowserDriver``.

Unlike the unit tests under ``tests/`` (which inject fakes and never launch a
real browser), this test actually starts headless Chromium and drives a page
end to end, validating that ``BrowserDriver.launch`` wires browser -> context
-> page -> stealth against the real Playwright stack.

It is skipped unless ``RUN_BROWSER_SMOKE=1`` is set, so local developers need
no Chromium install. CI sets that variable and runs
``uv run playwright install --with-deps chromium`` first.
"""

import os
import unittest

from src.browser.driver import MODE_HEADLESS, BrowserDriver


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
