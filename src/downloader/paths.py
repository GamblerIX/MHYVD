from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

from .url_resolver import MEDIA_EXTENSIONS

FALLBACK_FILENAME = "untitled"


DEFAULT_MEDIA_EXTENSION = ".mp4"


FALLBACK_CATEGORY = "uncategorized"


_CATEGORY_SEPARATOR_RE = re.compile(r"[/\\]+")


INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]+')


NEWS_ID_RE = re.compile(r"/news/(\d+)")


_WHITESPACE_RE = re.compile(r"\s+")

__all__ = [
    "FALLBACK_FILENAME",
    "FALLBACK_CATEGORY",
    "DEFAULT_MEDIA_EXTENSION",
    "sanitize_filename",
    "sanitize_category",
    "extract_news_id",
    "media_extension_for_url",
    "build_output_path",
]


def sanitize_category(category: str) -> str:
    segments = []
    for segment in _CATEGORY_SEPARATOR_RE.split(category):
        segment = segment.strip()
        if not segment or not segment.strip("."):
            continue
        segments.append(segment)
    return "/".join(segments) or FALLBACK_CATEGORY


def sanitize_filename(title: str) -> str:
    normalized = unicodedata.normalize("NFKC", title)

    cleaned = "".join(
        char for char in normalized if not unicodedata.category(char).startswith("C")
    )

    sanitized = INVALID_FILENAME_CHARS_RE.sub(" ", cleaned)
    sanitized = _WHITESPACE_RE.sub(" ", sanitized).strip(" .")

    return sanitized or FALLBACK_FILENAME


def extract_news_id(url: str) -> str:
    match = NEWS_ID_RE.search(url)
    if match:
        return match.group(1)
    return "unknown"


def media_extension_for_url(video_url: str | None) -> str:
    if not video_url:
        return DEFAULT_MEDIA_EXTENSION
    suffix = PurePosixPath(urlparse(video_url).path).suffix.lower()
    if suffix in MEDIA_EXTENSIONS:
        return suffix
    return DEFAULT_MEDIA_EXTENSION


def build_output_path(
    output_dir: str | Path,
    category: str,
    title: str,
    news_id: str,
    video_url: str | None = None,
) -> Path:
    safe_category = sanitize_category(category)
    safe_name = sanitize_filename(title)
    extension = media_extension_for_url(video_url)
    filename = f"{safe_name} [{news_id}]{extension}"
    return Path(output_dir) / safe_category / filename
