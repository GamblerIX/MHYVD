from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.uploader.gdrive import GoogleDriveUploader


class FakeDriveClient:
    def __init__(self) -> None:
        self.folders: dict[tuple[str, str | None], str] = {}
        self.files: dict[tuple[str, str], int] = {}
        self.uploads: list[tuple[str, str]] = []
        self.fail_upload = False
        self._next_id = 0

    def _new_id(self) -> str:
        self._next_id += 1
        return f"id{self._next_id}"

    def find_folder(self, name: str, parent_id: str | None) -> str | None:
        return self.folders.get((name, parent_id))

    def create_folder(self, name: str, parent_id: str | None) -> str:
        folder_id = self._new_id()
        self.folders[(name, parent_id)] = folder_id
        return folder_id

    def find_file(self, name: str, parent_id: str) -> tuple[str, int] | None:
        size = self.files.get((name, parent_id))
        if size is None:
            return None
        return "fileid", size

    def upload_file(self, local_path: Path, name: str, parent_id: str) -> None:
        if self.fail_upload:
            raise RuntimeError("quota exceeded")
        self.files[(name, parent_id)] = local_path.stat().st_size
        self.uploads.append((name, parent_id))


class GoogleDriveUploaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.client = FakeDriveClient()

    def _touch(self, relative: str, content: bytes = b"data") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _uploader(self) -> GoogleDriveUploader:
        return GoogleDriveUploader(client_factory=lambda: self.client)

    def test_uploads_into_mirrored_folder_tree(self) -> None:
        self._touch("videos/pv/character/clip.mp4")
        summary = self._uploader().upload_all(self.root)
        self.assertEqual(summary.uploaded, 1)
        created = {name for name, _ in self.client.folders}
        self.assertEqual(created, {"MHYVD", "videos", "pv", "character"})
        self.assertEqual(len(self.client.uploads), 1)

    def test_skips_existing_same_size(self) -> None:
        self._touch("videos/clip.mp4", b"data")
        first = self._uploader().upload_all(self.root)
        self.assertEqual(first.uploaded, 1)
        second = self._uploader().upload_all(self.root)
        self.assertEqual(second.skipped, 1)
        self.assertEqual(second.uploaded, 0)

    def test_reuploads_when_size_differs(self) -> None:
        self._touch("videos/clip.mp4", b"data")
        self._uploader().upload_all(self.root)
        self._touch("videos/clip.mp4", b"longer content")
        summary = self._uploader().upload_all(self.root)
        self.assertEqual(summary.uploaded, 1)

    def test_folder_lookup_is_cached_per_run(self) -> None:
        self._touch("videos/a.mp4")
        self._touch("videos/b.mp4")
        self._uploader().upload_all(self.root)
        # videos folder created once, not per file.
        self.assertEqual(
            sum(1 for name, _ in self.client.folders if name == "videos"), 1
        )

    def test_upload_failure_reported_not_raised(self) -> None:
        self._touch("videos/clip.mp4")
        self.client.fail_upload = True
        summary = self._uploader().upload_all(self.root)
        self.assertEqual(summary.failed, 1)
        self.assertIn("quota exceeded", summary.results[0].error or "")

    def test_client_factory_error_becomes_summary_error(self) -> None:
        def boom() -> FakeDriveClient:
            raise RuntimeError("missing google libraries")

        self._touch("videos/clip.mp4")
        uploader = GoogleDriveUploader(client_factory=boom)
        summary = uploader.upload_all(self.root)
        self.assertFalse(summary.ok)
        self.assertIn("missing google libraries", summary.error or "")

    def test_exists_true_after_upload(self) -> None:
        self._touch("videos/clip.mp4")
        uploader = self._uploader()
        uploader.upload_all(self.root)
        self.assertTrue(uploader.exists(Path("videos/clip.mp4")))

    def test_exists_false_and_creates_no_folders(self) -> None:
        uploader = self._uploader()
        self.assertFalse(uploader.exists(Path("videos/clip.mp4")))
        self.assertEqual(self.client.folders, {})

    def test_exists_false_when_file_missing_in_existing_folder(self) -> None:
        self._touch("videos/other.mp4")
        uploader = self._uploader()
        uploader.upload_all(self.root)
        self.assertFalse(uploader.exists(Path("videos/clip.mp4")))

    def test_module_imports_without_google_libraries(self) -> None:
        import src.uploader.gdrive  # noqa: F401


if __name__ == "__main__":
    unittest.main()
