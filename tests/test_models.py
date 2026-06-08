"""Unit tests for the frozen dataclass models in ``src.models``."""

from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from src.constants import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_SKIPPED
from src.models import (
    DownloadResult,
    NewsItem,
    PipelineResult,
    Rule,
    SourceMetadata,
    VideoItem,
)


def _result(
    status: str,
    *,
    title: str = "t",
    category: str = "videos/pv",
    bytes_written: int = 0,
    error: str | None = None,
) -> DownloadResult:
    return DownloadResult(
        title=title,
        url="https://sr.mihoyo.com/news/1",
        category=category,
        video_url="https://example.com/v.mp4",
        local_path=Path("out") / "v.mp4",
        status=status,
        bytes_written=bytes_written,
        error=error,
    )


class TestNewsItem(unittest.TestCase):
    def test_is_frozen(self) -> None:
        item = NewsItem(title="hello", url="https://x/news/1")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            item.title = "changed"  # type: ignore[misc]

    def test_default_category_is_none(self) -> None:
        item = NewsItem(title="hello", url="https://x/news/1")
        self.assertIsNone(item.category)

    def test_with_category_returns_new_item(self) -> None:
        item = NewsItem(title="hello", url="https://x/news/1")
        tagged = item.with_category("videos/pv")
        self.assertEqual(tagged.category, "videos/pv")
        self.assertEqual(tagged.title, item.title)
        self.assertEqual(tagged.url, item.url)
        # Original is unchanged (immutability).
        self.assertIsNone(item.category)
        self.assertIsNot(tagged, item)


class TestVideoItem(unittest.TestCase):
    def test_is_frozen(self) -> None:
        video = VideoItem(title="t", url="u", category="videos/pv")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            video.video_url = "x"  # type: ignore[misc]

    def test_optional_defaults(self) -> None:
        video = VideoItem(title="t", url="u", category="videos/pv")
        self.assertIsNone(video.video_url)
        self.assertIsNone(video.file_size)
        self.assertIsNone(video.local_path)


class TestSourceMetadataAndRule(unittest.TestCase):
    def test_source_metadata_frozen(self) -> None:
        meta = SourceMetadata(
            source_key="honkai-star-rail/cn",
            game="honkai-star-rail",
            region="cn",
            base_url="https://sr.mihoyo.com",
        )
        with self.assertRaises(dataclasses.FrozenInstanceError):
            meta.region = "global"  # type: ignore[misc]

    def test_rule_frozen_with_tuple_keywords(self) -> None:
        rule = Rule(category="videos/pv", keywords=("PV", "预告"))
        self.assertEqual(rule.keywords, ("PV", "预告"))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            rule.category = "x"  # type: ignore[misc]


class TestDownloadResult(unittest.TestCase):
    def test_is_frozen(self) -> None:
        result = _result(STATUS_DOWNLOADED)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            result.status = STATUS_FAILED  # type: ignore[misc]

    def test_as_markdown_includes_status_and_bytes(self) -> None:
        result = _result(STATUS_DOWNLOADED, title="My Video", bytes_written=2048)
        md = result.as_markdown()
        self.assertIn(STATUS_DOWNLOADED, md)
        self.assertIn("My Video", md)
        self.assertIn("2048", md)

    def test_as_markdown_includes_error_for_failure(self) -> None:
        result = _result(STATUS_FAILED, error="no video url")
        md = result.as_markdown()
        self.assertIn(STATUS_FAILED, md)
        self.assertIn("no video url", md)


class TestPipelineResult(unittest.TestCase):
    def test_defaults(self) -> None:
        pr = PipelineResult()
        self.assertEqual(pr.news_count, 0)
        self.assertEqual(pr.classified_categories, {})
        self.assertEqual(pr.download_results, ())
        self.assertFalse(pr.completed)
        self.assertIsNone(pr.error)
        self.assertEqual((pr.downloaded, pr.skipped, pr.failed), (0, 0, 0))

    def test_is_frozen(self) -> None:
        pr = PipelineResult()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            pr.news_count = 5  # type: ignore[misc]

    def test_derived_counts(self) -> None:
        results = (
            _result(STATUS_DOWNLOADED),
            _result(STATUS_DOWNLOADED),
            _result(STATUS_SKIPPED),
            _result(STATUS_FAILED),
        )
        pr = PipelineResult(news_count=4, download_results=results)
        self.assertEqual(pr.downloaded, 2)
        self.assertEqual(pr.skipped, 1)
        self.assertEqual(pr.failed, 1)
        # Sum of derived counts equals total results.
        self.assertEqual(
            pr.downloaded + pr.skipped + pr.failed, len(pr.download_results)
        )

    def test_as_markdown_non_empty_and_reports_counts(self) -> None:
        results = (_result(STATUS_DOWNLOADED), _result(STATUS_FAILED, error="boom"))
        pr = PipelineResult(
            news_count=2,
            classified_categories={"videos/pv": 1, "others": 1},
            download_results=results,
            completed=True,
        )
        md = pr.as_markdown()
        self.assertTrue(md.strip())
        self.assertIn("Downloaded: 1", md)
        self.assertIn("Skipped: 0", md)
        self.assertIn("Failed: 1", md)
        self.assertIn("videos/pv", md)
        self.assertIn("completed", md)

    def test_as_markdown_includes_error_when_present(self) -> None:
        pr = PipelineResult(completed=False, error="fetch failed")
        md = pr.as_markdown()
        self.assertIn("fetch failed", md)
        self.assertIn("incomplete", md)


if __name__ == "__main__":
    unittest.main()
