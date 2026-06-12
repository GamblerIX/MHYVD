from __future__ import annotations

import json
import logging
from pathlib import Path

from ..downloader.playwright_downloader import select_video_categories
from ..models import NewsItem

logger = logging.getLogger("cache.list_export")

__all__ = ["export_video_list", "build_export_payload"]


def _item_dict(item: NewsItem) -> dict[str, str | None]:
    return {"title": item.title, "url": item.url, "category": item.category}


def build_export_payload(
    grouped: dict[str, list[NewsItem]],
) -> dict[str, list[dict[str, str | None]]]:
    fetched = [_item_dict(item) for items in grouped.values() for item in items]
    video_groups = select_video_categories(grouped)
    videos = [_item_dict(item) for items in video_groups.values() for item in items]
    return {"fetched": fetched, "videos": videos}


def export_video_list(
    grouped: dict[str, list[NewsItem]], output_path: str | Path
) -> None:
    path = Path(output_path)
    payload = build_export_payload(grouped)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    logger.info(
        "Exported video list to %s (%d fetched, %d videos)",
        path,
        len(payload["fetched"]),
        len(payload["videos"]),
    )
