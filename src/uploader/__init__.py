from __future__ import annotations

from .base import UploadResult, UploadSummary, scan_local_files
from .gdrive import GoogleDriveUploader
from .registry import UnknownUploaderError, UploaderRegistry
from .streaming import StreamingUploadStats, make_post_download_hook
from .webdav import WebDAVUploader

__all__ = [
    "UploadResult",
    "UploadSummary",
    "scan_local_files",
    "UploaderRegistry",
    "UnknownUploaderError",
    "WebDAVUploader",
    "GoogleDriveUploader",
    "StreamingUploadStats",
    "make_post_download_hook",
    "default_registry",
    "get_uploader_registry",
]


default_registry = UploaderRegistry()
default_registry.register(WebDAVUploader.name, WebDAVUploader)
default_registry.register(GoogleDriveUploader.name, GoogleDriveUploader)


def get_uploader_registry() -> UploaderRegistry:
    return default_registry
