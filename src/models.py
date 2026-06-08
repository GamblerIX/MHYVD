"""Immutable data models and result renderers for MHYVD.

Every model here is a frozen dataclass (Requirement 13.2/13.3) so that values
flow through the pipeline without accidental mutation. ``PipelineResult`` and
``DownloadResult`` additionally provide ``as_markdown()`` renderers
(Requirement 13.6) used by the CLI to print a human-readable summary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .constants import STATUS_DOWNLOADED, STATUS_FAILED, STATUS_SKIPPED

__all__ = [
    "NewsItem",
    "VideoItem",
    "DownloadResult",
    "SourceMetadata",
    "Rule",
    "PipelineResult",
]


@dataclass(frozen=True)
class NewsItem:
    """A single news/article entry retrieved from a source.

    ``category`` is ``None`` until the Classify_Stage assigns one.
    """

    title: str
    url: str
    category: str | None = None

    def with_category(self, category: str) -> NewsItem:
        """Return a copy of this item with ``category`` set.

        ``NewsItem`` is frozen, so classification produces new items rather
        than mutating existing ones.
        """
        return NewsItem(title=self.title, url=self.url, category=category)


@dataclass(frozen=True)
class VideoItem:
    """A video associated with a :class:`NewsItem`."""

    title: str
    url: str
    category: str
    video_url: str | None = None
    file_size: int | None = None
    local_path: Path | None = None


@dataclass(frozen=True)
class DownloadResult:
    """The outcome of attempting to download one video.

    ``status`` is one of the ``STATUS_*`` constants
    (``downloaded`` / ``skipped`` / ``failed``).
    """

    title: str
    url: str
    category: str
    video_url: str
    local_path: Path
    status: str
    bytes_written: int = 0
    remote_size: int | None = None
    error: str | None = None

    def as_markdown(self) -> str:
        """Render this result as a single markdown list line.

        Always includes the status so the line is self-describing; appends the
        bytes written for successful downloads and the error for failures.
        """
        line = f"- **{self.status}** — {self.title} (`{self.category}`)"
        if self.status == STATUS_DOWNLOADED:
            line += f" — {self.bytes_written} bytes"
        if self.error:
            line += f" — error: {self.error}"
        return line


@dataclass(frozen=True)
class SourceMetadata:
    """Static metadata describing a registered source adapter."""

    source_key: str
    game: str
    region: str
    base_url: str


@dataclass(frozen=True)
class Rule:
    """A single classification rule: a category and its trigger keywords."""

    category: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PipelineResult:
    """Aggregated counts and results from one pipeline execution."""

    news_count: int = 0
    classified_categories: dict[str, int] = field(default_factory=dict)
    download_results: tuple[DownloadResult, ...] = ()
    completed: bool = False
    error: str | None = None

    @property
    def downloaded(self) -> int:
        """Number of download results with ``downloaded`` status."""
        return sum(1 for r in self.download_results if r.status == STATUS_DOWNLOADED)

    @property
    def skipped(self) -> int:
        """Number of download results with ``skipped`` status."""
        return sum(1 for r in self.download_results if r.status == STATUS_SKIPPED)

    @property
    def failed(self) -> int:
        """Number of download results with ``failed`` status."""
        return sum(1 for r in self.download_results if r.status == STATUS_FAILED)

    def as_markdown(self) -> str:
        """Render a markdown summary of the whole pipeline run.

        Includes the fetched news count, per-category counts, and the
        downloaded/skipped/failed totals so the summary stands on its own.
        """
        lines: list[str] = ["# Pipeline Result", ""]
        status = "completed" if self.completed else "incomplete"
        lines.append(f"- Status: **{status}**")
        if self.error:
            lines.append(f"- Error: {self.error}")
        lines.append(f"- News items fetched: {self.news_count}")
        lines.append(f"- Downloaded: {self.downloaded}")
        lines.append(f"- Skipped: {self.skipped}")
        lines.append(f"- Failed: {self.failed}")
        lines.append(f"- Total download results: {len(self.download_results)}")

        if self.classified_categories:
            lines.append("")
            lines.append("## Categories")
            for category, count in self.classified_categories.items():
                lines.append(f"- {category}: {count}")

        if self.download_results:
            lines.append("")
            lines.append("## Downloads")
            for result in self.download_results:
                lines.append(result.as_markdown())

        return "\n".join(lines)
