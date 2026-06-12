from __future__ import annotations

from .. import __version__
from .base import Downloader
from .playwright_downloader import PlaywrightDownloader
from .registry import DownloaderRegistry, UnknownDownloaderError

__all__ = [
    "__version__",
    "Downloader",
    "DownloaderRegistry",
    "UnknownDownloaderError",
    "PlaywrightDownloader",
    "default_registry",
    "get_downloader_registry",
]


PLAYWRIGHT_DOWNLOADER_NAME = "playwright"


default_registry = DownloaderRegistry()
default_registry.register(PLAYWRIGHT_DOWNLOADER_NAME, PlaywrightDownloader)


def get_downloader_registry() -> DownloaderRegistry:
    return default_registry
