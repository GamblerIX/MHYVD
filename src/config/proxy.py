from __future__ import annotations

import os
from collections.abc import Callable, Mapping

ENV_PROXY_VARS: tuple[str, ...] = ("HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY")


_WINREG_INTERNET_SETTINGS = (
    r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
)


SystemProxyLookup = Callable[[], str | None]


def resolve_env_proxy(environ: Mapping[str, str] | None = None) -> str | None:
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
    if os.name != "nt":
        return None

    try:  # pragma: no cover
        import winreg
    except ImportError:  # pragma: no cover
        return None

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
    except (OSError, FileNotFoundError):  # pragma: no cover
        return None


def resolve_proxy(
    *,
    environ: Mapping[str, str] | None = None,
    system_proxy_lookup: SystemProxyLookup | None = None,
) -> str | None:
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
