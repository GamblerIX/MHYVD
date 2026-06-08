"""下载器插件模块"""

from .base import DownloaderPlugin
from .playwright import PlaywrightDownloader

__all__ = ["DownloaderPlugin", "PlaywrightDownloader"]
