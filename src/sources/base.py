from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from ..models import NewsItem, SourceMetadata

if TYPE_CHECKING:  # pragma: no cover
    from ..browser.driver import BrowserDriver
    from ..cache.fetch_cache import FetchCache

__all__ = [
    "SourceAdapter",
    "SourceMetadata",
    "absolutize_href",
    "build_news_items",
    "filter_resume_cached",
    "should_continue_load_more",
]


DEFAULT_MAX_INTERACTIONS = 1000


DEFAULT_FETCH_TIME_BUDGET = 3000.0


class SourceAdapter(ABC):
    metadata: ClassVar[SourceMetadata]

    def __init__(
        self,
        base_url: str,
        proxy: str | None = None,
        resume: bool = False,
        fetch_cache: FetchCache | None = None,
        max_interactions: int = DEFAULT_MAX_INTERACTIONS,
        fetch_time_budget: float = DEFAULT_FETCH_TIME_BUDGET,
        limit: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.base_url = base_url
        self.proxy = proxy
        self.resume = resume
        self.fetch_cache = fetch_cache
        self.max_interactions = max_interactions
        self.fetch_time_budget = fetch_time_budget
        self.limit = limit

    @abstractmethod
    async def fetch_news(self, driver: BrowserDriver) -> list[NewsItem]:
        raise NotImplementedError


def absolutize_href(base_url: str, href: str) -> str:
    try:
        return urljoin(base_url, href)
    except ValueError:
        return href


def build_news_items(
    base_url: str, raw_pairs: Iterable[tuple[str, str]]
) -> list[NewsItem]:
    seen_titles: set[str] = set()
    seen_urls: set[str] = set()
    items: list[NewsItem] = []
    for title, href in raw_pairs:
        if not title or not href:
            continue
        url = absolutize_href(base_url, href)
        if title in seen_titles or url in seen_urls:
            continue
        seen_titles.add(title)
        seen_urls.add(url)
        items.append(NewsItem(title=title, url=url))
    return items


def filter_resume_cached(
    items: Iterable[NewsItem], fetch_cache: FetchCache | None
) -> list[NewsItem]:
    if fetch_cache is None:
        return list(items)
    return [item for item in items if not fetch_cache.contains(item.url)]


def should_continue_load_more(
    interactions: int,
    max_interactions: int,
    elapsed: float,
    budget: float,
    new_items_loaded: bool,
) -> bool:
    return interactions < max_interactions and elapsed < budget and new_items_loaded
