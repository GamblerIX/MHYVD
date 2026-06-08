"""
下载器插件基类
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Any
from pathlib import Path

from core.plugin import Plugin
from core.models import NewsItem, DownloadResult


class DownloaderPlugin(Plugin, ABC):
    """下载器插件基类"""

    def __init__(
        self,
        output_dir: str = "downloads",
        max_concurrent: int = 1,
        retry_count: int = 3,
        timeout: int = 60,
        proxy: Optional[str] = None,
        resume: bool = False,
        cache_file: Optional[str] = None,
        **kwargs: Any,
    ):
        self.output_dir = Path(output_dir)
        self.max_concurrent = max_concurrent
        self.retry_count = retry_count
        self.timeout = timeout
        self.proxy = proxy
        self.resume = resume
        self.cache_file = Path(cache_file) if cache_file else self.output_dir / ".download_cache.json"

    @abstractmethod
    async def download(
        self, items: Dict[str, List[NewsItem]], **kwargs: Any
    ) -> List[DownloadResult]:
        """
        下载视频

        Args:
            items: 按类别分组的新闻字典

        Returns:
            下载结果列表
        """
        pass

    async def execute(
        self, data: Dict[str, List[NewsItem]], **kwargs: Any
    ) -> List[DownloadResult]:
        """执行下载"""
        return await self.download(data, **kwargs)
