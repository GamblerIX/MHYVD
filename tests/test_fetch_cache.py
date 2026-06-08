"""Tests for ``src.cache.fetch_cache.FetchCache``.

Covers unit/example cases plus property-based tests for Property 22
(fetch-cache round-trip) from the design document.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.cache.fetch_cache import FetchCache

try:  # pragma: no cover - exercised only when hypothesis is installed
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


class FetchCacheBasicsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "fetch_cache.json"

    def test_new_cache_is_empty(self) -> None:
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), set())
        self.assertEqual(len(cache), 0)

    def test_add_then_contains(self) -> None:
        cache = FetchCache(self.cache_path)
        cache.add("https://sr.mihoyo.com/news/1")
        self.assertTrue(cache.contains("https://sr.mihoyo.com/news/1"))
        self.assertIn("https://sr.mihoyo.com/news/1", cache)
        self.assertFalse(cache.contains("https://sr.mihoyo.com/news/2"))

    def test_add_persists_immediately(self) -> None:
        cache = FetchCache(self.cache_path)
        cache.add("https://sr.mihoyo.com/news/1")
        # The file must exist and contain the URL right after add(), without
        # any explicit flush/close step.
        self.assertTrue(self.cache_path.exists())
        data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertEqual(data, ["https://sr.mihoyo.com/news/1"])

    def test_add_is_idempotent(self) -> None:
        cache = FetchCache(self.cache_path)
        cache.add("https://x.com/news/1")
        cache.add("https://x.com/news/1")
        self.assertEqual(cache.urls(), {"https://x.com/news/1"})
        self.assertEqual(len(cache), 1)

    def test_urls_returns_copy(self) -> None:
        cache = FetchCache(self.cache_path)
        cache.add("https://x.com/news/1")
        snapshot = cache.urls()
        snapshot.add("https://x.com/news/2")
        # Mutating the returned set must not affect the cache.
        self.assertEqual(cache.urls(), {"https://x.com/news/1"})

    def test_reload_reflects_persisted_urls(self) -> None:
        cache = FetchCache(self.cache_path)
        cache.add("https://x.com/news/1")
        cache.add("https://x.com/news/2")

        reloaded = FetchCache(self.cache_path)
        self.assertEqual(
            reloaded.urls(), {"https://x.com/news/1", "https://x.com/news/2"}
        )

    def test_existing_readable_file_loaded(self) -> None:
        self.cache_path.write_text(
            json.dumps(["https://a.com/news/1", "https://a.com/news/2"]),
            encoding="utf-8",
        )
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), {"https://a.com/news/1", "https://a.com/news/2"})


class FetchCacheResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "fetch_cache.json"

    def test_missing_file_loads_empty(self) -> None:
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), set())

    def test_corrupt_json_loads_empty(self) -> None:
        self.cache_path.write_text("{not valid json", encoding="utf-8")
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), set())

    def test_wrong_shape_object_loads_empty(self) -> None:
        # A JSON object instead of an array is unexpected -> empty cache.
        self.cache_path.write_text(
            json.dumps({"url": "https://x.com/news/1"}), encoding="utf-8"
        )
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), set())

    def test_empty_file_loads_empty(self) -> None:
        self.cache_path.write_text("", encoding="utf-8")
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), set())

    def test_array_with_non_strings_keeps_only_strings(self) -> None:
        self.cache_path.write_text(
            json.dumps(["https://x.com/1", 5, None, {"a": 1}, "https://x.com/2"]),
            encoding="utf-8",
        )
        cache = FetchCache(self.cache_path)
        self.assertEqual(cache.urls(), {"https://x.com/1", "https://x.com/2"})

    def test_recovers_after_corrupt_load(self) -> None:
        self.cache_path.write_text("garbage", encoding="utf-8")
        cache = FetchCache(self.cache_path)
        # Adding still works and overwrites the corrupt file with valid JSON.
        cache.add("https://x.com/news/1")
        reloaded = FetchCache(self.cache_path)
        self.assertEqual(reloaded.urls(), {"https://x.com/news/1"})


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class FetchCacheRoundTripPropertyTests(unittest.TestCase):
    """Property 22 — fetch-cache round-trip.

    Adding a set of URLs to a FetchCache and then loading a fresh FetchCache
    from the same file reflects exactly those URLs; a missing or corrupt cache
    file loads as an empty cache without raising.

    **Validates: Requirements 8.3, 8.5, 8.6, 14.4**
    """

    @settings(max_examples=300)
    @given(st.sets(st.text()))
    def test_round_trip_reflects_exactly_added_urls(self, url_set: set[str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "fetch_cache.json"
            cache = FetchCache(cache_path)
            for url in url_set:
                cache.add(url)

            reloaded = FetchCache(cache_path)
            self.assertEqual(reloaded.urls(), url_set)
            for url in url_set:
                self.assertTrue(reloaded.contains(url))

    @settings(max_examples=200)
    @given(st.sets(st.text()))
    def test_add_persists_after_each_call(self, url_set: set[str]) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "fetch_cache.json"
            cache = FetchCache(cache_path)
            seen: set[str] = set()
            for url in url_set:
                cache.add(url)
                seen.add(url)
                # Loading a fresh cache mid-stream reflects all URLs added so
                # far, proving each add() persisted immediately.
                self.assertEqual(FetchCache(cache_path).urls(), seen)

    @settings(max_examples=200)
    @given(st.binary())
    def test_arbitrary_file_contents_load_without_raising(self, blob: bytes) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "fetch_cache.json"
            cache_path.write_bytes(blob)
            # Must never raise regardless of file contents; either parses to a
            # set of strings or falls back to empty.
            cache = FetchCache(cache_path)
            self.assertIsInstance(cache.urls(), set)


if __name__ == "__main__":
    unittest.main()
