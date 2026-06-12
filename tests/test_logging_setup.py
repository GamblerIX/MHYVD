from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from src.logging_setup import (
    DATE_FORMAT,
    LOG_FORMAT,
    LoggingSetupError,
    setup_logging,
    shutdown_logging,
)

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


def _reset_root_logger() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # pragma: no cover
            pass


class SetupLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)

        self.addCleanup(_reset_root_logger)
        _reset_root_logger()

    def test_configures_console_and_file_handlers(self) -> None:
        log_file = self.tmp_path / "run.log"
        root = setup_logging(log_level="INFO", log_file=log_file)

        stream_handlers = [
            h
            for h in root.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ]
        file_handlers = [h for h in root.handlers if isinstance(h, logging.FileHandler)]
        self.assertEqual(len(stream_handlers), 1)
        self.assertEqual(len(file_handlers), 1)

    def test_handlers_set_to_configured_level(self) -> None:
        log_file = self.tmp_path / "run.log"
        root = setup_logging(log_level="DEBUG", log_file=log_file)
        self.assertEqual(root.level, logging.DEBUG)
        for handler in root.handlers:
            self.assertEqual(handler.level, logging.DEBUG)

    def test_writes_records_to_file(self) -> None:
        log_file = self.tmp_path / "run.log"
        setup_logging(log_level="INFO", log_file=log_file)
        logging.getLogger("mhyvd.test").info("hello world")
        shutdown_logging()

        contents = log_file.read_text(encoding="utf-8")
        self.assertIn("hello world", contents)
        self.assertIn("mhyvd.test", contents)
        self.assertIn("[INFO]", contents)

    def test_no_path_creates_timestamped_file_under_logs_dir(self) -> None:
        log_dir = self.tmp_path / "logs"
        setup_logging(log_level="INFO", log_dir=log_dir)
        logging.getLogger("x").info("msg")
        shutdown_logging()

        created = list(log_dir.glob("run_*.log"))
        self.assertEqual(len(created), 1)

        self.assertRegex(created[0].name, r"^run_\d{8}_\d{6}\.log$")

    def test_creates_missing_parent_directory(self) -> None:
        log_file = self.tmp_path / "nested" / "deep" / "run.log"
        setup_logging(log_level="INFO", log_file=log_file)
        shutdown_logging()
        self.assertTrue(log_file.exists())

    def test_repeated_setup_does_not_accumulate_handlers(self) -> None:
        log_file = self.tmp_path / "run.log"
        setup_logging(log_level="INFO", log_file=log_file)
        root = setup_logging(log_level="INFO", log_file=log_file)

        self.assertEqual(len(root.handlers), 2)

    def test_invalid_level_raises_setup_error(self) -> None:
        with self.assertRaises(LoggingSetupError):
            setup_logging(log_level="NOPE")

    def test_setup_failure_raises_logging_setup_error(self) -> None:

        blocker = self.tmp_path / "iam_a_file"
        blocker.write_text("x", encoding="utf-8")
        bad_path = blocker / "run.log"
        with self.assertRaises(LoggingSetupError):
            setup_logging(log_level="INFO", log_file=bad_path)


class ShutdownLoggingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp_path = Path(self._tmp.name)
        self.addCleanup(_reset_root_logger)
        _reset_root_logger()

    def test_shutdown_flushes_buffered_records(self) -> None:
        log_file = self.tmp_path / "run.log"
        setup_logging(log_level="INFO", log_file=log_file)
        logging.getLogger("flush.test").warning("must be flushed")
        shutdown_logging()
        self.assertIn("must be flushed", log_file.read_text(encoding="utf-8"))

    def test_shutdown_is_safe_when_setup_never_ran(self) -> None:
        _reset_root_logger()

        shutdown_logging()

    def test_shutdown_is_idempotent(self) -> None:
        log_file = self.tmp_path / "run.log"
        setup_logging(log_level="INFO", log_file=log_file)
        shutdown_logging()

        shutdown_logging()

    def test_shutdown_after_partial_setup(self) -> None:

        _reset_root_logger()
        root = logging.getLogger()
        log_file = self.tmp_path / "partial.log"
        handler = logging.FileHandler(log_file, encoding="utf-8")
        root.addHandler(handler)

        shutdown_logging()
        self.assertEqual(root.handlers, [])


class LogFormatTests(unittest.TestCase):
    def _format(self, name: str, level: int, message: str) -> str:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        return formatter.format(record)

    def test_format_contains_all_fields(self) -> None:
        formatted = self._format("my.logger", logging.WARNING, "a message")
        self.assertIn("WARNING", formatted)
        self.assertIn("my.logger", formatted)
        self.assertIn("a message", formatted)

        self.assertRegex(formatted, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class Property29LoggingFormatCompleteness(unittest.TestCase):
    _LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]

    @settings(max_examples=300)
    @given(
        name=st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",), blacklist_characters="\x00"
            ),
            min_size=1,
            max_size=40,
        ),
        level=st.sampled_from(_LEVELS),
        message=st.text(
            alphabet=st.characters(
                blacklist_categories=("Cs",), blacklist_characters="\x00"
            ),
            min_size=0,
            max_size=80,
        ),
    )
    def test_formatted_record_contains_all_fields(
        self, name: str, level: int, message: str
    ) -> None:
        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
        record = logging.LogRecord(
            name=name,
            level=level,
            pathname=__file__,
            lineno=1,
            msg=message,
            args=(),
            exc_info=None,
        )
        formatted = formatter.format(record)

        self.assertRegex(formatted, r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}")

        self.assertIn(logging.getLevelName(level), formatted)

        self.assertIn(name, formatted)

        self.assertIn(message, formatted)


if __name__ == "__main__":
    unittest.main()
