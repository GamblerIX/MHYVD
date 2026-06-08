"""
下载缓存管理
"""

import json
import logging
from pathlib import Path
from typing import Dict, Set, Optional
from datetime import datetime

logger = logging.getLogger("cache")


class DownloadCache:
    """下载缓存管理器"""

    def __init__(self, cache_file: Path):
        self.cache_file = cache_file
        self._cache: Dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """加载缓存文件"""
        if self.cache_file.exists():
            try:
                with self.cache_file.open("r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                logger.debug("已加载缓存：%d 条记录", len(self._cache))
            except (json.JSONDecodeError, IOError) as e:
                logger.warning("缓存文件损坏，将创建新缓存：%s", e)
                self._cache = {}
        else:
            self._cache = {}

    def _save(self) -> None:
        """保存缓存文件"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with self.cache_file.open("w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)

    def _make_key(self, url: str) -> str:
        """生成缓存键"""
        return url

    def is_downloaded(self, url: str) -> bool:
        """检查 URL 是否已下载"""
        key = self._make_key(url)
        return key in self._cache

    def get_download_info(self, url: str) -> Optional[dict]:
        """获取下载信息"""
        key = self._make_key(url)
        return self._cache.get(key)

    def add(
        self,
        url: str,
        file_path: str,
        video_url: str,
        title: str,
        category: str,
        file_size: int = 0,
    ) -> None:
        """添加下载记录"""
        key = self._make_key(url)
        self._cache[key] = {
            "url": url,
            "file_path": file_path,
            "video_url": video_url,
            "title": title,
            "category": category,
            "file_size": file_size,
            "downloaded_at": datetime.now().isoformat(),
            "status": "completed",
        }
        self._save()
        logger.debug("已缓存下载记录：%s", title)

    def mark_failed(self, url: str, error: str) -> None:
        """标记下载失败"""
        key = self._make_key(url)
        if key in self._cache:
            self._cache[key]["status"] = "failed"
            self._cache[key]["error"] = error
            self._cache[key]["failed_at"] = datetime.now().isoformat()
        else:
            self._cache[key] = {
                "url": url,
                "status": "failed",
                "error": error,
                "failed_at": datetime.now().isoformat(),
            }
        self._save()

    def get_downloaded_urls(self) -> Set[str]:
        """获取所有已下载的 URL 集合"""
        return {
            record["url"]
            for record in self._cache.values()
            if record.get("status") == "completed"
        }

    def get_failed_urls(self) -> Set[str]:
        """获取所有下载失败的 URL 集合"""
        return {
            record["url"]
            for record in self._cache.values()
            if record.get("status") == "failed"
        }

    def clear(self) -> None:
        """清空缓存"""
        self._cache = {}
        self._save()
        logger.info("缓存已清空")

    def stats(self) -> dict:
        """获取缓存统计信息"""
        total = len(self._cache)
        completed = sum(
            1 for r in self._cache.values() if r.get("status") == "completed"
        )
        failed = sum(
            1 for r in self._cache.values() if r.get("status") == "failed"
        )
        return {
            "total": total,
            "completed": completed,
            "failed": failed,
        }
