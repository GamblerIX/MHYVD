"""The ``Downloader`` abstract base class.

A Downloader takes the classifier's grouped ``{category: [NewsItem]}`` mapping
and a ready :class:`~src.browser.driver.BrowserDriver`, resolves video URLs for
the items it is responsible for, downloads them, and returns a
:class:`~src.models.DownloadResult` for every item it processes
(Requirement 7). The contract is asynchronous because resolution and download
are I/O bound and run concurrently under a bounded semaphore.

Concrete implementations (for example
:class:`~src.downloader.playwright_downloader.PlaywrightDownloader`) decide
*how* URLs are resolved and files written, but every implementation must:

* process only the video categories it is meant to handle (Requirement 7.1),
* produce exactly one :class:`DownloadResult` per processed item, isolating
  per-item failures so one failure never drops or blocks the others
  (Requirement 12.2).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..models import DownloadResult, NewsItem

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..browser.driver import BrowserDriver

__all__ = ["Downloader"]


class Downloader(ABC):
    """Contract for resolving and downloading videos for grouped News_Items."""

    @abstractmethod
    async def download(
        self,
        grouped: dict[str, list[NewsItem]],
        driver: BrowserDriver,
    ) -> list[DownloadResult]:
        """Resolve and download videos for the relevant categories.

        Args:
            grouped: The classifier output mapping each category to its items.
            driver: A ready browser session used to load article pages.

        Returns:
            One :class:`DownloadResult` per processed item. Items in categories
            the downloader does not handle are not represented; every item the
            downloader *does* process yields a result even on failure.
        """
        raise NotImplementedError
