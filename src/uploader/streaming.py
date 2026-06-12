from __future__ import annotations

import dataclasses
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from ..constants import STATUS_DOWNLOADED
from ..models import DownloadResult
from .base import STATUS_FAILED, STATUS_SKIPPED, UploadResult

__all__ = ["StreamingUploadStats", "make_post_download_hook", "SingleFileUploader"]

logger = logging.getLogger("mhyvd.uploader.streaming")


class SingleFileUploader(Protocol):
    def upload_one(self, output_dir: Path, relative: Path) -> UploadResult: ...

    def exists(self, relative: Path) -> bool: ...


@dataclasses.dataclass
class StreamingUploadStats:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0

    @property
    def ok(self) -> bool:
        return self.failed == 0


def _prune_empty_dirs(path: Path, stop: Path) -> None:
    current = path.parent
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def make_post_download_hook(
    uploader: SingleFileUploader,
    output_dir: Path,
    *,
    stats: StreamingUploadStats | None = None,
    keep_local: bool = False,
) -> Callable[[DownloadResult], DownloadResult]:
    """Build a hook that uploads each downloaded file, then removes it locally.

    The hook runs after every successful download (download one -> upload one
    -> delete one), keeping local disk usage bounded to roughly one video.
    On upload failure the local file is kept and the result is annotated, but
    the download status is preserved so the pipeline keeps going.
    """
    tracked = stats if stats is not None else StreamingUploadStats()

    def hook(result: DownloadResult) -> DownloadResult:
        if result.status != STATUS_DOWNLOADED or result.local_path is None:
            return result
        local_path = Path(result.local_path)
        try:
            relative = local_path.relative_to(output_dir)
        except ValueError:
            logger.warning(
                "Not uploading %s: outside output dir %s", local_path, output_dir
            )
            return result

        try:
            upload = uploader.upload_one(output_dir, relative)
        except Exception as exc:  # noqa: BLE001
            tracked.failed += 1
            logger.error("Upload failed for %s (%s); keeping local file", relative, exc)
            return dataclasses.replace(result, error=f"upload failed: {exc}")

        if upload.status == STATUS_FAILED:
            tracked.failed += 1
            logger.error(
                "Upload failed for %s (%s); keeping local file",
                relative,
                upload.error,
            )
            return dataclasses.replace(result, error=f"upload failed: {upload.error}")

        if upload.status == STATUS_SKIPPED:
            tracked.skipped += 1
        else:
            tracked.uploaded += 1

        if not keep_local:
            try:
                local_path.unlink()
                _prune_empty_dirs(local_path, output_dir)
                logger.info("Removed local copy of %s after upload", relative)
            except OSError as exc:
                logger.warning("Could not remove %s: %s", local_path, exc)
        return result

    return hook
