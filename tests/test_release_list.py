from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.cache.fetch_cache import FetchCache
from src.models import NewsItem
from src.sources import get_source_registry
from src.sources.release_list import (
    DEFAULT_RELEASE_LIST_URL,
    RELEASE_LIST_SOURCE_KEY,
    ReleaseListAdapter,
    parse_list_payload,
)


def _payload(*pairs: tuple[str, str]) -> dict[str, Any]:
    fetched = [{"title": t, "url": u, "category": None} for t, u in pairs]
    return {"fetched": fetched, "videos": []}


def _fake_fetcher(payload: Any):
    calls: list[tuple[str, str | None]] = []

    def fetch_json(url: str, proxy: str | None) -> Any:
        calls.append((url, proxy))
        return payload

    fetch_json.calls = calls  # type: ignore[attr-defined]
    return fetch_json


class ParsePayloadTests(unittest.TestCase):
    def test_builds_items_from_fetched_list(self) -> None:
        payload = _payload(("A", "https://x/news/1"), ("B", "https://x/news/2"))
        items = parse_list_payload(DEFAULT_RELEASE_LIST_URL, payload)
        self.assertEqual(
            items,
            [
                NewsItem(title="A", url="https://x/news/1"),
                NewsItem(title="B", url="https://x/news/2"),
            ],
        )

    def test_dedupes_and_skips_incomplete_entries(self) -> None:
        payload = {
            "fetched": [
                {"title": "A", "url": "https://x/news/1"},
                {"title": "A", "url": "https://x/news/other"},
                {"title": "B", "url": "https://x/news/1"},
                {"title": "", "url": "https://x/news/2"},
                {"title": "C"},
                "not-a-mapping",
                {"title": "D", "url": "https://x/news/3"},
            ]
        }
        items = parse_list_payload(DEFAULT_RELEASE_LIST_URL, payload)
        self.assertEqual([item.title for item in items], ["A", "D"])

    def test_relative_urls_are_absolutised_against_base(self) -> None:
        payload = _payload(("A", "/news/1"))
        items = parse_list_payload("https://example.com/list.json", payload)
        self.assertEqual(items[0].url, "https://example.com/news/1")

    def test_rejects_non_mapping_payload(self) -> None:
        with self.assertRaises(ValueError):
            parse_list_payload(DEFAULT_RELEASE_LIST_URL, ["not", "a", "dict"])

    def test_rejects_payload_without_fetched_list(self) -> None:
        with self.assertRaises(ValueError):
            parse_list_payload(DEFAULT_RELEASE_LIST_URL, {"videos": []})


class FetchNewsTests(unittest.TestCase):
    def _run(self, adapter: ReleaseListAdapter) -> list[NewsItem]:

        return asyncio.run(adapter.fetch_news(None))  # type: ignore[arg-type]

    def test_fetches_from_base_url_with_proxy(self) -> None:
        fetcher = _fake_fetcher(_payload(("A", "https://x/news/1")))
        adapter = ReleaseListAdapter(
            base_url="https://example.com/list.json",
            proxy="http://proxy:8080",
            fetch_json=fetcher,
        )
        items = self._run(adapter)
        self.assertEqual(len(items), 1)
        self.assertEqual(
            fetcher.calls,  # type: ignore[attr-defined]
            [("https://example.com/list.json", "http://proxy:8080")],
        )

    def test_empty_fetched_list_returns_empty_without_raising(self) -> None:
        adapter = ReleaseListAdapter(
            base_url=DEFAULT_RELEASE_LIST_URL, fetch_json=_fake_fetcher(_payload())
        )
        self.assertEqual(self._run(adapter), [])

    def test_resume_filters_cached_urls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = FetchCache(Path(tmp) / "fetch_cache.json")
            cache.add("https://x/news/1")
            fetcher = _fake_fetcher(
                _payload(("A", "https://x/news/1"), ("B", "https://x/news/2"))
            )
            adapter = ReleaseListAdapter(
                base_url=DEFAULT_RELEASE_LIST_URL,
                resume=True,
                fetch_cache=cache,
                fetch_json=fetcher,
            )
            items = self._run(adapter)
            self.assertEqual([item.title for item in items], ["B"])

    def test_limit_is_applied_before_recording_to_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = FetchCache(Path(tmp) / "fetch_cache.json")
            fetcher = _fake_fetcher(
                _payload(("A", "https://x/news/1"), ("B", "https://x/news/2"))
            )
            adapter = ReleaseListAdapter(
                base_url=DEFAULT_RELEASE_LIST_URL,
                resume=True,
                fetch_cache=cache,
                limit=1,
                fetch_json=fetcher,
            )
            items = self._run(adapter)
            self.assertEqual(len(items), 1)
            self.assertTrue(cache.contains("https://x/news/1"))

            self.assertFalse(cache.contains("https://x/news/2"))

    def test_fetch_failure_propagates(self) -> None:
        def boom(url: str, proxy: str | None) -> Any:
            raise OSError("network down")

        adapter = ReleaseListAdapter(base_url=DEFAULT_RELEASE_LIST_URL, fetch_json=boom)
        with self.assertRaises(OSError):
            self._run(adapter)


class RegistrationTests(unittest.TestCase):
    def test_registered_under_release_url_list(self) -> None:
        registry = get_source_registry()
        self.assertTrue(registry.is_registered(RELEASE_LIST_SOURCE_KEY))

    def test_metadata_base_url_is_default_release_asset(self) -> None:
        self.assertEqual(ReleaseListAdapter.metadata.base_url, DEFAULT_RELEASE_LIST_URL)
        self.assertEqual(
            ReleaseListAdapter.metadata.source_key, RELEASE_LIST_SOURCE_KEY
        )


if __name__ == "__main__":
    unittest.main()
