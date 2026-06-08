"""Pure helpers for media URL normalization and deduplication.

These functions isolate the media-URL logic from any browser or network I/O so
that it can be exercised directly by tests. The behavior is ported from the
legacy ``bak/plugins/downloader/playwright.py`` downloader:

- ``normalize_media_url`` trims whitespace, fixes protocol-relative ``//`` URLs
  to ``https``, requires an ``http``/``https`` scheme together with a
  ``.mp4``/``.mkv``/``.flv`` extension, and rejects OSS ``snapshot`` thumbnail
  URLs (those whose ``x-oss-process`` query parameter requests a snapshot).
- ``dedupe_media_urls`` performs an order-preserving deduplication over the
  normalized candidates, dropping any candidate that does not normalize to a
  valid media URL.
"""

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

#: Recognized media file extensions (lower case, including the leading dot).
MEDIA_EXTENSIONS: tuple[str, ...] = (".mp4", ".mkv", ".flv")

#: Regex used elsewhere to scrape candidate media URLs out of raw page HTML.
MEDIA_URL_RE = re.compile(
    r"https?://[^\"'<>\s]+?\.(?:mp4|mkv|flv)(?:\?[^\"'<>\s]*)?",
    re.IGNORECASE,
)


def normalize_media_url(candidate: str) -> str | None:
    """Normalize a single candidate media URL.

    Args:
        candidate: A raw URL string gathered from a DOM element, page HTML, or a
            captured network response. May contain surrounding whitespace or use
            a protocol-relative ``//`` scheme.

    Returns:
        The normalized URL when the candidate is a valid media URL, otherwise
        ``None``. A candidate is valid only when, after trimming and fixing a
        protocol-relative scheme, it uses an ``http`` or ``https`` scheme, its
        path ends with one of :data:`MEDIA_EXTENSIONS`, and it is not an OSS
        ``snapshot`` thumbnail.
    """
    if not isinstance(candidate, str):
        return None

    value = candidate.strip()
    if not value:
        return None

    # Fix protocol-relative URLs (e.g. ``//host/path.mp4``) to https.
    if value.startswith("//"):
        value = f"https:{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"}:
        return None

    # The path must end with a recognized media extension.
    suffix = PurePosixPath(parsed.path).suffix.lower()
    if suffix not in MEDIA_EXTENSIONS:
        return None

    # Reject OSS snapshot thumbnails: these encode a snapshot directive in the
    # ``x-oss-process`` query parameter and are not the full media file.
    query_values = parse_qs(parsed.query)
    oss_process = "".join(query_values.get("x-oss-process", []))
    if "snapshot" in oss_process.lower():
        return None

    return value


def dedupe_media_urls(candidates: list[str]) -> list[str]:
    """Order-preserving deduplication of normalized media URLs.

    Args:
        candidates: Raw candidate URLs gathered from DOM elements, page HTML, and
            captured network responses, in priority order.

    Returns:
        The list of normalized media URLs in first-seen order, with duplicates
        and any candidate that fails :func:`normalize_media_url` dropped.
    """
    unique_urls: list[str] = []
    seen: set[str] = set()

    for candidate in candidates:
        url = normalize_media_url(candidate)
        if url is None or url in seen:
            continue
        seen.add(url)
        unique_urls.append(url)

    return unique_urls
