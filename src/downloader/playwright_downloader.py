from __future__ import annotations

import asyncio
import logging
import os
import shutil
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constants import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_SKIPPED
from ..models import DownloadResult, NewsItem
from .base import Downloader
from .bilibili import (
    BILIBILI_URL_RE,
    BilibiliResolver,
    download_headers,
    extract_bilibili_refs,
)
from .paths import build_output_path, extract_news_id
from .url_resolver import (
    MEDIA_EXTENSIONS,
    MEDIA_URL_RE,
    dedupe_media_urls,
    normalize_media_url,
)

if TYPE_CHECKING:  # pragma: no cover
    from ..browser.driver import BrowserDriver
    from ..cache.download_cache import DownloadCache

logger = logging.getLogger("downloader.playwright")


VIDEO_CATEGORY_PREFIX = "videos/"


ResolveAttempt = Callable[["BrowserDriver", NewsItem], Awaitable[str | None]]


FileDownloader = Callable[[str, Path], Awaitable[dict]]


DiskUsage = Callable[[Path], int]


BilibiliResolve = Callable[[str], str | None]


RemoteExists = Callable[[Path], bool]


MIN_FREE_BYTES = 5 * 1024**3

__all__ = [
    "PlaywrightDownloader",
    "select_video_categories",
    "classify_download_outcome",
    "VIDEO_CATEGORY_PREFIX",
    "MIN_FREE_BYTES",
]


def select_video_categories(
    grouped: dict[str, list[NewsItem]],
) -> dict[str, list[NewsItem]]:
    return {
        category: items
        for category, items in grouped.items()
        if category.startswith(VIDEO_CATEGORY_PREFIX)
    }


def classify_download_outcome(
    *,
    video_url: str | None,
    download_succeeded: bool,
    validation_passed: bool,
) -> str:
    if not video_url:
        return STATUS_FAILED
    if download_succeeded and validation_passed:
        return STATUS_DOWNLOADED
    return STATUS_FAILED


def _validation_passed(bytes_written: int, remote_size: int | None) -> bool:
    if remote_size is not None and remote_size > 0:
        return bytes_written == remote_size
    return bytes_written > 0


