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
    title: str
    url: str
    category: str | None = None

    def with_category(self, category: str) -> NewsItem:
        return NewsItem(title=self.title, url=self.url, category=category)


@dataclass(frozen=True)
class VideoItem:
    title: str
    url: str
    category: str
    video_url: str | None = None
    file_size: int | None = None
    local_path: Path | None = None


@dataclass(frozen=True)
class DownloadResult:
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
        line = f"- **{self.status}** — {self.title} (`{self.category}`)"
        if self.status == STATUS_DOWNLOADED:
            line += f" — {self.bytes_written} bytes"
        if self.error:
            line += f" — error: {self.error}"
        return line


@dataclass(frozen=True)
class SourceMetadata:
    source_key: str
    game: str
    region: str
    base_url: str


@dataclass(frozen=True)
class Rule:
    category: str
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class PipelineResult:
    news_count: int = 0
    classified_categories: dict[str, int] = field(default_factory=dict)
    download_results: tuple[DownloadResult, ...] = ()
    completed: bool = False
    error: str | None = None

    timed_out: bool = False

    @property
    def downloaded(self) -> int:
        return sum(1 for r in self.download_results if r.status == STATUS_DOWNLOADED)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.download_results if r.status == STATUS_SKIPPED)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.download_results if r.status == STATUS_FAILED)

    def as_markdown(self) -> str:
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
