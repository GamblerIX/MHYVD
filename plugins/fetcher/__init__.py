"""抓取器插件模块"""

from .base import FetcherPlugin
from .sr_mihoyo_com import SrMihoyoComFetcher

__all__ = ["FetcherPlugin", "SrMihoyoComFetcher"]
