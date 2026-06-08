"""Source_Registry: maps Source_Keys to Source_Adapter classes (Requirement 1).

The :class:`SourceRegistry` is the registry that maps a Source_Key (for
example ``"honkai-star-rail/cn"``) to the :class:`SourceAdapter` subclass
registered under it and constructs adapter instances on demand
(Requirements 1.2, 1.3, 1.5, 1.8). It builds on the generic
:class:`~src.registry.Registry` helper so the registration, listing, and
membership logic lives in one place (Requirement 13.5), layering on the
adapter-construction policy and the Source_Key-aware error type.

The central guarantee (Property 1 / Requirement 1.4) is that
:meth:`SourceRegistry.create` checks registration *first* and raises
:class:`UnknownSourceKeyError` -- naming the requested Source_Key -- before it
ever attempts to construct an adapter. A miss therefore never partially builds
or imports anything.
"""

from __future__ import annotations

from typing import Any

from ..registry import Registry, RegistryKeyError
from .base import SourceAdapter

__all__ = ["SourceRegistry", "UnknownSourceKeyError"]


class UnknownSourceKeyError(RegistryKeyError):
    """Raised when an unregistered Source_Key is requested.

    Subclasses :class:`~src.registry.RegistryKeyError` (and therefore
    ``KeyError``) so existing handlers keep working, while giving callers a
    Source_Key-specific type to catch. The message and the
    :attr:`~src.registry.RegistryKeyError.name` attribute always carry the
    requested Source_Key so it can be surfaced to the user (Requirement 1.4).
    """

    def __init__(self, source_key: str) -> None:
        self.source_key = source_key
        super().__init__(source_key)


class SourceRegistry:
    """Registry of Source_Keys to :class:`SourceAdapter` classes.

    Examples
    --------
    >>> registry = SourceRegistry()
    >>> registry.register("honkai-star-rail/cn", HonkaiStarRailCnAdapter)
    >>> registry.is_registered("honkai-star-rail/cn")
    True
    >>> registry.list_keys()
    ['honkai-star-rail/cn']
    >>> adapter = registry.create(
    ...     "honkai-star-rail/cn", base_url="https://sr.mihoyo.com"
    ... )
    >>> isinstance(adapter, HonkaiStarRailCnAdapter)
    True
    """

    def __init__(self) -> None:
        # The generic helper stores the Source_Key -> adapter-class mapping and
        # answers listing/membership questions (Requirement 13.5).
        self._registry: Registry[type[SourceAdapter]] = Registry()

    def register(self, source_key: str, cls: type[SourceAdapter]) -> None:
        """Register adapter ``cls`` under ``source_key`` (Requirement 1.2).

        Re-registering an existing Source_Key overwrites the previous adapter,
        which lets a custom adapter replace a built-in one.
        """
        self._registry.register(source_key, cls)

    def is_registered(self, source_key: str) -> bool:
        """Return whether an adapter is registered under ``source_key``."""
        return self._registry.is_registered(source_key)

    def list_keys(self) -> list[str]:
        """Return all registered Source_Keys in registration order (Req 1.5)."""
        return self._registry.names()

    def create(self, source_key: str, **kwargs: Any) -> SourceAdapter:
        """Construct the adapter registered under ``source_key``.

        Registration is checked **first**: if ``source_key`` is not registered,
        :class:`UnknownSourceKeyError` is raised naming the key *before* any
        adapter construction is attempted (Requirement 1.4). On a hit, the
        registered class is instantiated with ``**kwargs`` and returned
        (Requirement 1.3).
        """
        if not self._registry.is_registered(source_key):
            raise UnknownSourceKeyError(source_key)
        cls = self._registry.get(source_key)
        return cls(**kwargs)
