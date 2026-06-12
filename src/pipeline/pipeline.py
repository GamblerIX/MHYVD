from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ..browser.driver import (
    DEFAULT_MODE,
    DEFAULT_TIMEOUT,
    BrowserDriver,
    BrowserLaunchError,
)
from ..models import NewsItem, PipelineResult
from ..runtime import Deadline
from .fallback import AttemptFailure, aggregate_failure_reasons, decide_fetch_modes

if TYPE_CHECKING:  # pragma: no cover
    from ..classifier.base import Classifier
    from ..downloader.base import Downloader
    from ..sources.base import SourceAdapter

logger = logging.getLogger("pipeline")

__all__ = ["Pipeline", "should_run_downstream"]


ZERO_ITEMS_REASON = "no News_Items retrieved (reported count 0)"


DriverFactory = Callable[[str], BrowserDriver]


CrashIdentifier = Callable[[BrowserDriver, BaseException], "tuple[bool, str | None]"]


ListExporter = Callable[["dict[str, list[NewsItem]]", Path], None]


def should_run_downstream(reported_count: int) -> bool:
    return reported_count > 0


def _default_list_exporter(grouped: dict[str, list[NewsItem]], path: Path) -> None:
    from ..cache.list_export import export_video_list

    export_video_list(grouped, path)


def _default_crash_identifier(
    driver: BrowserDriver, exc: BaseException
) -> tuple[bool, str | None]:
    text = str(exc)
    if "crash" in text.lower():
        return True, f"page crashed during fetch: {text}"
    return False, None


@dataclass
class _FetchAttempt:
    failed: bool
    reason: str = ""
    items: list[NewsItem] | None = None
    driver: BrowserDriver | None = None


