from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .base import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_UPLOADED,
    UploadResult,
    UploadSummary,
    iter_parent_dirs,
    scan_local_files,
)

__all__ = ["GoogleDriveUploader", "DriveClient", "DriveClientFactory"]

logger = logging.getLogger("mhyvd.uploader.gdrive")

OAUTH_SCOPES = ("https://www.googleapis.com/auth/drive.file",)


class DriveClient(Protocol):
    def find_folder(self, name: str, parent_id: str | None) -> str | None: ...

    def create_folder(self, name: str, parent_id: str | None) -> str: ...

    def find_file(self, name: str, parent_id: str) -> tuple[str, int] | None: ...

    def upload_file(self, local_path: Path, name: str, parent_id: str) -> None: ...


DriveClientFactory = Callable[[], DriveClient]


class _GoogleApiDriveClient:
    """Real Drive client. Imports Google libraries lazily on construction."""

    def __init__(self, client_secret_path: str, token_path: str) -> None:
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaFileUpload
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError(
                "Google Drive support requires the optional dependencies; "
                "install with: uv sync --extra gdrive"
            ) from exc

        self._media_file_upload = MediaFileUpload
        token_file = Path(token_path).expanduser()
        credentials = None
        if token_file.exists():
            credentials = Credentials.from_authorized_user_file(
                str(token_file), list(OAUTH_SCOPES)
            )
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        elif not credentials or not credentials.valid:
            if not client_secret_path:
                raise RuntimeError(
                    "no valid token and upload.gdrive.client_secret_path is unset"
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                client_secret_path, list(OAUTH_SCOPES)
            )
            credentials = flow.run_local_server(port=0)
        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(credentials.to_json(), encoding="utf-8")
        self._service = build("drive", "v3", credentials=credentials)

    @staticmethod
    def _escape(name: str) -> str:
        return name.replace("\\", "\\\\").replace("'", "\\'")

    def find_folder(self, name: str, parent_id: str | None) -> str | None:
        query = (
            f"name = '{self._escape(name)}' and "
            "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        )
        if parent_id:
            query += f" and '{parent_id}' in parents"
        response = (
            self._service.files()
            .list(q=query, fields="files(id)", pageSize=1)
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def create_folder(self, name: str, parent_id: str | None) -> str:
        body: dict[str, object] = {
            "name": name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            body["parents"] = [parent_id]
        created = self._service.files().create(body=body, fields="id").execute()
        return str(created["id"])

    def find_file(self, name: str, parent_id: str) -> tuple[str, int] | None:
        query = (
            f"name = '{self._escape(name)}' and '{parent_id}' in parents "
            "and trashed = false"
        )
        response = (
            self._service.files()
            .list(q=query, fields="files(id, size)", pageSize=1)
            .execute()
        )
        files = response.get("files", [])
        if not files:
            return None
        return files[0]["id"], int(files[0].get("size", -1))

    def upload_file(self, local_path: Path, name: str, parent_id: str) -> None:
        media = self._media_file_upload(
            str(local_path), resumable=True, chunksize=16 * 1024 * 1024
        )
        request = self._service.files().create(
            body={"name": name, "parents": [parent_id]}, media_body=media, fields="id"
        )
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                logger.info("  %s: %d%%", local_path.name, int(status.progress() * 100))


class GoogleDriveUploader:
    name = "gdrive"

    def __init__(
        self,
        *,
        client_secret_path: str = "",
        token_path: str = "~/.config/mhyvd/gdrive-token.json",
        folder_name: str = "MHYVD",
        client_factory: DriveClientFactory | None = None,
    ) -> None:
        self._folder_name = folder_name
        self._client_factory = client_factory or (
            lambda: _GoogleApiDriveClient(client_secret_path, token_path)
        )
        self._folder_ids: dict[str, str] = {}
        self._client_instance: DriveClient | None = None

    def _client(self) -> DriveClient:
        if self._client_instance is None:
            self._client_instance = self._client_factory()
        return self._client_instance

    def _folder_id_for(self, client: DriveClient, relative: Path) -> str:
        chain = [self._folder_name] if self._folder_name else []
        chain.extend(parent.name for parent in iter_parent_dirs(relative))
        parent_id: str | None = None
        key_parts: list[str] = []
        for name in chain:
            key_parts.append(name)
            key = "/".join(key_parts)
            cached = self._folder_ids.get(key)
            if cached is None:
                cached = client.find_folder(name, parent_id)
                if cached is None:
                    cached = client.create_folder(name, parent_id)
                self._folder_ids[key] = cached
            parent_id = cached
        if parent_id is None:
            raise RuntimeError("upload.gdrive.folder_name must not be empty")
        return parent_id

    def _upload_one(
        self, client: DriveClient, output_dir: Path, relative: Path
    ) -> UploadResult:
        local_path = output_dir / relative
        local_size = local_path.stat().st_size
        folder_id = self._folder_id_for(client, relative)
        existing = client.find_file(relative.name, folder_id)
        if existing is not None and existing[1] == local_size:
            logger.info("Skip (exists, same size): %s", relative.as_posix())
            return UploadResult(relative.as_posix(), STATUS_SKIPPED, size=local_size)

        logger.info("Uploading %s (%d bytes)", relative.as_posix(), local_size)
        client.upload_file(local_path, relative.name, folder_id)
        logger.info("Uploaded %s", relative.as_posix())
        return UploadResult(relative.as_posix(), STATUS_UPLOADED, size=local_size)

    def exists(self, relative: Path) -> bool:
        """True when the remote file exists; never creates missing folders."""
        client = self._client()
        chain = [self._folder_name] if self._folder_name else []
        chain.extend(parent.name for parent in iter_parent_dirs(relative))
        parent_id: str | None = None
        key_parts: list[str] = []
        for name in chain:
            key_parts.append(name)
            key = "/".join(key_parts)
            cached = self._folder_ids.get(key)
            if cached is None:
                cached = client.find_folder(name, parent_id)
                if cached is None:
                    return False
                self._folder_ids[key] = cached
            parent_id = cached
        if parent_id is None:
            return False
        return client.find_file(relative.name, parent_id) is not None

    def upload_one(self, output_dir: Path, relative: Path) -> UploadResult:
        """Upload a single file; raises on client/API failure."""
        return self._upload_one(self._client(), output_dir, relative)

    def upload_all(self, output_dir: Path) -> UploadSummary:
        try:
            client = self._client()
        except Exception as exc:
            return UploadSummary(error=str(exc))

        files = scan_local_files(output_dir)
        if not files:
            logger.info("No uploadable files under %s", output_dir)
            return UploadSummary()

        results: list[UploadResult] = []
        for index, relative in enumerate(files, start=1):
            logger.info("[%d/%d] %s", index, len(files), relative.as_posix())
            try:
                results.append(self._upload_one(client, output_dir, relative))
            except Exception as exc:
                logger.error("Failed: %s (%s)", relative.as_posix(), exc)
                results.append(
                    UploadResult(relative.as_posix(), STATUS_FAILED, error=str(exc))
                )
        return UploadSummary(results=tuple(results))
