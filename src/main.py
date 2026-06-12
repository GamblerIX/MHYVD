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
from .sources.release_list import DEFAULT_RELEASE_LIST_URL, RELEASE_LIST_SOURCE_KEY

__all__ = ["main", "build_parser"]

logger = logging.getLogger("mhyvd")


DEFAULT_DOWNLOADER_NAME = "playwright"


FETCH_CACHE_RELATIVE_PATH = (".cache", "fetch_cache.json")


DOWNLOAD_CACHE_RELATIVE_PATH = (".cache", "download_cache.json")


LIST_EXPORT_RELATIVE_PATH = ("cache.json",)


PipelineFactory = Callable[..., Any]


class _CliParserExit(Exception):
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
    def error(self, message: str) -> None:  # type: ignore[override]
        unknown = "invalid choice" in message and "argument command" in message
        raise _CliParserExit(2, message, unknown_subcommand=unknown)

    def exit(self, status: int = 0, message: str | None = None) -> None:  # type: ignore[override]
        raise _CliParserExit(status, message)


def build_parser() -> argparse.ArgumentParser:
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
    run_parser.add_argument(
        "-o",
        "--timeout",
        type=float,
        default=None,
        help="fetch-stage time budget / per-operation timeout in seconds; "
        "download time is not counted (overrides config)",
    )

    mode_group = run_parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--headless",
        dest="headless",
        action="store_true",
        help="run the browser in headless mode (for CI/servers)",
    )
    mode_group.add_argument(
        "--headed",
        dest="headed",
        action="store_true",
        help="run the browser in headed (visible window) mode (default)",
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

    list_group = run_parser.add_mutually_exclusive_group()
    list_group.add_argument(
        "--list-only",
        action="store_true",
        help="fetch, classify and export the URL list without downloading videos",
    )
    list_group.add_argument(
        "--from-release",
        nargs="?",
        const=DEFAULT_RELEASE_LIST_URL,
        default=None,
        metavar="URL",
        help="skip the browser scrape: download the url-list.json published on "
        "the GitHub url-list release (or the given URL) and download its "
        "videos (overrides --source)",
    )
    run_parser.add_argument(
        "--upload",
        choices=("webdav", "gdrive"),
        default=None,
        help="stream each downloaded video to this backend and delete the "
        "local copy once uploaded (download one, upload one, repeat)",
    )
    run_parser.add_argument(
        "--no-fallback",
        action="store_true",
        help="disable the headless->headed fallback",
    )

    subparsers.add_parser("list-sources", help="list all registered Source_Keys")

    for backend, help_text in (
        ("webdav", "upload downloaded videos to a WebDAV server"),
        ("gdrive", "upload downloaded videos to Google Drive (OAuth)"),
    ):
        upload_parser = subparsers.add_parser(f"upload-{backend}", help=help_text)
        upload_parser.add_argument(
            "-c", "--config", default=None, help="path to the YAML configuration file"
        )
        upload_parser.add_argument(
            "--log-level",
            choices=("DEBUG", "INFO", "WARNING", "ERROR"),
            default="INFO",
            help="logging level (default: INFO)",
        )
        upload_parser.add_argument(
            "--log-file",
            default=None,
            help="path to the log file (default: timestamped)",
        )
    return parser


class _LimitedAdapter:
    def __init__(self, inner: Any, limit: int | None) -> None:
        self._inner = inner
        self._limit = limit

    async def fetch_news(self, driver: Any) -> list[NewsItem]:
        items = await self._inner.fetch_news(driver)
        if self._limit is not None and self._limit >= 0:
            return list(items)[: self._limit]
        return list(items)


def _default_pipeline_factory(**kwargs: Any) -> Pipeline:
    return Pipeline(**kwargs)


def _build_rules(config: Config) -> list[Rule] | None:
    raw_rules = config.rules
    if not raw_rules:
        return None
    return [
        Rule(category=rule["category"], keywords=tuple(rule.get("keywords", [])))
        for rule in raw_rules
    ]


def _resolve_mode(args: argparse.Namespace) -> str:
    if getattr(args, "headed", False):
        return MODE_HEADED
    if getattr(args, "headless", False):
        return MODE_HEADLESS
    return DEFAULT_MODE


def _cmd_list_sources() -> int:
    registry = get_source_registry()
    for key in registry.list_keys():
        print(key)
    return EXIT_SUCCESS


def _silence_proactor_shutdown_noise() -> None:
    if sys.platform != "win32":
        return

    previous_hook = sys.unraisablehook

    def _hook(unraisable: Any) -> None:
        exc = unraisable.exc_value
        if isinstance(exc, ValueError) and "I/O operation on closed pipe" in str(exc):
            return
        previous_hook(unraisable)

    sys.unraisablehook = _hook


UploaderFactory = Callable[..., Any]


def _cmd_upload(
    backend: str,
    args: argparse.Namespace,
    *,
    uploader_factory: UploaderFactory | None = None,
) -> int:
    try:
        setup_logging(args.log_level, args.log_file)
    except LoggingSetupError as exc:
        print(f"Failed to configure logging: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        try:
            config = Config(args.config)
        except ConfigError as exc:
            logger.error("Configuration error: %s", exc)
            return EXIT_ERROR

        try:
            uploader = _build_uploader(
                config, backend, uploader_factory=uploader_factory
            )
        except (ValueError, RuntimeError) as exc:
            logger.error("Uploader configuration error: %s", exc)
            return EXIT_ERROR

        summary = uploader.upload_all(config.output_dir)
        if summary.error:
            logger.error("Upload failed: %s", summary.error)
            return EXIT_ERROR
        logger.info(
            "Upload finished: %d uploaded, %d skipped, %d failed",
            summary.uploaded,
            summary.skipped,
            summary.failed,
        )
        return EXIT_SUCCESS if summary.ok else EXIT_ERROR
    finally:
        shutdown_logging()


def _cmd_run(
    args: argparse.Namespace,
    *,
    pipeline_factory: PipelineFactory,
    uploader_factory: UploaderFactory | None = None,
) -> int:

    try:
        setup_logging(args.log_level, args.log_file)
    except LoggingSetupError as exc:
        print(f"Failed to configure logging: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        try:
            config = Config(args.config)
        except ConfigError as exc:
            logger.error("Configuration error: %s", exc)
            return EXIT_ERROR

        source_key = args.source or config.source_key

        base_url_override: str | None = None
        if args.from_release:
            source_key = RELEASE_LIST_SOURCE_KEY
            base_url_override = args.from_release
        proxy = args.proxy or resolve_proxy()
        mode = _resolve_mode(args)
        fallback_enabled = not args.no_fallback
        timeout = args.timeout if args.timeout is not None else config.timeout

        if config.retry_count == 0:
            logger.warning("Retry count is zero; automatic error recovery is disabled.")

        try:
            adapter = _build_adapter(
                config,
                source_key,
                proxy,
                args.resume,
                args.limit,
                base_url_override=base_url_override,
            )
        except UnknownSourceKeyError as exc:
            logger.error("Unknown source key: %s", exc)
            return EXIT_ERROR

        adapter = _LimitedAdapter(adapter, args.limit)
        classifier = _build_classifier(config)

        upload_stats = None
        post_download = None
        remote_exists = None
        if args.upload:
            from .uploader import StreamingUploadStats, make_post_download_hook

            try:
                uploader = _build_uploader(
                    config, args.upload, uploader_factory=uploader_factory
                )
            except (ValueError, RuntimeError) as exc:
                logger.error("Uploader configuration error: %s", exc)
                return EXIT_ERROR
            upload_stats = StreamingUploadStats()
            post_download = make_post_download_hook(
                uploader, config.output_dir, stats=upload_stats
            )
            remote_exists = getattr(uploader, "exists", None)

        controller = ShutdownController()
        downloader = _build_downloader(
            config,
            proxy,
            args.resume,
            timeout,
            should_stop=lambda: controller.shutdown_requested,
            post_download=post_download,
            remote_exists=remote_exists,
        )

        list_export_path = config.output_dir.joinpath(*LIST_EXPORT_RELATIVE_PATH)

        pipeline = pipeline_factory(
            adapter=adapter,
            classifier=classifier,
            downloader=downloader,
            mode=mode,
            proxy=proxy,
            timeout=timeout,
            fallback_enabled=fallback_enabled,
            resume=args.resume,
            download_enabled=not args.list_only,
            list_export_path=list_export_path,
            fetch_budget=timeout,
        )

        _silence_proactor_shutdown_noise()
        controller.install()
        try:
            result, timed_out = asyncio.run(
                run_with_time_budget(pipeline.run(), None, controller=controller)
            )
        finally:
            controller.uninstall()

        timed_out = timed_out or (
            isinstance(result, PipelineResult) and result.timed_out
        )
        interrupted = controller.shutdown_requested
        exit_code = choose_exit_code(timed_out, interrupted)

        if timed_out:
            budget = timeout or 0
            minutes, seconds = divmod(int(budget), 60)
            logging.getLogger(source_key).error("Timeout for %dm%ds", minutes, seconds)

        if (
            exit_code == EXIT_SUCCESS
            and isinstance(result, PipelineResult)
            and result.error is not None
        ):
            exit_code = EXIT_ERROR

        if upload_stats is not None:
            logger.info(
                "Streaming upload: %d uploaded, %d skipped, %d failed",
                upload_stats.uploaded,
                upload_stats.skipped,
                upload_stats.failed,
            )
            if exit_code == EXIT_SUCCESS and not upload_stats.ok:
                exit_code = EXIT_ERROR

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
    *,
    base_url_override: str | None = None,
) -> Any:
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
        base_url=base_url_override or metadata.base_url,
        proxy=proxy,
        resume=resume,
        fetch_cache=fetch_cache,
        limit=limit,
    )


def _source_metadata(registry: Any, source_key: str) -> Any:

    adapter_cls = registry._registry.get(source_key)  # noqa: SLF001
    return adapter_cls.metadata


def _build_uploader(
    config: Config,
    backend: str,
    *,
    uploader_factory: UploaderFactory | None = None,
) -> Any:
    section = config.upload_config(backend)
    if uploader_factory is not None:
        return uploader_factory(**section)
    from .uploader import get_uploader_registry

    if backend == "webdav":
        return get_uploader_registry().create(
            "webdav",
            base_url=section.get("url", ""),
            username=section.get("username", ""),
            password=section.get("password", ""),
            remote_dir=section.get("remote_dir", "MHYVD"),
        )
    return get_uploader_registry().create(
        "gdrive",
        client_secret_path=section.get("client_secret_path", ""),
        token_path=section.get("token_path", "~/.config/mhyvd/gdrive-token.json"),
        folder_name=section.get("folder_name", "MHYVD"),
    )


def _build_classifier(config: Config) -> Any:
    classifier_registry = ClassifierRegistry()
    classifier_registry.register(RuleBasedClassifier.name, RuleBasedClassifier)
    rules = _build_rules(config)
    return classifier_registry.create(config.classifier, rules=rules)


def _build_downloader(
    config: Config,
    proxy: str | None,
    resume: bool,
    timeout: float,
    *,
    should_stop: Callable[[], bool] | None = None,
    post_download: Callable[[Any], Any] | None = None,
    remote_exists: Callable[[Any], bool] | None = None,
) -> Any:
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
        timeout=timeout,
        proxy=proxy,
        resume=resume,
        bilibili_cookie=config.get("bilibili_cookie") or None,
        download_cache=download_cache,
        should_stop=should_stop,
        post_download=post_download,
        remote_exists=remote_exists,
    )


def main(
    argv: list[str] | None = None,
    *,
    pipeline_factory: PipelineFactory | None = None,
    uploader_factory: UploaderFactory | None = None,
) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except _CliParserExit as exc:
        if exc.message:
            print(exc.message, file=sys.stderr)

        return EXIT_ERROR if exc.unknown_subcommand else EXIT_SUCCESS

    if args.command == "list-sources":
        return _cmd_list_sources()
    if args.command == "run":
        return _cmd_run(
            args,
            pipeline_factory=pipeline_factory or _default_pipeline_factory,
            uploader_factory=uploader_factory,
        )
    if args.command in ("upload-webdav", "upload-gdrive"):
        return _cmd_upload(
            args.command.removeprefix("upload-"),
            args,
            uploader_factory=uploader_factory,
        )

    parser.error(f"unknown command: {args.command}")  # pragma: no cover
    return EXIT_ERROR  # pragma: no cover


if __name__ == "__main__":
    raise SystemExit(main())
