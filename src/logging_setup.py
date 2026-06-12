from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


DEFAULT_LOG_DIR = "logs"


class LoggingSetupError(RuntimeError):
    pass


def _resolve_level(log_level: str | int) -> int:
    if isinstance(log_level, int):
        return log_level
    if isinstance(log_level, str):
        resolved = logging.getLevelName(log_level.strip().upper())

        if isinstance(resolved, int):
            return resolved
    raise LoggingSetupError(f"invalid log level: {log_level!r}")


def _build_log_path(log_file: str | Path | None, log_dir: str | Path) -> Path:
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
    try:
        level = _resolve_level(log_level)
        log_path = _build_log_path(log_file, log_dir)

        log_path.parent.mkdir(parents=True, exist_ok=True)

        formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

        root = logging.getLogger()
        root.setLevel(level)

        for handler in list(root.handlers):
            root.removeHandler(handler)
            try:
                handler.close()
            except Exception:  # pragma: no cover
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
    except Exception as exc:  # noqa: BLE001
        raise LoggingSetupError(f"failed to configure logging: {exc}") from exc


def shutdown_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        try:
            handler.flush()
        except Exception:  # pragma: no cover
            pass
        try:
            handler.close()
        except Exception:  # pragma: no cover
            pass
        try:
            root.removeHandler(handler)
        except Exception:  # pragma: no cover
            pass

    logging.shutdown()


__all__ = [
    "LoggingSetupError",
    "setup_logging",
    "shutdown_logging",
    "LOG_FORMAT",
    "DATE_FORMAT",
    "DEFAULT_LOG_DIR",
]
