from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "UploadResult",
    "UploadSummary",
    "scan_local_files",
    "STATUS_UPLOADED",
    "STATUS_SKIPPED",
    "STATUS_FAILED",
]

STATUS_UPLOADED = "uploaded"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

SKIP_NAMES = {"cache.json"}
SKIP_SUFFIXES = {".part", ".json", ".log"}
SKIP_DIRS = {".cache"}


@dataclass(frozen=True)
class UploadResult:
    relative_path: str
    status: str
    size: int = 0
    error: str | None = None


@dataclass(frozen=True)
class UploadSummary:
    results: tuple[UploadResult, ...] = ()
    error: str | None = None

    @property
    def uploaded(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_UPLOADED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_SKIPPED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status == STATUS_FAILED)

    @property
    def ok(self) -> bool:
        return self.error is None and self.failed == 0


def scan_local_files(output_dir: Path) -> list[Path]:
    """Collect uploadable files under output_dir, relative paths sorted.

    Cache artifacts, partial downloads, and metadata files are excluded.
    """
    if not output_dir.is_dir():
        return []
    found: list[Path] = []
    for path in sorted(output_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(output_dir)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.name in SKIP_NAMES or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        found.append(relative)
    return found


def iter_parent_dirs(relative: Path) -> Iterable[Path]:
    """Yield ancestor directories of relative path, shallowest first."""
    parents = [p for p in relative.parents if str(p) != "."]
    yield from reversed(parents)
