"""Playwright-stealth Chromium ``Browser_Driver``.

This module owns browser automation for MHYVD (Requirement 3). The
:class:`BrowserDriver` launches Chromium through Playwright with
**playwright-stealth** applied in *both* Headless_Mode and Headed_Mode, routes
traffic through an optional proxy, and tears the session down deterministically
(page -> context -> browser) with each close bounded by a configured timeout.

Design notes
------------
* **Lazy Playwright import.** Playwright (and playwright-stealth) are imported
  only when a browser is actually launched. Importing this module therefore
  never requires those packages to be installed, which keeps the bulk of the
  codebase -- and this module's unit tests -- runnable without a real browser.
* **Dependency injection for testing.** The Playwright entrypoint and the
  stealth applicator are injectable through the constructor
  (``playwright_factory`` / ``stealth``). Tests substitute lightweight fakes to
  exercise the mode->launch-args mapping, proxy-settings construction, and the
  bounded-timeout cleanup logic without launching Chromium.
* **No silent fallback.** The driver itself never downgrades a requested mode.
  When a launch fails it raises :class:`BrowserLaunchError`; when Headed_Mode
  specifically cannot launch, the error makes clear that the driver did not
  fall back to Headless_Mode (Requirement 3.5). The headless->headed *fallback*
  policy lives in the pipeline layer, not here.

Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from playwright.async_api import ProxySettings

logger = logging.getLogger("browser.driver")

# --- Browser launch modes (Requirement 3.2/3.3) ---
MODE_HEADLESS = "headless"
MODE_HEADED = "headed"
VALID_MODES = (MODE_HEADLESS, MODE_HEADED)

#: Default mode when none is specified (Requirement 3.2: headless is primary).
DEFAULT_MODE = MODE_HEADLESS

#: Chromium launch args applied in both modes. Reduces automated-browser
#: detection in concert with playwright-stealth (ported from the original code).
DEFAULT_LAUNCH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
)

#: Default per-close timeout (seconds) used when the caller does not specify one.
DEFAULT_TIMEOUT = 30.0


# A zero-arg callable returning a Playwright context-manager object (the value
# returned by ``playwright.async_api.async_playwright()``), which exposes an
# async ``start()`` -> playwright and the started playwright exposes ``stop()``.
PlaywrightFactory = Callable[[], Any]

# An async callable that applies stealth to a freshly created page.
StealthApplicator = Callable[[Any], Awaitable[None]]


class BrowserLaunchError(RuntimeError):
    """Raised when the browser cannot be launched in the requested mode.

    For Headed_Mode this signals that the driver did **not** fall back to
    Headless_Mode (Requirement 3.5); the caller decides what to do next.
    """


def headless_flag(mode: str) -> bool:
    """Map a browser ``mode`` to Playwright's ``headless`` launch flag.

    Args:
        mode: Either :data:`MODE_HEADLESS` or :data:`MODE_HEADED`.

    Returns:
        ``True`` for Headless_Mode, ``False`` for Headed_Mode.

    Raises:
        ValueError: If ``mode`` is not a recognised mode.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown browser mode {mode!r}; expected one of {VALID_MODES}"
        )
    return mode == MODE_HEADLESS


def build_launch_args() -> list[str]:
    """Return the Chromium launch arguments applied in both modes."""
    return list(DEFAULT_LAUNCH_ARGS)


def build_proxy_settings(proxy: str | None) -> ProxySettings | None:
    """Build Playwright ``ProxySettings`` for the configured proxy.

    Playwright's ``ProxySettings`` is a ``TypedDict``; at runtime a plain
    mapping with a ``server`` key is the correct, equivalent value to pass to
    ``new_context(proxy=...)`` (Requirement 3.6).

    Args:
        proxy: The proxy server address, or ``None``/empty for no proxy.

    Returns:
        A ``{"server": proxy}`` mapping when a proxy is configured, else
        ``None`` (no proxy routing).
    """
    if not proxy:
        return None
    return {"server": proxy}  # type: ignore[return-value]


def _default_playwright_factory() -> Any:
    """Return the Playwright async entrypoint context-manager object.

    Imported lazily so this module can be imported without Playwright
    installed.
    """
    from playwright.async_api import async_playwright  # noqa: WPS433 (lazy)

    return async_playwright()


async def _default_apply_stealth(page: Any) -> None:
    """Apply playwright-stealth to ``page``, tolerating API differences.

    playwright-stealth has shipped a few different surface APIs. This tries the
    modern ``Stealth`` class first and falls back to the legacy
    ``stealth_async`` function. Imported lazily.
    """
    try:  # Modern API (playwright-stealth >= 2.x): Stealth().apply_stealth_async
        from playwright_stealth import Stealth  # noqa: WPS433 (lazy)
    except ImportError:
        Stealth = None  # type: ignore[assignment]

    if Stealth is not None:
        await Stealth().apply_stealth_async(page)
        return

    # Legacy API (playwright-stealth 1.x): stealth_async(page)
    from playwright_stealth import stealth_async  # noqa: WPS433 (lazy)

    await stealth_async(page)


