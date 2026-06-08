"""Command-line interface for MHYVD (Requirement 10).

This module defines the ``argparse`` subcommand CLI and ``main(argv) -> int``,
the single entrypoint that wires the whole system together: it loads
:class:`~src.config.settings.Config`, establishes logging, resolves the proxy,
builds the Source_Adapter / Classifier / Downloader from their registries, and
drives the :class:`~src.pipeline.pipeline.Pipeline` under an overall time
budget with interrupt handling.

Subcommands
-----------
* ``run`` -- execute the full pipeline (Requirement 10.2). Options:
  ``--config/-c``, ``--source/-s``, ``--proxy/-p``, a mutually exclusive
  ``--headless`` / ``--headed`` group, ``--limit/-l``, ``--log-level``,
  ``--log-file``, ``--resume``, and ``--no-fallback``
  (Requirements 10.3-10.10).
* ``list-sources`` -- print every registered Source_Key (Requirement 10.11).

Exit codes and output
----------------------
``main`` returns an integer exit code. The pipeline outcome is mapped through
:func:`~src.runtime.choose_exit_code` (timeout 124 > interrupt 130 > success 0,
Requirement 12.3). Configuration and logging-setup failures map to
``EXIT_ERROR`` after being reported (Requirements 11.1, 12.5). The
``as_markdown()`` summary is printed **iff** the pipeline fully completed its
execution -- never on timeout or interrupt (Requirement 10.13, Property 27).

Argument-error policy (Requirement 10.12)
-----------------------------------------
An *unknown subcommand* is reported and exits with a **non-zero** status. Every
other argument error (a missing required argument, an invalid option value)
exits with a **zero** status. This is implemented by :class:`_CliParser`, which
turns ``argparse``'s normal ``SystemExit(2)`` into a structured signal that
``main`` maps to the correct exit code.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Callable
from typing import Any

from .browser.driver import DEFAULT_MODE, MODE_HEADED, MODE_HEADLESS
from .classifier.registry import ClassifierRegistry
from .classifier.rule_based import RuleBasedClassifier
from .config.proxy import resolve_proxy
from .config.settings import Config, ConfigError
from .constants import EXIT_ERROR, EXIT_SUCCESS
from .downloader import get_downloader_registry
from .logging_setup import LoggingSetupError, setup_logging, shutdown_logging
from .models import NewsItem, PipelineResult, Rule
from .pipeline.pipeline import Pipeline
from .runtime import ShutdownController, choose_exit_code, run_with_time_budget
from .sources import get_source_registry
from .sources.registry import UnknownSourceKeyError

__all__ = ["main", "build_parser"]

logger = logging.getLogger("mhyvd")

#: Registered name of the default downloader (see :mod:`src.downloader`).
DEFAULT_DOWNLOADER_NAME = "playwright"

#: Cache file (relative to the output directory) backing Resume_Mode fetching.
FETCH_CACHE_RELATIVE_PATH = (".cache", "fetch_cache.json")

#: Cache file (relative to the output directory) backing Download_Cache records.
DOWNLOAD_CACHE_RELATIVE_PATH = (".cache", "download_cache.json")

#: Factory that builds the object whose ``run()`` coroutine the CLI awaits.
#: Injectable so tests can drive ``main`` without launching a real browser.
PipelineFactory = Callable[..., Any]


# --------------------------------------------------------------------------- #
# Argument parsing with the Requirement 10.12 error policy.
# --------------------------------------------------------------------------- #
class _CliParserExit(Exception):
    """Internal signal raised instead of ``argparse``'s ``SystemExit``.

    Carries the intended ``status`` (as argparse would have used), the message
    argparse wanted to print, and whether the failure was specifically an
    *unknown subcommand* -- the one argument error that must exit non-zero
    (Requirement 10.12).
    """

    def __init__(
        self,
        status: int,
        message: str | None = None,
        *,
        unknown_subcommand: bool = False,
    ) -> None:
        super().__init__(message or "")
        self.status = status
        self.message = message
        self.unknown_subcommand = unknown_subcommand


class _CliParser(argparse.ArgumentParser):
    """``ArgumentParser`` that reports errors without calling ``sys.exit``.

    ``error`` and ``exit`` raise :class:`_CliParserExit` so ``main`` can decide
    the process exit code. An unknown subcommand is flagged so it can map to a
    non-zero code while all other argument errors map to zero
    (Requirement 10.12). Subparsers inherit this class automatically, so an
    invalid option value on a subcommand follows the same policy.
    """

    def error(self, message: str) -> None:  # type: ignore[override]
        unknown = "invalid choice" in message and "argument command" in message
        raise _CliParserExit(2, message, unknown_subcommand=unknown)

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        raise _CliParserExit(status, message)


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with the ``run`` and ``list-sources`` commands."""
    parser = _CliParser(
        prog="mhyvd",
        description="MHYVD - scrape and download miHoYo/HoYoverse game videos",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="command", required=True)

    run_parser = subparsers.add_parser("run", help="run the full download pipeline")
    run_parser.add_argument(
        "-c", "--config", default=None, help="path to the YAML configuration file"
    )
    run_parser.add_argument(
        "-s",
        "--source",
        default=None,
        help="Source_Key to run (e.g. honkai-star-rail/cn)",
    )
    run_parser.add_argument(
        "-p", "--proxy", default=None, help="proxy server address (overrides config)"
    )

    mode_group = run_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="run the browser in headless mode (default)",
    )
    mode_group.add_argument(
        "--headed",
        dest="headed",
        action="store_true",
        help="run the browser in headed (visible window) mode",
    )

    run_parser.add_argument(
        "-l",
        "--limit",
        type=int,
        default=None,
        help="limit the number of videos processed (for testing)",
    )
    run_parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="logging level (default: INFO)",
    )
    run_parser.add_argument(
        "--log-file", default=None, help="path to the log file (default: timestamped)"
    )
    run_parser.add_argument(
        "--resume", action="store_true", help="enable Resume_Mode (skip cached work)"
    )
    run_parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="disable the headless->headed fallback",
    )

    subparsers.add_parser("list-sources", help="list all registered Source_Keys")
    return parser