class PlaywrightDownloader(Downloader):
    def __init__(
        self,
        output_dir: str | Path = "downloads",
        max_concurrent: int = 1,
        retry_count: int = 3,
        timeout: float = 60.0,
        proxy: str | None = None,
        resume: bool = False,
        min_free_bytes: int = MIN_FREE_BYTES,
        bilibili_cookie: str | None = None,
        *,
        resolve_attempt: ResolveAttempt | None = None,
        file_downloader: FileDownloader | None = None,
        disk_usage: DiskUsage | None = None,
        bilibili_resolver: BilibiliResolve | None = None,
        download_cache: DownloadCache | None = None,
        should_stop: Callable[[], bool] | None = None,
        post_download: Callable[[DownloadResult], DownloadResult] | None = None,
        remote_exists: RemoteExists | None = None,
        **kwargs: Any,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.max_concurrent = max(1, int(max_concurrent))
        self.retry_count = max(0, int(retry_count))
        self.timeout = timeout
        self.proxy = proxy
        self.resume = resume
        self.min_free_bytes = max(0, int(min_free_bytes))
        self.bilibili_cookie = bilibili_cookie or None
        self.download_cache = download_cache
        self._resolve_attempt = resolve_attempt or self._default_resolve_attempt
        self._file_downloader = file_downloader or self._default_download_file
        self._disk_usage = disk_usage or self._default_disk_usage
        self._bilibili_resolver = (
            bilibili_resolver
            or BilibiliResolver(self.bilibili_cookie, timeout=timeout).resolve
        )
        self._should_stop = should_stop or (lambda: False)
        self._post_download = post_download
        self._remote_exists = remote_exists

    async def download(
        self,
        grouped: dict[str, list[NewsItem]],
        driver: BrowserDriver,
    ) -> list[DownloadResult]:
        video_groups = select_video_categories(grouped)
        items = [
            item.with_category(category)
            for category, news_list in video_groups.items()
            for item in news_list
        ]

        if not items:
            logger.info("No videos to download")
            return []

        total = len(items)
        logger.info("Downloading %d video(s)", total)

        semaphore = asyncio.Semaphore(self.max_concurrent)
        done = 0

        async def process(item: NewsItem) -> DownloadResult:
            nonlocal done
            async with semaphore:
                result = await self._process_item(driver, item)
                # Streaming upload: finish uploading (and deleting) this file
                # before the semaphore frees a slot for the next download.
                if (
                    self._post_download is not None
                    and result.status == STATUS_DOWNLOADED
                ):
                    result = await asyncio.to_thread(self._post_download, result)

            done += 1
            logger.info("[%d/%d] %s: %s", done, total, result.status, item.title)
            return result

        return await asyncio.gather(*(process(item) for item in items))

    async def _process_item(
        self, driver: BrowserDriver, item: NewsItem
    ) -> DownloadResult:
        category = item.category or ""
        news_id = extract_news_id(item.url)

        target = build_output_path(self.output_dir, category, item.title, news_id)

        try:
            if self._should_stop():
                return DownloadResult(
                    title=item.title,
                    url=item.url,
                    category=category,
                    video_url="",
                    local_path=target,
                    status=STATUS_FAILED,
                    error="Shutdown requested before download",
                )

            if self.resume:
                existing = self._find_existing_target(category, item.title, news_id)
                if existing is not None:
                    logger.info("Skipping already-downloaded %s", item.title)
                    return DownloadResult(
                        title=item.title,
                        url=item.url,
                        category=category,
                        video_url="",
                        local_path=existing,
                        status=STATUS_SKIPPED,
                        bytes_written=0,
                        remote_size=existing.stat().st_size,
                    )

            remote = await asyncio.to_thread(
                self._find_remote_existing, category, item.title, news_id
            )
            if remote is not None:
                logger.info("Skipping %s: already on remote storage", item.title)
                return DownloadResult(
                    title=item.title,
                    url=item.url,
                    category=category,
                    video_url="",
                    local_path=self.output_dir / remote,
                    status=STATUS_SKIPPED,
                    bytes_written=0,
                )

            free = self._free_disk_bytes()
            if free is not None and free <= self.min_free_bytes:
                message = (
                    "Insufficient disk space: "
                    f"{free / 1024**3:.2f} GiB free, "
                    f"need > {self.min_free_bytes / 1024**3:.2f} GiB"
                )
                logger.warning("%s; skipping download of %s", message, item.title)
                return DownloadResult(
                    title=item.title,
                    url=item.url,
                    category=category,
                    video_url="",
                    local_path=target,
                    status=STATUS_FAILED,
                    error=message,
                )

            video_url = await self._resolve_video_url(driver, item)

            if not video_url:
                return DownloadResult(
                    title=item.title,
                    url=item.url,
                    category=category,
                    video_url="",
                    local_path=target,
                    status=STATUS_FAILED,
                    error="No video URL resolved",
                )

            target = build_output_path(
                self.output_dir, category, item.title, news_id, video_url=video_url
            )

            download_succeeded = True
            error: str | None = None
            bytes_written = 0
            remote_size: int | None = None
            try:
                outcome = await self._file_downloader(video_url, target)
                bytes_written = int(outcome.get("bytes_written", 0))
                remote_size = outcome.get("remote_size")
            except Exception as exc:  # noqa: BLE001
                download_succeeded = False
                error = str(exc)
                logger.warning("Download failed for %s: %s", item.url, exc)

            validation_passed = download_succeeded and _validation_passed(
                bytes_written, remote_size
            )
            status = classify_download_outcome(
                video_url=video_url,
                download_succeeded=download_succeeded,
                validation_passed=validation_passed,
            )
            if status == STATUS_FAILED and error is None:
                error = "Download validation failed"

            if status == STATUS_DOWNLOADED and self.download_cache is not None:
                self.download_cache.add(
                    article_url=item.url,
                    video_url=video_url,
                    file_path=str(target),
                    title=item.title,
                    category=category,
                    file_size=bytes_written,
                )

            return DownloadResult(
                title=item.title,
                url=item.url,
                category=category,
                video_url=video_url,
                local_path=target,
                status=status,
                bytes_written=bytes_written if status == STATUS_DOWNLOADED else 0,
                remote_size=remote_size,
                error=error if status == STATUS_FAILED else None,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected error processing %s", item.url)
            return DownloadResult(
                title=item.title,
                url=item.url,
                category=category,
                video_url="",
                local_path=target,
                status=STATUS_FAILED,
                error=str(exc),
            )

    def _free_disk_bytes(self) -> int | None:
        try:
            return int(self._disk_usage(self.output_dir))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Disk space check failed for %s: %s", self.output_dir, exc)
            return None

    @staticmethod
    def _default_disk_usage(directory: Path) -> int:
        probe = directory.resolve()
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        return shutil.disk_usage(probe).free

    def _find_existing_target(
        self, category: str, title: str, news_id: str
    ) -> Path | None:
        for extension in MEDIA_EXTENSIONS:
            candidate = build_output_path(
                self.output_dir,
                category,
                title,
                news_id,
                video_url=f"x{extension}",
            )
            if candidate.exists():
                return candidate
        return None

    def _find_remote_existing(
        self, category: str, title: str, news_id: str
    ) -> Path | None:
        """Probe remote storage for any extension candidate of this item.

        A probe failure never blocks the download: it is logged and treated
        as "not found" so the pipeline falls through to a normal download.
        """
        if self._remote_exists is None:
            return None
        for extension in MEDIA_EXTENSIONS:
            candidate = build_output_path(
                self.output_dir,
                category,
                title,
                news_id,
                video_url=f"x{extension}",
            )
            relative = candidate.relative_to(self.output_dir)
            try:
                if self._remote_exists(relative):
                    return relative
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Remote existence check failed for %s: %s", relative, exc
                )
                return None
        return None

    async def _resolve_video_url(
        self, driver: BrowserDriver, item: NewsItem
    ) -> str | None:
        for attempt in range(self.retry_count):
            if self._should_stop():
                return None
            try:
                url = await self._resolve_attempt(driver, item)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Resolution attempt %d/%d for %s failed: %s",
                    attempt + 1,
                    self.retry_count,
                    item.url,
                    exc,
                )
                url = None
            if url:
                return url
        if self.retry_count:
            logger.warning("No video URL found for %s", item.url)
        return None

    async def _default_resolve_attempt(
        self, driver: BrowserDriver, item: NewsItem
    ) -> str | None:  # pragma: no cover
        context = getattr(driver, "_context", None)
        if context is None:
            raise RuntimeError("Browser driver has no active context")

        page = await context.new_page()
        captured: list[str] = []

        def on_response(response: Any) -> None:
            url = normalize_media_url(response.url)
            if url:
                captured.append(url)

        page.on("response", on_response)
        try:
            await page.goto(item.url, wait_until="domcontentloaded", timeout=60000)
            try:
                await page.wait_for_selector("video", timeout=8000)
            except Exception:  # noqa: BLE001
                await page.wait_for_timeout(2000)

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
                for (const frame of document.querySelectorAll('iframe[src]')) {
                    candidates.push(frame.src || frame.getAttribute('src') || '');
                }
                return candidates;
                }"""
            )
            html = await page.content()
            html_urls = MEDIA_URL_RE.findall(html)

            media_urls = dedupe_media_urls([*dom_urls, *html_urls, *captured])
            if media_urls:
                return media_urls[0]

            refs = extract_bilibili_refs([*dom_urls, *BILIBILI_URL_RE.findall(html)])
            for ref in refs:
                resolved = await asyncio.to_thread(self._bilibili_resolver, ref)
                if resolved:
                    return resolved
            return None
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001
                pass

    async def _default_download_file(
        self, video_url: str, target: Path
    ) -> dict:  # pragma: no cover
        return await asyncio.to_thread(self._download_file_blocking, video_url, target)

    def _download_file_blocking(self, video_url: str, target: Path) -> dict:
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(f"{target.suffix}.part")

        request = urllib.request.Request(
            video_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                ),
                **download_headers(video_url, self.bilibili_cookie),
            },
        )
        bytes_written = 0
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                remote_size = int(response.headers.get("Content-Length", 0)) or None
                with open(part, "wb") as handle:
                    while chunk := response.read(1024 * 1024):
                        handle.write(chunk)
                        bytes_written += len(chunk)
        except BaseException:
            part.unlink(missing_ok=True)
            raise

        os.replace(part, target)
        return {"bytes_written": bytes_written, "remote_size": remote_size}
