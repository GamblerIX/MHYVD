"""Tests for ``src.cache.list_export``.

Covers the export payload shape (all fetched items plus the ``videos/*``
subset) and the on-disk JSON writer.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.cache.list_export import build_export_payload, export_video_list
from src.models import NewsItem


def _grouped() -> dict[str, list[NewsItem]]:
    """A classified mapping mixing videos/* and non-video categories."""
    return {
        "videos/pv/character": [
            NewsItem("角色 PV：A", "https://x/1", "videos/pv/character"),
            NewsItem("角色 PV：B", "https://x/2", "videos/pv/character"),
        ],
        "news/notice": [
            NewsItem("公告 C", "https://x/3", "news/notice"),
        ],
        "videos/op": [
            NewsItem("OP：D", "https://x/4", "videos/op"),
        ],
    }


class BuildExportPayloadTests(unittest.TestCase):
    def test_fetched_holds_every_item(self) -> None:
        payload = build_export_payload(_grouped())
        urls = [item["url"] for item in payload["fetched"]]
        self.assertEqual(
            urls, ["https://x/1", "https://x/2", "https://x/3", "https://x/4"]
        )

    def test_videos_holds_only_video_categories(self) -> None:
        payload = build_export_payload(_grouped())
        urls = [item["url"] for item in payload["videos"]]
        # videos/* only; the news/notice item is excluded.
        self.assertEqual(urls, ["https://x/1", "https://x/2", "https://x/4"])

    def test_item_fields(self) -> None:
        payload = build_export_payload(_grouped())
        self.assertEqual(
            payload["fetched"][0],
            {
                "title": "角色 PV：A",
                "url": "https://x/1",
                "category": "videos/pv/character",
            },
        )

    def test_empty_grouped(self) -> None:
        payload = build_export_payload({})
        self.assertEqual(payload, {"fetched": [], "videos": []})


class ExportVideoListTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "out" / "cache.json"

    def test_writes_json_and_creates_parent(self) -> None:
        export_video_list(_grouped(), self.path)
        self.assertTrue(self.path.exists())
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(len(data["fetched"]), 4)
        self.assertEqual(len(data["videos"]), 3)

    def test_non_ascii_preserved(self) -> None:
        export_video_list(_grouped(), self.path)
        raw = self.path.read_text(encoding="utf-8")
        self.assertIn("角色 PV：A", raw)


if __name__ == "__main__":
    unittest.main()
