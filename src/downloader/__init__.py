"""Downloader subsystem: URL resolution, path building, and video download.

Importing this package builds the :data:`default_registry` and registers every
built-in :class:`~src.downloader.base.Downloader` on it, so callers obtain a
fully-populated registry through :func:`get_downloader_registry` without having
to know which downloaders exist. New downloaders are added by registering them
here.
"""

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

#: The registered name of the default Playwright downloader.
PLAYWRIGHT_DOWNLOADER_NAME = "playwright"

#: Process-wide registry pre-populated with the built-in downloaders.
default_registry = DownloaderRegistry()
default_registry.register(PLAYWRIGHT_DOWNLOADER_NAME, PlaywrightDownloader)


def get_downloader_registry() -> DownloaderRegistry:
    """Return the process-wide registry populated with built-in downloaders."""
    return default_registry
