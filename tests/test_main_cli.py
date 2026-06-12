from __future__ import annotations

import asyncio
import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import yaml

from src.constants import (
    EXIT_ERROR,
    EXIT_SUCCESS,
    EXIT_TIMEOUT,
)
from src.main import _LimitedAdapter, main
from src.models import NewsItem, PipelineResult
from src.sources import get_source_registry
from src.sources.release_list import DEFAULT_RELEASE_LIST_URL, ReleaseListAdapter


def _write_config(directory: Path, **overrides: Any) -> Path:
    data: dict[str, Any] = {
        "source_key": "honkai-star-rail/cn",
        "classifier": "rule_based",
        "output_dir": str(directory / "out"),
        "concurrency": 1,
        "retry_count": 3,
        "timeout": 30,
    }
    data.update(overrides)
    path = directory / "config.yaml"
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(data, handle, allow_unicode=True)
    return path


class FakePipeline:
    def __init__(self, result: PipelineResult, *, delay: float = 0.0) -> None:
        self._result = result
        self._delay = delay
        self.ran = False

    async def run(self) -> PipelineResult:
        self.ran = True
        if self._delay:
            await asyncio.sleep(self._delay)
        return self._result


def make_factory(result: PipelineResult, *, delay: float = 0.0):
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> FakePipeline:
        captured.update(kwargs)
        captured["pipeline"] = FakePipeline(result, delay=delay)
        return captured["pipeline"]

    factory.captured = captured  # type: ignore[attr-defined]
    return factory


def completed_result() -> PipelineResult:
    return PipelineResult(news_count=3, completed=True)


class TmpDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.log_file = self.tmp_path / "run.log"

    def run_main(self, argv: list[str], **kwargs: Any) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv, **kwargs)
        return code, out.getvalue(), err.getvalue()


class ListSourcesTests(TmpDirTestCase):
    def test_lists_all_registered_keys(self) -> None:
        code, out, _ = self.run_main(["list-sources"])
        self.assertEqual(code, EXIT_SUCCESS)
        for key in get_source_registry().list_keys():
            self.assertIn(key, out)

    def test_includes_hsr_cn(self) -> None:
        _, out, _ = self.run_main(["list-sources"])
        self.assertIn("honkai-star-rail/cn", out)


class ArgumentErrorTests(TmpDirTestCase):
    def test_unknown_subcommand_exits_non_zero(self) -> None:
        code, _, err = self.run_main(["frobnicate"])
        self.assertNotEqual(code, EXIT_SUCCESS)
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("invalid choice", err)

    def test_invalid_option_value_exits_zero(self) -> None:

        code, _, _ = self.run_main(["run", "--log-level", "TRACE"])
        self.assertEqual(code, EXIT_SUCCESS)

    def test_no_subcommand_exits_zero(self) -> None:

        code, _, _ = self.run_main([])
        self.assertEqual(code, EXIT_SUCCESS)

    def test_unrecognized_argument_exits_zero(self) -> None:
        code, _, _ = self.run_main(["list-sources", "--bogus"])
        self.assertEqual(code, EXIT_SUCCESS)


class RunCompletionTests(TmpDirTestCase):
    def test_prints_summary_on_full_completion(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        code, out, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("# Pipeline Result", out)
        self.assertTrue(factory.captured["pipeline"].ran)  # type: ignore[attr-defined]

    def test_prints_summary_on_completed_failure(self) -> None:

        result = PipelineResult(news_count=0, completed=True, error="fetch failed")
        config = _write_config(self.tmp_path)
        code, out, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(result),
        )
        self.assertEqual(code, EXIT_ERROR)
        self.assertIn("# Pipeline Result", out)
        self.assertIn("fetch failed", out)

    def test_no_summary_and_timeout_code_on_fetch_timeout(self) -> None:

        result = PipelineResult(news_count=0, completed=False, timed_out=True)
        config = _write_config(self.tmp_path)
        code, out, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(result),
        )
        self.assertEqual(code, EXIT_TIMEOUT)
        self.assertNotIn("# Pipeline Result", out)

    def test_slow_run_is_not_timed_out_by_overall_budget(self) -> None:

        config = _write_config(self.tmp_path, timeout=0.05)
        code, out, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(completed_result(), delay=0.2),
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIn("# Pipeline Result", out)

    def test_timeout_is_passed_to_pipeline_as_fetch_budget(self) -> None:
        config = _write_config(self.tmp_path, timeout=42)
        factory = make_factory(completed_result())
        self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=factory,
        )
        self.assertEqual(factory.captured["fetch_budget"], 42)  # type: ignore[attr-defined]

    def test_incomplete_result_is_not_printed(self) -> None:

        result = PipelineResult(news_count=0, completed=False)
        config = _write_config(self.tmp_path)
        code, out, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(result),
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertNotIn("# Pipeline Result", out)


class BrowserModeTests(TmpDirTestCase):
    def _captured_mode(self, extra: list[str]) -> str:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file), *extra],
            pipeline_factory=factory,
        )
        return factory.captured["mode"]  # type: ignore[attr-defined]

    def test_default_mode_is_headed(self) -> None:
        self.assertEqual(self._captured_mode([]), "headed")

    def test_headless_flag_selects_headless(self) -> None:
        self.assertEqual(self._captured_mode(["--headless"]), "headless")

    def test_headed_flag_selects_headed(self) -> None:
        self.assertEqual(self._captured_mode(["--headed"]), "headed")


