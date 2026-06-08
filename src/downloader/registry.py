"""The ``DownloaderRegistry``: a name -> Downloader class registry.

Builds on the generic :class:`src.registry.Registry` helper (Requirement 13.5)
to map a downloader name (for example ``playwright``) to its
:class:`~src.downloader.base.Downloader` subclass and construct instances on
demand. Lookup checks registration first and raises an error naming the
requested downloader before attempting any construction, mirroring the
Source_Registry and Classifier_Registry behaviour.
"""

from __future__ import annotations

from ..registry import Registry, RegistryKeyError
from .base import Downloader

__all__ = ["DownloaderRegistry", "UnknownDownloaderError"]


class UnknownDownloaderError(RegistryKeyError):
    """Raised when an unregistered downloader name is requested.

    Subclasses :class:`~src.registry.RegistryKeyError` (itself a ``KeyError``)
    and always names the requested downloader in its message.
    """


class DownloaderRegistry:
    """Maps a downloader name to its :class:`Downloader` class."""

    def __init__(self) -> None:
        self._registry: Registry[type[Downloader]] = Registry()

    def register(self, name: str, cls: type[Downloader]) -> None:
        """Register downloader ``cls`` under ``name``.

        Re-registering an existing name overwrites the previous class, letting
        callers replace a default implementation with a custom one.
        """
        self._registry.register(name, cls)

    def create(self, name: str, **kwargs: object) -> Downloader:
        """Construct the downloader registered under ``name``.

        Checks registration first and raises :class:`UnknownDownloaderError`
        naming ``name`` before attempting construction when nothing is
        registered under it. Any keyword arguments are forwarded to the
        downloader constructor.
        """
        if not self._registry.is_registered(name):
            raise UnknownDownloaderError(name)
        cls = self._registry.get(name)
        return cls(**kwargs)

    def is_registered(self, name: str) -> bool:
        """Return whether a downloader is registered under ``name``."""
        return self._registry.is_registered(name)

    def names(self) -> list[str]:
        """Return all registered downloader names in registration order."""
        return self._registry.names()

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)
