"""Download_Cache persistence.

``DownloadCache`` wraps a JSON object keyed by article URL. Each record holds
the article URL, the resolved video URL, the local file path, the title, the
category, and the file size of a downloaded video. It backs Resume_Mode for the
Download_Stage so that already-downloaded videos can be recognised across runs.

The cache is persisted immediately on every :meth:`DownloadCache.add` so that an
interruption never loses a completed download record (Requirement 8.4). A
missing or unreadable/corrupt cache file loads as an empty cache without raising
(Requirement 8.5), while an existing readable file is loaded as-is
(Requirement 8.6).

Logic is ported from the legacy ``bak/utils/cache.py`` implementation, trimmed
to the fields required by the design's Cache Models section.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: The record fields persisted for each downloaded video, keyed by article URL.
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
    """A JSON-backed record of downloaded videos keyed by article URL.

    Each record is a mapping with the keys ``url`` (article URL), ``video_url``
    (resolved video URL), ``file_path``, ``title``, ``category``, and
    ``file_size``.
    """

    def __init__(self, cache_file: str | Path) -> None:
        self.cache_file = Path(cache_file)
        self._records: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load records from :attr:`cache_file`.

        A missing or corrupt/unreadable file results in an empty cache rather
        than an error. A present, readable file is loaded as-is.
        """
        if not self.cache_file.exists():
            self._records = {}
            return
        try:
            with self.cache_file.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            # ValueError covers json.JSONDecodeError; OSError covers permission
            # and other read errors. Either way we start empty.
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
            # Unexpected JSON shape (e.g. a list); treat as corrupt.
            logger.warning(
                "Download cache %s has unexpected shape, starting empty",
                self.cache_file,
            )
            self._records = {}

    def _save(self) -> None:
        """Persist the current records to :attr:`cache_file`."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as handle:
            json.dump(self._records, handle, ensure_ascii=False, indent=2)

    def is_downloaded(self, url: str) -> bool:
        """Return whether the article ``url`` has a recorded download."""
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
        """Record a downloaded video and persist immediately.

        The record is keyed by ``article_url`` and stores the resolved video
        URL, local file path, title, category, and file size.
        """
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
        """Return the records mapping (article URL -> record)."""
        return self._records