# --------------------------------------------------------------------------- #
# Helpers.
# --------------------------------------------------------------------------- #
class _LimitedAdapter:
    """Wrap a Source_Adapter to cap the number of items it returns.

    Implements ``--limit`` (Requirement 10.7) by slicing the fetched
    :class:`NewsItem` list before it reaches the Classify_Stage and
    Download_Stage. A ``limit`` of ``None`` (or negative) is treated as "no
    limit". Only ``fetch_news`` is delegated, which is all the pipeline drives.
    """

    def __init__(self, inner: Any, limit: int | None) -> None:
        self._inner = inner
        self._limit = limit

    async def fetch_news(self, driver: Any) -> list[NewsItem]:
        items = await self._inner.fetch_news(driver)
        if self._limit is not None and self._limit >= 0:
            return list(items)[: self._limit]
        return list(items)


def _default_pipeline_factory(**kwargs: Any) -> Pipeline:
    """Build a real :class:`Pipeline` from the wired collaborators."""
    return Pipeline(**kwargs)


def _build_rules(config: Config) -> list[Rule] | None:
    """Convert Config rule mappings into :class:`Rule` objects (or ``None``).

    Config exposes rules as ``[{"category": ..., "keywords": [...]}, ...]``.
    They are converted to :class:`Rule` instances for the classifier; an empty
    list yields ``None`` so the classifier falls back to its built-in defaults
    (Requirement 6.6).
    """
    raw_rules = config.rules
    if not raw_rules:
        return None
    return [
        Rule(category=rule["category"], keywords=tuple(rule.get("keywords", [])))
        for rule in raw_rules
    ]


def _resolve_mode(args: argparse.Namespace) -> str:
    """Resolve the browser mode from the mutually exclusive mode flags."""
    if getattr(args, "headed", False):
        return MODE_HEADED
    if getattr(args, "headless", False):
        return MODE_HEADLESS
    return DEFAULT_MODE


# --------------------------------------------------------------------------- #
# Subcommands.
# --------------------------------------------------------------------------- #
def _cmd_list_sources() -> int:
    """Print every registered Source_Key, one per line (Requirement 10.11)."""
    registry = get_source_registry()
    for key in registry.list_keys():
        print(key)
    return EXIT_SUCCESS


