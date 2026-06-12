from __future__ import annotations

from ..registry import Registry, RegistryKeyError
from .base import Classifier

__all__ = ["ClassifierRegistry", "UnknownClassifierError"]


class UnknownClassifierError(RegistryKeyError):
    pass


class ClassifierRegistry:
    def __init__(self) -> None:
        self._registry: Registry[type[Classifier]] = Registry()

    def register(self, name: str, cls: type[Classifier]) -> None:
        self._registry.register(name, cls)

    def create(self, name: str, **kwargs: object) -> Classifier:
        if not self._registry.is_registered(name):
            raise UnknownClassifierError(name)
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