class Pipeline:
    def __init__(
        self,
        adapter: SourceAdapter,
        classifier: Classifier,
        downloader: Downloader,
        *,
        mode: str = DEFAULT_MODE,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        fallback_enabled: bool = True,
        resume: bool = False,
        download_enabled: bool = True,
        list_export_path: str | Path | None = None,
        fetch_budget: float | None = None,
        driver_factory: DriverFactory | None = None,
        crash_identifier: CrashIdentifier | None = None,
        list_exporter: ListExporter | None = None,
    ) -> None:
        self.adapter = adapter
        self.classifier = classifier
        self.downloader = downloader
        self.mode = mode
        self.proxy = proxy
        self.timeout = timeout
        self.fallback_enabled = fallback_enabled
        self.resume = resume
        self.download_enabled = download_enabled
        self.list_export_path = Path(list_export_path) if list_export_path else None
        self.fetch_budget = fetch_budget
        self._driver_factory = driver_factory or self._default_driver_factory
        self._crash_identifier = crash_identifier or _default_crash_identifier
        self._list_exporter = list_exporter or _default_list_exporter

    async def run(self) -> PipelineResult:
        modes = decide_fetch_modes(self.mode, self.fallback_enabled)
        attempts: list[AttemptFailure] = []
        winning: _FetchAttempt | None = None
        winning_count = 0

        deadline = Deadline(self.fetch_budget)

        for index, mode in enumerate(modes):
            has_next = index < len(modes) - 1
            try:
                attempt = await asyncio.wait_for(
                    self._attempt_fetch(mode), timeout=deadline.remaining()
                )
            except TimeoutError:
                return self._fetch_timeout_result()

            if attempt.failed:
                attempts.append(AttemptFailure(mode=mode, reason=attempt.reason))
                self._log_failed_attempt(mode, attempt.reason, has_next)
                continue

            reported_count = self._count_news(attempt.items or [])
            if should_run_downstream(reported_count):
                winning = attempt
                winning_count = reported_count
                break

            await self._safe_close(attempt.driver)
            attempts.append(AttemptFailure(mode=mode, reason=ZERO_ITEMS_REASON))
            self._log_failed_attempt(mode, ZERO_ITEMS_REASON, has_next)

        if winning is None:
            report = aggregate_failure_reasons(attempts)
            logger.error("Fetch failed in every mode: %s", report)
            return PipelineResult(news_count=0, completed=True, error=report)

        try:
            return await self._classify_and_download(winning, winning_count)
        finally:
            await self._safe_close(winning.driver)

    def _fetch_timeout_result(self) -> PipelineResult:
        budget = self.fetch_budget or 0
        logger.error("Fetch stage exceeded its %ss time budget", budget)
        return PipelineResult(
            news_count=0,
            completed=False,
            timed_out=True,
            error=f"fetch stage timed out after {budget:g}s",
        )

    async def _attempt_fetch(self, mode: str) -> _FetchAttempt:
        driver = self._driver_factory(mode)

        try:
            await driver.launch()
        except BrowserLaunchError as exc:
            await self._safe_close(driver)
            return _FetchAttempt(
                failed=True, reason=f"browser launch error in {mode} mode: {exc}"
            )
        except asyncio.CancelledError:
            await self._safe_close(driver)
            raise
        except Exception as exc:  # noqa: BLE001
            await self._safe_close(driver)
            return _FetchAttempt(
                failed=True, reason=f"browser launch error in {mode} mode: {exc}"
            )

        try:
            items = await self.adapter.fetch_news(driver)
        except asyncio.CancelledError:
            await self._safe_close(driver)
            raise
        except Exception as exc:  # noqa: BLE001
            reason = self._fetch_failure_reason(mode, driver, exc)
            await self._safe_close(driver)
            return _FetchAttempt(failed=True, reason=reason)

        return _FetchAttempt(failed=False, items=list(items), driver=driver)

    def _fetch_failure_reason(
        self, mode: str, driver: BrowserDriver, exc: BaseException
    ) -> str:
        is_crash, detail = self._guarded_identify_crash(driver, exc)
        if is_crash and detail:
            return f"fetch failed in {mode} mode: {detail}"
        if is_crash:
            return f"fetch failed in {mode} mode: page crash (details unavailable)"
        return f"fetch failed in {mode} mode: {exc}"

    def _guarded_identify_crash(
        self, driver: BrowserDriver, exc: BaseException
    ) -> tuple[bool, str | None]:
        try:
            return self._crash_identifier(driver, exc)
        except Exception as id_exc:  # noqa: BLE001
            logger.warning(
                "Crash identification step failed (%s); reporting fetch failure "
                "without crash details",
                id_exc,
            )
            return False, None

    async def _classify_and_download(
        self, attempt: _FetchAttempt, reported_count: int
    ) -> PipelineResult:
        items = attempt.items or []

        try:
            grouped = self.classifier.classify(items)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Classification failed")
            return PipelineResult(
                news_count=reported_count,
                completed=True,
                error=f"Classification failed: {exc}",
            )

        categories = {category: len(group) for category, group in grouped.items()}
        logger.info(
            "Classified %d item(s) into %d categor(y/ies)",
            reported_count,
            len(categories),
        )

        self._export_list(grouped)

        if not self.download_enabled:
            logger.info("Download stage disabled (list-only run); skipping")
            return PipelineResult(
                news_count=reported_count,
                classified_categories=categories,
                download_results=(),
                completed=True,
                error=None,
            )

        assert attempt.driver is not None
        results = await self.downloader.download(grouped, attempt.driver)

        return PipelineResult(
            news_count=reported_count,
            classified_categories=categories,
            download_results=tuple(results),
            completed=True,
            error=None,
        )

    def _export_list(self, grouped: dict[str, list[NewsItem]]) -> None:
        if self.list_export_path is None:
            return
        try:
            self._list_exporter(grouped, self.list_export_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to export video list to %s: %s", self.list_export_path, exc
            )

    def _count_news(self, items: list[NewsItem]) -> int:
        return len(items)

    def _default_driver_factory(self, mode: str) -> BrowserDriver:
        return BrowserDriver(mode=mode, proxy=self.proxy, timeout=self.timeout)

    async def _safe_close(self, driver: BrowserDriver | None) -> None:
        if driver is None:
            return
        try:
            await driver.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Error closing browser driver: %s", exc)

    def _log_failed_attempt(self, mode: str, reason: str, has_next: bool) -> None:
        if has_next:
            logger.warning(
                "Fetch attempt in %s mode failed (%s); falling back to headed mode",
                mode,
                reason,
            )
        else:
            logger.error("Fetch attempt in %s mode failed: %s", mode, reason)
