"""Generic name->class registry helper.

A small, reusable registry that maps string names to classes. The concrete
registries in the codebase (``SourceRegistry``, ``ClassifierRegistry``,
``DownloaderRegistry``) build on top of this helper so the registration,
lookup, listing, and membership-check logic lives in one single-responsibility
place (Requirement 13.5).

The helper is intentionally minimal and pure: it stores registrations and
answers questions about them. Construction policy (extra error types, factory
keyword arguments, and so on) is layered on by the specific registries.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Generic, TypeVar

#: The type of value stored under each name. Defaults to ``type`` so the common
#: name->class use case keeps full typing, but any value can be registered.
T = TypeVar("T")


class RegistryKeyError(KeyError):
    """Raised when a name is requested that is not present in a registry.

    Subclasses ``KeyError`` so existing ``except KeyError`` handlers keep
    working. The message always names the missing key so callers (and the
    specific registries that wrap this helper) can surface it to users.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} is not registered")


class Registry(Generic[T]):
    """A generic mapping of names to registered values (typically classes).

    Examples
    --------
    >>> registry: Registry[type] = Registry()
    >>> registry.register("a", int)
    >>> registry.get("a") is int
    True
    >>> "a" in registry
    True
    >>> registry.names()
    ['a']
    """

    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, name: str, value: T) -> None:
        """Register ``value`` under ``name``.

        Re-registering an existing name overwrites the previous value, which
        lets callers replace a default implementation with a custom one.
        """
        self._items[name] = value

    def get(self, name: str) -> T:
        """Return the value registered under ``name``.

        Raises ``RegistryKeyError`` (a ``KeyError`` subclass) naming the key
        when nothing is registered under ``name``.
        """
        try:
            return self._items[name]
        except KeyError:
            raise RegistryKeyError(name) from None

    #: ``lookup`` is an alias for :meth:`get` for call sites that prefer the
    #: more descriptive verb.
    lookup = get

    def is_registered(self, name: str) -> bool:
        """Return whether something is registered under ``name``."""
        return name in self._items

    #: ``contains`` is an alias for :meth:`is_registered`.
    contains = is_registered

    def names(self) -> list[str]:
        """Return the list of all registered names in registration order."""
        return list(self._items)

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"{type(self).__name__}({self.names()!r})"


__all__ = [
    "Registry",
    "RegistryKeyError",
]
