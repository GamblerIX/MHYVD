from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.uploader.base import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_UPLOADED,
    UploadResult,
    UploadSummary,
    iter_parent_dirs,
    scan_local_files,
)


class ScanLocalFilesTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _touch(self, relative: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    def test_missing_dir_returns_empty(self) -> None:
        self.assertEqual(scan_local_files(self.root / "nope"), [])

    def test_collects_videos_and_skips_artifacts(self) -> None:
        self._touch("videos/pv/character/a.mp4")
        self._touch("videos/op/b.mp4")
        self._touch("videos/op/b.mp4.part")
        self._touch("cache.json")
        self._touch(".cache/fetch_cache.json")
        self._touch("run.log")
        found = scan_local_files(self.root)
        self.assertEqual(
            [p.as_posix() for p in found],
            ["videos/op/b.mp4", "videos/pv/character/a.mp4"],
        )

    def test_iter_parent_dirs_shallowest_first(self) -> None:
        parts = [p.as_posix() for p in iter_parent_dirs(Path("a/b/c/file.mp4"))]
        self.assertEqual(parts, ["a", "a/b", "a/b/c"])

    def test_iter_parent_dirs_top_level_file(self) -> None:
        self.assertEqual(list(iter_parent_dirs(Path("file.mp4"))), [])


class UploadSummaryTest(unittest.TestCase):
    def test_counts_and_ok(self) -> None:
        summary = UploadSummary(
            results=(
                UploadResult("a.mp4", STATUS_UPLOADED, size=1),
                UploadResult("b.mp4", STATUS_SKIPPED, size=1),
                UploadResult("c.mp4", STATUS_FAILED, error="boom"),
            )
        )
        self.assertEqual(summary.uploaded, 1)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.failed, 1)
        self.assertFalse(summary.ok)

    def test_ok_when_no_failures(self) -> None:
        summary = UploadSummary(results=(UploadResult("a.mp4", STATUS_UPLOADED),))
        self.assertTrue(summary.ok)

    def test_error_makes_not_ok(self) -> None:
        self.assertFalse(UploadSummary(error="bad credentials").ok)


if __name__ == "__main__":
    unittest.main()
