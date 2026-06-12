from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import urllib.request
from collections.abc import Callable, Iterable
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

logger = logging.getLogger("downloader.bilibili")

__all__ = [
    "BILIBILI_URL_RE",
    "QN_1080P",
    "QN_HIGH",
    "BilibiliResolver",
    "download_headers",
    "enc_wbi",
    "extract_bilibili_refs",
    "get_mixin_key",
    "parse_video_id",
]


BILIBILI_URL_RE = re.compile(
    r"(?:https?:)?//[^\"'<>\s]*bilibili\.com[^\"'<>\s]*",
    re.IGNORECASE,
)


QN_1080P = 80


QN_HIGH = 116


WBI_MIXIN_TAB: tuple[int, ...] = (
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
)


_WBI_CHR_FILTER = re.compile(r"[!'()*]")

_NAV_API = "https://api.bilibili.com/x/web-interface/nav"
_VIEW_API = "https://api.bilibili.com/x/web-interface/view"
_PLAYURL_API = "https://api.bilibili.com/x/player/wbi/playurl"

_BVID_PATH_RE = re.compile(r"/video/(BV[0-9A-Za-z]+)")
_AVID_PATH_RE = re.compile(r"/video/av(\d+)", re.IGNORECASE)


HttpGet = Callable[[str], dict]


def get_mixin_key(orig: str) -> str:
    return "".join(orig[index] for index in WBI_MIXIN_TAB if index < len(orig))[:32]


def enc_wbi(params: dict[str, Any], img_key: str, sub_key: str, wts: int) -> str:
    mixin_key = get_mixin_key(img_key + sub_key)
    signed = dict(params)
    signed["wts"] = wts
    query = "&".join(
        f"{quote(str(key), safe='')}="
        f"{quote(_WBI_CHR_FILTER.sub('', str(signed[key])), safe='')}"
        for key in sorted(signed)
    )
    w_rid = hashlib.md5((query + mixin_key).encode("utf-8")).hexdigest()
    return f"{query}&w_rid={w_rid}"


def parse_video_id(url: str) -> dict[str, str] | None:
    value = url.strip()
    if value.startswith("//"):
        value = f"https:{value}"
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if not (host == "bilibili.com" or host.endswith(".bilibili.com")):
        return None

    query = parse_qs(parsed.query)
    bvid = "".join(query.get("bvid", []))
    if bvid.startswith("BV"):
        return {"bvid": bvid}
    aid = "".join(query.get("aid", []))
    if aid.isdigit():
        return {"aid": aid}

    match = _BVID_PATH_RE.search(parsed.path)
    if match:
        return {"bvid": match.group(1)}
    match = _AVID_PATH_RE.search(parsed.path)
    if match:
        return {"aid": match.group(1)}
    return None


def extract_bilibili_refs(candidates: Iterable[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, str):
            continue
        ids = parse_video_id(candidate)
        if ids is None:
            continue
        key = json.dumps(ids, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        refs.append(candidate.strip())
    return refs


def download_headers(video_url: str, cookie: str | None = None) -> dict[str, str]:
    host = urlparse(video_url).hostname or ""
    if not (
        host.endswith(".bilivideo.com")
        or host == "bilivideo.com"
        or host.endswith(".bilibili.com")
        or host == "bilibili.com"
    ):
        return {}
    headers = {"Referer": "https://www.bilibili.com/"}
    if cookie:
        headers["Cookie"] = cookie
    return headers


class BilibiliResolver:
    def __init__(
        self,
        cookie: str | None = None,
        *,
        http_get: HttpGet | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.cookie = cookie or None
        self.timeout = timeout
        self._http_get = http_get or self._default_http_get
        self._wbi_keys: tuple[str, str] | None = None

    def resolve(self, ref_url: str) -> str | None:
        ids = parse_video_id(ref_url)
        if ids is None:
            return None

        view_query = "&".join(f"{key}={value}" for key, value in sorted(ids.items()))
        view = self._http_get(f"{_VIEW_API}?{view_query}")
        view_data = view.get("data") or {}
        bvid = view_data.get("bvid")
        cid = view_data.get("cid")
        if not bvid or not cid:
            logger.warning("Bilibili view lookup failed for %s: %s", ref_url, view)
            return None

        params: dict[str, Any] = {
            "bvid": bvid,
            "cid": cid,
            "fnval": 1,
            "fnver": 0,
            "fourk": 1,
        }
        if self.cookie:
            params["qn"] = QN_HIGH
        else:
            params["qn"] = QN_1080P
            params["try_look"] = 1

        img_key, sub_key = self._get_wbi_keys()
        query = enc_wbi(params, img_key, sub_key, wts=int(time.time()))
        playurl = self._http_get(f"{_PLAYURL_API}?{query}")
        data = playurl.get("data") or {}
        durl = data.get("durl") or []
        url = durl[0].get("url") if durl and isinstance(durl[0], dict) else None
        if not url:
            logger.warning(
                "Bilibili playurl returned no durl for %s (code=%s)",
                ref_url,
                playurl.get("code"),
            )
            return None
        logger.info(
            "Resolved Bilibili video %s at quality %s", bvid, data.get("quality")
        )
        return str(url)

    def _get_wbi_keys(self) -> tuple[str, str]:
        if self._wbi_keys is None:
            nav = self._http_get(_NAV_API)
            wbi_img = (nav.get("data") or {}).get("wbi_img") or {}
            img_key = _key_from_url(str(wbi_img.get("img_url", "")))
            sub_key = _key_from_url(str(wbi_img.get("sub_url", "")))
            if not img_key or not sub_key:
                raise RuntimeError("Bilibili nav response carried no WBI keys")
            self._wbi_keys = (img_key, sub_key)
        return self._wbi_keys

    def _default_http_get(self, url: str) -> dict:  # pragma: no cover
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                ),
                "Referer": "https://www.bilibili.com/",
                **({"Cookie": self.cookie} if self.cookie else {}),
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = response.read().decode("utf-8")
        parsed = json.loads(body)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"unexpected non-object JSON from {url}")
        return parsed


def _key_from_url(key_url: str) -> str:
    return PurePosixPath(urlparse(key_url).path).stem
