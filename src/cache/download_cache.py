from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


RECORD_FIELDS = (
    "url",
    "video_url",
    "file_path",
    "title",
    "category",
    "file_size",
)

__all__ = ["DownloadCache", "RECORD_FIELDS"]


class DownloadCache:
    def __init__(self, cache_file: str | Path) -> None:
        self.cache_file = Path(cache_file)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.cache_file.exists():
            self._records = {}
            return
        try:
            with self.cache_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            logger.warning(
                "Download cache %s is unreadable, starting empty: %s",
                self.cache_file,
                exc,
            )
            self._records = {}
            return

        if isinstance(data, dict):
            self._records = {
                str(key): dict(value)
                for key, value in data.items()
                if isinstance(value, dict)
            }
            logger.debug("Loaded download cache: %d record(s)", len(self._records))
        else:
            logger.warning(
                "Download cache %s has unexpected shape, starting empty",
                self.cache_file,
            )
            self._records = {}

    def _save(self) -> None:
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as handle:
            json.dump(self._records, handle, ensure_ascii=False, indent=2)

    def is_downloaded(self, url: str) -> bool:
        return url in self._records

    def add(
        self,
        article_url: str,
        video_url: str,
        file_path: str,
        title: str,
        category: str,
        file_size: int,
    ) -> None:
        self._records[article_url] = {
            "url": article_url,
            "video_url": video_url,
            "file_path": file_path,
            "title": title,
            "category": category,
            "file_size": file_size,
        }
        self._save()
        logger.debug("Cached download record for %s", article_url)

    def records(self) -> dict[str, dict[str, Any]]:
        return self._records
