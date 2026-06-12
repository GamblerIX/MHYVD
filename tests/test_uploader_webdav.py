from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.uploader.webdav import WebDAVUploader


class FakeServer:
    """Records requests; remote state is a name -> size mapping."""

    def __init__(self, remote: dict[str, int] | None = None) -> None:
        self.remote = remote or {}
        self.calls: list[tuple[str, str]] = []
        self.fail_put = False

    def __call__(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        body_path: Path | None,
    ) -> tuple[int, dict[str, str]]:
        self.calls.append((method, url))
        if method == "HEAD":
            size = self.remote.get(url)
            if size is None:
                return 404, {}
            return 200, {"Content-Length": str(size)}
        if method == "MKCOL":
            return 201, {}
        if method == "PUT":
            if self.fail_put:
                return 507, {}
            assert body_path is not None
            self.remote[url] = body_path.stat().st_size
            return 201, {}
        return 405, {}


class WebDAVUploaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def _touch(self, relative: str, content: bytes = b"data") -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def _uploader(self, server: FakeServer) -> WebDAVUploader:
        return WebDAVUploader(
            base_url="https://dav.example.com/",
            username="user",
            password="pass",
            remote_dir="MHYVD",
            request_fn=server,
        )

    def test_requires_base_url(self) -> None:
        with self.assertRaises(ValueError):
            WebDAVUploader(base_url="", username="u", password="p")

    def test_uploads_new_file_and_creates_dirs(self) -> None:
        self._touch("videos/op/clip.mp4")
        server = FakeServer()
        summary = self._uploader(server).upload_all(self.root)
        self.assertEqual(summary.uploaded, 1)
        self.assertTrue(summary.ok)
        methods = [method for method, _ in server.calls]
        self.assertIn("MKCOL", methods)
        self.assertIn("PUT", methods)
        put_url = next(url for method, url in server.calls if method == "PUT")
        self.assertEqual(put_url, "https://dav.example.com/MHYVD/videos/op/clip.mp4")

    def test_skips_existing_same_size(self) -> None:
        self._touch("videos/op/clip.mp4", b"data")
        url = "https://dav.example.com/MHYVD/videos/op/clip.mp4"
        server = FakeServer(remote={url: 4})
        summary = self._uploader(server).upload_all(self.root)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(summary.uploaded, 0)
        self.assertNotIn("PUT", [method for method, _ in server.calls])

    def test_reuploads_when_size_differs(self) -> None:
        self._touch("videos/op/clip.mp4", b"data")
        url = "https://dav.example.com/MHYVD/videos/op/clip.mp4"
        server = FakeServer(remote={url: 999})
        summary = self._uploader(server).upload_all(self.root)
        self.assertEqual(summary.uploaded, 1)

    def test_put_failure_is_reported_not_raised(self) -> None:
        self._touch("videos/op/clip.mp4")
        server = FakeServer()
        server.fail_put = True
        summary = self._uploader(server).upload_all(self.root)
        self.assertEqual(summary.failed, 1)
        self.assertFalse(summary.ok)
        self.assertIn("507", summary.results[0].error or "")

    def test_failure_does_not_stop_remaining_files(self) -> None:
        self._touch("videos/a.mp4")
        self._touch("videos/b.mp4")

        class FailFirstPut(FakeServer):
            def __call__(self, method, url, headers, body_path):
                if method == "PUT" and url.endswith("a.mp4"):
                    return 500, {}
                return super().__call__(method, url, headers, body_path)

        summary = self._uploader(FailFirstPut()).upload_all(self.root)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.uploaded, 1)

    def test_url_quotes_unicode_names(self) -> None:
        self._touch("videos/角色 PV.mp4")
        server = FakeServer()
        self._uploader(server).upload_all(self.root)
        put_url = next(url for method, url in server.calls if method == "PUT")
        self.assertNotIn(" ", put_url)
        self.assertTrue(put_url.startswith("https://dav.example.com/MHYVD/videos/"))

    def test_empty_dir_is_success(self) -> None:
        summary = self._uploader(FakeServer()).upload_all(self.root)
        self.assertTrue(summary.ok)
        self.assertEqual(len(summary.results), 0)

    def test_exists_true_for_remote_file(self) -> None:
        url = "https://dav.example.com/MHYVD/videos/op/clip.mp4"
        server = FakeServer(remote={url: 4})
        self.assertTrue(self._uploader(server).exists(Path("videos/op/clip.mp4")))

    def test_exists_false_when_missing(self) -> None:
        server = FakeServer()
        self.assertFalse(self._uploader(server).exists(Path("videos/op/clip.mp4")))

    def test_exists_raises_on_server_error(self) -> None:
        class ErrorServer(FakeServer):
            def __call__(self, method, url, headers, body_path):
                return 500, {}

        with self.assertRaises(RuntimeError):
            self._uploader(ErrorServer()).exists(Path("videos/op/clip.mp4"))


if __name__ == "__main__":
    unittest.main()
