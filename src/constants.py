"""Shared constants for MHYVD.

Holds the download status strings, the default classification category, and the
process exit codes used across the pipeline and CLI. Keeping these centralised
avoids magic strings/numbers scattered through the codebase.
"""

from __future__ import annotations

# --- Download status strings (see Download_Result.status) ---
STATUS_DOWNLOADED = "downloaded"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

#: Every valid Download_Result status value.
DOWNLOAD_STATUSES = (STATUS_DOWNLOADED, STATUS_SKIPPED, STATUS_FAILED)

# --- Classification ---
#: Category assigned when no rule keyword matches a News_Item title.
DEFAULT_CATEGORY = "others"

# --- Process exit codes ---
EXIT_SUCCESS = 0  # normal completion
EXIT_TIMEOUT = 124  # overall time budget exceeded
EXIT_INTERRUPTED = 130  # user interrupt (SIGINT)
EXIT_ERROR = 1  # generic failure (config error, startup failure, etc.)

__all__ = [
    "STATUS_DOWNLOADED",
    "STATUS_SKIPPED",
    "STATUS_FAILED",
    "DOWNLOAD_STATUSES",
    "DEFAULT_CATEGORY",
    "EXIT_SUCCESS",
    "EXIT_TIMEOUT",
    "EXIT_INTERRUPTED",
    "EXIT_ERROR",
]
