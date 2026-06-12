from __future__ import annotations

from collections.abc import Iterator
from typing import Generic, TypeVar

T = TypeVar("T")


class RegistryKeyError(KeyError):
    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"{name!r} is not registered")


class Registry(Generic[T]):
    def __init__(self) -> None:
        self._items: dict[str, T] = {}

    def register(self, name: str, value: T) -> None:
        self._items[name] = value

    def get(self, name: str) -> T:
        try:
            return self._items[name]
        except KeyError:
            raise RegistryKeyError(name) from None

    lookup = get

    def is_registered(self, name: str) -> bool:
        return name in self._items

    contains = is_registered

    def names(self) -> list[str]:
        return list(self._items)

    def __contains__(self, name: object) -> bool:
        return name in self._items

    def __iter__(self) -> Iterator[str]:
        return iter(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}({self.names()!r})"


__all__ = [
    "Registry",
    "RegistryKeyError",
]
