"""Honkai: Star Rail CN Source_Adapter (``honkai-star-rail/cn``).

This adapter scrapes the China-server Honkai: Star Rail news listing at
``https://sr.mihoyo.com`` (Requirement 1.6). It ports the working logic from
the legacy ``bak/plugins/fetcher/sr_mihoyo_com.py`` fetcher onto the new
Source_Adapter contract:

* it navigates to the news page using the :class:`BrowserDriver` it is given
  (it never launches its own browser),
* it clicks the "load more" control in a **bounded** loop -- continuing only
  while the interaction count is below the configured maximum, the elapsed time
  is below the configured budget, and the previous click actually loaded new
  items (Requirement 5.2),
* it extracts ``(title, href)`` pairs via ``page.evaluate``, absolutises the
  hrefs against the base URL, and dedupes by both title and URL
  (Requirements 2.2, 2.3),
* it returns an empty list cleanly when nothing is found (Requirement 2.4),
* under Resume_Mode it excludes URLs already in the Fetch_Cache
  (Requirement 2.5), and
* it records each retrieved URL in the Fetch_Cache immediately upon retrieval
  (Requirements 5.5, 8.1).

The browser-independent parts of this behaviour live as pure helpers in
:mod:`src.sources.base` (``absolutize_href``, ``build_news_items``,
``filter_resume_cached``, ``should_continue_load_more``) so they can be
property-tested without a browser; this module wires them to the live page.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from ..models import NewsItem, SourceMetadata
from .base import (
    SourceAdapter,
    build_news_items,
    filter_resume_cached,
    should_continue_load_more,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..browser.driver import BrowserDriver

logger = logging.getLogger("sources.honkai_star_rail_cn")

__all__ = ["HonkaiStarRailCnAdapter"]

#: Base URL for the China-server Honkai: Star Rail site (Requirement 1.6).
BASE_URL = "https://sr.mihoyo.com"

#: Relative path (joined onto the base URL) of the news listing page.
NEWS_PATH = "/news?nav=news"

#: CSS selector matching each news entry anchor in the listing.
NEWS_ITEM_SELECTOR = '.news-list .list-wrap > a[href*="/news/"]'

#: CSS selector matching the "load more" control.
LOAD_MORE_BUTTON_SELECTOR = ".btn-more-wrap"

#: Page-navigation timeout (milliseconds).
PAGE_LOAD_TIMEOUT_MS = 30000

#: Timeout (milliseconds) waiting for the first batch of news to render.
INITIAL_WAIT_TIMEOUT_MS = 20000

#: Pause (milliseconds) after each "load more" click to let new items render.
LOAD_MORE_WAIT_MS = 1500

#: JavaScript run in the page to extract ``{title, href}`` records. Ported from
#: the legacy fetcher: prefer an explicit ``.title`` node, otherwise fall back
#: to the first non-empty line of the anchor's text.
_EXTRACT_JS = r"""(selector) => {
    const elements = document.querySelectorAll(selector);
    const results = [];
    for (const el of elements) {
        const href = el.getAttribute('href');
        if (!href) continue;

        const titleNode = el.querySelector('.title');
        let title = '';
        if (titleNode) {
            title = titleNode.innerText.trim();
        } else {
            const text = el.innerText || '';
            const lines = text.split('\n')
                .map(l => l.trim())
                .filter(Boolean);
            title = lines[0] || '';
        }

        if (title) {
            results.push({ title, href });
        }
    }
    return results;
}"""


class HonkaiStarRailCnAdapter(SourceAdapter):
    """Source_Adapter for ``honkai-star-rail/cn`` (``sr.mihoyo.com``)."""

    metadata: ClassVar[SourceMetadata] = SourceMetadata(
        source_key="honkai-star-rail/cn",
        game="honkai-star-rail",
        region="cn",
        base_url=BASE_URL,
    )

    async def fetch_news(self, driver: BrowserDriver) -> list[NewsItem]:
        """Load the full HSR-CN news list using ``driver``.

        Returns absolute-URL :class:`NewsItem` objects deduped by title and
        URL, with Fetch_Cache URLs excluded under Resume_Mode. Returns an empty
        list (without raising) when no news renders.
        """
        page = driver.page
        news_url = urljoin(self.base_url, NEWS_PATH)

        logger.info("Fetching news list: %s", news_url)
        await page.goto(
            news_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS
        )

        # Wait for the first batch. If nothing renders, return cleanly (Req 2.4).
        try:
            await page.wait_for_selector(
                NEWS_ITEM_SELECTOR, timeout=INITIAL_WAIT_TIMEOUT_MS
            )
        except Exception as exc:  # noqa: BLE001 - any wait failure means "no news"
            logger.warning("No news rendered before timeout: %s", exc)
            return []

        await self._load_all(page)

        raw = await page.evaluate(_EXTRACT_JS, NEWS_ITEM_SELECTOR)
        raw_pairs = [
            (item.get("title", ""), item.get("href", ""))
            for item in raw
            if item.get("title") and item.get("href")
        ]

        items = build_news_items(self.base_url, raw_pairs)

        # Resume_Mode: drop URLs already fetched in a previous run (Req 2.5).
        if self.resume:
            before = len(items)
            items = filter_resume_cached(items, self.fetch_cache)
            skipped = before - len(items)
            if skipped:
                logger.info("Skipped %d already-fetched items (resume)", skipped)

        # Apply ``--limit`` *before* recording to the Fetch_Cache so only the
        # kept items are persisted; items beyond the limit are left unfetched
        # and remain available on a later run (Requirement 10.7).
        if self.limit is not None and self.limit >= 0:
            items = items[: self.limit]

        # Record each retrieved URL immediately upon retrieval (Req 5.5, 8.1).
        if self.fetch_cache is not None:
            for item in items:
                self.fetch_cache.add(item.url)

        logger.info("Retrieved %d news items", len(items))
        return items

    async def _load_all(self, page: Any) -> None:
        """Drive the bounded "load more" loop on ``page`` (Requirement 5.2).

        Each iteration is gated by :func:`should_continue_load_more`: the loop
        continues only while interactions remain under
        :attr:`max_interactions`, elapsed time remains under
        :attr:`fetch_time_budget`, and the previous click actually loaded new
        items. The first iteration is always permitted (``new_items_loaded``
        starts ``True``) provided the button exists and is visible.
        """
        load_more = page.locator(LOAD_MORE_BUTTON_SELECTOR).first
        if await load_more.count() <= 0:
            logger.warning("No 'load more' control found; page layout may differ")
            return

        prev_count = await page.locator(NEWS_ITEM_SELECTOR).count()
        interactions = 0
        elapsed = 0.0
        new_items_loaded = True
        start = asyncio.get_event_loop().time()

        while should_continue_load_more(
            interactions,
            self.max_interactions,
            elapsed,
            self.fetch_time_budget,
            new_items_loaded,
        ):
            if not await load_more.is_visible():
                logger.info("'load more' control no longer visible; stopping")
                break

            await load_more.click()
            await page.wait_for_timeout(LOAD_MORE_WAIT_MS)
            interactions += 1

            new_count = await page.locator(NEWS_ITEM_SELECTOR).count()
            new_items_loaded = new_count > prev_count
            prev_count = new_count
            elapsed = asyncio.get_event_loop().time() - start

        logger.info("Performed %d 'load more' interactions", interactions)
