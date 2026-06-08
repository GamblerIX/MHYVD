"""Tests for the :class:`Pipeline` orchestrator (``src.pipeline.pipeline``).

The browser, source, classifier, and downloader collaborators are all replaced
with lightweight fakes (and an injected driver factory), so these tests drive
the full orchestration — fetch, headless->headed fallback, the reported-count
gate, classify, download, and the guarded page-crash path — without launching a
real browser or touching the network.

Coverage includes unit/example cases plus property-based tests for the design
document's:

* **Property 9 (news-count aggregation)** — ``PipelineResult.news_count``
  equals the length of the fetched list.
  **Validates: Requirements 5.3**
* **Property 10 (reported-count gating)** — Classify/Download run iff the
  reported count is > 0, and the pipeline acts on the reported count even when
  the actual list differs.
  **Validates: Requirements 5.4**
"""

from __future__ import annotations

import asyncio
import unittest

from src.browser.driver import (
    MODE_HEADED,
    MODE_HEADLESS,
    BrowserLaunchError,
)
from src.constants import STATUS_DOWNLOADED
from src.models import DownloadResult, NewsItem
from src.pipeline.pipeline import Pipeline, should_run_downstream

try:  # pragma: no cover - exercised only when hypothesis is installed
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


def run(coro):
    """Run an async coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# Fakes.
# --------------------------------------------------------------------------- #
class FakeDriver:
    """A stand-in BrowserDriver that records launch/close and may fail launch.

    ``launch_error`` (when set) is raised from :meth:`launch` to simulate a
    browser/launch failure; ``crash_error`` is unused here but kept symmetric.
    """

    def __init__(self, mode: str, *, launch_error: Exception | None = None) -> None:
        self.mode = mode
        self.launch_error = launch_error
        self.launched = False
        self.closed = False

    async def launch(self):
        if self.launch_error is not None:
            raise self.launch_error
        self.launched = True
        return self

    async def aclose(self) -> None:
        self.closed = True


class FakeAdapter:
    """A Source_Adapter fake whose fetch behaviour is scripted per call.

    ``results`` is a list of "what to do on attempt N": either a ``list`` of
    NewsItems to return, or an ``Exception`` instance to raise. Records the
    drivers it was given so tests can assert which mode each attempt used.
    """

    def __init__(self, results: list) -> None:
        self._results = list(results)
        self.calls = 0
        self.seen_drivers: list[FakeDriver] = []

    async def fetch_news(self, driver) -> list[NewsItem]:
        self.seen_drivers.append(driver)
        outcome = self._results[min(self.calls, len(self._results) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return list(outcome)


class FakeClassifier:
    """A Classifier fake: groups items into a fixed category (or raises)."""

    def __init__(
        self, *, category: str = "videos/pv", error: Exception | None = None
    ) -> None:
        self.category = category
        self.error = error
        self.classified: list[NewsItem] | None = None

    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        if self.error is not None:
            raise self.error
        self.classified = list(items)
        grouped: dict[str, list[NewsItem]] = {}
        for item in items:
            grouped.setdefault(self.category, []).append(
                item.with_category(self.category)
            )
        return grouped


class FakeDownloader:
    """A Downloader fake: one ``downloaded`` result per item, records its calls."""

    def __init__(self) -> None:
        self.called = False
        self.grouped: dict | None = None
        self.driver = None

    async def download(self, grouped, driver) -> list[DownloadResult]:
        self.called = True
        self.grouped = grouped
        self.driver = driver
        results: list[DownloadResult] = []
        for category, items in grouped.items():
            for item in items:
                results.append(
                    DownloadResult(
                        title=item.title,
                        url=item.url,
                        category=category,
                        video_url="https://cdn/clip.mp4",
                        local_path=__import__("pathlib").Path("x.mp4"),
                        status=STATUS_DOWNLOADED,
                        bytes_written=10,
                    )
                )
        return results


def make_items(n: int) -> list[NewsItem]:
    return [
        NewsItem(title=f"Title {i}", url=f"https://sr.mihoyo.com/news/{i}")
        for i in range(n)
    ]


def make_pipeline(
    adapter,
    classifier=None,
    downloader=None,
    *,
    mode: str = MODE_HEADLESS,
    fallback_enabled: bool = True,
    crash_identifier=None,
    drivers: list[FakeDriver] | None = None,
):
    """Build a Pipeline wired with fakes and a recording driver factory."""
    classifier = classifier or FakeClassifier()
    downloader = downloader or FakeDownloader()
    created: list[FakeDriver] = []

    def factory(m: str) -> FakeDriver:
        if drivers is not None:
            driver = drivers[len(created)]
        else:
            driver = FakeDriver(m)
        created.append(driver)
        return driver

    pipeline = Pipeline(
        adapter,
        classifier,
        downloader,
        mode=mode,
        fallback_enabled=fallback_enabled,
        driver_factory=factory,
        crash_identifier=crash_identifier,
    )
    pipeline._created_drivers = created  # type: ignore[attr-defined]
    return pipeline


# --------------------------------------------------------------------------- #
# should_run_downstream (Property 10 helper).
# --------------------------------------------------------------------------- #
class ShouldRunDownstreamTests(unittest.TestCase):
    def test_zero_is_false(self) -> None:
        self.assertFalse(should_run_downstream(0))

    def test_positive_is_true(self) -> None:
        self.assertTrue(should_run_downstream(1))
        self.assertTrue(should_run_downstream(100))

    def test_negative_is_false(self) -> None:
        self.assertFalse(should_run_downstream(-1))


# --------------------------------------------------------------------------- #
# Happy path.
# --------------------------------------------------------------------------- #
class HappyPathTests(unittest.TestCase):
    def test_successful_run_aggregates_everything(self) -> None:
        adapter = FakeAdapter([make_items(3)])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader)

        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertIsNone(result.error)
        self.assertEqual(result.news_count, 3)
        self.assertEqual(result.classified_categories, {"videos/pv": 3})
        self.assertEqual(len(result.download_results), 3)
        self.assertEqual(result.downloaded, 3)
        self.assertTrue(downloader.called)

    def test_headless_only_when_fallback_disabled_and_succeeds(self) -> None:
        adapter = FakeAdapter([make_items(2)])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        result = run(pipeline.run())
        self.assertEqual(result.news_count, 2)
        # Only one driver was ever built (headless), and it ran the fetch.
        self.assertEqual(len(pipeline._created_drivers), 1)
        self.assertEqual(adapter.seen_drivers[0].mode, MODE_HEADLESS)

    def test_winning_driver_is_closed_after_download(self) -> None:
        adapter = FakeAdapter([make_items(1)])
        pipeline = make_pipeline(adapter)
        run(pipeline.run())
        self.assertTrue(pipeline._created_drivers[0].closed)

    def test_downloader_receives_winning_driver(self) -> None:
        adapter = FakeAdapter([make_items(1)])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader)
        run(pipeline.run())
        self.assertIs(downloader.driver, pipeline._created_drivers[0])


# --------------------------------------------------------------------------- #
# Reported-count gating (Property 10 at the pipeline level).
# --------------------------------------------------------------------------- #
class GatingTests(unittest.TestCase):
    def test_zero_items_no_fallback_reports_no_news(self) -> None:
        adapter = FakeAdapter([[]])  # headless returns zero items
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader, fallback_enabled=False)
        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertFalse(downloader.called)
        self.assertEqual(result.classified_categories, {})
        self.assertTrue(result.error)

    def test_acts_on_reported_count_when_list_nonempty_but_count_zero(self) -> None:
        """A reported count of 0 stops downstream even if items were retrieved."""
        adapter = FakeAdapter([make_items(5)])
        classifier = FakeClassifier()
        downloader = FakeDownloader()
        pipeline = make_pipeline(
            adapter,
            classifier=classifier,
            downloader=downloader,
            fallback_enabled=False,
        )
        # Force the reported count to 0 regardless of the actual list length.
        pipeline._count_news = lambda items: 0  # type: ignore[assignment]

        result = run(pipeline.run())
        self.assertFalse(downloader.called)
        self.assertIsNone(classifier.classified)
        self.assertEqual(result.news_count, 0)

    def test_acts_on_reported_count_when_list_empty_but_count_positive(self) -> None:
        """A positive reported count runs downstream even with an empty list."""
        adapter = FakeAdapter([[]])
        classifier = FakeClassifier()
        downloader = FakeDownloader()
        pipeline = make_pipeline(
            adapter,
            classifier=classifier,
            downloader=downloader,
            fallback_enabled=False,
        )
        pipeline._count_news = lambda items: 7  # type: ignore[assignment]

        result = run(pipeline.run())
        # Downstream ran, acting on the reported count of 7.
        self.assertTrue(downloader.called)
        self.assertEqual(classifier.classified, [])
        self.assertEqual(result.news_count, 7)
        self.assertEqual(result.classified_categories, {})


# --------------------------------------------------------------------------- #
# Fallback behaviour (Requirements 4.2, 4.4, 4.5).
# --------------------------------------------------------------------------- #
class FallbackTests(unittest.TestCase):
    def test_zero_items_headless_falls_back_to_headed_success(self) -> None:
        # Headless -> zero items, headed -> 2 items.
        adapter = FakeAdapter([[], make_items(2)])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader, fallback_enabled=True)
        result = run(pipeline.run())

        self.assertEqual(result.news_count, 2)
        self.assertTrue(downloader.called)
        # Two drivers built: headless then headed.
        self.assertEqual(
            [d.mode for d in pipeline._created_drivers], [MODE_HEADLESS, MODE_HEADED]
        )
        # The headless driver was closed before the headed attempt.
        self.assertTrue(pipeline._created_drivers[0].closed)

    def test_browser_error_headless_falls_back_to_headed(self) -> None:
        adapter = FakeAdapter([RuntimeError("net::ERR blocked"), make_items(1)])
        pipeline = make_pipeline(adapter, fallback_enabled=True)
        result = run(pipeline.run())
        self.assertEqual(result.news_count, 1)
        self.assertEqual(adapter.seen_drivers[1].mode, MODE_HEADED)

    def test_both_modes_fail_reports_each_reason(self) -> None:
        adapter = FakeAdapter(
            [RuntimeError("headless boom"), RuntimeError("headed boom")]
        )
        pipeline = make_pipeline(adapter, fallback_enabled=True)
        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertIsNotNone(result.error)
        self.assertIn("headless boom", result.error)
        self.assertIn("headed boom", result.error)
        self.assertIn(MODE_HEADLESS, result.error)
        self.assertIn(MODE_HEADED, result.error)

    def test_both_modes_zero_items_reports_failure(self) -> None:
        adapter = FakeAdapter([[], []])
        pipeline = make_pipeline(adapter, fallback_enabled=True)
        result = run(pipeline.run())
        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertIn(MODE_HEADLESS, result.error)
        self.assertIn(MODE_HEADED, result.error)

    def test_no_fallback_does_not_attempt_headed(self) -> None:
        adapter = FakeAdapter([RuntimeError("headless boom")])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        result = run(pipeline.run())
        # Only the headless attempt happened.
        self.assertEqual(adapter.calls, 1)
        self.assertEqual(len(pipeline._created_drivers), 1)
        self.assertIn("headless boom", result.error)

    def test_explicit_headed_skips_headless(self) -> None:
        adapter = FakeAdapter([make_items(2)])
        pipeline = make_pipeline(adapter, mode=MODE_HEADED, fallback_enabled=True)
        result = run(pipeline.run())
        self.assertEqual(result.news_count, 2)
        self.assertEqual(len(pipeline._created_drivers), 1)
        self.assertEqual(pipeline._created_drivers[0].mode, MODE_HEADED)

    def test_launch_error_is_treated_as_browser_failure(self) -> None:
        drivers = [
            FakeDriver(MODE_HEADLESS, launch_error=BrowserLaunchError("cannot launch")),
            FakeDriver(MODE_HEADED),
        ]
        adapter = FakeAdapter([make_items(1)])
        pipeline = make_pipeline(adapter, fallback_enabled=True, drivers=drivers)
        result = run(pipeline.run())
        # Headless launch failed -> fell back to headed which fetched 1 item.
        self.assertEqual(result.news_count, 1)
        self.assertTrue(drivers[0].closed)


# --------------------------------------------------------------------------- #
# Page-crash handling (Requirement 12.1).
# --------------------------------------------------------------------------- #
class CrashHandlingTests(unittest.TestCase):
    def test_crash_identified_in_failure_reason(self) -> None:
        adapter = FakeAdapter([RuntimeError("Target crashed unexpectedly")])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        result = run(pipeline.run())
        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertIn("crash", result.error.lower())

    def test_guarded_crash_id_failure_reports_without_details(self) -> None:
        def boom_identifier(driver, exc):
            raise RuntimeError("crash-id mechanism itself failed")

        adapter = FakeAdapter([RuntimeError("page crashed")])
        pipeline = make_pipeline(
            adapter, fallback_enabled=False, crash_identifier=boom_identifier
        )
        # Must not raise; reports a fetch failure without crash details.
        result = run(pipeline.run())
        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertIsNotNone(result.error)
        # The original exception text is still surfaced, but no crash detail.
        self.assertIn("page crashed", result.error)
        self.assertNotIn("page crashed during fetch", result.error)

    def test_driver_closed_after_fetch_crash(self) -> None:
        adapter = FakeAdapter([RuntimeError("Target crashed")])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        run(pipeline.run())
        self.assertTrue(pipeline._created_drivers[0].closed)


# --------------------------------------------------------------------------- #
# Classify failure (Requirement 6.4).
# --------------------------------------------------------------------------- #
class ClassifyFailureTests(unittest.TestCase):
    def test_classification_failure_is_reported_not_raised(self) -> None:
        adapter = FakeAdapter([make_items(2)])
        classifier = FakeClassifier(error=ValueError("bad rules"))
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, classifier=classifier, downloader=downloader)
        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 2)
        self.assertFalse(downloader.called)
        self.assertIn("Classification failed", result.error)


# --------------------------------------------------------------------------- #
# Property-based tests.
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class PropertyTests(unittest.TestCase):
    # ---- Property 9: news-count aggregation ---- #
    @settings(max_examples=200, deadline=None)
    @given(st.integers(min_value=1, max_value=50))
    def test_property_9_news_count_equals_list_length(self, n: int) -> None:
        """**Validates: Requirements 5.3**"""
        adapter = FakeAdapter([make_items(n)])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        result = run(pipeline.run())
        self.assertEqual(result.news_count, n)

    # ---- Property 10: reported-count gating ---- #
    @settings(max_examples=200, deadline=None)
    @given(st.integers(min_value=0, max_value=30))
    def test_property_10_gating_on_reported_count(self, reported: int) -> None:
        """**Validates: Requirements 5.4**

        Drive the pipeline with an arbitrary actual list while forcing the
        reported count to ``reported``. Classify/Download must run iff the
        reported count is > 0, and the recorded ``news_count`` is the reported
        count regardless of the actual list length.
        """
        adapter = FakeAdapter([make_items(3)])  # actual list length fixed at 3
        classifier = FakeClassifier()
        downloader = FakeDownloader()
        pipeline = make_pipeline(
            adapter,
            classifier=classifier,
            downloader=downloader,
            fallback_enabled=False,
        )
        pipeline._count_news = lambda items, _r=reported: _r  # type: ignore[assignment]

        result = run(pipeline.run())

        self.assertEqual(should_run_downstream(reported), downloader.called)
        if reported > 0:
            self.assertEqual(result.news_count, reported)
            self.assertIsNotNone(classifier.classified)
        else:
            self.assertEqual(result.news_count, 0)
            self.assertIsNone(classifier.classified)

    # ---- Property 10 (pure helper) over the full integer range ---- #
    @settings(max_examples=200)
    @given(st.integers(min_value=-100, max_value=100))
    def test_property_10_helper_is_count_positive(self, count: int) -> None:
        """**Validates: Requirements 5.4**"""
        self.assertEqual(should_run_downstream(count), count > 0)


if __name__ == "__main__":
    unittest.main()