class ListOnlyTests(TmpDirTestCase):
    def test_list_only_disables_download(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        code, _, _ = self.run_main(
            [
                "run",
                "-c",
                str(config),
                "--list-only",
                "--log-file",
                str(self.log_file),
            ],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertFalse(factory.captured["download_enabled"])  # type: ignore[attr-defined]

    def test_download_enabled_by_default(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        code, _, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertTrue(factory.captured["download_enabled"])  # type: ignore[attr-defined]


class FromReleaseTests(TmpDirTestCase):
    def _inner_adapter(self, factory: Any) -> Any:
        adapter = factory.captured["adapter"]
        self.assertIsInstance(adapter, _LimitedAdapter)
        return adapter._inner  # noqa: SLF001

    def test_from_release_selects_release_adapter_with_default_url(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        code, _, _ = self.run_main(
            [
                "run",
                "-c",
                str(config),
                "--from-release",
                "--log-file",
                str(self.log_file),
            ],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        inner = self._inner_adapter(factory)
        self.assertIsInstance(inner, ReleaseListAdapter)
        self.assertEqual(inner.base_url, DEFAULT_RELEASE_LIST_URL)
        self.assertTrue(factory.captured["download_enabled"])  # type: ignore[attr-defined]

    def test_from_release_accepts_a_custom_url(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        custom = "https://example.com/my-list.json"
        code, _, _ = self.run_main(
            [
                "run",
                "-c",
                str(config),
                "--from-release",
                custom,
                "--log-file",
                str(self.log_file),
            ],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        inner = self._inner_adapter(factory)
        self.assertIsInstance(inner, ReleaseListAdapter)
        self.assertEqual(inner.base_url, custom)

    def test_from_release_overrides_source_flag(self) -> None:
        config = _write_config(self.tmp_path)
        factory = make_factory(completed_result())
        code, _, _ = self.run_main(
            [
                "run",
                "-c",
                str(config),
                "-s",
                "honkai-star-rail/cn",
                "--from-release",
                "--log-file",
                str(self.log_file),
            ],
            pipeline_factory=factory,
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertIsInstance(self._inner_adapter(factory), ReleaseListAdapter)

    def test_from_release_and_list_only_are_mutually_exclusive(self) -> None:

        factory = make_factory(completed_result())
        code, _, err = self.run_main(
            ["run", "--list-only", "--from-release"], pipeline_factory=factory
        )
        self.assertEqual(code, EXIT_SUCCESS)
        self.assertNotIn("pipeline", factory.captured)  # type: ignore[attr-defined]
        self.assertIn("not allowed with", err)


class RunConfigErrorTests(TmpDirTestCase):
    def test_missing_config_file_exits_error(self) -> None:
        missing = self.tmp_path / "nope.yaml"
        code, _, _ = self.run_main(
            ["run", "-c", str(missing), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(completed_result()),
        )
        self.assertEqual(code, EXIT_ERROR)

    def test_unknown_source_key_exits_error(self) -> None:
        config = _write_config(self.tmp_path)
        code, _, _ = self.run_main(
            [
                "run",
                "-c",
                str(config),
                "-s",
                "no-such-game/nowhere",
                "--log-file",
                str(self.log_file),
            ],
            pipeline_factory=make_factory(completed_result()),
        )
        self.assertEqual(code, EXIT_ERROR)


class RetryWarningTests(TmpDirTestCase):
    def test_zero_retry_emits_warning(self) -> None:
        config = _write_config(self.tmp_path, retry_count=0)
        with self.assertLogs("mhyvd", level="WARNING") as captured:
            code = main(
                ["run", "-c", str(config), "--log-file", str(self.log_file)],
                pipeline_factory=make_factory(completed_result()),
            )
        self.assertEqual(code, EXIT_SUCCESS)
        joined = "\n".join(captured.output)
        self.assertIn("Retry count is zero", joined)

    def test_nonzero_retry_emits_no_zero_retry_warning(self) -> None:
        config = _write_config(self.tmp_path, retry_count=2)

        code, _, _ = self.run_main(
            ["run", "-c", str(config), "--log-file", str(self.log_file)],
            pipeline_factory=make_factory(completed_result()),
        )
        self.assertEqual(code, EXIT_SUCCESS)


class LimitAdapterTests(unittest.TestCase):
    class _Inner:
        def __init__(self, items: list[NewsItem]) -> None:
            self._items = items

        async def fetch_news(self, driver: Any) -> list[NewsItem]:
            return list(self._items)

    @staticmethod
    def _items(n: int) -> list[NewsItem]:
        return [NewsItem(title=f"T{i}", url=f"https://x/news/{i}") for i in range(n)]

    def test_limit_caps_items(self) -> None:
        inner = self._Inner(self._items(10))
        adapter = _LimitedAdapter(inner, 3)
        result = asyncio.run(adapter.fetch_news(None))
        self.assertEqual(len(result), 3)

    def test_no_limit_returns_all(self) -> None:
        inner = self._Inner(self._items(5))
        adapter = _LimitedAdapter(inner, None)
        result = asyncio.run(adapter.fetch_news(None))
        self.assertEqual(len(result), 5)

    def test_limit_larger_than_list_returns_all(self) -> None:
        inner = self._Inner(self._items(2))
        adapter = _LimitedAdapter(inner, 100)
        result = asyncio.run(adapter.fetch_news(None))
        self.assertEqual(len(result), 2)

    def test_run_passes_limited_adapter_to_pipeline(self) -> None:

        with tempfile.TemporaryDirectory() as tmp:
            config = _write_config(Path(tmp))
            factory = make_factory(completed_result())
            code = main(
                [
                    "run",
                    "-c",
                    str(config),
                    "-l",
                    "5",
                    "--log-file",
                    str(Path(tmp) / "run.log"),
                ],
                pipeline_factory=factory,
            )
            self.assertEqual(code, EXIT_SUCCESS)
            adapter = factory.captured["adapter"]  # type: ignore[attr-defined]
            self.assertIsInstance(adapter, _LimitedAdapter)


if __name__ == "__main__":
    unittest.main()
