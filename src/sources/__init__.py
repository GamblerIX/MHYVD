"""Source subsystem: the Source_Adapter contract, registry, and adapters.

Importing this package builds the :data:`default_registry` and registers every
built-in Source_Adapter on it, so callers obtain a fully-populated registry
through :func:`get_source_registry` without having to know which adapters
exist. New games/regions are added by registering additional adapters here
(Requirement 1.7).
"""

from __future__ import annotations

from .. import __version__
from .honkai_star_rail_cn import HonkaiStarRailCnAdapter
from .registry import SourceRegistry, UnknownSourceKeyError

__all__ = [
    "__version__",
    "SourceRegistry",
    "UnknownSourceKeyError",
    "HonkaiStarRailCnAdapter",
    "default_registry",
    "get_source_registry",
]

#: Process-wide registry pre-populated with the built-in adapters.
default_registry = SourceRegistry()
default_registry.register(
    HonkaiStarRailCnAdapter.metadata.source_key, HonkaiStarRailCnAdapter
)


def get_source_registry() -> SourceRegistry:
    """Return the process-wide registry populated with built-in adapters."""
    return default_registry
