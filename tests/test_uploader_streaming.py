from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.constants import STATUS_DOWNLOADED, STATUS_FAILED
from src.models import DownloadResult
from src.uploader.base import (
    STATUS_SKIPPED,
    STATUS_UPLOADED,
    UploadResult,
)
from src.uploader.streaming import StreamingUploadStats, make_post_download_hook


class _RecordingUploader:
    def __init__(self, status: str = STATUS_UPLOADED, error: Exception | None = None):
        self.status = status
        self.error = error
        self.calls: list[tuple[Path, Path]] = []

    def upload_one(self, output_dir: Path, relative: Path) -> UploadResult:
        self.calls.append((output_dir, relative))
        if self.error is not None:
            raise self.error
        return UploadResult(relative.as_posix(), self.status, size=1)


def _result(path: Path, status: str = STATUS_DOWNLOADED) -> DownloadResult:
    return DownloadResult(
        title="t",
        url="https://example.com/a",
        category="videos/test",
        video_url="https://example.com/v.mp4",
        local_path=path,
        status=status,
        bytes_written=1,
    )


class MakePostDownloadHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.output_dir = Path(self._tmp.name)

    def _make_file(self) -> Path:
        path = self.output_dir / "videos" / "test" / "v.mp4"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"x")
        return path

    def test_uploads_then_deletes_local_file_and_empty_dirs(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader()
        stats = StreamingUploadStats()
        hook = make_post_download_hook(uploader, self.output_dir, stats=stats)

        result = hook(_result(path))

        self.assertEqual(uploader.calls, [(self.output_dir, Path("videos/test/v.mp4"))])
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        self.assertTrue(self.output_dir.exists())
        self.assertEqual(stats.uploaded, 1)
        self.assertEqual(result.status, STATUS_DOWNLOADED)
        self.assertIsNone(result.error)

    def test_skipped_upload_still_deletes_local_file(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader(status=STATUS_SKIPPED)
        stats = StreamingUploadStats()
        hook = make_post_download_hook(uploader, self.output_dir, stats=stats)

        hook(_result(path))

        self.assertFalse(path.exists())
        self.assertEqual(stats.skipped, 1)

    def test_upload_exception_keeps_file_and_annotates_result(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader(error=RuntimeError("boom"))
        stats = StreamingUploadStats()
        hook = make_post_download_hook(uploader, self.output_dir, stats=stats)

        result = hook(_result(path))

        self.assertTrue(path.exists())
        self.assertEqual(stats.failed, 1)
        self.assertEqual(result.status, STATUS_DOWNLOADED)
        self.assertIn("upload failed", result.error or "")

    def test_failed_upload_result_keeps_file(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader(status="failed")
        stats = StreamingUploadStats()
        hook = make_post_download_hook(uploader, self.output_dir, stats=stats)

        result = hook(_result(path))

        self.assertTrue(path.exists())
        self.assertEqual(stats.failed, 1)
        self.assertIn("upload failed", result.error or "")

    def test_non_downloaded_results_are_passed_through(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader()
        hook = make_post_download_hook(uploader, self.output_dir)

        result = hook(_result(path, status=STATUS_FAILED))

        self.assertEqual(uploader.calls, [])
        self.assertTrue(path.exists())
        self.assertEqual(result.status, STATUS_FAILED)

    def test_keep_local_skips_deletion(self) -> None:
        path = self._make_file()
        uploader = _RecordingUploader()
        hook = make_post_download_hook(uploader, self.output_dir, keep_local=True)

        hook(_result(path))

        self.assertTrue(path.exists())

    def test_path_outside_output_dir_is_not_uploaded(self) -> None:
        outside = Path(self._tmp.name).parent / "elsewhere.mp4"
        uploader = _RecordingUploader()
        hook = make_post_download_hook(uploader, self.output_dir)

        result = hook(_result(outside))

        self.assertEqual(uploader.calls, [])
        self.assertEqual(result.status, STATUS_DOWNLOADED)


if __name__ == "__main__":
    unittest.main()
