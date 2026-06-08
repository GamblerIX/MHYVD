"""The Playwright-based :class:`Downloader` implementation.

:class:`PlaywrightDownloader` is the concrete Download_Stage component
(Requirement 7). Given the classifier's grouped ``{category: [NewsItem]}``
mapping and a ready :class:`~src.browser.driver.BrowserDriver`, it:

* processes **only** the categories whose path begins with ``videos/``
  (Requirement 7.1, Property 13) -- see :func:`select_video_categories`;
* resolves each item's video URL from DOM ``<video>``/``<source>``/``<a>``
  elements, a regex scan of the page HTML, and captured network responses,
  retrying resolution up to ``retry_count`` times (Requirement 7.8,
  Property 18);
* bounds the number of simultaneous downloads with an :class:`asyncio.Semaphore`
  sized to the configured concurrency, supporting ``concurrency == 1``
  (Requirement 7.7, Property 17);
* writes each video to a ``.part`` temporary file and atomically
  :func:`os.replace`\\ s it onto the target only after the write completes
  (Requirement 7.4);
* under Resume_Mode skips any item whose target file already exists, producing
  a ``skipped`` result (Requirement 8.2, Property 19);
* maps every outcome to ``downloaded`` / ``skipped`` / ``failed`` through the
  pure :func:`classify_download_outcome` helper (Requirements 7.5, 7.6,
  Property 16); and
* isolates per-item failures so every processed item yields exactly one
  :class:`~src.models.DownloadResult` and one failure never drops or blocks the
  others (Requirement 12.2, Property 20).

The pieces that touch a real browser or the network are isolated behind small
injectable seams (``resolve_attempt`` and ``download_file``) so the bulk of the
logic is exercised by tests with lightweight fakes and temp files -- no real
browser is required.

Resolution and URL-normalization logic is ported from the original plugin-based
downloader.
"""

from __future__ import annotations

