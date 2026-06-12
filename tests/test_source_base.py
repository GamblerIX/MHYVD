from __future__ import annotations

import asyncio
import unittest

from src.models import NewsItem
from src.models import SourceMetadata as ModelsSourceMetadata
from src.sources.base import (
    DEFAULT_FETCH_TIME_BUDGET,
    DEFAULT_MAX_INTERACTIONS,
    SourceAdapter,
    SourceMetadata,
)


class _ConcreteAdapter(SourceAdapter):
    metadata = SourceMetadata(
        source_key="honkai-star-rail/cn",
        game="honkai-star-rail",
        region="cn",
        base_url="https://sr.mihoyo.com",
    )

    async def fetch_news(self, driver: object) -> list[NewsItem]:

        return [NewsItem(title="t", url="https://sr.mihoyo.com/news/1")]


class TestSourceMetadataReexport(unittest.TestCase):
    def test_reexported_metadata_is_models_metadata(self) -> None:
        self.assertIs(SourceMetadata, ModelsSourceMetadata)

    def test_metadata_exposes_required_fields(self) -> None:
        meta = SourceMetadata(
            source_key="genshin-impact/global",
            game="genshin-impact",
            region="global",
            base_url="https://genshin.hoyoverse.com",
        )
        self.assertEqual(meta.source_key, "genshin-impact/global")
        self.assertEqual(meta.game, "genshin-impact")
        self.assertEqual(meta.region, "global")
        self.assertEqual(meta.base_url, "https://genshin.hoyoverse.com")


class TestSourceAdapterABC(unittest.TestCase):
    def test_abstract_base_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            SourceAdapter("https://sr.mihoyo.com")  # type: ignore[abstract]

    def test_subclass_without_fetch_news_cannot_be_instantiated(self) -> None:
        class _Incomplete(SourceAdapter):
            metadata = SourceMetadata(
                source_key="g/r", game="g", region="r", base_url="https://x"
            )

        with self.assertRaises(TypeError):
            _Incomplete("https://x")  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self) -> None:
        adapter = _ConcreteAdapter("https://sr.mihoyo.com")
        self.assertIsInstance(adapter, SourceAdapter)


class TestConstructorStoresParams(unittest.TestCase):
    def test_defaults(self) -> None:
        adapter = _ConcreteAdapter("https://sr.mihoyo.com")
        self.assertEqual(adapter.base_url, "https://sr.mihoyo.com")
        self.assertIsNone(adapter.proxy)
        self.assertFalse(adapter.resume)
        self.assertIsNone(adapter.fetch_cache)
        self.assertEqual(adapter.max_interactions, DEFAULT_MAX_INTERACTIONS)
        self.assertEqual(adapter.fetch_time_budget, DEFAULT_FETCH_TIME_BUDGET)

    def test_explicit_values_are_stored(self) -> None:
        sentinel_cache = object()
        adapter = _ConcreteAdapter(
            "https://sr.mihoyo.com",
            proxy="http://127.0.0.1:8080",
            resume=True,
            fetch_cache=sentinel_cache,  # type: ignore[arg-type]
            max_interactions=10,
            fetch_time_budget=12.5,
        )
        self.assertEqual(adapter.proxy, "http://127.0.0.1:8080")
        self.assertTrue(adapter.resume)
        self.assertIs(adapter.fetch_cache, sentinel_cache)
        self.assertEqual(adapter.max_interactions, 10)
        self.assertEqual(adapter.fetch_time_budget, 12.5)

    def test_extra_kwargs_are_accepted_and_ignored(self) -> None:

        adapter = _ConcreteAdapter(
            "https://sr.mihoyo.com", unexpected="value", another=123
        )
        self.assertEqual(adapter.base_url, "https://sr.mihoyo.com")
        self.assertFalse(hasattr(adapter, "unexpected"))


class TestFetchNewsContract(unittest.TestCase):
    def test_fetch_news_returns_news_items(self) -> None:
        adapter = _ConcreteAdapter("https://sr.mihoyo.com")
        items = asyncio.run(adapter.fetch_news(driver=None))
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], NewsItem)


if __name__ == "__main__":
    unittest.main()
