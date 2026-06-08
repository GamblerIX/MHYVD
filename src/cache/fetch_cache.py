"""Fetch_Cache persistence: a set of already-fetched News_Item URLs.

The :class:`FetchCache` wraps a JSON array of URLs stored on disk. It is used
by Resume_Mode to skip News_Items that were retrieved in a previous run.

Design notes (see the "Cache Models" section and Property 22 in the design
document):

- ``contains(url)`` reports whether a URL is already cached.
- ``add(url)`` records a URL and **persists immediately** to disk so that an
  interrupted run keeps the URLs fetched up to that point.
- ``urls()`` returns the cached URLs.
- A missing or corrupt cache file loads as an **empty** cache without raising,
  mirroring the resilience of the original cache loader.

Only serialisation lives here; the on-disk format is a UTF-8 JSON array of
strings (``["https://...", ...]``).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("cache.fetch")

__all__ = ["FetchCache"]


class FetchCache:
    """Persistent set of fetched News_Item URLs backed by a JSON array file."""

    def __init__(self, cache_file: str | Path) -> None:
        """Create a cache bound to ``cache_file`` and load any existing data.

        A missing or corrupt file results in an empty cache; no error is
        raised.
        """
        self.cache_file = Path(cache_file)
        self._urls: set[str] = set()
        self._load()

    def _load(self) -> None:
        """Load URLs from :attr:`cache_file`, tolerating missing/corrupt data.

        The file is expected to hold a JSON array of strings. Anything that
        cannot be parsed into such a list (missing file, invalid JSON, wrong
        shape, I/O error) yields an empty cache.
        """
        if not self.cache_file.exists():
            self._urls = set()
            return
        try:
            with self.cache_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Fetch cache file unreadable, starting empty: %s", exc)
            self._urls = set()
            return

        if isinstance(data, list):
            self._urls = {item for item in data if isinstance(item, str)}
        else:
            logger.warning(
                "Fetch cache file has unexpected shape (%s), starting empty",
                type(data).__name__,
            )
            self._urls = set()

    def _save(self) -> None:
        """Persist the current URL set to :attr:`cache_file` as a JSON array."""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(sorted(self._urls), f, ensure_ascii=False, indent=2)

    def contains(self, url: str) -> bool:
        """Return ``True`` if ``url`` is recorded in the cache."""
        return url in self._urls

    def add(self, url: str) -> None:
        """Record ``url`` and immediately persist the cache to disk.

        Adding a URL that is already cached is a no-op for the in-memory set
        but still persists, keeping the on-disk file consistent.
        """
        self._urls.add(url)
        self._save()

    def urls(self) -> set[str]:
        """Return a copy of the cached URLs."""
        return set(self._urls)

    def __contains__(self, url: object) -> bool:
        return isinstance(url, str) and url in self._urls

    def __len__(self) -> int:
        return len(self._urls)