def _silence_proactor_shutdown_noise() -> None:
    """Suppress the spurious Windows ``ProactorEventLoop`` teardown tracebacks.

    On Windows, :func:`asyncio.run` uses the ``ProactorEventLoop`` (required for
    the subprocess transports Playwright relies on). When the loop is closed,
    Playwright's subprocess-pipe transports are finalised by the garbage
    collector *after* the loop has shut down. Their ``__del__`` builds a
    ``ResourceWarning`` message via ``f"unclosed transport {self!r}"``; that
    ``repr`` calls ``fileno()`` on an already-closed pipe and raises
    ``ValueError: I/O operation on closed pipe``. Because it is raised inside
    ``__del__``, Python routes it through :data:`sys.unraisablehook` and prints
    the noisy "Exception ignored in" traceback. The run itself is unaffected;
    only the teardown is noisy (a known CPython/Playwright Windows interaction).

    A ``warnings`` filter cannot help here: the crash happens while building the
    warning's *argument* (``{self!r}``), before ``warnings.warn`` ever runs. So
    we install an :data:`sys.unraisablehook` that drops exactly this exception
    and delegates everything else to the previous hook. This is a no-op on
    non-Windows platforms, where the Proactor loop (and thus the noise) is absent.
    """
    if sys.platform != "win32":
        return

    previous_hook = sys.unraisablehook

    def _hook(unraisable: Any) -> None:
        exc = unraisable.exc_value
        if isinstance(exc, ValueError) and "I/O operation on closed pipe" in str(exc):
            return
        previous_hook(unraisable)

    sys.unraisablehook = _hook


