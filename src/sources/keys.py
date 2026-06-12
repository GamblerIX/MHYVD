from __future__ import annotations

SOURCE_KEY_SEPARATOR = "/"


def make_source_key(game: str, region: str) -> str:
    return f"{game}{SOURCE_KEY_SEPARATOR}{region}"


def parse_source_key(key: str) -> tuple[str, str]:
    if SOURCE_KEY_SEPARATOR not in key:
        raise ValueError(
            f"Invalid source key {key!r}: expected format "
            f"'{{game}}{SOURCE_KEY_SEPARATOR}{{region}}'"
        )
    game, region = key.split(SOURCE_KEY_SEPARATOR, 1)
    return game, region
