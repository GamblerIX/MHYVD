from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from src.config.settings import Config
from src.main import main
from src.uploader.base import (
    STATUS_FAILED,
    STATUS_UPLOADED,
    UploadResult,
    UploadSummary,
)


class FakeUploader:
    def __init__(self, summary: UploadSummary) -> None:
        self.summary = summary
        self.seen_output_dir: Path | None = None

    def upload_all(self, output_dir: Path) -> UploadSummary:
        self.seen_output_dir = output_dir
        return self.summary


class UploadCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config_path = self.root / "config.yaml"
        self.config_path.write_text(
            f"output_dir: {self.root / 'downloads'}\n", encoding="utf-8"
        )
        self.log_file = self.root / "test.log"

    def _run(self, command: str, summary: UploadSummary) -> tuple[int, FakeUploader]:
        uploader = FakeUploader(summary)
        code = main(
            [
                command,
                "-c",
                str(self.config_path),
                "--log-file",
                str(self.log_file),
            ],
            uploader_factory=lambda **kwargs: uploader,
        )
        return code, uploader

    def test_upload_webdav_success_exit_zero(self) -> None:
        summary = UploadSummary(results=(UploadResult("a.mp4", STATUS_UPLOADED),))
        code, uploader = self._run("upload-webdav", summary)
        self.assertEqual(code, 0)
        self.assertEqual(uploader.seen_output_dir, self.root / "downloads")

    def test_upload_gdrive_failure_exit_nonzero(self) -> None:
        summary = UploadSummary(
            results=(UploadResult("a.mp4", STATUS_FAILED, error="boom"),)
        )
        code, _ = self._run("upload-gdrive", summary)
        self.assertEqual(code, 1)

    def test_summary_error_exit_nonzero(self) -> None:
        code, _ = self._run("upload-webdav", UploadSummary(error="bad credentials"))
        self.assertEqual(code, 1)

    def test_missing_config_exits_nonzero(self) -> None:
        code = main(
            [
                "upload-webdav",
                "-c",
                str(self.root / "missing.yaml"),
                "--log-file",
                str(self.log_file),
            ],
            uploader_factory=lambda **kwargs: FakeUploader(UploadSummary()),
        )
        self.assertEqual(code, 1)


class RunStreamingUploadCliTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.config_path = self.root / "config.yaml"
        self.config_path.write_text(
            "upload:\n"
            "  webdav:\n"
            "    url: https://dav.example\n"
            "    username: u\n"
            "    password: p\n"
            f"output_dir: {self.root / 'downloads'}\n",
            encoding="utf-8",
        )
        self.log_file = self.root / "test.log"

    def _pipeline_factory(self):
        from src.models import PipelineResult

        class FakePipeline:
            async def run(self) -> PipelineResult:
                return PipelineResult(news_count=1, completed=True)

        return lambda **kwargs: FakePipeline()

    def test_run_upload_builds_uploader_from_config(self) -> None:
        captured: dict[str, object] = {}

        def uploader_factory(**kwargs: object) -> FakeUploader:
            captured.update(kwargs)
            return FakeUploader(UploadSummary())

        code = main(
            [
                "run",
                "-c",
                str(self.config_path),
                "--log-file",
                str(self.log_file),
                "--upload",
                "webdav",
            ],
            pipeline_factory=self._pipeline_factory(),
            uploader_factory=uploader_factory,
        )
        self.assertEqual(code, 0)
        self.assertEqual(captured.get("url"), "https://dav.example")
        self.assertEqual(captured.get("username"), "u")

    def test_run_upload_config_error_exits_nonzero(self) -> None:
        def uploader_factory(**kwargs: object) -> FakeUploader:
            raise ValueError("WebDAV base_url is required")

        code = main(
            [
                "run",
                "-c",
                str(self.config_path),
                "--log-file",
                str(self.log_file),
                "--upload",
                "webdav",
            ],
            pipeline_factory=self._pipeline_factory(),
            uploader_factory=uploader_factory,
        )
        self.assertEqual(code, 1)


class UploadConfigEnvOverrideTest(unittest.TestCase):
    def test_env_overrides_webdav_credentials(self) -> None:
        config = Config.from_mapping(
            {"upload": {"webdav": {"url": "https://file.example", "username": "file"}}}
        )
        original = dict(os.environ)
        os.environ["MHYVD_WEBDAV_URL"] = "https://env.example"
        os.environ["MHYVD_WEBDAV_PASSWORD"] = "secret"
        try:
            section = config.upload_config("webdav")
        finally:
            os.environ.clear()
            os.environ.update(original)
        self.assertEqual(section["url"], "https://env.example")
        self.assertEqual(section["username"], "file")
        self.assertEqual(section["password"], "secret")

    def test_gdrive_defaults_present(self) -> None:
        config = Config.from_mapping({})
        section = config.upload_config("gdrive")
        self.assertEqual(section["folder_name"], "MHYVD")
        self.assertIn("token_path", section)


if __name__ == "__main__":
    unittest.main()
