from __future__ import annotations

from .. import __version__
from .honkai_star_rail_cn import HonkaiStarRailCnAdapter
from .registry import SourceRegistry, UnknownSourceKeyError
from .release_list import ReleaseListAdapter

__all__ = [
    "__version__",
    "SourceRegistry",
    "UnknownSourceKeyError",
    "HonkaiStarRailCnAdapter",
    "ReleaseListAdapter",
    "default_registry",
    "get_source_registry",
]


default_registry = SourceRegistry()
default_registry.register(
    HonkaiStarRailCnAdapter.metadata.source_key, HonkaiStarRailCnAdapter
)
default_registry.register(ReleaseListAdapter.metadata.source_key, ReleaseListAdapter)


def get_source_registry() -> SourceRegistry:
    return default_registry