class BrowserDriver:
    """Launch and manage a Playwright-stealth Chromium browser session.

    Construct with a ``mode`` (defaulting to Headless_Mode), an optional
    ``proxy`` server, and a per-close ``timeout``. Call :meth:`launch` to open
    browser -> context -> page (with stealth applied), then :meth:`aclose` to
    tear the session down. The instance is also an async context manager.
    """

    def __init__(
        self,
        mode: str = DEFAULT_MODE,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        playwright_factory: PlaywrightFactory | None = None,
        stealth: StealthApplicator | None = None,
    ) -> None:
        """Initialise the driver.

        Args:
            mode: :data:`MODE_HEADLESS` (default) or :data:`MODE_HEADED`.
            proxy: Optional proxy server address; routed via ``ProxySettings``.
            timeout: Per-close timeout in seconds for :meth:`aclose`.
            playwright_factory: Override the Playwright entrypoint (testing).
            stealth: Override the stealth applicator (testing).

        Raises:
            ValueError: If ``mode`` is not a recognised mode.
        """
        if mode not in VALID_MODES:
            raise ValueError(
                f"Unknown browser mode {mode!r}; expected one of {VALID_MODES}"
            )
        self.mode = mode
        self.proxy = proxy
        self.timeout = timeout
        self._playwright_factory = playwright_factory or _default_playwright_factory
        self._stealth = stealth or _default_apply_stealth

        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None

    @property
    def headless(self) -> bool:
        """Whether this driver launches in Headless_Mode."""
        return headless_flag(self.mode)

    @property
    def page(self) -> Any:
        """The current page, or ``None`` when no session is active."""
        return self._page

    async def launch(self) -> Any:
        """Launch Chromium and open a stealth-enabled page.

        Opens browser -> context (with proxy when configured) -> page, then
        applies playwright-stealth (Requirement 3.1). Headless_Mode is the
        default (Requirement 3.2); Headed_Mode opens a visible window
        (Requirement 3.3).

        Returns:
            The opened page object.

        Raises:
            BrowserLaunchError: If the browser cannot be launched. For
                Headed_Mode this explicitly indicates no fallback to
                Headless_Mode occurred (Requirement 3.5).
        """
        headless = self.headless
        proxy_settings = build_proxy_settings(self.proxy)

        # Start Playwright first so a launch failure can be reported cleanly.
        self._playwright = await self._playwright_factory().start()

        try:
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=build_launch_args(),
            )
            self._context = await self._browser.new_context(proxy=proxy_settings)
            self._page = await self._context.new_page()
            await self._stealth(self._page)
        except Exception as exc:  # noqa: BLE001 - normalise into a clear error
            # Tear down any partially-created resources, then surface the
            # failure. The driver never silently falls back (Requirement 3.5).
            await self.aclose()
            if not headless:
                raise BrowserLaunchError(
                    "Failed to launch Chromium in headed mode; not falling back "
                    f"to headless mode: {exc}"
                ) from exc
            raise BrowserLaunchError(
                f"Failed to launch Chromium in headless mode: {exc}"
            ) from exc

        logger.info(
            "Launched Chromium (mode=%s, proxy=%s)",
            self.mode,
            self.proxy or "none",
        )
        return self._page

    async def aclose(self) -> None:
        """Close the session: page -> context -> browser, each time-bounded.

        Each close is wrapped in :func:`asyncio.wait_for` with the configured
        timeout so a hung resource cannot block shutdown (Requirement 3.7).
        Failures and timeouts are logged but never raised, and every resource
        is attempted regardless of earlier failures. Playwright itself is then
        stopped (also time-bounded).
        """
        await self._close_one(self._page, "page")
        self._page = None
        await self._close_one(self._context, "context")
        self._context = None
        await self._close_one(self._browser, "browser")
        self._browser = None

        if self._playwright is not None:
            await self._stop_one(self._playwright.stop, "playwright")
            self._playwright = None

    async def _close_one(self, resource: Any, name: str) -> None:
        """Close ``resource`` under the configured timeout, never raising."""
        if resource is None:
            return
        await self._stop_one(resource.close, name)

    async def _stop_one(self, closer: Callable[[], Awaitable[None]], name: str) -> None:
        """Await ``closer()`` bounded by ``self.timeout``; swallow failures."""
        try:
            await asyncio.wait_for(closer(), timeout=self.timeout)
        except TimeoutError:
            logger.warning("Timed out closing %s after %ss", name, self.timeout)
        except Exception as exc:  # noqa: BLE001 - cleanup must not raise
            logger.debug("Error closing %s: %s", name, exc)

    async def __aenter__(self) -> BrowserDriver:
        await self.launch()
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        await self.aclose()


__all__ = [
    "BrowserDriver",
    "BrowserLaunchError",
    "MODE_HEADLESS",
    "MODE_HEADED",
    "VALID_MODES",
    "DEFAULT_MODE",
    "DEFAULT_TIMEOUT",
    "DEFAULT_LAUNCH_ARGS",
    "headless_flag",
    "build_launch_args",
    "build_proxy_settings",
]
