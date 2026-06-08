"""Proxy resolution for MHYVD.

This module resolves which proxy server (if any) the browser and network
layers should use. Resolution follows a fixed precedence (Requirements 9.6,
9.7, 9.8, 14.5):

1. **Environment proxy variables** -- ``HTTPS_PROXY`` / ``HTTP_PROXY`` /
   ``ALL_PROXY`` (and their lower-case spellings).
2. **System proxy** -- the host operating system's configured proxy. On
   Windows this is read from the registry; on other platforms there is no
   system-proxy source and this step yields ``None``.
3. **No proxy** -- ``None`` when neither of the above is available.

The resolution is intentionally pure and testable: :func:`resolve_proxy`
accepts an injectable environment mapping and an injectable system-proxy
lookup, so the precedence logic can be exercised without touching the real
process environment or the Windows registry. The registry read in
:func:`resolve_system_proxy` is guarded so it skips cleanly on non-Windows
hosts and never raises.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping

# Environment variable names consulted for a proxy server, in precedence order.
# HTTPS is preferred over HTTP (matching the original behaviour), with ALL_PROXY
# as a final environment-level fallback. For each name the upper-case spelling
# is checked before the conventional lower-case spelling.
ENV_PROXY_VARS: tuple[str, ...] = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")

# Windows registry location of the per-user Internet proxy settings.
_WINREG_INTERNET_SETTINGS = (
    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
)

#: A callable that returns the system proxy server, or ``None`` when there is
#: no system proxy configured.
SystemProxyLookup = Callable[[], str | None]


def resolve_env_proxy(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the proxy server configured via environment variables, if any.

    The variables in :data:`ENV_PROXY_VARS` are consulted in order; for each,
    the upper-case spelling takes precedence over the lower-case spelling. A
    value that is empty or only whitespace is treated as *not set*. The first
    non-empty value found is returned with surrounding whitespace stripped.

    Args:
        environ: Environment mapping to read from. Defaults to ``os.environ``.

    Returns:
        The configured proxy server string, or ``None`` if none is set.
    """
    env = os.environ if environ is None else environ
    for name in ENV_PROXY_VARS:
        value = env.get(name)
        if value is None:
            value = env.get(name.lower())
        if value is not None:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


def resolve_system_proxy() -> str | None:
    """Return the operating-system proxy server, or ``None``.

    On Windows the per-user Internet Settings registry key is read: if proxy
    use is enabled and a server is configured, that server is returned (with an
    ``http://`` scheme prepended when no scheme is present). On non-Windows
    hosts -- or whenever the registry cannot be read -- ``None`` is returned.
    This function never raises.
    """
    if os.name != "nt":
        return None

    try:  # pragma: no cover - import availability depends on the platform
        import winreg
    except ImportError:  # pragma: no cover - winreg missing outside Windows
        return None

    # winreg exists only on Windows; on other platforms mypy cannot see its
    # attributes. The os.name guard above already makes this branch Windows-only.
    try:
        with winreg.OpenKey(  # type: ignore[attr-defined]
            winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
            _WINREG_INTERNET_SETTINGS,
        ) as key:
            proxy_enabled, _ = winreg.QueryValueEx(key, "ProxyEnable")  # type: ignore[attr-defined]
            if not proxy_enabled:
                return None
            proxy_server, _ = winreg.QueryValueEx(key, "ProxyServer")  # type: ignore[attr-defined]
            if not proxy_server:
                return None
            proxy_server = str(proxy_server).strip()
            if not proxy_server:
                return None
            if not proxy_server.startswith(("http://", "https://")):
                proxy_server = f"http://{proxy_server}"
            return proxy_server
    except (OSError, FileNotFoundError):  # pragma: no cover - registry errors
        return None


def resolve_proxy(
    *,
    environ: Mapping[str, str] | None = None,
    system_proxy_lookup: SystemProxyLookup | None = None,
) -> str | None:
    """Resolve the proxy server to use following the configured precedence.

    Precedence: environment proxy -> system proxy -> ``None``.

    Both inputs are injectable to keep the precedence logic pure and testable:

    Args:
        environ: Environment mapping for the environment-variable step.
            Defaults to ``os.environ``.
        system_proxy_lookup: Callable returning the system proxy server (or
            ``None``). Defaults to :func:`resolve_system_proxy`.

    Returns:
        The environment proxy when present; otherwise the system proxy when
        present; otherwise ``None``.
    """
    env_proxy = resolve_env_proxy(environ)
    if env_proxy is not None:
        return env_proxy

    lookup = (
        resolve_system_proxy if system_proxy_lookup is None else system_proxy_lookup
    )
    system_proxy = lookup()
    if system_proxy:
        return system_proxy

    return None
