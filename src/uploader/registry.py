from __future__ import annotations

from typing import Any

from ..registry import Registry, RegistryKeyError

__all__ = ["UploaderRegistry", "UnknownUploaderError"]


class UnknownUploaderError(RegistryKeyError):
    pass


class UploaderRegistry:
    def __init__(self) -> None:
        self._registry: Registry[type[Any]] = Registry()

    def register(self, name: str, cls: type[Any]) -> None:
        self._registry.register(name, cls)

    def create(self, name: str, **kwargs: object) -> Any:
        if not self._registry.is_registered(name):
            raise UnknownUploaderError(name)
        cls = self._registry.get(name)
        return cls(**kwargs)

    def is_registered(self, name: str) -> bool:
        return self._registry.is_registered(name)

    def names(self) -> list[str]:
        return self._registry.names()

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)
