from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from playwright.async_api import ProxySettings

logger = logging.getLogger("browser.driver")


MODE_HEADLESS = "headless"
MODE_HEADED = "headed"
VALID_MODES = (MODE_HEADLESS, MODE_HEADED)


DEFAULT_MODE = MODE_HEADED


DEFAULT_LAUNCH_ARGS: tuple[str, ...] = (
    "--disable-blink-features=AutomationControlled",
)


DEFAULT_TIMEOUT = 30.0


PlaywrightFactory = Callable[[], Any]


StealthApplicator = Callable[[Any], Awaitable[None]]


class BrowserLaunchError(RuntimeError):
    pass


def headless_flag(mode: str) -> bool:
    if mode not in VALID_MODES:
        raise ValueError(
            f"Unknown browser mode {mode!r}; expected one of {VALID_MODES}"
        )
    return mode == MODE_HEADLESS


def build_launch_args() -> list[str]:
    return list(DEFAULT_LAUNCH_ARGS)


def build_proxy_settings(proxy: str | None) -> ProxySettings | None:
    if not proxy:
        return None
    return {"server": proxy}  # type: ignore[return-value]


def _default_playwright_factory() -> Any:
    from playwright.async_api import async_playwright  # noqa: WPS433

    return async_playwright()


async def _default_apply_stealth(page: Any) -> None:
    try:
        from playwright_stealth import Stealth  # noqa: WPS433
    except ImportError:
        Stealth = None  # type: ignore[assignment]

    if Stealth is not None:
        await Stealth().apply_stealth_async(page)
        return

    from playwright_stealth import stealth_async  # noqa: WPS433

    await stealth_async(page)


class BrowserDriver:
    def __init__(
        self,
        mode: str = DEFAULT_MODE,
        proxy: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
        *,
        playwright_factory: PlaywrightFactory | None = None,
        stealth: StealthApplicator | None = None,
    ) -> None:
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
        return headless_flag(self.mode)

    @property
    def page(self) -> Any:
        return self._page

    async def launch(self) -> Any:
        headless = self.headless
        proxy_settings = build_proxy_settings(self.proxy)

        self._playwright = await self._playwright_factory().start()

        try:
            self._browser = await self._playwright.chromium.launch(
                headless=headless,
                args=build_launch_args(),
            )
            self._context = await self._browser.new_context(proxy=proxy_settings)
            self._page = await self._context.new_page()
            await self._stealth(self._page)
        except Exception as exc:  # noqa: BLE001
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
        if resource is None:
            return
        await self._stop_one(resource.close, name)

    async def _stop_one(self, closer: Callable[[], Awaitable[None]], name: str) -> None:
        try:
            await asyncio.wait_for(closer(), timeout=self.timeout)
        except TimeoutError:
            logger.warning("Timed out closing %s after %ss", name, self.timeout)
        except Exception as exc:  # noqa: BLE001
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
