"""The ``ClassifierRegistry``: a name -> Classifier class registry.

Builds on the generic :class:`src.registry.Registry` helper (Requirement 13.5)
to map a classifier name (for example ``rule_based``) to its
:class:`~src.classifier.base.Classifier` subclass and construct instances on
demand. Lookup checks registration first and raises an error naming the
requested classifier before attempting any construction.
"""

from __future__ import annotations

from ..registry import Registry, RegistryKeyError
from .base import Classifier

__all__ = ["ClassifierRegistry", "UnknownClassifierError"]


class UnknownClassifierError(RegistryKeyError):
    """Raised when an unregistered classifier name is requested.

    Subclasses :class:`~src.registry.RegistryKeyError` (itself a ``KeyError``)
    and always names the requested classifier in its message.
    """


class ClassifierRegistry:
    """Maps a classifier name to its :class:`Classifier` class."""

    def __init__(self) -> None:
        self._registry: Registry[type[Classifier]] = Registry()

    def register(self, name: str, cls: type[Classifier]) -> None:
        """Register classifier ``cls`` under ``name``.

        Re-registering an existing name overwrites the previous class, letting
        callers replace a default implementation with a custom one.
        """
        self._registry.register(name, cls)

    def create(self, name: str, **kwargs: object) -> Classifier:
        """Construct the classifier registered under ``name``.

        Checks registration first and raises :class:`UnknownClassifierError`
        naming ``name`` before attempting construction when nothing is
        registered under it. Any keyword arguments are forwarded to the
        classifier constructor.
        """
        if not self._registry.is_registered(name):
            raise UnknownClassifierError(name)
        cls = self._registry.get(name)
        return cls(**kwargs)

    def is_registered(self, name: str) -> bool:
        """Return whether a classifier is registered under ``name``."""
        return self._registry.is_registered(name)

    def names(self) -> list[str]:
        """Return all registered classifier names in registration order."""
        return self._registry.names()

    def __contains__(self, name: object) -> bool:
        return name in self._registry

    def __len__(self) -> int:
        return len(self._registry)
