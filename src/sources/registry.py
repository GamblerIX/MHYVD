from __future__ import annotations

from typing import Any

from ..registry import Registry, RegistryKeyError
from .base import SourceAdapter

__all__ = ["SourceRegistry", "UnknownSourceKeyError"]


class UnknownSourceKeyError(RegistryKeyError):
    def __init__(self, source_key: str) -> None:
        self.source_key = source_key
        super().__init__(source_key)


class SourceRegistry:
    def __init__(self) -> None:

        self._registry: Registry[type[SourceAdapter]] = Registry()

    def register(self, source_key: str, cls: type[SourceAdapter]) -> None:
        self._registry.register(source_key, cls)

    def is_registered(self, source_key: str) -> bool:
        return self._registry.is_registered(source_key)

    def list_keys(self) -> list[str]:
        return self._registry.names()

    def create(self, source_key: str, **kwargs: Any) -> SourceAdapter:
        if not self._registry.is_registered(source_key):
            raise UnknownSourceKeyError(source_key)
        cls = self._registry.get(source_key)
        return cls(**kwargs)
