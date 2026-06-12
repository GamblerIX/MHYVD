from __future__ import annotations

import base64
import logging
from collections.abc import Callable
from pathlib import Path

from .base import (
    STATUS_FAILED,
    STATUS_SKIPPED,
    STATUS_UPLOADED,
    UploadResult,
    UploadSummary,
    iter_parent_dirs,
    scan_local_files,
)

__all__ = ["WebDAVUploader", "RequestFn"]

logger = logging.getLogger("mhyvd.uploader.webdav")

# request_fn(method, url, headers, body_path) -> (status_code, headers)
# body_path is a local file streamed as the request body, or None.
RequestFn = Callable[
    [str, str, dict[str, str], Path | None], tuple[int, dict[str, str]]
]


def _default_request_fn(
    method: str, url: str, headers: dict[str, str], body_path: Path | None
) -> tuple[int, dict[str, str]]:
    import urllib.error
    import urllib.request

    data = None
    handle = None
    if body_path is not None:
        handle = body_path.open("rb")
        data = handle
        headers = {**headers, "Content-Length": str(body_path.stat().st_size)}
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {})
    finally:
        if handle is not None:
            handle.close()


class WebDAVUploader:
    name = "webdav"

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        remote_dir: str = "MHYVD",
        request_fn: RequestFn | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("WebDAV base_url is required")
        self._base_url = base_url.rstrip("/")
        self._remote_dir = remote_dir.strip("/")
        self._request_fn = request_fn or _default_request_fn
        credentials = f"{username}:{password}".encode()
        self._auth_header = "Basic " + base64.b64encode(credentials).decode("ascii")
        self._known_dirs: set[str] = set()

    def _url(self, remote_path: str) -> str:
        import urllib.parse

        parts = [self._remote_dir, remote_path] if self._remote_dir else [remote_path]
        quoted = "/".join(
            urllib.parse.quote(segment)
            for part in parts
            for segment in part.split("/")
            if segment
        )
        return f"{self._base_url}/{quoted}"

    def _request(
        self, method: str, remote_path: str, body_path: Path | None = None
    ) -> tuple[int, dict[str, str]]:
        headers = {"Authorization": self._auth_header}
        return self._request_fn(method, self._url(remote_path), headers, body_path)

    def _ensure_dirs(self, relative: Path) -> None:
        chain = [""] if self._remote_dir else []
        for parent in iter_parent_dirs(relative):
            chain.append(parent.as_posix())
        for remote_path in chain:
            if remote_path in self._known_dirs:
                continue
            status, _ = self._request("MKCOL", remote_path + "/")
            # 201 created; 405 already exists.
            if status not in (201, 405, 200, 301):
                raise RuntimeError(f"MKCOL {remote_path!r} failed with HTTP {status}")
            self._known_dirs.add(remote_path)

    def _remote_size(self, relative: Path) -> int | None:
        status, headers = self._request("HEAD", relative.as_posix())
        if status == 404:
            return None
        if status >= 400:
            raise RuntimeError(
                f"HEAD {relative.as_posix()!r} failed with HTTP {status}"
            )
        lowered = {key.lower(): value for key, value in headers.items()}
        length = lowered.get("content-length")
        return int(length) if length is not None and length.isdigit() else -1

    def exists(self, relative: Path) -> bool:
        """True when the remote file exists; raises on transport failure."""
        return self._remote_size(relative) is not None

    def upload_one(self, output_dir: Path, relative: Path) -> UploadResult:
        """Upload a single file; raises on transport/protocol failure."""
        return self._upload_one(output_dir, relative)

    def _upload_one(self, output_dir: Path, relative: Path) -> UploadResult:
        local_path = output_dir / relative
        local_size = local_path.stat().st_size
        remote_size = self._remote_size(relative)
        if remote_size is not None and remote_size == local_size:
            logger.info("Skip (exists, same size): %s", relative.as_posix())
            return UploadResult(relative.as_posix(), STATUS_SKIPPED, size=local_size)

        self._ensure_dirs(relative)
        logger.info("Uploading %s (%d bytes)", relative.as_posix(), local_size)
        status, _ = self._request("PUT", relative.as_posix(), body_path=local_path)
        if status not in (200, 201, 204):
            raise RuntimeError(f"PUT {relative.as_posix()!r} failed with HTTP {status}")
        logger.info("Uploaded %s", relative.as_posix())
        return UploadResult(relative.as_posix(), STATUS_UPLOADED, size=local_size)

    def upload_all(self, output_dir: Path) -> UploadSummary:
        try:
            files = scan_local_files(output_dir)
        except OSError as exc:
            return UploadSummary(error=f"failed to scan {output_dir}: {exc}")
        if not files:
            logger.info("No uploadable files under %s", output_dir)
            return UploadSummary()

        results: list[UploadResult] = []
        for index, relative in enumerate(files, start=1):
            logger.info("[%d/%d] %s", index, len(files), relative.as_posix())
            try:
                results.append(self._upload_one(output_dir, relative))
            except Exception as exc:
                logger.error("Failed: %s (%s)", relative.as_posix(), exc)
                results.append(
                    UploadResult(relative.as_posix(), STATUS_FAILED, error=str(exc))
                )
        return UploadSummary(results=tuple(results))
