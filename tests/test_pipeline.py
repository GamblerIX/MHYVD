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

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


def run(coro):
    return asyncio.run(coro)


class FakeDriver:
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
    download_enabled: bool = True,
    crash_identifier=None,
    drivers: list[FakeDriver] | None = None,
    fetch_budget: float | None = None,
):
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
        download_enabled=download_enabled,
        fetch_budget=fetch_budget,
        driver_factory=factory,
        crash_identifier=crash_identifier,
    )
    pipeline._created_drivers = created  # type: ignore[attr-defined]
    return pipeline


class ShouldRunDownstreamTests(unittest.TestCase):
    def test_zero_is_false(self) -> None:
        self.assertFalse(should_run_downstream(0))

    def test_positive_is_true(self) -> None:
        self.assertTrue(should_run_downstream(1))
        self.assertTrue(should_run_downstream(100))

    def test_negative_is_false(self) -> None:
        self.assertFalse(should_run_downstream(-1))


class SlowAdapter:
    def __init__(self, delay: float, items: list[NewsItem]) -> None:
        self._delay = delay
        self._items = items

    async def fetch_news(self, driver) -> list[NewsItem]:
        await asyncio.sleep(self._delay)
        return list(self._items)


class SlowDownloader(FakeDownloader):
    def __init__(self, delay: float) -> None:
        super().__init__()
        self._delay = delay

    async def download(self, grouped, driver):
        await asyncio.sleep(self._delay)
        return await super().download(grouped, driver)


class FetchBudgetTests(unittest.TestCase):
    def test_slow_fetch_times_out(self) -> None:
        pipeline = make_pipeline(SlowAdapter(1.0, make_items(2)), fetch_budget=0.05)

        result = run(pipeline.run())

        self.assertTrue(result.timed_out)
        self.assertFalse(result.completed)
        self.assertIn("timed out", result.error or "")

        self.assertTrue(all(d.closed for d in pipeline._created_drivers))

    def test_slow_download_is_not_budgeted(self) -> None:
        downloader = SlowDownloader(0.2)
        pipeline = make_pipeline(
            FakeAdapter([make_items(2)]), downloader=downloader, fetch_budget=0.05
        )

        result = run(pipeline.run())

        self.assertFalse(result.timed_out)
        self.assertTrue(result.completed)
        self.assertEqual(result.downloaded, 2)

    def test_no_budget_means_no_timeout(self) -> None:
        pipeline = make_pipeline(SlowAdapter(0.05, make_items(1)), fetch_budget=None)

        result = run(pipeline.run())

        self.assertFalse(result.timed_out)
        self.assertTrue(result.completed)


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


class GatingTests(unittest.TestCase):
    def test_zero_items_no_fallback_reports_no_news(self) -> None:
        adapter = FakeAdapter([[]])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader, fallback_enabled=False)
        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertFalse(downloader.called)
        self.assertEqual(result.classified_categories, {})
        self.assertTrue(result.error)

    def test_acts_on_reported_count_when_list_nonempty_but_count_zero(self) -> None:
        adapter = FakeAdapter([make_items(5)])
        classifier = FakeClassifier()
        downloader = FakeDownloader()
        pipeline = make_pipeline(
            adapter,
            classifier=classifier,
            downloader=downloader,
            fallback_enabled=False,
        )

        pipeline._count_news = lambda items: 0  # type: ignore[assignment]

        result = run(pipeline.run())
        self.assertFalse(downloader.called)
        self.assertIsNone(classifier.classified)
        self.assertEqual(result.news_count, 0)

    def test_acts_on_reported_count_when_list_empty_but_count_positive(self) -> None:
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

        self.assertTrue(downloader.called)
        self.assertEqual(classifier.classified, [])
        self.assertEqual(result.news_count, 7)
        self.assertEqual(result.classified_categories, {})


