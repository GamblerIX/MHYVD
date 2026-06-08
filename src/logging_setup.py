"""Logging configuration for MHYVD.

Provides :func:`setup_logging` and :func:`shutdown_logging`, which configure
console + file handlers and flush buffered records on exit respectively.

Design notes (see Requirement 11 / Property 29):

* ``setup_logging`` attaches a console handler (stdout) and a file handler to
  the root logger, both at the configured level. When no log file path is
  provided it writes to a timestamped file under a ``logs/`` directory.
* Every record is formatted with a timestamp, level, logger name, and message
  (Property 29 — logging format completeness).
* If logging configuration fails, ``setup_logging`` raises
  :class:`LoggingSetupError`. The CLI maps this to a non-zero exit code so the
  process fails startup rather than continuing without logging (Requirement
  11.1).
* ``shutdown_logging`` flushes and closes handlers and is safe to call even if
  ``setup_logging`` never ran or only partially completed — this covers the
  case where the process exits after an early startup failure (Requirement
  11.4).
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

#: Format applied to every log record. Includes timestamp, level, logger name,
#: and message so formatted records are self-describing (Requirement 11.3 /
#: Property 29).
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Default directory for auto-generated, timestamped log files.
DEFAULT_LOG_DIR = "logs"


class LoggingSetupError(RuntimeError):
    """Raised when logging configuration fails.

    The CLI maps this to a non-zero exit code so the process fails startup
    rather than continuing with logging unconfigured (Requirement 11.1).
    """


def _resolve_level(log_level: str | int) -> int:
    """Translate a level name or numeric value into a logging level int.

    Raises :class:`LoggingSetupError` when the level cannot be resolved.
    """
    if isinstance(log_level, int):
        return log_level
    if isinstance(log_level, str):
        resolved = logging.getLevelName(log_level.strip().upper())
        # ``getLevelName`` returns an int for known names and the string
        # "Level <x>" for unknown ones.
        if isinstance(resolved, int):
            return resolved
    raise LoggingSetupError(f"invalid log level: {log_level!r}")


def _build_log_path(log_file: str | Path | None, log_dir: str | Path) -> Path:
    """Return the log file path, generating a timestamped name when needed."""
    if log_file is not None:
        return Path(log_file)
    log_dir_path = Path(log_dir)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir_path / f"run_{timestamp}.log"


def setup_logging(
    log_level: str | int = "INFO",
    log_file: str | Path | None = None,
    log_dir: str | Path = DEFAULT_LOG_DIR,
) -> logging.Logger:
    """Configure console + file logging at ``log_level``.

    Args:
        log_level: Logging level name (``DEBUG``/``INFO``/``WARNING``/``ERROR``)
            or numeric level.
        log_file: Explicit log file path. When ``None`` a timestamped file is
            created under ``log_dir`` (Requirement 11.2).
        log_dir: Directory used for the auto-generated log file when
            ``log_file`` is not provided.

    Returns:
        The configured root logger.

    Raises:
        LoggingSetupError: If logging configuration fails for any reason. The
            caller is expected to map this to a non-zero exit code
            (Requirement 11.1).
    """
    try:
        level = _resolve_level(log_level)
        log_path = _build_log_path(log_file, log_dir)

        # Ensure the parent directory exists before creating the file handler.
        log_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        root = logging.getLogger()
        root.setLevel(level)
        # Replace any handlers from a previous configuration so repeated calls
        # (and tests) start from a clean slate.
        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        file_handler = logging.FileHandler(log_path, encoding="utf-8", mode="w")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

        root.info("Logging initialised; writing to %s", log_path)
        return root
    except LoggingSetupError:
        raise
    except Exception as exc:  # noqa: BLE001 - any failure means startup fails
        raise LoggingSetupError(f"failed to configure logging: {exc}") from exc


def shutdown_logging() -> None:
    """Flush and close all logging handlers.

    Safe to call even if :func:`setup_logging` never ran or only partially
    completed, so it can be used in a ``finally`` block that also runs after an
    early startup failure (Requirement 11.4). Any per-handler error is
    swallowed so shutdown never raises.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.flush()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            handler.close()
        except Exception:  # pragma: no cover - defensive
            pass
        try:
            root.removeHandler(handler)
        except Exception:  # pragma: no cover - defensive
            pass
    # Final flush of the logging framework's internal state.
    logging.shutdown()


__all__ = [
    "LoggingSetupError",
    "setup_logging",
    "shutdown_logging",
    "LOG_FORMAT",
    "DATE_FORMAT",
    "DEFAULT_LOG_DIR",
]