import asyncio
import logging
import os
import urllib.request
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..constants import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_SKIPPED
from ..models import DownloadResult, NewsItem
from .base import Downloader
from .paths import build_output_path, extract_news_id
from .url_resolver import (
    MEDIA_EXTENSIONS,
    MEDIA_URL_RE,
    dedupe_media_urls,
    normalize_media_url,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..browser.driver import BrowserDriver
    from ..cache.download_cache import DownloadCache

logger = logging.getLogger("downloader.playwright")

#: Category paths handled by the Download_Stage all live beneath this prefix.
VIDEO_CATEGORY_PREFIX = "videos/"

#: A single resolution attempt: given the driver and an item, return a resolved
#: media URL or ``None`` when this attempt found nothing.
ResolveAttempt = Callable[["BrowserDriver", NewsItem], Awaitable[str | None]]

#: A file downloader: fetch ``video_url`` to ``target`` (writing via a ``.part``
#: temp file) and return an outcome mapping with ``bytes_written`` /
#: ``remote_size`` keys.
FileDownloader = Callable[[str, Path], Awaitable[dict]]

__all__ = [
    "PlaywrightDownloader",
    "select_video_categories",
    "classify_download_outcome",
    "VIDEO_CATEGORY_PREFIX",
]


def select_video_categories(
    grouped: dict[str, list[NewsItem]],
) -> dict[str, list[NewsItem]]:
    """Return only the categories the Downloader processes.

    A category is processed if and only if its path begins with ``videos/``
    (Requirement 7.1, Property 13). The returned mapping preserves the input's
    insertion order and shares the original item lists (no copying).
    """
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
    """Map a download outcome to a status string (Property 16).

    * When no video URL was resolved, the status is ``failed``
      (Requirement 7.5).
    * Otherwise the status is ``downloaded`` **iff** the download succeeded and
      all validation checks passed, and ``failed`` in every other case
      (Requirement 7.6) -- so a byte transfer that succeeds but fails
      validation is still ``failed``.
    """
    if not video_url:
        return STATUS_FAILED
    if download_succeeded and validation_passed:
        return STATUS_DOWNLOADED
    return STATUS_FAILED


def _validation_passed(bytes_written: int, remote_size: int | None) -> bool:
    """Return whether a completed transfer passes validation.

    When the server reported a positive content length, the written byte count
    must match it; otherwise any non-empty transfer is accepted.
    """
    if remote_size is not None and remote_size > 0:
        return bytes_written == remote_size
    return bytes_written > 0


class PlaywrightDownloader(Downloader):
    """Resolve and download videos for the ``videos/*`` categories."""

    def __init__(
        self,
        output_dir: str | Path = "downloads",
        max_concurrent: int = 1,
        retry_count: int = 3,
        timeout: float = 60.0,
        proxy: str | None = None,
        resume: bool = False,
        *,
        resolve_attempt: ResolveAttempt | None = None,
        file_downloader: FileDownloader | None = None,
        download_cache: DownloadCache | None = None,
        should_stop: Callable[[], bool] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the downloader.

        Args:
            output_dir: Root directory for downloaded files.
            max_concurrent: Maximum simultaneous downloads (``>= 1``).
            retry_count: Number of resolution attempts before giving up
                (``>= 0``; ``0`` means do not attempt resolution at all).
            timeout: Per-request network timeout in seconds for the default
                downloader.
            proxy: Optional proxy server address used by the default downloader.
            resume: When true, an existing target file yields a ``skipped``
                result instead of being re-downloaded.
            resolve_attempt: Override the single-attempt resolver (testing).
            file_downloader: Override the file downloader (testing).
            download_cache: Optional Download_Cache; when provided, a successful
                download is recorded to it before the result is returned
                (Requirement 8.4). ``None`` disables download-record caching.
            should_stop: Optional predicate polled before starting each item and
                before each resolution attempt. When it returns ``True`` the
                downloader stops starting *new* work and short-circuits the
                retry loop, so a user interrupt aborts promptly instead of
                draining the whole queue (Requirement 12.4). Defaults to a
                predicate that never stops.
        """
        self.output_dir = Path(output_dir)
        self.max_concurrent = max(1, int(max_concurrent))
        self.retry_count = max(0, int(retry_count))
        self.timeout = timeout
        self.proxy = proxy
        self.resume = resume
        self.download_cache = download_cache
        self._resolve_attempt = resolve_attempt or self._default_resolve_attempt
        self._file_downloader = file_downloader or self._default_download_file
        self._should_stop = should_stop or (lambda: False)

    # ------------------------------------------------------------------ #
    # Public contract.
    # ------------------------------------------------------------------ #
    async def download(
        self,
        grouped: dict[str, list[NewsItem]],
        driver: BrowserDriver,
    ) -> list[DownloadResult]:
        """Resolve and download videos for the ``videos/*`` categories.

        Concurrency is bounded by an :class:`asyncio.Semaphore` of size
        :attr:`max_concurrent` (Requirement 7.7). Every processed item yields
        exactly one :class:`DownloadResult`; per-item failures are isolated so
        one failure never drops or blocks the others (Requirement 12.2).
        """
        video_groups = select_video_categories(grouped)
        items = [
            item.with_category(category)
            for category, news_list in video_groups.items()
            for item in news_list
        ]

        if not items:
            logger.info("No videos to download")
            return []

        logger.info("Downloading %d video(s)", len(items))

        semaphore = asyncio.Semaphore(self.max_concurrent)

        async def process(item: NewsItem) -> DownloadResult:
            async with semaphore:
                return await self._process_item(driver, item)

        return await asyncio.gather(*(process(item) for item in items))

    # ------------------------------------------------------------------ #
    # Per-item processing.
    # ------------------------------------------------------------------ #
    async def _process_item(
        self, driver: BrowserDriver, item: NewsItem
    ) -> DownloadResult:
        """Process a single item, always returning a :class:`DownloadResult`.

        Any unexpected error is caught and turned into a ``failed`` result so
        that one item's failure never propagates out of :meth:`download`
        (Requirement 12.2, Property 20).
        """
        category = item.category or ""
        news_id = extract_news_id(item.url)
        # Provisional target with the default extension; the final extension is
        # derived from the resolved video URL (which may be .mov etc.) below.
        target = build_output_path(self.output_dir, category, item.title, news_id)

        try:
            # Shutdown requested before this item started any work: don't begin
            # a new (expensive) page load. Report it as failed so the item is
            # still accounted for (Property 20) rather than silently dropped.
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

            # Resume: an existing target file is skipped (Requirement 8.2).
            # Resolution determines the real extension, but in resume mode we
            # must decide to skip *without* resolving (resolution is the
            # expensive page load). So we look for an already-downloaded file
            # under any recognised media extension.
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

            video_url = await self._resolve_video_url(driver, item)

            # No resolved URL -> failed with an error (Requirement 7.5).
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

            # Now that the URL is known, fix the target extension to match it
            # (e.g. .mov), so the saved file is not mislabelled .mp4.
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
            except Exception as exc:  # noqa: BLE001 - isolate per-item failure
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

            # Persist a Download_Cache record for a successful download only
            # (Requirement 8.4). Skipped/failed items are never recorded.
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
        except Exception as exc:  # noqa: BLE001 - never let one item escape
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

    def _find_existing_target(
        self, category: str, title: str, news_id: str
    ) -> Path | None:
        """Return an already-downloaded target file for resume, or ``None``.

        Because the extension is only known after resolution (and resume must
        skip *without* resolving), this checks the target stem under every
        recognised media extension and returns the first that exists.
        """
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

    async def _resolve_video_url(
        self, driver: BrowserDriver, item: NewsItem
    ) -> str | None:
        """Resolve the video URL, retrying up to :attr:`retry_count` times.

        A resolution that always fails is attempted exactly :attr:`retry_count`
        times before ``None`` is returned (Requirement 7.8, Property 18). With
        ``retry_count == 0`` no attempt is made and ``None`` is returned
        immediately.
        """
        for attempt in range(self.retry_count):
            # Stop retrying once a shutdown has been requested so an interrupt
            # is not delayed by the remaining attempts (Requirement 12.4).
            if self._should_stop():
                return None
            try:
                url = await self._resolve_attempt(driver, item)
            except Exception as exc:  # noqa: BLE001 - a failed attempt is just None
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

    # ------------------------------------------------------------------ #
    # Default browser/network seams (not exercised by unit tests).
    # ------------------------------------------------------------------ #
    async def _default_resolve_attempt(
        self, driver: BrowserDriver, item: NewsItem
    ) -> str | None:  # pragma: no cover - requires a real browser
        """Open the article page and resolve a media URL from it.

        Gathers candidates from captured network responses, DOM
        ``<video>``/``<source>``/``<a>`` elements, and a regex scan of the page
        HTML (Requirement 7.2), then returns the first valid deduplicated media
        URL.
        """
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
            except Exception:  # noqa: BLE001 - video element is best-effort
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
                return candidates;
                }"""
            )
            html = await page.content()
            html_urls = MEDIA_URL_RE.findall(html)

            media_urls = dedupe_media_urls([*dom_urls, *html_urls, *captured])
            return media_urls[0] if media_urls else None
        finally:
            try:
                await page.close()
            except Exception:  # noqa: BLE001 - cleanup must not raise
                pass

    async def _default_download_file(
        self, video_url: str, target: Path
    ) -> dict:  # pragma: no cover - performs real network/disk I/O
        """Download ``video_url`` to ``target`` via a ``.part`` temp file.

        The bytes are streamed to ``target`` + ``.part`` and only then atomically
        moved onto ``target`` with :func:`os.replace` (Requirement 7.4). The
        blocking transfer runs in a worker thread so the event loop stays free.
        """
        return await asyncio.to_thread(self._download_file_blocking, video_url, target)

    def _download_file_blocking(
        self, video_url: str, target: Path
    ) -> dict:  # pragma: no cover - performs real network/disk I/O
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_suffix(f"{target.suffix}.part")

        request = urllib.request.Request(
            video_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                )
            },
        )
        bytes_written = 0
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            remote_size = int(response.headers.get("Content-Length", 0)) or None
            with open(part, "wb") as handle:
                while chunk := response.read(1024 * 1024):
                    handle.write(chunk)
                    bytes_written += len(chunk)

        os.replace(part, target)
        return {"bytes_written": bytes_written, "remote_size": remote_size}
