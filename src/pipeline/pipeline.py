"""The :class:`Pipeline` orchestrator.

This is the Orchestration Layer's I/O-driving component (Requirements 4, 5,
12.1). It sequences the three stages — Fetch -> Classify -> Download — and
applies the headless->headed fallback policy, then folds everything into a
single :class:`~src.models.PipelineResult`.

What the pipeline does, step by step
------------------------------------
1. **Decide modes.** :func:`~src.pipeline.fallback.decide_fetch_modes` turns
   the selected browser mode + fallback flag into an ordered list of modes to
   attempt (Requirement 4.1/4.2/4.3/4.6).
2. **Fetch per attempt.** For each mode it builds a fresh
   :class:`~src.browser.driver.BrowserDriver`, launches it, and runs the
   Fetch_Stage (``adapter.fetch_news``). A *failed* attempt is one that
   raises a browser/launch error **or** reports zero News_Items
   (Requirement 4.2). On a failed attempt with a remaining mode, the pipeline
   logs the fallback and its reason (Requirement 4.4) and tries the next mode.
   The driver of every failed attempt is always closed (``aclose``).
3. **All attempts failed.** If no attempt yields a positive reported count, the
   pipeline reports a failure whose message carries every attempt's reason via
   :func:`~src.pipeline.fallback.aggregate_failure_reasons` (Requirement 4.5).
4. **Gate on the reported count.** The Classify_Stage and Download_Stage run if
   and only if the *reported* fetch count is greater than zero
   (:func:`should_run_downstream`); the pipeline acts on the reported count
   even if the actual list differs (Requirement 5.4, Property 10). The reported
   count is recorded in ``PipelineResult.news_count`` (Requirement 5.3,
   Property 9).
5. **Classify + Download.** The winning attempt's driver is kept open and
   passed to the Download_Stage; per-category counts and ``DownloadResult``\\ s
   are aggregated into the ``PipelineResult`` (Requirements 6.5, 8.7). The
   driver is closed once download finishes.
6. **Page crash during fetch** (Requirement 12.1). When the Fetch_Stage raises,
   a *guarded* crash-identification step runs: if it identifies a crash the
   failure reason names it; if the identification step itself fails it is
   swallowed and the pipeline reports a fetch failure *without* crash details
   rather than raising.

``completed`` semantics
-----------------------
``PipelineResult.completed`` is ``True`` whenever the pipeline runs to a
definitive, self-reported conclusion — success, "no News_Items retrieved", an
all-attempts-failed report, or a classification failure. ``run`` always reaches
such a conclusion, so it always returns ``completed=True``. ``completed`` is
left ``False`` only for abnormal external termination (overall timeout or user
interrupt) handled outside this class in :mod:`src.runtime`. The CLI prints the
``as_markdown()`` summary exactly when ``completed`` is ``True`` (Req 10.13).

Requirements: 4.2, 4.4, 4.5, 5.1, 5.3, 5.4, 6.4, 6.5, 8.7, 12.1.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..browser.driver import (
    DEFAULT_MODE,
    DEFAULT_TIMEOUT,
    BrowserDriver,
    BrowserLaunchError,
)
from ..models import NewsItem, PipelineResult
from .fallback import AttemptFailure, aggregate_failure_reasons, decide_fetch_modes

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..classifier.base import Classifier
    from ..downloader.base import Downloader
    from ..sources.base import SourceAdapter

logger = logging.getLogger("pipeline")

__all__ = ["Pipeline", "should_run_downstream"]

#: Reason recorded for an attempt that launched and fetched without error but
#: reported zero News_Items. A zero-count attempt is treated as a failure so it
#: can trigger a Headed_Mode fallback (Requirement 4.2) and so the combined
#: report explains why every attempt failed (Requirement 4.5).
ZERO_ITEMS_REASON = "no News_Items retrieved (reported count 0)"

#: A factory that builds a :class:`BrowserDriver` for a given mode. Injectable
#: so tests can supply fake drivers without launching Chromium.
DriverFactory = Callable[[str], BrowserDriver]

#: A guarded crash-identification step: given the driver and the exception
#: raised by the Fetch_Stage, return ``(is_crash, detail)``. ``detail`` is a
#: human-readable description when a crash is identified, else ``None``. May be
#: injected for testing; the pipeline wraps every call so that a *raising*
#: identifier is downgraded to "no crash details" (Requirement 12.1).
CrashIdentifier = Callable[[BrowserDriver, BaseException], "tuple[bool, str | None]"]


def should_run_downstream(reported_count: int) -> bool:
    """Return whether the Classify/Download stages should run (Property 10).

    The gate is a pure function of the **reported** fetch count: the downstream
    stages run if and only if the reported count is greater than zero. The
    pipeline always feeds this the reported count (not ``len`` of the actual
    list), so it "acts on the reported count even when the actual list differs"
    (Requirement 5.4).
    """
    return reported_count > 0


def _default_crash_identifier(
    driver: BrowserDriver, exc: BaseException
) -> tuple[bool, str | None]:
    """Best-effort crash identification from a Fetch_Stage exception.

    Treats an exception whose text mentions a crash (Playwright surfaces page
    crashes with a "crash"/"Target crashed" message) as a page crash and
    returns a short description. This function may raise — the pipeline calls it
    through a guard that downgrades any failure here to "no crash details"
    (Requirement 12.1).
    """
    text = str(exc)
    if "crash" in text.lower():
        return True, f"page crashed during fetch: {text}"
    return False, None


@dataclass
class _FetchAttempt:
    """The outcome of one fetch attempt in a single browser mode.

    A *failed* attempt (``failed`` is ``True``) carries a ``reason`` and has
    already had its driver closed. A *successful* attempt carries the fetched
    ``items`` and keeps its ``driver`` open for the Download_Stage.
    """

    failed: bool
    reason: str = ""
    items: list[NewsItem] | None = None
    driver: BrowserDriver | None = None


class Pipeline:
    """Drive Fetch -> Classify -> Download with headless->headed fallback.

    The collaborators (source adapter, classifier, downloader) are injected so
    the pipeline stays agnostic of any concrete game/region, rule set, or
    download mechanism. The browser-driver factory is injectable too, which is
    what lets the tests exercise the whole orchestration — including the
    fallback and crash paths — without launching a real browser.
    """

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
        driver_factory: DriverFactory | None = None,
        crash_identifier: CrashIdentifier | None = None,
    ) -> None:
        """Wire the pipeline's collaborators and browser configuration.

        Args:
            adapter: The Source_Adapter driving the Fetch_Stage.
            classifier: The Classifier driving the Classify_Stage.
            downloader: The Downloader driving the Download_Stage.
            mode: Selected browser mode (:data:`~src.browser.driver.MODE_HEADLESS`
                by default); combined with ``fallback_enabled`` to decide the
                ordered modes to attempt.
            proxy: Optional proxy server address passed to each driver.
            timeout: Per-close timeout (seconds) passed to each driver.
            fallback_enabled: Whether a Headed_Mode fallback may be attempted
                after a Headless_Mode failure (Requirement 4.2/4.3).
            resume: Resume_Mode flag (informational at the pipeline level; the
                adapter and downloader own the caching behaviour).
            driver_factory: Override the per-mode driver builder (testing).
            crash_identifier: Override the crash-identification step (testing).
        """
        self.adapter = adapter
        self.classifier = classifier
        self.downloader = downloader
        self.mode = mode
        self.proxy = proxy
        self.timeout = timeout
        self.fallback_enabled = fallback_enabled
        self.resume = resume
        self._driver_factory = driver_factory or self._default_driver_factory
        self._crash_identifier = crash_identifier or _default_crash_identifier

    # ------------------------------------------------------------------ #
    # Public contract.
    # ------------------------------------------------------------------ #
    async def run(self) -> PipelineResult:
        """Execute the pipeline and return an aggregated :class:`PipelineResult`.

        See the module docstring for the full sequence. Always returns a result
        with ``completed=True``; failures are reported through the result's
        ``error`` field rather than by raising.
        """
        modes = decide_fetch_modes(self.mode, self.fallback_enabled)
        attempts: list[AttemptFailure] = []
        winning: _FetchAttempt | None = None
        winning_count = 0

        for index, mode in enumerate(modes):
            has_next = index < len(modes) - 1
            attempt = await self._attempt_fetch(mode)

            if attempt.failed:
                attempts.append(AttemptFailure(mode=mode, reason=attempt.reason))
                self._log_failed_attempt(mode, attempt.reason, has_next)
                continue

            reported_count = self._count_news(attempt.items or [])
            if should_run_downstream(reported_count):
                winning = attempt
                winning_count = reported_count
                break

            # Launched and fetched cleanly but reported zero items: treat as a
            # failed attempt so it can fall back / be reported (Req 4.2/4.5).
            await self._safe_close(attempt.driver)
            attempts.append(AttemptFailure(mode=mode, reason=ZERO_ITEMS_REASON))
            self._log_failed_attempt(mode, ZERO_ITEMS_REASON, has_next)

        if winning is None:
            # Every attempted mode failed: report carrying each reason (Req 4.5).
            report = aggregate_failure_reasons(attempts)
            logger.error("Fetch failed in every mode: %s", report)
            return PipelineResult(news_count=0, completed=True, error=report)

        try:
            return await self._classify_and_download(winning, winning_count)
        finally:
            # The winning attempt kept its driver open for downloading; close it.
            await self._safe_close(winning.driver)

    # ------------------------------------------------------------------ #
    # Fetch_Stage (per mode).
    # ------------------------------------------------------------------ #
    async def _attempt_fetch(self, mode: str) -> _FetchAttempt:
        """Run one fetch attempt in ``mode``, returning a :class:`_FetchAttempt`.

        Builds and launches a driver, runs ``adapter.fetch_news``, and isolates
        every failure into a reason string. A launch failure, a browser error,
        or a page crash during fetch all produce a failed attempt with the
        driver closed; a clean fetch produces a successful attempt that *keeps*
        the driver open for the Download_Stage.
        """
        driver = self._driver_factory(mode)

        # --- Launch (Requirement 3): a launch failure is a browser error. ---
        try:
            await driver.launch()
        except BrowserLaunchError as exc:
            await self._safe_close(driver)
            return _FetchAttempt(
                failed=True, reason=f"browser launch error in {mode} mode: {exc}"
            )
        except Exception as exc:  # noqa: BLE001 - any launch failure is a failure
            await self._safe_close(driver)
            return _FetchAttempt(
                failed=True, reason=f"browser launch error in {mode} mode: {exc}"
            )

        # --- Fetch_Stage (Requirement 5.1). ---
        try:
            items = await self.adapter.fetch_news(driver)
        except Exception as exc:  # noqa: BLE001 - normalise into a failed attempt
            reason = self._fetch_failure_reason(mode, driver, exc)
            await self._safe_close(driver)
            return _FetchAttempt(failed=True, reason=reason)

        # Successful fetch: keep the driver open for downloading.
        return _FetchAttempt(failed=False, items=list(items), driver=driver)

    def _fetch_failure_reason(
        self, mode: str, driver: BrowserDriver, exc: BaseException
    ) -> str:
        """Build the failure reason for a Fetch_Stage exception (Req 12.1).

        Runs the guarded crash-identification step. When a crash is identified
        the reason names it; when the identification step itself fails the
        reason is a plain fetch failure *without* crash details (the guard never
        lets that failure escape).
        """
        is_crash, detail = self._guarded_identify_crash(driver, exc)
        if is_crash and detail:
            return f"fetch failed in {mode} mode: {detail}"
        if is_crash:
            # Identified as a crash but no usable detail.
            return f"fetch failed in {mode} mode: page crash (details unavailable)"
        return f"fetch failed in {mode} mode: {exc}"

    def _guarded_identify_crash(
        self, driver: BrowserDriver, exc: BaseException
    ) -> tuple[bool, str | None]:
        """Call the crash identifier, never raising (Requirement 12.1).

        If the crash-identification mechanism itself raises, the failure is
        swallowed and ``(False, None)`` is returned so the pipeline reports a
        fetch failure without crash details rather than propagating the error.
        """
        try:
            return self._crash_identifier(driver, exc)
        except Exception as id_exc:  # noqa: BLE001 - guard the crash-id step
            logger.warning(
                "Crash identification step failed (%s); reporting fetch failure "
                "without crash details",
                id_exc,
            )
            return False, None

    # ------------------------------------------------------------------ #
    # Classify_Stage + Download_Stage.
    # ------------------------------------------------------------------ #
    async def _classify_and_download(
        self, attempt: _FetchAttempt, reported_count: int
    ) -> PipelineResult:
        """Run Classify + Download for a winning fetch attempt.

        Records the reported news count (Req 5.3), the per-category counts
        (Req 6.5), and the aggregated ``DownloadResult``\\ s (Req 8.7). A
        Classify_Stage failure is reported as a definitive failure rather than
        raised (Requirement 6.4).
        """
        items = attempt.items or []

        # Classify_Stage (Requirement 6). A grouping failure is reported.
        try:
            grouped = self.classifier.classify(items)
        except Exception as exc:  # noqa: BLE001 - report a classification failure
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

        # Download_Stage (Requirement 7); the downloader handles videos/* only.
        assert attempt.driver is not None  # winning attempts keep their driver
        results = await self.downloader.download(grouped, attempt.driver)

        return PipelineResult(
            news_count=reported_count,
            classified_categories=categories,
            download_results=tuple(results),
            completed=True,
            error=None,
        )

    # ------------------------------------------------------------------ #
    # Helpers.
    # ------------------------------------------------------------------ #
    def _count_news(self, items: list[NewsItem]) -> int:
        """Return the *reported* fetch count for ``items`` (Property 9).

        Defaults to the length of the fetched list, so
        ``PipelineResult.news_count == len(fetched_list)`` (Requirement 5.3).
        Isolated as a seam so the gating logic depends on this single reported
        count, which is what makes "act on the reported count" testable
        (Property 10).
        """
        return len(items)

    def _default_driver_factory(self, mode: str) -> BrowserDriver:
        """Build a :class:`BrowserDriver` for ``mode`` from the browser config."""
        return BrowserDriver(mode=mode, proxy=self.proxy, timeout=self.timeout)

    async def _safe_close(self, driver: BrowserDriver | None) -> None:
        """Close ``driver`` (``aclose``) without ever raising.

        Each fetch attempt closes its own driver; cleanup failures are logged
        and swallowed so they never mask the pipeline's actual outcome.
        """
        if driver is None:
            return
        try:
            await driver.aclose()
        except Exception as exc:  # noqa: BLE001 - cleanup must not raise
            logger.debug("Error closing browser driver: %s", exc)

    def _log_failed_attempt(self, mode: str, reason: str, has_next: bool) -> None:
        """Log a failed attempt, noting the fallback when one will follow.

        When another mode will be attempted next, this records the fallback and
        its reason (Requirement 4.4); otherwise it logs the failure of the final
        attempt.
        """
        if has_next:
            logger.warning(
                "Fetch attempt in %s mode failed (%s); falling back to headed mode",
                mode,
                reason,
            )
        else:
            logger.error("Fetch attempt in %s mode failed: %s", mode, reason)
