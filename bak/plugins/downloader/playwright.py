"""
Playwright 下载器
"""

import asyncio
import logging
import re
import unicodedata
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright, ProxySettings

from core.models import NewsItem, DownloadResult
from plugins.downloader.base import DownloaderPlugin
from core.plugin import PluginMetadata, PluginRegistry

logger = logging.getLogger("downloader.playwright")

MEDIA_EXTENSIONS = (".mp4", ".mkv", ".flv")
MEDIA_URL_RE = re.compile(
    r"https?://[^\"'<>\s]+?\.(?:mp4|mkv|flv)(?:\?[^\"'<>\s]*)?",
    re.IGNORECASE,
)
NEWS_ID_RE = re.compile(r"/news/(\d+)")
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]+')


class PlaywrightDownloader(DownloaderPlugin):
    """基于 Playwright 的视频下载器"""

    metadata = PluginMetadata(
        name="playwright",
        version="1.0.0",
        description="基于 Playwright 的视频下载器",
    )

    def __init__(
        self,
        output_dir: str = "downloads",
        max_concurrent: int = 1,
        retry_count: int = 3,
        timeout: int = 60,
        proxy: Optional[str] = None,
        resume: bool = False,
        **kwargs: Any,
    ):
        super().__init__(
            output_dir=output_dir,
            max_concurrent=max_concurrent,
            retry_count=retry_count,
            timeout=timeout,
            proxy=proxy,
            resume=resume,
        )
        self._shutdown_requested = False

    def request_shutdown(self) -> None:
        """请求关闭"""
        self._shutdown_requested = True
        logger.info("已请求关闭，将保存进度并退出...")

    def is_shutdown_requested(self) -> bool:
        """检查是否已请求关闭"""
        return self._shutdown_requested

    async def download(
        self, items: Dict[str, List[NewsItem]], headless: bool = True, **kwargs: Any
    ) -> List[DownloadResult]:
        """
        下载视频

        Args:
            items: 按类别分组的新闻字典
            headless: 是否使用无头模式

        Returns:
            下载结果列表
        """
        all_items = self._flatten_items(items)

        if not all_items:
            logger.warning("没有待下载的视频")
            return []

        logger.info("共 %d 个视频待下载", len(all_items))

        semaphore = asyncio.Semaphore(self.max_concurrent)
        proxy_config: Optional[ProxySettings] = None

        if self.proxy:
            proxy_config = ProxySettings(server=self.proxy)

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--disable-blink-features=AutomationControlled"],
            )

            try:
                context = await browser.new_context(proxy=proxy_config)
                results: List[DownloadResult] = []

                async def process_item(item: NewsItem) -> None:
                    async with semaphore:
                        if self.is_shutdown_requested():
                            return
                        result = await self._process_item(context, item)
                        results.append(result)

                await asyncio.gather(
                    *[process_item(item) for item in all_items]
                )

                return results

            finally:
                await browser.close()

    def _flatten_items(
        self, items: Dict[str, List[NewsItem]]
    ) -> List[NewsItem]:
        """扁平化所有待下载项"""
        all_items = []
        for category, news_list in items.items():
            for item in news_list:
                categorized_item = item.with_category(category)
                all_items.append(categorized_item)
        return all_items

    async def _process_item(
        self, context: Any, item: NewsItem
    ) -> DownloadResult:
        """处理单个新闻项"""
        output_path = self._build_output_path(item)
        item_category = item.category or ""

        # resume 模式：检查文件是否已存在
        if self.resume and output_path.exists():
            logger.info("  跳过已下载：%s", item.title)
            return DownloadResult(
                title=item.title,
                url=item.url,
                category=item_category,
                video_url="",
                local_path=output_path,
                status="skipped",
                bytes_written=0,
                remote_size=output_path.stat().st_size,
            )

        video_url = await self._discover_video_url(context, item)

        if not video_url:
            return DownloadResult(
                title=item.title,
                url=item.url,
                category=item_category,
                video_url="",
                local_path=Path(),
                status="failed",
                error="未找到视频 URL",
            )

        try:
            result = await self._download_file(video_url, output_path)
            return DownloadResult(
                title=item.title,
                url=item.url,
                category=item_category,
                video_url=video_url,
                local_path=output_path,
                status=result["status"],
                bytes_written=result.get("bytes_written", 0),
                remote_size=result.get("remote_size"),
            )
        except Exception as e:
            return DownloadResult(
                title=item.title,
                url=item.url,
                category=item_category,
                video_url=video_url,
                local_path=output_path,
                status="failed",
                error=str(e),
            )

    async def _discover_video_url(
        self, context: Any, item: NewsItem
    ) -> Optional[str]:
        """发现视频 URL"""
        last_exception = None

        for attempt in range(self.retry_count):
            page = await context.new_page()
            captured_urls: List[str] = []

            def on_response(response: Any) -> None:
                url = self._normalize_media_url(response.url)
                if url:
                    captured_urls.append(url)

            page.on("response", on_response)

            try:
                await page.goto(
                    item.url, wait_until="domcontentloaded", timeout=60000
                )

                try:
                    await page.wait_for_selector("video", timeout=8000)
                except Exception:
                    await page.wait_for_timeout(2000)

                media_urls = await self._extract_media_urls_from_page(
                    page, captured_urls
                )

                if media_urls:
                    return media_urls[0]

                if attempt < self.retry_count - 1:
                    logger.warning(
                        "  第 %d/%d 次尝试未找到媒体 URL，%d 秒后重试...",
                        attempt + 1,
                        self.retry_count,
                        2,
                    )
                    await asyncio.sleep(2)

            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "  第 %d/%d 次尝试失败：%s",
                    attempt + 1,
                    self.retry_count,
                    str(exc),
                )
                await asyncio.sleep(2)
            finally:
                try:
                    await page.close()
                except Exception:
                    pass

        logger.warning("未发现视频地址：%s", item.url)
        return None

    async def _extract_media_urls_from_page(
        self, page: Any, captured_urls: List[str]
    ) -> List[str]:
        """从页面提取媒体 URL"""
        dom_urls = await page.evaluate(
            """() => {
                const candidates = [];
                for (const video of document.querySelectorAll('video')) {
                    candidates.push(video.currentSrc || video.src || '');
                    for (const source of video.querySelectorAll('source')) {
                        candidates.push(source.src || source.getAttribute('src') || '');
                    }
                }
                for (const anchor of document.querySelectorAll('a[href]')) {
                    candidates.push(anchor.href || anchor.getAttribute('href') || '');
                }
                return candidates;
            }"""
        )

        html = await page.content()
        html_urls = MEDIA_URL_RE.findall(html)

        all_urls = self._dedupe_media_urls(
            [*dom_urls, *html_urls, *captured_urls]
        )
        return all_urls

    def _normalize_media_url(self, candidate: str) -> Optional[str]:
        """标准化媒体 URL"""
        value = candidate.strip()
        if not value:
            return None

        if value.startswith("//"):
            value = f"https:{value}"

        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"}:
            return None

        if Path(parsed.path).suffix.lower() not in MEDIA_EXTENSIONS:
            return None

        query_values = parse_qs(parsed.query)
        oss_process = "".join(query_values.get("x-oss-process", []))
        if "snapshot" in oss_process.lower():
            return None

        return value

    def _dedupe_media_urls(self, candidates: List[str]) -> List[str]:
        """去重媒体 URL"""
        unique_urls: List[str] = []
        seen: set[str] = set()

        for candidate in candidates:
            url = self._normalize_media_url(candidate)
            if url is None or url in seen:
                continue
            seen.add(url)
            unique_urls.append(url)

        return unique_urls

    def _build_output_path(self, item: NewsItem) -> Path:
        """构建输出路径"""
        news_id = self._extract_news_id(item.url)
        safe_name = self._sanitize_filename(item.title)
        base_name = f"{safe_name} [{news_id}]"
        category = item.category or "others"

        return self.output_dir / category / f"{base_name}.mp4"

    def _extract_news_id(self, url: str) -> str:
        """提取新闻 ID"""
        match = NEWS_ID_RE.search(url)
        if match:
            return match.group(1)
        return "unknown"

    def _sanitize_filename(self, value: str) -> str:
        """清理文件名"""
        normalized = unicodedata.normalize("NFKC", value)
        cleaned = [
            char
            for char in normalized
            if not unicodedata.category(char).startswith("C")
        ]

        sanitized = INVALID_FILENAME_CHARS_RE.sub(" ", "".join(cleaned))
        sanitized = re.sub(r"\s+", " ", sanitized).strip(" .")
        return sanitized or "untitled"

    async def _download_file(
        self, url: str, target: Path
    ) -> Dict[str, Any]:
        """下载文件"""
        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            return {
                "status": "skipped",
                "bytes_written": 0,
                "remote_size": target.stat().st_size,
            }

        temp_target = target.with_suffix(f"{target.suffix}.part")

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                )
            },
        )

        with urllib.request.urlopen(
            request, timeout=self.timeout
        ) as response:
            remote_size = int(
                response.headers.get("Content-Length", 0)
            )
            bytes_written = 0

            with open(temp_target, "wb") as f:
                while chunk := response.read(1024 * 1024):
                    f.write(chunk)
                    bytes_written += len(chunk)

        temp_target.replace(target)

        return {
            "status": "downloaded",
            "bytes_written": bytes_written,
            "remote_size": remote_size,
        }


PluginRegistry.register("playwright", PlaywrightDownloader)
