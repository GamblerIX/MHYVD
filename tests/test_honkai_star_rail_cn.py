from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.cache.fetch_cache import FetchCache
from src.models import NewsItem
from src.sources import default_registry, get_source_registry
from src.sources.honkai_star_rail_cn import (
    BASE_URL,
    LOAD_MORE_BUTTON_SELECTOR,
    NEWS_ITEM_SELECTOR,
    HonkaiStarRailCnAdapter,
)
from src.sources.registry import SourceRegistry


class FakeLocator:
    def __init__(self, page: FakePage, selector: str) -> None:
        self._page = page
        self._selector = selector

    @property
    def first(self) -> FakeLocator:
        return self

    async def count(self) -> int:
        return self._page.count_for(self._selector)

    async def is_visible(self) -> bool:
        return self._page.button_visible()

    async def click(self) -> None:
        self._page.do_click()


class FakePage:
    def __init__(
        self,
        *,
        total: int = 5,
        initial: int = 2,
        per_click: int = 2,
        has_button: bool = True,
        render_fail: bool = False,
    ) -> None:
        self.total = total
        self.visible = min(initial, total)
        self.per_click = per_click
        self.has_button = has_button
        self.render_fail = render_fail
        self.clicks = 0
        self.goto_calls: list[str] = []

    async def goto(self, url: str, **kwargs: object) -> None:
        self.goto_calls.append(url)

    async def wait_for_selector(self, selector: str, **kwargs: object) -> None:
        if self.render_fail:
            raise TimeoutError("no news rendered")

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self, selector)

    async def wait_for_timeout(self, ms: int) -> None:
        return None

    async def evaluate(self, expression: str, selector: str) -> list[dict]:
        return [
            {"title": f"News {i}", "href": f"/news/{i}"} for i in range(self.visible)
        ]

    def count_for(self, selector: str) -> int:
        if selector == LOAD_MORE_BUTTON_SELECTOR:
            return 1 if self.has_button else 0
        if selector == NEWS_ITEM_SELECTOR:
            return self.visible
        return 0

    def button_visible(self) -> bool:
        return self.has_button

    def do_click(self) -> None:
        self.clicks += 1
        self.visible = min(self.visible + self.per_click, self.total)


class FakeDriver:
    def __init__(self, page: FakePage) -> None:
        self.page = page


def run(coro):
    return asyncio.run(coro)


class FetchNewsTests(unittest.TestCase):
    def _adapter(self, **kwargs) -> HonkaiStarRailCnAdapter:
        kwargs.setdefault("base_url", BASE_URL)
        return HonkaiStarRailCnAdapter(**kwargs)

    def test_returns_absolute_deduped_items(self) -> None:
        page = FakePage(total=5, initial=5, per_click=0)
        adapter = self._adapter()
        items = run(adapter.fetch_news(FakeDriver(page)))

        self.assertEqual(len(items), 5)
        for item in items:
            self.assertIsInstance(item, NewsItem)
            self.assertTrue(item.url.startswith("https://sr.mihoyo.com/news/"))

        self.assertEqual(len({i.title for i in items}), 5)
        self.assertEqual(len({i.url for i in items}), 5)

    def test_navigates_to_news_page(self) -> None:
        page = FakePage()
        adapter = self._adapter()
        run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(page.goto_calls, ["https://sr.mihoyo.com/news?nav=news"])

    def test_empty_when_nothing_renders(self) -> None:
        page = FakePage(render_fail=True)
        adapter = self._adapter()
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(items, [])

    def test_load_more_loads_all_items(self) -> None:

        page = FakePage(total=7, initial=2, per_click=2)
        adapter = self._adapter()
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(len(items), 7)

    def test_load_more_bounded_by_max_interactions(self) -> None:

        page = FakePage(total=100, initial=2, per_click=2)
        adapter = self._adapter(max_interactions=1)
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(page.clicks, 1)

        self.assertEqual(len(items), 4)

    def test_load_more_stops_when_no_new_items(self) -> None:

        page = FakePage(total=2, initial=2, per_click=0)
        adapter = self._adapter(max_interactions=50)
        items = run(adapter.fetch_news(FakeDriver(page)))

        self.assertEqual(page.clicks, 1)
        self.assertEqual(len(items), 2)

    def test_load_more_bounded_by_time_budget(self) -> None:
        page = FakePage(total=100, initial=2, per_click=2)

        adapter = self._adapter(fetch_time_budget=0.0)
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(page.clicks, 0)
        self.assertEqual(len(items), 2)

    def test_each_load_more_click_is_logged(self) -> None:

        page = FakePage(total=7, initial=2, per_click=2)
        adapter = self._adapter()
        with self.assertLogs("sources.honkai_star_rail_cn", level="INFO") as captured:
            run(adapter.fetch_news(FakeDriver(page)))
        click_lines = [m for m in captured.output if "'load more' click" in m]
        self.assertEqual(len(click_lines), page.clicks)
        self.assertIn("click 1/", click_lines[0])
        self.assertIn("total 7", click_lines[-1])

    def test_no_button_skips_load_more(self) -> None:
        page = FakePage(total=5, initial=3, per_click=2, has_button=False)
        adapter = self._adapter()
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(page.clicks, 0)
        self.assertEqual(len(items), 3)


