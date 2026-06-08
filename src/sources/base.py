"""Source_Adapter contract and re-exported :class:`SourceMetadata`.

This module defines the abstract contract that every Source_Adapter implements
and that the pipeline drives uniformly (Requirement 2). A Source_Adapter knows
how to load a game/region news list using a browser session it is *given*
rather than one it launches itself; this decoupling is what lets the
orchestrator drive headless/headed attempts (and a headless->headed fallback)
without the adapter knowing or caring about browser mode.

The contract is deliberately minimal -- a constructor capturing the fetch
parameters plus a single ``fetch_news(driver)`` coroutine -- so that new games
and regions (``honkai-star-rail/global``, ``genshin-impact/cn``,
``genshin-impact/global``, ...) are added purely by registering new adapter
subclasses, with no changes to the pipeline, classifier, or downloader
(Requirement 1.7).

``SourceMetadata`` is defined once in :mod:`src.models`. To avoid duplicating
the dataclass while still honouring the design's module layout (which lists
``SourceMetadata`` alongside the adapter in ``sources/base.py``), it is
imported from the models module and re-exported here. Adapters and callers may
therefore import it from either location interchangeably (Requirement 2.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from ..models import NewsItem, SourceMetadata

if TYPE_CHECKING:  # pragma: no cover - typing only
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

#: Default ceiling on "load more" interactions during a fetch. Bounds the
#: load-more loop together with :data:`DEFAULT_FETCH_TIME_BUDGET`
#: (see Requirement 5.2 / the Honkai: Star Rail adapter in Task 12).
DEFAULT_MAX_INTERACTIONS = 300

#: Default wall-clock budget (seconds) for a single fetch.
DEFAULT_FETCH_TIME_BUDGET = 1000.0


class SourceAdapter(ABC):
    """Abstract contract for retrieving a game/region news list.

    Concrete adapters declare their static :attr:`metadata` (Source_Key, game,
    region, base URL) as a class attribute and implement :meth:`fetch_news`.
    The pipeline constructs an adapter through the Source_Registry, then calls
    :meth:`fetch_news` with a ready :class:`~src.browser.driver.BrowserDriver`.

    The metadata exposes ``source_key``, ``game``, ``region``, and ``base_url``
    (Requirement 2.1). Because every adapter shares this same construction and
    fetch signature, the orchestrator drives them uniformly and new sources are
    added by registration alone (Requirement 1.7).
    """

    #: Static description of the source. Concrete subclasses must set this.
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
        """Capture the parameters governing a fetch.

        Args:
            base_url: The site root the adapter scrapes (for example
                ``https://sr.mihoyo.com``). Relative hrefs are absolutised
                against this during fetching.
            proxy: Optional proxy server address; informational here since the
                browser session is owned by the driver passed to
                :meth:`fetch_news`.
            resume: When ``True``, URLs already present in :attr:`fetch_cache`
                are excluded from the returned items (Resume_Mode).
            fetch_cache: Fetch_Cache used for resume filtering and to record
                newly retrieved URLs; ``None`` disables caching.
            max_interactions: Upper bound on "load more" interactions so the
                load-more loop always terminates (Requirement 5.2).
            fetch_time_budget: Wall-clock budget in seconds for a single fetch;
                another bound on the load-more loop (Requirement 5.2).
            limit: Optional cap on the number of items returned (``--limit``,
                Requirement 10.7). The cap is applied *before* fetched URLs are
                recorded to :attr:`fetch_cache`, so under Resume_Mode only the
                kept items are persisted and the remainder can be fetched on a
                later run. ``None`` (or a negative value) means no limit.
            **kwargs: Accepted and ignored so the Source_Registry can pass
                extra construction arguments uniformly across adapters.
        """
        self.base_url = base_url
        self.proxy = proxy
        self.resume = resume
        self.fetch_cache = fetch_cache
        self.max_interactions = max_interactions
        self.fetch_time_budget = fetch_time_budget
        self.limit = limit

    @abstractmethod
    async def fetch_news(self, driver: BrowserDriver) -> list[NewsItem]:
        """Load the full news list using the provided browser driver.

        Implementations drive the given :class:`BrowserDriver` to load the
        source's news listing (following any "load more" interaction up to the
        configured interaction/time bounds), then return :class:`NewsItem`
        objects that are:

        * **absolute-URL** (relative hrefs absolutised against
          :attr:`base_url`),
        * **deduped** by both title and URL, and
        * **resume-filtered** -- URLs already in :attr:`fetch_cache` are
          excluded when :attr:`resume` is enabled.

        Returning an empty list (when nothing is found) is valid and must not
        raise.

        Args:
            driver: A ready browser session the adapter uses to load pages.

        Returns:
            The list of retrieved :class:`NewsItem` objects.
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# Pure helpers shared by concrete adapters.
#
# These functions hold the parts of an adapter's behaviour that do not require
# a browser, so they can be unit/property tested directly (Properties 3, 4, 5,
# and 8). Concrete adapters drive the browser to gather raw ``(title, href)``
# pairs and then delegate to these helpers for absolutisation, deduplication,
# resume filtering, and load-more termination.
# --------------------------------------------------------------------------- #


def absolutize_href(base_url: str, href: str) -> str:
    """Resolve ``href`` against ``base_url`` into an absolute URL.

    A relative href (for example ``/news/123``) is joined onto ``base_url``;
    an already-absolute href is returned essentially unchanged. This is exactly
    :func:`urllib.parse.urljoin` (Property 3 / Requirement 2.3).
    """
    return urljoin(base_url, href)


def build_news_items(
    base_url: str, raw_pairs: Iterable[tuple[str, str]]
) -> list[NewsItem]:
    """Build a deduped, absolute-URL :class:`NewsItem` list from raw pairs.

    Args:
        base_url: The site root used to absolutise relative hrefs.
        raw_pairs: Iterable of ``(title, href)`` pairs as scraped from the page
            (possibly containing duplicates, empties, and relative hrefs).

    Returns:
        A list of :class:`NewsItem` in first-seen order where every title is
        unique, every URL is unique, and every URL is absolute. Pairs with an
        empty title or empty href are skipped, and a duplicate title *or* a
        duplicate (absolutised) URL drops the later pair. An empty input yields
        an empty list without raising (Property 4 / Requirements 2.2, 2.4).
    """
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
    """Drop items whose URL is already recorded in ``fetch_cache``.

    When ``fetch_cache`` is ``None`` every item is preserved. Otherwise the
    result contains no URL present in the cache and preserves every item whose
    URL is not cached, in order (Property 5 / Requirements 2.5, 8.1, 14.3).
    """
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
    """Decide whether the load-more loop should run another iteration.

    The loop continues **iff** the interaction count is still below the
    configured maximum, the elapsed wall-clock time is still below the
    configured budget, *and* the previous interaction actually loaded new
    items; otherwise it stops (Property 8 / Requirement 5.2).
    """
    return interactions < max_interactions and elapsed < budget and new_items_loaded
