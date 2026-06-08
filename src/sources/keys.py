"""Source_Key composition and parsing helpers.

A ``Source_Key`` uniquely identifies a :class:`SourceAdapter` and is formed
from a Game key and a Region key as ``"{game}/{region}"`` (for example
``"honkai-star-rail/cn"``). :func:`make_source_key` and
:func:`parse_source_key` are a round-trip pair: parsing a composed key always
yields back the original ``(game, region)`` pair.
"""

from __future__ import annotations

# The single separator between the game key and the region key in a Source_Key.
SOURCE_KEY_SEPARATOR = "/"


def make_source_key(game: str, region: str) -> str:
    """Compose a Source_Key from a game key and a region key.

    Returns ``f"{game}/{region}"``.
    """
    return f"{game}{SOURCE_KEY_SEPARATOR}{region}"


def parse_source_key(key: str) -> tuple[str, str]:
    """Parse a Source_Key into its ``(game, region)`` components.

    This is the inverse of :func:`make_source_key`. The key is split on the
    first separator so that game keys never contain the separator while region
    keys are returned verbatim.

    Raises:
        ValueError: If ``key`` does not contain the Source_Key separator.
    """
    if SOURCE_KEY_SEPARATOR not in key:
        raise ValueError(
            f"Invalid source key {key!r}: expected format "
            f"'{{game}}{SOURCE_KEY_SEPARATOR}{{region}}'"
        )
    game, region = key.split(SOURCE_KEY_SEPARATOR, 1)
    return game, region
