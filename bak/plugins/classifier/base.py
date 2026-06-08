"""
分类器插件基类
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any

from core.plugin import Plugin
from core.models import NewsItem


class ClassifierPlugin(Plugin, ABC):
    """分类器插件基类"""

    @abstractmethod
    async def classify(
        self, items: List[NewsItem], **kwargs: Any
    ) -> Dict[str, List[NewsItem]]:
        """
        对新闻进行分类

        Args:
            items: 新闻条目列表

        Returns:
            按类别分组的新闻字典
        """
        pass

    async def execute(
        self, data: List[NewsItem], **kwargs: Any
    ) -> Dict[str, List[NewsItem]]:
        """执行分类"""
        return await self.classify(data, **kwargs)
