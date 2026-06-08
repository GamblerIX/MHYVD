"""Tests for the Playwright downloader (``src.downloader.playwright_downloader``).

Browser interaction and network I/O are isolated behind two injectable seams
(``resolve_attempt`` and ``file_downloader``), so these tests drive the full
download orchestration with lightweight fakes and temp-file writes -- no real
browser is launched. Coverage includes unit/example cases plus property-based
tests for the design document's Properties 13, 16, 17, 18, 19, and 20.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from src.constants import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_SKIPPED
from src.downloader.base import Downloader
from src.downloader.playwright_downloader import (
    PlaywrightDownloader,
    classify_download_outcome,
    select_video_categories,
)
from src.downloader.registry import DownloaderRegistry, UnknownDownloaderError
from src.models import DownloadResult, NewsItem

try:  # pragma: no cover - exercised only when hypothesis is installed
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
def run(coro):
    """Run an async coroutine to completion on a fresh event loop."""
    return asyncio.run(coro)


def make_items(category: str, count: int) -> list[NewsItem]:
    return [
        NewsItem(title=f"Title {i}", url=f"https://sr.mihoyo.com/news/{i}")
        for i in range(count)
    ]


class _Driver:
    """A stand-in for BrowserDriver. The fakes never touch it."""


# --------------------------------------------------------------------------- #
# select_video_categories (Property 13).
# --------------------------------------------------------------------------- #
class SelectVideoCategoriesTests(unittest.TestCase):
    def test_keeps_only_videos_prefix(self) -> None:
        grouped = {
            "videos/pv": make_items("videos/pv", 1),
            "videos/pv/character": make_items("videos/pv/character", 2),
            "others": make_items("others", 3),
            "news": make_items("news", 1),
        }
        selected = select_video_categories(grouped)
        self.assertEqual(set(selected), {"videos/pv", "videos/pv/character"})

    def test_bare_videos_without_slash_excluded(self) -> None:
        grouped = {"videos": make_items("videos", 1)}
        self.assertEqual(select_video_categories(grouped), {})

    def test_empty_mapping(self) -> None:
        self.assertEqual(select_video_categories({}), {})

    def test_shares_item_lists(self) -> None:
        items = make_items("videos/pv", 2)
        grouped = {"videos/pv": items}
        selected = select_video_categories(grouped)
        self.assertIs(selected["videos/pv"], items)


# --------------------------------------------------------------------------- #
# classify_download_outcome (Property 16).
# --------------------------------------------------------------------------- #
class ClassifyOutcomeTests(unittest.TestCase):
    def test_no_url_is_failed(self) -> None:
        self.assertEqual(
            classify_download_outcome(
                video_url=None, download_succeeded=True, validation_passed=True
            ),
            STATUS_FAILED,
        )
        self.assertEqual(
            classify_download_outcome(
                video_url="", download_succeeded=True, validation_passed=True
            ),
            STATUS_FAILED,
        )

    def test_downloaded_only_when_both_true(self) -> None:
        self.assertEqual(
            classify_download_outcome(
                video_url="u", download_succeeded=True, validation_passed=True
            ),
            STATUS_DOWNLOADED,
        )
        for ds, vp in ((True, False), (False, True), (False, False)):
            self.assertEqual(
                classify_download_outcome(
                    video_url="u", download_succeeded=ds, validation_passed=vp
                ),
                STATUS_FAILED,
            )


# --------------------------------------------------------------------------- #
# download() orchestration: example cases.
# --------------------------------------------------------------------------- #
class DownloadOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _writer(self):
        """A file_downloader that writes via a .part file then atomically moves."""

        async def download_file(video_url: str, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(f"{target.suffix}.part")
            data = video_url.encode("utf-8")
            part.write_bytes(data)
            # Target must not exist until the atomic replace completes.
            os.replace(part, target)
            return {"bytes_written": len(data), "remote_size": len(data)}

        return download_file

    def test_ignores_non_video_categories(self) -> None:
        async def resolve(driver, item):
            return f"https://cdn/{item.title}.mp4"

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=self._writer(),
        )
        grouped = {
            "videos/pv": make_items("videos/pv", 2),
            "others": make_items("others", 3),
        }
        results = run(dl.download(grouped, _Driver()))
        # Only the 2 video items are processed.
        self.assertEqual(len(results), 2)
        self.assertTrue(all(r.category == "videos/pv" for r in results))

    def test_successful_download_reports_bytes(self) -> None:
        async def resolve(driver, item):
            return "https://cdn/clip.mp4"

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=self._writer(),
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_DOWNLOADED)
        self.assertGreater(result.bytes_written, 0)
        self.assertTrue(result.local_path.exists())

    def test_target_extension_follows_resolved_url(self) -> None:
        # A .mov video must be saved as .mov, not mislabelled .mp4.
        async def resolve(driver, item):
            return "https://fastcdn.mihoyo.com/x/abc_123.mov"

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=self._writer(),
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_DOWNLOADED)
        self.assertEqual(result.local_path.suffix, ".mov")
        self.assertTrue(result.local_path.exists())

    def test_part_file_replaced_atomically(self) -> None:
        seen_states: list[bool] = []

        async def resolve(driver, item):
            return "https://cdn/clip.mp4"

        async def download_file(video_url: str, target: Path) -> dict:
            target.parent.mkdir(parents=True, exist_ok=True)
            part = target.with_suffix(f"{target.suffix}.part")
            part.write_bytes(b"payload")
            # While writing, the target should not yet exist.
            seen_states.append(target.exists())
            os.replace(part, target)
            # No leftover .part file after replacement.
            seen_states.append(part.exists())
            return {"bytes_written": 7, "remote_size": 7}

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=download_file,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        run(dl.download(grouped, _Driver()))
        self.assertEqual(seen_states, [False, False])

    def test_no_url_yields_failed_with_error(self) -> None:
        async def resolve(driver, item):
            return None

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=self._writer(),
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertTrue(result.error)

    def test_download_exception_yields_failed(self) -> None:
        async def resolve(driver, item):
            return "https://cdn/clip.mp4"

        async def boom(video_url: str, target: Path) -> dict:
            raise OSError("disk full")

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=boom,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertIn("disk full", result.error or "")

    def test_validation_failure_downgrades_to_failed(self) -> None:
        async def resolve(driver, item):
            return "https://cdn/clip.mp4"

        async def short_download(video_url: str, target: Path) -> dict:
            # Reports a remote size that does not match the bytes written.
            return {"bytes_written": 3, "remote_size": 100}

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resolve_attempt=resolve,
            file_downloader=short_download,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_FAILED)
        self.assertTrue(result.error)

    def test_empty_grouping_returns_empty(self) -> None:
        async def resolve(driver, item):
            return "https://cdn/clip.mp4"

        dl = PlaywrightDownloader(output_dir=self.out, resolve_attempt=resolve)
        self.assertEqual(run(dl.download({}, _Driver())), [])
        self.assertEqual(
            run(dl.download({"others": make_items("others", 2)}, _Driver())),
            [],
        )


# --------------------------------------------------------------------------- #
# Resume skip (Property 19).
# --------------------------------------------------------------------------- #
class ResumeSkipTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.out = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_existing_target_is_skipped(self) -> None:
        # Pre-create the target file for the single item.
        item = NewsItem(title="Clip", url="https://sr.mihoyo.com/news/55")
        target = self.out / "videos/pv" / "Clip [55].mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"already here")

        resolved = False

        async def resolve(driver, it):
            nonlocal resolved
            resolved = True
            return "https://cdn/clip.mp4"

        dl = PlaywrightDownloader(
            output_dir=self.out, resume=True, resolve_attempt=resolve
        )
        grouped = {"videos/pv": [item]}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(result.status, STATUS_SKIPPED)
        # Skipped without even attempting resolution.
        self.assertFalse(resolved)

    def test_existing_target_any_extension_is_skipped(self) -> None:
        # A previously-downloaded .mov file must still be recognised as the
        # target for this item even though resolution (which determines the
        # extension) is skipped in resume mode.
        item = NewsItem(title="Clip", url="https://sr.mihoyo.com/news/55")
        target = self.out / "videos/pv" / "Clip [55].mov"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"already here")

        resolved = False

        async def resolve(driver, it):
            nonlocal resolved
            resolved = True
            return "https://cdn/clip.mov"

        dl = PlaywrightDownloader(
            output_dir=self.out, resume=True, resolve_attempt=resolve
        )
        [result] = run(dl.download({"videos/pv": [item]}, _Driver()))
        self.assertEqual(result.status, STATUS_SKIPPED)
        self.assertFalse(resolved)
        self.assertEqual(result.local_path.suffix, ".mov")

    def test_without_resume_existing_file_not_skipped(self) -> None:
        item = NewsItem(title="Clip", url="https://sr.mihoyo.com/news/55")
        target = self.out / "videos/pv" / "Clip [55].mp4"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"old")

        async def resolve(driver, it):
            return "https://cdn/clip.mp4"

        async def writer(video_url: str, tgt: Path) -> dict:
            return {"bytes_written": 10, "remote_size": 10}

        dl = PlaywrightDownloader(
            output_dir=self.out,
            resume=False,
            resolve_attempt=resolve,
            file_downloader=writer,
        )
        [result] = run(dl.download({"videos/pv": [item]}, _Driver()))
        self.assertEqual(result.status, STATUS_DOWNLOADED)


# --------------------------------------------------------------------------- #
# Shutdown awareness (Bug A: prompt interrupt).
# --------------------------------------------------------------------------- #
class ShutdownAwarenessTests(unittest.TestCase):
    def test_no_new_items_resolved_once_shutdown_requested(self) -> None:
        # With concurrency 1 the items run serially; once shutdown is requested
        # after the first resolves, no further item should be resolved.
        stop = False
        resolved_urls: list[str] = []

        def should_stop() -> bool:
            return stop

        async def resolve(driver, item):
            nonlocal stop
            resolved_urls.append(item.url)
            stop = True  # request shutdown after the first resolution
            return "https://cdn/clip.mp4"

        async def writer(video_url: str, target: Path) -> dict:
            return {"bytes_written": 4, "remote_size": 4}

        dl = PlaywrightDownloader(
            output_dir="unused",
            max_concurrent=1,
            resolve_attempt=resolve,
            file_downloader=writer,
            should_stop=should_stop,
        )
        grouped = {"videos/pv": make_items("videos/pv", 5)}
        results = run(dl.download(grouped, _Driver()))
        # Only the first item is resolved; the rest short-circuit.
        self.assertEqual(len(resolved_urls), 1)
        # Every item still yields exactly one result (Property 20 preserved).
        self.assertEqual(len(results), 5)
        statuses = [r.status for r in results]
        self.assertEqual(statuses.count(STATUS_DOWNLOADED), 1)
        # The skipped-for-shutdown items are reported as failed, not dropped.
        self.assertEqual(statuses.count(STATUS_FAILED), 4)

    def test_retry_loop_stops_on_shutdown(self) -> None:
        attempts = 0
        stop = False

        def should_stop() -> bool:
            return stop

        async def fail_then_request_stop(driver, item):
            nonlocal attempts, stop
            attempts += 1
            stop = True  # request shutdown during the first attempt
            return None

        dl = PlaywrightDownloader(
            output_dir="unused",
            retry_count=5,
            resolve_attempt=fail_then_request_stop,
            should_stop=should_stop,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        # Retry budget is 5, but shutdown stops further attempts after the first.
        self.assertEqual(attempts, 1)
        self.assertEqual(result.status, STATUS_FAILED)


# --------------------------------------------------------------------------- #
# Retry budget (Property 18).
# --------------------------------------------------------------------------- #
class RetryBudgetTests(unittest.TestCase):
    def _count_attempts(self, retry_count: int) -> tuple[int, DownloadResult]:
        attempts = 0

        async def always_fail(driver, item):
            nonlocal attempts
            attempts += 1
            return None

        dl = PlaywrightDownloader(
            output_dir="unused", retry_count=retry_count, resolve_attempt=always_fail
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        return attempts, result

    def test_attempts_equal_retry_count(self) -> None:
        for retry_count in (0, 1, 2, 3, 5):
            attempts, result = self._count_attempts(retry_count)
            self.assertEqual(attempts, retry_count)
            self.assertEqual(result.status, STATUS_FAILED)

    def test_stops_after_first_success(self) -> None:
        attempts = 0

        async def succeed_second(driver, item):
            nonlocal attempts
            attempts += 1
            return "https://cdn/clip.mp4" if attempts >= 2 else None

        async def writer(video_url: str, target: Path) -> dict:
            return {"bytes_written": 5, "remote_size": 5}

        dl = PlaywrightDownloader(
            output_dir="unused",
            retry_count=5,
            resolve_attempt=succeed_second,
            file_downloader=writer,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(attempts, 2)
        self.assertEqual(result.status, STATUS_DOWNLOADED)

    def test_raising_attempt_counts_and_is_isolated(self) -> None:
        attempts = 0

        async def raises(driver, item):
            nonlocal attempts
            attempts += 1
            raise RuntimeError("nav crashed")

        dl = PlaywrightDownloader(
            output_dir="unused", retry_count=3, resolve_attempt=raises
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(attempts, 3)
        self.assertEqual(result.status, STATUS_FAILED)


# --------------------------------------------------------------------------- #
# Concurrency bound (Property 17).
# --------------------------------------------------------------------------- #
class ConcurrencyTests(unittest.TestCase):
    def _measure_peak(self, concurrency: int, item_count: int) -> tuple[int, int]:
        current = 0
        peak = 0

        async def resolve(driver, item):
            return f"https://cdn/{item.title}.mp4"

        async def slow_download(video_url: str, target: Path) -> dict:
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0.01)
            current -= 1
            return {"bytes_written": 4, "remote_size": 4}

        dl = PlaywrightDownloader(
            output_dir="unused",
            max_concurrent=concurrency,
            resolve_attempt=resolve,
            file_downloader=slow_download,
        )
        grouped = {"videos/pv": make_items("videos/pv", item_count)}
        results = run(dl.download(grouped, _Driver()))
        return peak, len(results)

    def test_concurrency_one_is_serial(self) -> None:
        peak, count = self._measure_peak(1, 6)
        self.assertEqual(peak, 1)
        self.assertEqual(count, 6)

    def test_peak_never_exceeds_limit(self) -> None:
        for concurrency in (2, 3, 5):
            peak, count = self._measure_peak(concurrency, 12)
            self.assertLessEqual(peak, concurrency)
            self.assertEqual(count, 12)


# --------------------------------------------------------------------------- #
# Download isolation (Property 20).
# --------------------------------------------------------------------------- #
class IsolationTests(unittest.TestCase):
    def test_every_item_yields_result_despite_failures(self) -> None:
        async def resolve(driver, item):
            # Items with an even index fail to resolve.
            idx = int(item.url.rsplit("/", 1)[-1])
            return None if idx % 2 == 0 else "https://cdn/clip.mp4"

        async def writer(video_url: str, target: Path) -> dict:
            return {"bytes_written": 3, "remote_size": 3}

        dl = PlaywrightDownloader(
            output_dir="unused",
            resolve_attempt=resolve,
            file_downloader=writer,
        )
        grouped = {"videos/pv": make_items("videos/pv", 8)}
        results = run(dl.download(grouped, _Driver()))
        self.assertEqual(len(results), 8)
        statuses = {int(r.url.rsplit("/", 1)[-1]): r.status for r in results}
        for idx, status in statuses.items():
            expected = STATUS_FAILED if idx % 2 == 0 else STATUS_DOWNLOADED
            self.assertEqual(status, expected)


# --------------------------------------------------------------------------- #
# Registry integration.
# --------------------------------------------------------------------------- #
class RegistryTests(unittest.TestCase):
    def test_register_and_create(self) -> None:
        registry = DownloaderRegistry()
        registry.register("playwright", PlaywrightDownloader)
        self.assertTrue(registry.is_registered("playwright"))
        instance = registry.create("playwright", output_dir="x")
        self.assertIsInstance(instance, PlaywrightDownloader)
        self.assertIsInstance(instance, Downloader)

    def test_unknown_name_raises_naming_key(self) -> None:
        registry = DownloaderRegistry()
        with self.assertRaises(UnknownDownloaderError) as ctx:
            registry.create("missing")
        self.assertIn("missing", str(ctx.exception))

    def test_default_registry_has_playwright(self) -> None:
        from src.downloader import get_downloader_registry

        registry = get_downloader_registry()
        self.assertTrue(registry.is_registered("playwright"))


# --------------------------------------------------------------------------- #
# Property-based tests.
# --------------------------------------------------------------------------- #
@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class PropertyTests(unittest.TestCase):
    # ---- Property 13: download processes only video categories ---- #
    @settings(max_examples=200, deadline=None)
    @given(
        st.dictionaries(
            keys=st.text(min_size=1, max_size=20).filter(lambda s: "\x00" not in s),
            values=st.integers(min_value=0, max_value=3),
            max_size=8,
        )
    )
    def test_property_13_only_video_categories(self, spec: dict) -> None:
        """**Validates: Requirements 7.1, 14.2**"""
        grouped = {cat: make_items(cat, n) for cat, n in spec.items()}
        selected = select_video_categories(grouped)
        expected = {cat for cat in grouped if cat.startswith("videos/")}
        self.assertEqual(set(selected), expected)
        # Every selected category's items are preserved untouched.
        for cat in selected:
            self.assertIs(selected[cat], grouped[cat])

    # ---- Property 16: resolution-to-status mapping ---- #
    @settings(max_examples=300)
    @given(
        st.one_of(st.none(), st.just(""), st.text(min_size=1, max_size=10)),
        st.booleans(),
        st.booleans(),
    )
    def test_property_16_status_mapping(
        self, video_url: str | None, ds: bool, vp: bool
    ) -> None:
        """**Validates: Requirements 7.5, 7.6**"""
        status = classify_download_outcome(
            video_url=video_url, download_succeeded=ds, validation_passed=vp
        )
        if not video_url:
            self.assertEqual(status, STATUS_FAILED)
        elif ds and vp:
            self.assertEqual(status, STATUS_DOWNLOADED)
        else:
            self.assertEqual(status, STATUS_FAILED)

    # ---- Property 17: concurrency bound ---- #
    @settings(max_examples=40, deadline=None)
    @given(
        st.integers(min_value=1, max_value=6),
        st.integers(min_value=0, max_value=15),
    )
    def test_property_17_concurrency_bound(
        self, concurrency: int, item_count: int
    ) -> None:
        """**Validates: Requirements 7.7, 14.6**"""
        current = 0
        peak = 0

        async def resolve(driver, item):
            return f"https://cdn/{item.title}.mp4"

        async def slow_download(video_url: str, target: Path) -> dict:
            nonlocal current, peak
            current += 1
            peak = max(peak, current)
            await asyncio.sleep(0)
            current -= 1
            return {"bytes_written": 1, "remote_size": 1}

        dl = PlaywrightDownloader(
            output_dir="unused",
            max_concurrent=concurrency,
            resolve_attempt=resolve,
            file_downloader=slow_download,
        )
        grouped = {"videos/pv": make_items("videos/pv", item_count)}
        results = run(dl.download(grouped, _Driver()))
        self.assertEqual(len(results), item_count)
        self.assertLessEqual(peak, concurrency)

    # ---- Property 18: retry-count budget ---- #
    @settings(max_examples=50, deadline=None)
    @given(st.integers(min_value=0, max_value=8))
    def test_property_18_retry_budget(self, retry_count: int) -> None:
        """**Validates: Requirements 7.8, 14.6**"""
        attempts = 0

        async def always_fail(driver, item):
            nonlocal attempts
            attempts += 1
            return None

        dl = PlaywrightDownloader(
            output_dir="unused",
            retry_count=retry_count,
            resolve_attempt=always_fail,
        )
        grouped = {"videos/pv": make_items("videos/pv", 1)}
        [result] = run(dl.download(grouped, _Driver()))
        self.assertEqual(attempts, retry_count)
        self.assertEqual(result.status, STATUS_FAILED)

    # ---- Property 19: resume skips existing target files ---- #
    @settings(max_examples=40, deadline=None)
    @given(st.integers(min_value=1, max_value=6))
    def test_property_19_resume_skips_existing(self, item_count: int) -> None:
        """**Validates: Requirements 8.2, 14.3**"""
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            items = make_items("videos/pv", item_count)
            # Pre-create every target file.
            from src.downloader.paths import build_output_path, extract_news_id

            for item in items:
                target = build_output_path(
                    out, "videos/pv", item.title, extract_news_id(item.url)
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"x")

            async def resolve(driver, item):  # pragma: no cover - never called
                raise AssertionError("resolution attempted for existing target")

            dl = PlaywrightDownloader(
                output_dir=out, resume=True, resolve_attempt=resolve
            )
            results = run(dl.download({"videos/pv": items}, _Driver()))
            self.assertEqual(len(results), item_count)
            self.assertTrue(all(r.status == STATUS_SKIPPED for r in results))

    # ---- Property 20: download isolation ---- #
    @settings(max_examples=60, deadline=None)
    @given(st.lists(st.booleans(), min_size=1, max_size=12))
    def test_property_20_isolation(self, fail_flags: list) -> None:
        """**Validates: Requirements 12.2**"""
        items = [
            NewsItem(title=f"T{i}", url=f"https://sr.mihoyo.com/news/{i}")
            for i in range(len(fail_flags))
        ]
        should_fail = {items[i].url: flag for i, flag in enumerate(fail_flags)}

        async def resolve(driver, item):
            return None if should_fail[item.url] else "https://cdn/clip.mp4"

        async def writer(video_url: str, target: Path) -> dict:
            return {"bytes_written": 2, "remote_size": 2}

        dl = PlaywrightDownloader(
            output_dir="unused",
            resolve_attempt=resolve,
            file_downloader=writer,
        )
        results = run(dl.download({"videos/pv": items}, _Driver()))
        # Every item produces exactly one result.
        self.assertEqual(len(results), len(items))
        by_url = {r.url: r for r in results}
        self.assertEqual(set(by_url), set(should_fail))
        for url, failed in should_fail.items():
            expected = STATUS_FAILED if failed else STATUS_DOWNLOADED
            self.assertEqual(by_url[url].status, expected)


if __name__ == "__main__":
    unittest.main()
