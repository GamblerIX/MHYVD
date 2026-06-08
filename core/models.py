"""
数据模型定义
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any
from pathlib import Path


@dataclass(frozen=True)
class NewsItem:
    """新闻条目"""

    title: str
    url: str
    category: Optional[str] = None

    def with_category(self, category: str) -> "NewsItem":
        """返回带类别的副本"""
        return NewsItem(title=self.title, url=self.url, category=category)


@dataclass(frozen=True)
class VideoItem:
    """视频条目"""

    title: str
    url: str
    category: str
    video_url: Optional[str] = None
    file_size: Optional[int] = None
    local_path: Optional[Path] = None


@dataclass
class DownloadResult:
    """下载结果"""

    title: str
    url: str
    category: str
    video_url: str
    local_path: Path
    status: str  # downloaded / skipped / failed
    bytes_written: int = 0
    remote_size: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "title": self.title,
            "url": self.url,
            "category": self.category,
            "video_url": self.video_url,
            "local_path": str(self.local_path),
            "status": self.status,
            "bytes_written": self.bytes_written,
            "remote_size": self.remote_size,
            "error": self.error,
        }


@dataclass
class PipelineResult:
    """流水线执行结果"""

    news_count: int = 0
    classified_categories: Dict[str, int] = field(default_factory=dict)
    download_results: List[DownloadResult] = field(default_factory=list)

    @property
    def downloaded(self) -> int:
        """成功下载数量"""
        return sum(1 for r in self.download_results if r.status == "downloaded")

    @property
    def skipped(self) -> int:
        """跳过数量"""
        return sum(1 for r in self.download_results if r.status == "skipped")

    @property
    def failed(self) -> int:
        """失败数量"""
        return sum(1 for r in self.download_results if r.status == "failed")

    def summary(self) -> Dict[str, Any]:
        """获取执行摘要"""
        return {
            "news_count": self.news_count,
            "categories": self.classified_categories,
            "downloaded": self.downloaded,
            "skipped": self.skipped,
            "failed": self.failed,
            "total": len(self.download_results),
        }