class FallbackTests(unittest.TestCase):
    def test_zero_items_headless_falls_back_to_headed_success(self) -> None:

        adapter = FakeAdapter([[], make_items(2)])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader, fallback_enabled=True)
        result = run(pipeline.run())

        self.assertEqual(result.news_count, 2)
        self.assertTrue(downloader.called)

        self.assertEqual(
            [d.mode for d in pipeline._created_drivers], [MODE_HEADLESS, MODE_HEADED]
        )

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

        self.assertEqual(result.news_count, 1)
        self.assertTrue(drivers[0].closed)


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

        result = run(pipeline.run())
        self.assertTrue(result.completed)
        self.assertEqual(result.news_count, 0)
        self.assertIsNotNone(result.error)

        self.assertIn("page crashed", result.error)
        self.assertNotIn("page crashed during fetch", result.error)

    def test_driver_closed_after_fetch_crash(self) -> None:
        adapter = FakeAdapter([RuntimeError("Target crashed")])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        run(pipeline.run())
        self.assertTrue(pipeline._created_drivers[0].closed)


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


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class PropertyTests(unittest.TestCase):
    @settings(max_examples=200, deadline=None)
    @given(st.integers(min_value=1, max_value=50))
    def test_property_9_news_count_equals_list_length(self, n: int) -> None:
        adapter = FakeAdapter([make_items(n)])
        pipeline = make_pipeline(adapter, fallback_enabled=False)
        result = run(pipeline.run())
        self.assertEqual(result.news_count, n)

    @settings(max_examples=200, deadline=None)
    @given(st.integers(min_value=0, max_value=30))
    def test_property_10_gating_on_reported_count(self, reported: int) -> None:
        adapter = FakeAdapter([make_items(3)])
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

    @settings(max_examples=200)
    @given(st.integers(min_value=-100, max_value=100))
    def test_property_10_helper_is_count_positive(self, count: int) -> None:
        self.assertEqual(should_run_downstream(count), count > 0)


class ListExportTests(unittest.TestCase):
    def _pipeline(self, adapter, *, path, exporter):
        pipeline = make_pipeline(adapter)
        pipeline.list_export_path = path  # type: ignore[attr-defined]
        pipeline._list_exporter = exporter  # type: ignore[attr-defined]
        return pipeline

    def test_export_called_after_classify_with_grouped(self) -> None:
        captured: dict = {}

        def exporter(grouped, path):
            captured["grouped"] = grouped
            captured["path"] = path

        adapter = FakeAdapter([make_items(2)])
        pipeline = self._pipeline(adapter, path="cache.json", exporter=exporter)
        result = run(pipeline.run())

        self.assertEqual(captured["path"], "cache.json")

        self.assertIn("videos/pv", captured["grouped"])
        self.assertEqual(result.news_count, 2)

    def test_no_export_when_path_unset(self) -> None:
        calls = []
        adapter = FakeAdapter([make_items(1)])
        pipeline = self._pipeline(
            adapter, path=None, exporter=lambda g, p: calls.append(p)
        )
        run(pipeline.run())
        self.assertEqual(calls, [])

    def test_export_failure_is_swallowed(self) -> None:
        def exporter(grouped, path):
            raise OSError("disk full")

        adapter = FakeAdapter([make_items(1)])
        pipeline = self._pipeline(adapter, path="cache.json", exporter=exporter)

        result = run(pipeline.run())
        self.assertTrue(result.completed)
        self.assertIsNone(result.error)

    def test_no_export_when_fetch_fails(self) -> None:
        calls = []
        adapter = FakeAdapter([[]])
        pipeline = self._pipeline(
            adapter, path="cache.json", exporter=lambda g, p: calls.append(p)
        )
        run(pipeline.run())
        self.assertEqual(calls, [])


class DownloadDisabledTests(unittest.TestCase):
    def test_download_stage_skipped(self) -> None:
        adapter = FakeAdapter([make_items(3)])
        downloader = FakeDownloader()
        pipeline = make_pipeline(adapter, downloader=downloader, download_enabled=False)

        result = run(pipeline.run())

        self.assertTrue(result.completed)
        self.assertIsNone(result.error)
        self.assertEqual(result.news_count, 3)
        self.assertEqual(result.classified_categories, {"videos/pv": 3})
        self.assertEqual(result.download_results, ())
        self.assertFalse(downloader.called)

    def test_export_still_runs_without_download(self) -> None:
        captured: dict = {}
        adapter = FakeAdapter([make_items(2)])
        pipeline = make_pipeline(adapter, download_enabled=False)
        pipeline.list_export_path = "cache.json"  # type: ignore[attr-defined]
        pipeline._list_exporter = lambda g, p: captured.update(  # type: ignore[attr-defined]
            grouped=g, path=p
        )

        result = run(pipeline.run())

        self.assertEqual(captured["path"], "cache.json")
        self.assertIn("videos/pv", captured["grouped"])
        self.assertTrue(result.completed)
        self.assertIsNone(result.error)

    def test_driver_closed_when_download_disabled(self) -> None:
        adapter = FakeAdapter([make_items(1)])
        pipeline = make_pipeline(adapter, download_enabled=False)

        run(pipeline.run())

        drivers = pipeline._created_drivers  # type: ignore[attr-defined]
        self.assertTrue(drivers)
        self.assertTrue(all(driver.closed for driver in drivers))


if __name__ == "__main__":
    unittest.main()
