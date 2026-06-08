"""Browser subsystem: the Playwright-stealth Chromium Browser_Driver."""

from __future__ import annotations

from .. import __version__
from .driver import (
    DEFAULT_MODE,
    MODE_HEADED,
    MODE_HEADLESS,
    VALID_MODES,
    BrowserDriver,
    BrowserLaunchError,
    build_launch_args,
    build_proxy_settings,
    headless_flag,
)

__all__ = [
    "__version__",
    "BrowserDriver",
    "BrowserLaunchError",
    "DEFAULT_MODE",
    "MODE_HEADED",
    "MODE_HEADLESS",
    "VALID_MODES",
    "build_launch_args",
    "build_proxy_settings",
    "headless_flag",
]
