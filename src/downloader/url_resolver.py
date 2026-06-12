from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urlparse

__all__ = [
    "MEDIA_EXTENSIONS",
    "MEDIA_URL_RE",
    "normalize_media_url",
    "dedupe_media_urls",
]


MEDIA_EXTENSIONS: tuple[str, ...] = (
    ".mp4",
    ".mkv",
    ".flv",
    ".mov",
    ".webm",
    ".m4v",
)


MEDIA_URL_RE = re.compile(
    r"https?://[^\"'<>\s]+?\.(?:mp4|mkv|flv|mov|webm|m4v)(?:\?[^\"'<>\s]*)?",
    re.IGNORECASE,
)


def normalize_media_url(candidate: str) -> str | None:
    if not isinstance(candidate, str):
        return None

    value = candidate.strip()
    if not value:
        return None

    if value.startswith("//"):
        value = f"https:{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None

    suffix = PurePosixPath(parsed.path).suffix.lower()
    if suffix not in MEDIA_EXTENSIONS:
        return None

    query_values = parse_qs(parsed.query)
    oss_process = "".join(query_values.get("x-oss-process", []))
    if "snapshot" in oss_process.lower():
        return None

    return value


def dedupe_media_urls(candidates: list[str]) -> list[str]:
    unique_urls: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        url = normalize_media_url(candidate)
        if url is None or url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)

    return unique_urls
