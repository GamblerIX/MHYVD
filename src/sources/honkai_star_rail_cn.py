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

if TYPE_CHECKING:  # pragma: no cover
    from ..browser.driver import BrowserDriver

logger = logging.getLogger("sources.honkai_star_rail_cn")

__all__ = ["HonkaiStarRailCnAdapter"]


BASE_URL = "https://sr.mihoyo.com"


NEWS_PATH = "/news?nav=news"


NEWS_ITEM_SELECTOR = '.news-list .list-wrap > a[href*="/news/"]'


LOAD_MORE_BUTTON_SELECTOR = ".btn-more-wrap"


PAGE_LOAD_TIMEOUT_MS = 30000


INITIAL_WAIT_TIMEOUT_MS = 20000


LOAD_MORE_WAIT_MS = 1500


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
    metadata: ClassVar[SourceMetadata] = SourceMetadata(
        source_key="honkai-star-rail/cn",
        game="honkai-star-rail",
        region="cn",
        base_url=BASE_URL,
    )

    async def fetch_news(self, driver: BrowserDriver) -> list[NewsItem]:
        page = driver.page
        news_url = urljoin(self.base_url, NEWS_PATH)

        logger.info("Fetching news list: %s", news_url)
        await page.goto(
            news_url, wait_until="domcontentloaded", timeout=PAGE_LOAD_TIMEOUT_MS
        )

        try:
            await page.wait_for_selector(
                NEWS_ITEM_SELECTOR, timeout=INITIAL_WAIT_TIMEOUT_MS
            )
        except Exception as exc:  # noqa: BLE001
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

        if self.resume:
            before = len(items)
            items = filter_resume_cached(items, self.fetch_cache)
            skipped = before - len(items)
            if skipped:
                logger.info("Skipped %d already-fetched items (resume)", skipped)

        if self.limit is not None and self.limit >= 0:
            items = items[: self.limit]

        if self.fetch_cache is not None:
            for item in items:
                self.fetch_cache.add(item.url)

        logger.info("Retrieved %d news items", len(items))
        return items

    async def _load_all(self, page: Any) -> None:
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
            elapsed = asyncio.get_event_loop().time() - start

            logger.info(
                "'load more' click %d/%d: +%d item(s) (total %d, %.1fs elapsed)",
                interactions,
                self.max_interactions,
                new_count - prev_count,
                new_count,
                elapsed,
            )
            prev_count = new_count

        logger.info("Performed %d 'load more' interactions", interactions)
