from __future__ import annotations

import asyncio
import json
import logging
import urllib.request
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from ..models import NewsItem, SourceMetadata
from .base import SourceAdapter, build_news_items, filter_resume_cached

if TYPE_CHECKING:  # pragma: no cover
    from ..browser.driver import BrowserDriver

__all__ = [
    "DEFAULT_RELEASE_LIST_URL",
    "RELEASE_LIST_SOURCE_KEY",
    "ReleaseListAdapter",
    "parse_list_payload",
]

logger = logging.getLogger("sources.release_list")


DEFAULT_RELEASE_LIST_URL = (
    "https://github.com/GamblerIX/MHYVD/releases/download/url-list/url-list.json"
)


RELEASE_LIST_SOURCE_KEY = "release/url-list"


JSON_FETCH_TIMEOUT = 60.0


JsonFetcher = Callable[[str, str | None], Any]


def _default_fetch_json(url: str, proxy: str | None) -> Any:
    handlers: list[urllib.request.BaseHandler] = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
    opener = urllib.request.build_opener(*handlers)
    with opener.open(url, timeout=JSON_FETCH_TIMEOUT) as response:
        raw = response.read()
    return json.loads(raw.decode("utf-8"))


def parse_list_payload(base_url: str, payload: Any) -> list[NewsItem]:
    if not isinstance(payload, dict) or not isinstance(payload.get("fetched"), list):
        raise ValueError(
            f"invalid url-list payload from {base_url}: "
            'expected a JSON object with a "fetched" list'
        )
    raw_pairs = [
        (entry.get("title", ""), entry.get("url", ""))
        for entry in payload["fetched"]
        if isinstance(entry, dict)
    ]
    return build_news_items(base_url, raw_pairs)


class ReleaseListAdapter(SourceAdapter):
    metadata: ClassVar[SourceMetadata] = SourceMetadata(
        source_key=RELEASE_LIST_SOURCE_KEY,
        game="release",
        region="url-list",
        base_url=DEFAULT_RELEASE_LIST_URL,
    )

    def __init__(
        self, *args: Any, fetch_json: JsonFetcher | None = None, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self._fetch_json = fetch_json or _default_fetch_json

    async def fetch_news(self, driver: BrowserDriver) -> list[NewsItem]:
        logger.info("Downloading URL list from %s", self.base_url)
        payload = await asyncio.to_thread(self._fetch_json, self.base_url, self.proxy)
        items = parse_list_payload(self.base_url, payload)
        logger.info("URL list contains %d item(s)", len(items))

        if self.resume:
            before = len(items)
            items = filter_resume_cached(items, self.fetch_cache)
            skipped = before - len(items)
            if skipped:
                logger.info("Skipped %d already-fetched items (resume)", skipped)

        if self.limit is not None and self.limit >= 0:
            items = items[: self.limit]

        if self.fetch_cache is not None:
            for item in items:
                self.fetch_cache.add(item.url)

        return items
