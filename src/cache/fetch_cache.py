from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("cache.fetch")

__all__ = ["FetchCache"]


class FetchCache:
    def __init__(self, cache_file: str | Path) -> None:
        self.cache_file = Path(cache_file)
        self._urls: set[str] = set()
        self._load()

    def _load(self) -> None:
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
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(sorted(self._urls), f, ensure_ascii=False, indent=2)

    def contains(self, url: str) -> bool:
        return url in self._urls

    def add(self, url: str) -> None:
        self._urls.add(url)
        self._save()

    def urls(self) -> set[str]:
        return set(self._urls)

    def __contains__(self, url: object) -> bool:
        return isinstance(url, str) and url in self._urls

    def __len__(self) -> int:
        return len(self._urls)
