from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..models import DownloadResult, NewsItem

if TYPE_CHECKING:  # pragma: no cover
    from ..browser.driver import BrowserDriver

__all__ = ["Downloader"]


class Downloader(ABC):
    @abstractmethod
    async def download(
        self,
        grouped: dict[str, list[NewsItem]],
        driver: BrowserDriver,
    ) -> list[DownloadResult]:
        raise NotImplementedError
