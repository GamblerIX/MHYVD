"""核心模块"""

from .models import NewsItem, VideoItem, DownloadResult, PipelineResult
from .pipeline import Pipeline
from .plugin import Plugin, PluginRegistry, PluginMetadata

__all__ = [
    "NewsItem",
    "VideoItem",
    "DownloadResult",
    "PipelineResult",
    "Pipeline",
    "Plugin",
    "PluginRegistry",
    "PluginMetadata",
]
