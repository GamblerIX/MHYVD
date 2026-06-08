"""
流水线管理
"""

import asyncio
import logging
from typing import Optional

from core.plugin import PluginRegistry
from core.models import PipelineResult
from config.settings import Config

logger = logging.getLogger("pipeline")


class Pipeline:
    """数据处理流水线"""

    def __init__(self, config: Optional[Config] = None, resume: bool = False):
        self.config = config or Config()
        self.resume = resume
        self.fetcher: Optional[PluginRegistry] = None
        self.classifier: Optional[PluginRegistry] = None
        self.downloader: Optional[PluginRegistry] = None

        self._load_plugins()
        self._init_plugins()

    def _load_plugins(self) -> None:
        """加载所有插件"""
        from plugins.fetcher import sr_mihoyo_com  # noqa: F401
        from plugins.classifier import rule_based  # noqa: F401
        from plugins.downloader import playwright  # noqa: F401

    def _init_plugins(self) -> None:
        """初始化插件实例"""
        fetcher_config = self.config.get("fetcher", {})
        classifier_config = self.config.get("classifier", {})
        downloader_config = self.config.get("downloader", {})

        self.fetcher = PluginRegistry.create(
            fetcher_config.get("plugin", "sr.mihoyo.com"),
            base_url=fetcher_config.get("base_url", "https://sr.mihoyo.com"),
            proxy=self.config.get_proxy(),
            resume=self.resume,
        )

        self.classifier = PluginRegistry.create(
            classifier_config.get("plugin", "rule_based")
        )

        self.downloader = PluginRegistry.create(
            downloader_config.get("plugin", "playwright"),
            output_dir=downloader_config.get("output_dir", "downloads"),
            max_concurrent=downloader_config.get("max_concurrent", 1),
            retry_count=downloader_config.get("retry_count", 3),
            timeout=downloader_config.get("timeout", 60),
            proxy=self.config.get_proxy(),
            resume=self.resume,
        )

    async def run(self, headless: bool = True) -> PipelineResult:
        """
        执行完整流水线

        Args:
            headless: 是否使用无头模式

        Returns:
            流水线执行结果

        Raises:
            RuntimeError: 当任一阶段失败时
        """
        result = PipelineResult()

        try:
            # 阶段 1：抓取新闻列表
            logger.info("=" * 50)
            logger.info("  阶段 1 / 3：抓取新闻列表")
            logger.info("=" * 50)

            news_items = await self.fetcher.execute(headless=headless)
            result.news_count = len(news_items)

            if not news_items:
                logger.warning("未抓取到任何新闻")
                return result

            logger.info("共抓取 %d 条新闻", len(news_items))

            # 阶段 2：分类筛选
            logger.info("=" * 50)
            logger.info("  阶段 2 / 3：分类筛选")
            logger.info("=" * 50)

            classified = await self.classifier.execute(news_items, headless=headless)
            result.classified_categories = {
                cat: len(items) for cat, items in classified.items()
            }

            logger.info("分类完成：%d 个类别", len(classified))

            # 阶段 3：视频下载
            logger.info("=" * 50)
            logger.info("  阶段 3 / 3：视频下载")
            logger.info("=" * 50)

            # 只下载 videos 分类下的视频
            video_items = {
                cat: items for cat, items in classified.items()
                if cat.startswith("videos/")
            }
            logger.info("过滤后：%d 个视频分类待下载", len(video_items))

            if video_items:
                download_results = await self.downloader.execute(video_items, headless=headless)
                result.download_results = download_results
            else:
                logger.info("没有视频分类，跳过下载阶段")
                result.download_results = []

            logger.info("=" * 50)
            logger.info(
                "✅ 流水线完成：成功 %d，跳过 %d，失败 %d",
                result.downloaded,
                result.skipped,
                result.failed,
            )
            logger.info("=" * 50)

            return result

        except asyncio.CancelledError:
            logger.warning("流水线被取消")
            raise
        except RuntimeError as e:
            logger.error("流水线运行时错误：%s", str(e))
            raise
        except Exception as e:
            logger.exception("流水线执行失败：%s", str(e))
            raise