def _cmd_run(args: argparse.Namespace, *, pipeline_factory: PipelineFactory) -> int:
    """Execute the ``run`` subcommand: wire and drive the full pipeline.

    Logging is established *first* so that a subsequent configuration failure is
    logged and flushed before the process exits (Requirements 11.1, 11.4, 12.5).
    """
    # --- Logging (established before config so config errors are logged). ---
    try:
        setup_logging(args.log_level, args.log_file)
    except LoggingSetupError as exc:
        print(f"Failed to configure logging: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        # --- Config (Requirement 9 / 12.5). ---
        try:
            config = Config(args.config)
        except ConfigError as exc:
            logger.error("Configuration error: %s", exc)
            return EXIT_ERROR

        # --- CLI overrides over config (Requirements 10.4, 10.5). ---
        source_key = args.source or config.source_key
        proxy = args.proxy or resolve_proxy()
        mode = _resolve_mode(args)
        fallback_enabled = not args.no_fallback

        # --- Zero-retry warning (Requirements 14.6, 14.7). ---
        if config.retry_count == 0:
            logger.warning("Retry count is zero; automatic error recovery is disabled.")

        # --- Build collaborators from their registries. ---
        try:
            adapter = _build_adapter(config, source_key, proxy, args.resume, args.limit)
        except UnknownSourceKeyError as exc:
            logger.error("Unknown source key: %s", exc)
            return EXIT_ERROR

        adapter = _LimitedAdapter(adapter, args.limit)
        classifier = _build_classifier(config)
        downloader = _build_downloader(config, proxy, args.resume)

        pipeline = pipeline_factory(
            adapter=adapter,
            classifier=classifier,
            downloader=downloader,
            mode=mode,
            proxy=proxy,
            timeout=config.timeout,
            fallback_enabled=fallback_enabled,
            resume=args.resume,
        )

        # --- Drive the pipeline under the overall time budget + interrupt. ---
        _silence_proactor_shutdown_noise()
        controller = ShutdownController()
        controller.install()
        try:
            result, timed_out = asyncio.run(
                run_with_time_budget(
                    pipeline.run(), config.timeout, controller=controller
                )
            )
        finally:
            controller.uninstall()

        interrupted = controller.shutdown_requested
        exit_code = choose_exit_code(timed_out, interrupted)

        # On timeout, report which source timed out and after how long, split
        # into whole minutes + seconds (minutes may be 0 for sub-minute budgets).
        if timed_out:
            budget = config.timeout or 0
            minutes, seconds = divmod(int(budget), 60)
            logging.getLogger(source_key).error(
                "Timeout for %dm%ds", minutes, seconds
            )

        # A self-reported pipeline failure (all fetch modes failed, or a
        # classification failure) is a runtime failure: map it to EXIT_ERROR
        # unless a timeout/interrupt already took precedence (design Exit-Code
        # Map: runtime failure -> 1).
        if (
            exit_code == EXIT_SUCCESS
            and isinstance(result, PipelineResult)
            and result.error is not None
        ):
            exit_code = EXIT_ERROR

        # Print the summary iff the pipeline fully completed -- whether it
        # reported success or failure, including error details on failure
        # (Req 10.13). This is gated on completion, NOT the exit code: a
        # completed-but-failed run exits non-zero (Exit-Code Map) yet still
        # prints its summary. A timeout or interrupt leaves the pipeline result
        # absent (``None``) so the isinstance guard suppresses output.
        if isinstance(result, PipelineResult) and result.completed:
            print(result.as_markdown())

        return exit_code
    finally:
        shutdown_logging()


def _build_adapter(
    config: Config,
    source_key: str,
    proxy: str | None,
    resume: bool,
    limit: int | None = None,
) -> Any:
    """Construct the Source_Adapter for ``source_key`` from the registry.

    The adapter's base URL comes from its registered metadata. When Resume_Mode
    is enabled a :class:`~src.cache.fetch_cache.FetchCache` under the output
    directory is supplied so already-fetched URLs are skipped and newly fetched
    URLs are recorded. ``limit`` is passed into the adapter so it slices the
    fetched list *before* recording to the Fetch_Cache, preventing items beyond
    the limit from being marked fetched and lost on a later resume run.
    """
    registry = get_source_registry()
    if not registry.is_registered(source_key):
        raise UnknownSourceKeyError(source_key)

    metadata = _source_metadata(registry, source_key)

    fetch_cache = None
    if resume:
        from .cache.fetch_cache import FetchCache

        cache_path = config.output_dir.joinpath(*FETCH_CACHE_RELATIVE_PATH)
        fetch_cache = FetchCache(cache_path)

    return registry.create(
        source_key,
        base_url=metadata.base_url,
        proxy=proxy,
        resume=resume,
        fetch_cache=fetch_cache,
        limit=limit,
    )


def _source_metadata(registry: Any, source_key: str) -> Any:
    """Return the static metadata of the adapter registered under ``source_key``."""
    # The registry's generic backing store holds the adapter class; its
    # ``metadata`` ClassVar carries the base URL needed for construction.
    adapter_cls = registry._registry.get(source_key)  # noqa: SLF001 - intentional
    return adapter_cls.metadata


def _build_classifier(config: Config) -> Any:
    """Construct the configured classifier with Config-supplied rules."""
    classifier_registry = ClassifierRegistry()
    classifier_registry.register(RuleBasedClassifier.name, RuleBasedClassifier)
    rules = _build_rules(config)
    return classifier_registry.create(config.classifier, rules=rules)


def _build_downloader(config: Config, proxy: str | None, resume: bool) -> Any:
    """Construct the default downloader with Config concurrency/retry/timeout.

    Under Resume_Mode a :class:`~src.cache.download_cache.DownloadCache` under
    the output directory is supplied so each successful download is recorded
    (Requirement 8.4); otherwise no download cache is wired.
    """
    downloader_registry = get_downloader_registry()

    download_cache = None
    if resume:
        from .cache.download_cache import DownloadCache

        cache_path = config.output_dir.joinpath(*DOWNLOAD_CACHE_RELATIVE_PATH)
        download_cache = DownloadCache(cache_path)

    return downloader_registry.create(
        DEFAULT_DOWNLOADER_NAME,
        output_dir=config.output_dir,
        max_concurrent=config.concurrency,
        retry_count=config.retry_count,
        timeout=config.timeout,
        proxy=proxy,
        resume=resume,
        download_cache=download_cache,
    )


# --------------------------------------------------------------------------- #
# Entrypoint.
# --------------------------------------------------------------------------- #
def main(
    argv: list[str] | None = None,
    *,
    pipeline_factory: PipelineFactory | None = None,
) -> int:
    """Parse ``argv`` and dispatch to the selected subcommand.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]`` when ``None``).
        pipeline_factory: Override the pipeline builder (testing); defaults to
            building a real :class:`Pipeline`.

    Returns:
        The process exit code (see the module docstring).
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliParserExit as exc:
        if exc.message:
            print(exc.message, file=sys.stderr)
        # Unknown subcommand -> non-zero; every other argument error -> zero
        # (Requirement 10.12).
        return EXIT_ERROR if exc.unknown_subcommand else EXIT_SUCCESS

    if args.command == "list-sources":
        return _cmd_list_sources()
    if args.command == "run":
        return _cmd_run(
            args, pipeline_factory=pipeline_factory or _default_pipeline_factory
        )

    # Defensive: argparse's required subcommand guard makes this unreachable.
    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return EXIT_ERROR  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
