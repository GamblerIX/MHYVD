"""Pure filename and output-path helpers for the Download_Stage.

These functions contain no I/O so they can be exercised exhaustively with
property-based tests (see Property 15 in the design document):

- :func:`sanitize_filename` turns an arbitrary article title into a string that
  is safe to use as a filename component.
- :func:`extract_news_id` pulls the numeric news identifier out of an article
  URL, falling back to ``"unknown"``.
- :func:`build_output_path` composes the final download target path from the
  output directory, category, sanitized title, and news id.

The logic is ported from the legacy ``bak/plugins/downloader/playwright.py``
implementation.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

#: Filename fallback used when sanitisation removes every usable character.
FALLBACK_FILENAME = "untitled"

#: Characters that are illegal in filenames on common filesystems (Windows is
#: the strictest, so we target its reserved set).
INVALID_FILENAME_CHARS_RE = re.compile(r'[<>:"/\\|?*]+')

#: Matches the numeric news id within an article URL, e.g. ``/news/12345``.
NEWS_ID_RE = re.compile(r"/news/(\d+)")

#: Collapses any run of whitespace into a single space.
_WHITESPACE_RE = re.compile(r"\s+")

__all__ = [
    "FALLBACK_FILENAME",
    "sanitize_filename",
    "extract_news_id",
    "build_output_path",
]


def sanitize_filename(title: str) -> str:
    """Return a filesystem-safe filename component derived from ``title``.

    The transformation, in order:

    1. NFKC-normalise the input so compatibility characters fold to canonical
       forms.
    2. Strip Unicode "control" characters (category beginning with ``C``),
       which covers control codes, format characters, surrogates, etc.
    3. Replace any run of the invalid characters ``<>:"/\\|?*`` with a single
       space.
    4. Collapse runs of whitespace to a single space and trim surrounding
       spaces and dots.
    5. Fall back to :data:`FALLBACK_FILENAME` (``"untitled"``) when the result
       is empty.

    The returned value never contains any of the invalid filename characters
    and is never empty.
    """
    normalized = unicodedata.normalize("NFKC", title)

    cleaned = "".join(
        char for char in normalized if not unicodedata.category(char).startswith("C")
    )

    sanitized = INVALID_FILENAME_CHARS_RE.sub(" ", cleaned)
    sanitized = _WHITESPACE_RE.sub(" ", sanitized).strip(" .")

    return sanitized or FALLBACK_FILENAME


def extract_news_id(url: str) -> str:
    """Extract the numeric news id from ``url``.

    Looks for the ``/news/<digits>`` segment used by the source sites. Returns
    the matched digits, or ``"unknown"`` when the URL has no such segment.
    """
    match = NEWS_ID_RE.search(url)
    if match:
        return match.group(1)
    return "unknown"


def build_output_path(
    output_dir: str | Path,
    category: str,
    title: str,
    news_id: str,
) -> Path:
    """Compose the download target path.

    The result is ``output_dir/category/"{sanitized_title} [{news_id}].mp4"``,
    where the title is sanitised via :func:`sanitize_filename`.
    """
    safe_name = sanitize_filename(title)
    filename = f"{safe_name} [{news_id}].mp4"
    return Path(output_dir) / category / filename
