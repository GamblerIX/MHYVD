"""Video-list export.

After the Classify_Stage, :func:`export_video_list` writes a JSON snapshot of a
pipeline run's news items to disk: every fetched :class:`~src.models.NewsItem`
under ``"fetched"`` and just the ``videos/*`` items (the ones the Downloader
will process) under ``"videos"``. The file is a plain export — it is *not* a
resume cache and is never read back; it exists so a caller can inspect what was
fetched and which items were classified as videos.

The on-disk format is a UTF-8 JSON object::

    {
      "fetched": [{"title": ..., "url": ..., "category": ...}, ...],
      "videos":  [{"title": ..., "url": ..., "category": ...}, ...]
    }

Only serialisation lives here. The function is a pure ``grouped -> path`` writer
so the pipeline can drive it behind an injectable seam and tests need no I/O
beyond a temp dir.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..downloader.playwright_downloader import select_video_categories
from ..models import NewsItem

logger = logging.getLogger("cache.list_export")

__all__ = ["export_video_list", "build_export_payload"]


def _item_dict(item: NewsItem) -> dict[str, str | None]:
    """Render a :class:`NewsItem` as a JSON-serialisable mapping."""
    return {"title": item.title, "url": item.url, "category": item.category}


def build_export_payload(
    grouped: dict[str, list[NewsItem]],
) -> dict[str, list[dict[str, str | None]]]:
    """Build the export payload from a classified ``grouped`` mapping.

    ``grouped`` maps each category to its classified :class:`NewsItem` list (the
    Classify_Stage output). The payload carries two lists, both preserving the
    grouped insertion order:

    * ``"fetched"`` -- every item across all categories.
    * ``"videos"`` -- only items in ``videos/*`` categories (the Downloader's
      selection, via :func:`select_video_categories`).
    """
    fetched = [_item_dict(item) for items in grouped.values() for item in items]
    video_groups = select_video_categories(grouped)
    videos = [_item_dict(item) for items in video_groups.values() for item in items]
    return {"fetched": fetched, "videos": videos}


def export_video_list(
    grouped: dict[str, list[NewsItem]], output_path: str | Path
) -> None:
    """Write the video-list export for ``grouped`` to ``output_path`` as JSON.

    The parent directory is created if missing. The payload is
    :func:`build_export_payload`'s output, serialised as UTF-8 JSON.
    """
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
