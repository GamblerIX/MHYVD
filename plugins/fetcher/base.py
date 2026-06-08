"""
抓取器插件基类
"""

import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional, Any, Set

from core.plugin import Plugin
from core.models import NewsItem

logger = logging.getLogger("fetcher")


class FetcherPlugin(Plugin, ABC):
    """抓取器插件基类"""

    def __init__(
        self,
        base_url: str,
        proxy: Optional[str] = None,
        resume: bool = False,
        cache_file: Optional[str] = None,
        **kwargs: Any,
    ):
        self.base_url = base_url
        self.proxy = proxy
        self.resume = resume
        self._cache_file = Path(cache_file) if cache_file else Path("cache/fetch_cache.json")
        self._cached_urls: Set[str] = set()
        
        if self.resume:
            self._load_cache()

    def _load_cache(self) -> None:
        """加载已抓取的 URL 缓存"""
        if self._cache_file.exists():
            try:
                with self._cache_file.open("r", encoding="utf-8") as f:
                    self._cached_urls = set(json.load(f))
                logger.info("已加载抓取缓存：%d 条 URL", len(self._cached_urls))
            except (json.JSONDecodeError, IOError):
                self._cached_urls = set()
        else:
            self._cached_urls = set()

    def _save_cache(self) -> None:
        """保存已抓取的 URL 缓存"""
        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self._cache_file.open("w", encoding="utf-8") as f:
            json.dump(list(self._cached_urls), f, ensure_ascii=False, indent=2)

    def _is_url_cached(self, url: str) -> bool:
        """检查 URL 是否已缓存"""
        return url in self._cached_urls

    def _add_to_cache(self, url: str) -> None:
        """添加 URL 到缓存"""
        self._cached_urls.add(url)
        self._save_cache()

    @abstractmethod
    async def fetch_news(self, **kwargs: Any) -> List[NewsItem]:
        """
        抓取新闻列表

        Returns:
            新闻条目列表
        """
        pass

    async def execute(self, data: Optional[Any] = None, **kwargs: Any) -> List[NewsItem]:
        """执行抓取"""
        return await self.fetch_news(**kwargs)
