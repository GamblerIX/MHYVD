from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.cache.download_cache import RECORD_FIELDS, DownloadCache

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


class DownloadCacheUnitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "downloads.json"

    def test_missing_file_loads_empty(self) -> None:
        cache = DownloadCache(self.cache_path)
        self.assertEqual(cache.records(), {})
        self.assertFalse(cache.is_downloaded("https://host/news/1"))

    def test_add_then_is_downloaded(self) -> None:
        cache = DownloadCache(self.cache_path)
        cache.add(
            "https://host/news/1",
            "https://cdn/v.mp4",
            "/out/videos/pv/title [1].mp4",
            "Title",
            "videos/pv",
            12345,
        )
        self.assertTrue(cache.is_downloaded("https://host/news/1"))
        self.assertFalse(cache.is_downloaded("https://host/news/2"))

    def test_add_persists_immediately(self) -> None:
        cache = DownloadCache(self.cache_path)
        cache.add(
            "https://host/news/1",
            "https://cdn/v.mp4",
            "/out/v.mp4",
            "Title",
            "videos/pv",
            42,
        )

        self.assertTrue(self.cache_path.exists())
        on_disk = json.loads(self.cache_path.read_text(encoding="utf-8"))
        self.assertIn("https://host/news/1", on_disk)
        self.assertEqual(on_disk["https://host/news/1"]["file_size"], 42)

    def test_record_holds_all_fields(self) -> None:
        cache = DownloadCache(self.cache_path)
        cache.add(
            "https://host/news/7",
            "https://cdn/v.mkv",
            "/out/v.mkv",
            "标题",
            "videos/character",
            999,
        )
        record = cache.records()["https://host/news/7"]
        for field in RECORD_FIELDS:
            self.assertIn(field, record)
        self.assertEqual(record["url"], "https://host/news/7")
        self.assertEqual(record["video_url"], "https://cdn/v.mkv")
        self.assertEqual(record["file_path"], "/out/v.mkv")
        self.assertEqual(record["title"], "标题")
        self.assertEqual(record["category"], "videos/character")
        self.assertEqual(record["file_size"], 999)

    def test_existing_readable_file_is_loaded(self) -> None:
        payload = {
            "https://host/news/1": {
                "url": "https://host/news/1",
                "video_url": "https://cdn/v.mp4",
                "file_path": "/out/v.mp4",
                "title": "T",
                "category": "videos/pv",
                "file_size": 5,
            }
        }
        self.cache_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        cache = DownloadCache(self.cache_path)
        self.assertTrue(cache.is_downloaded("https://host/news/1"))
        self.assertEqual(cache.records(), payload)

    def test_corrupt_file_loads_empty(self) -> None:
        self.cache_path.write_text("{ not valid json", encoding="utf-8")
        cache = DownloadCache(self.cache_path)
        self.assertEqual(cache.records(), {})

    def test_unexpected_shape_loads_empty(self) -> None:

        self.cache_path.write_text("[1, 2, 3]", encoding="utf-8")
        cache = DownloadCache(self.cache_path)
        self.assertEqual(cache.records(), {})

    def test_add_creates_parent_directories(self) -> None:
        nested = Path(self._tmp.name) / "a" / "b" / "downloads.json"
        cache = DownloadCache(nested)
        cache.add("https://host/news/1", "https://cdn/v.mp4", "/o", "T", "videos/pv", 1)
        self.assertTrue(nested.exists())

    def test_add_overwrites_same_article_url(self) -> None:
        cache = DownloadCache(self.cache_path)
        cache.add(
            "https://host/news/1", "https://cdn/a.mp4", "/o/a", "A", "videos/pv", 1
        )
        cache.add(
            "https://host/news/1", "https://cdn/b.mp4", "/o/b", "B", "videos/pv", 2
        )
        self.assertEqual(len(cache.records()), 1)
        self.assertEqual(
            cache.records()["https://host/news/1"]["video_url"], "https://cdn/b.mp4"
        )


class Property23DownloadCacheRoundTrip(unittest.TestCase):
    def _assert_round_trip(
        self, records: list[tuple[str, str, str, str, str, int]]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_path = Path(tmp) / "downloads.json"

            writer = DownloadCache(cache_path)
            for (
                article_url,
                video_url,
                file_path,
                title,
                category,
                file_size,
            ) in records:
                writer.add(
                    article_url, video_url, file_path, title, category, file_size
                )

            expected: dict[str, dict[str, object]] = {}
            for (
                article_url,
                video_url,
                file_path,
                title,
                category,
                file_size,
            ) in records:
                expected[article_url] = {
                    "url": article_url,
                    "video_url": video_url,
                    "file_path": file_path,
                    "title": title,
                    "category": category,
                    "file_size": file_size,
                }

            reader = DownloadCache(cache_path)
            self.assertEqual(reader.records(), expected)
            for article_url in expected:
                self.assertTrue(reader.is_downloaded(article_url))

    if _HAS_HYPOTHESIS:
        _text = st.text(max_size=40)
        _record = st.tuples(
            st.text(min_size=1, max_size=40),
            _text,
            _text,
            _text,
            _text,
            st.integers(min_value=0, max_value=10**15),
        )

        @settings(max_examples=200)
        @given(st.lists(_record, max_size=15))
        def test_round_trip_preserves_fields(
            self, records: list[tuple[str, str, str, str, str, int]]
        ) -> None:
            self._assert_round_trip(records)

    else:

        def test_round_trip_preserves_fields_fallback(self) -> None:
            import random

            rng = random.Random(20240608)
            alphabet = "abcDEF012-/ 标题:?"
            for _ in range(300):
                size = rng.randint(0, 15)
                records = []
                for _ in range(size):

                    def tok() -> str:
                        n = rng.randint(0, 12)
                        return "".join(rng.choice(alphabet) for _ in range(n))

                    records.append(
                        (
                            "url-" + tok() or "u",
                            tok(),
                            tok(),
                            tok(),
                            tok(),
                            rng.randint(0, 10**12),
                        )
                    )
                self._assert_round_trip(records)

    def test_missing_file_loads_empty_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache = DownloadCache(Path(tmp) / "absent.json")
            self.assertEqual(cache.records(), {})

    def test_corrupt_file_loads_empty_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "corrupt.json"
            path.write_text("\x00\x01 not json {{{", encoding="utf-8")
            cache = DownloadCache(path)
            self.assertEqual(cache.records(), {})


if __name__ == "__main__":
    unittest.main()