class ResumeAndCacheTests(unittest.TestCase):
    def test_resume_excludes_cached_and_caches_new(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "fetch_cache.json"
            cache = FetchCache(cache_file)
            cache.add("https://sr.mihoyo.com/news/0")
            cache.add("https://sr.mihoyo.com/news/1")

            page = FakePage(total=5, initial=5, per_click=0)
            adapter = HonkaiStarRailCnAdapter(
                base_url=BASE_URL, resume=True, fetch_cache=cache
            )
            items = run(adapter.fetch_news(FakeDriver(page)))

            urls = {i.url for i in items}

            self.assertNotIn("https://sr.mihoyo.com/news/0", urls)
            self.assertNotIn("https://sr.mihoyo.com/news/1", urls)
            self.assertEqual(len(items), 3)

            reloaded = FetchCache(cache_file)
            for i in range(5):
                self.assertTrue(reloaded.contains(f"https://sr.mihoyo.com/news/{i}"))

    def test_cache_populated_without_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "fetch_cache.json"
            cache = FetchCache(cache_file)
            page = FakePage(total=3, initial=3, per_click=0)
            adapter = HonkaiStarRailCnAdapter(base_url=BASE_URL, fetch_cache=cache)
            items = run(adapter.fetch_news(FakeDriver(page)))

            self.assertEqual(len(items), 3)
            reloaded = FetchCache(cache_file)
            self.assertEqual(len(reloaded), 3)

    def test_no_cache_is_tolerated(self) -> None:
        page = FakePage(total=3, initial=3, per_click=0)
        adapter = HonkaiStarRailCnAdapter(base_url=BASE_URL, resume=True)
        items = run(adapter.fetch_news(FakeDriver(page)))
        self.assertEqual(len(items), 3)


class RegistrationTests(unittest.TestCase):
    KEY = "honkai-star-rail/cn"

    def test_metadata_targets_sr_mihoyo(self) -> None:
        meta = HonkaiStarRailCnAdapter.metadata
        self.assertEqual(meta.source_key, self.KEY)
        self.assertEqual(meta.game, "honkai-star-rail")
        self.assertEqual(meta.region, "cn")
        self.assertEqual(meta.base_url, "https://sr.mihoyo.com")

    def test_default_registry_has_adapter(self) -> None:
        self.assertTrue(default_registry.is_registered(self.KEY))
        self.assertIn(self.KEY, default_registry.list_keys())
        self.assertIs(get_source_registry(), default_registry)

    def test_create_returns_adapter_instance(self) -> None:
        adapter = default_registry.create(self.KEY, base_url=BASE_URL)
        self.assertIsInstance(adapter, HonkaiStarRailCnAdapter)
        self.assertEqual(adapter.base_url, "https://sr.mihoyo.com")

    def test_can_register_on_fresh_registry(self) -> None:
        registry = SourceRegistry()
        registry.register(self.KEY, HonkaiStarRailCnAdapter)
        self.assertEqual(registry.list_keys(), [self.KEY])


if __name__ == "__main__":
    unittest.main()
