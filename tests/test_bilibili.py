from __future__ import annotations

import hashlib
import unittest
from urllib.parse import parse_qs, urlparse

from src.downloader.bilibili import (
    QN_1080P,
    QN_HIGH,
    WBI_MIXIN_TAB,
    BilibiliResolver,
    download_headers,
    enc_wbi,
    extract_bilibili_refs,
    get_mixin_key,
    parse_video_id,
)


class MixinKeyTests(unittest.TestCase):
    def test_mixin_key_is_reordered_prefix(self) -> None:
        orig = "".join(chr(ord("0") + i % 10) for i in range(64))
        expected = "".join(orig[i] for i in WBI_MIXIN_TAB)[:32]
        self.assertEqual(get_mixin_key(orig), expected)
        self.assertEqual(len(get_mixin_key(orig)), 32)


class EncWbiTests(unittest.TestCase):
    def test_signature_matches_md5_of_sorted_query(self) -> None:
        img_key = "7cd084941338484aae1ad9425b84077c"
        sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        query = enc_wbi({"foo": "114", "bar": "514"}, img_key, sub_key, wts=1700000000)
        base, _, w_rid = query.rpartition("&w_rid=")
        self.assertEqual(base, "bar=514&foo=114&wts=1700000000")
        mixin = get_mixin_key(img_key + sub_key)
        self.assertEqual(w_rid, hashlib.md5((base + mixin).encode("utf-8")).hexdigest())

    def test_filtered_chars_are_stripped_from_values(self) -> None:
        query = enc_wbi({"a": "x!'()*y"}, "k" * 32, "s" * 32, wts=1)
        self.assertIn("a=xy", query)


class ParseVideoIdTests(unittest.TestCase):
    def test_player_iframe_bvid(self) -> None:
        url = "//player.bilibili.com/player.html?bvid=BV1xx411c7mD&page=1"
        self.assertEqual(parse_video_id(url), {"bvid": "BV1xx411c7mD"})

    def test_player_iframe_aid(self) -> None:
        url = "https://player.bilibili.com/player.html?aid=170001"
        self.assertEqual(parse_video_id(url), {"aid": "170001"})

    def test_video_page_bvid(self) -> None:
        url = "https://www.bilibili.com/video/BV1xx411c7mD/?spm_id_from=x"
        self.assertEqual(parse_video_id(url), {"bvid": "BV1xx411c7mD"})

    def test_video_page_avid(self) -> None:
        url = "https://www.bilibili.com/video/av170001"
        self.assertEqual(parse_video_id(url), {"aid": "170001"})

    def test_non_bilibili_url_is_rejected(self) -> None:
        self.assertIsNone(parse_video_id("https://example.com/video/BV1xx411c7mD"))
        self.assertIsNone(parse_video_id("https://www.bilibili.com/read/cv1"))


class ExtractRefsTests(unittest.TestCase):
    def test_dedupes_by_video_id_and_preserves_order(self) -> None:
        refs = extract_bilibili_refs(
            [
                "https://example.com/page",
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "//player.bilibili.com/player.html?bvid=BV1xx411c7mD",
                "https://www.bilibili.com/video/av170001",
            ]
        )
        self.assertEqual(
            refs,
            [
                "https://www.bilibili.com/video/BV1xx411c7mD",
                "https://www.bilibili.com/video/av170001",
            ],
        )


class DownloadHeadersTests(unittest.TestCase):
    def test_bilivideo_host_gets_referer(self) -> None:
        headers = download_headers("https://upos-sz-mirror.bilivideo.com/v.mp4?e=1")
        self.assertEqual(headers, {"Referer": "https://www.bilibili.com/"})

    def test_cookie_is_attached_when_provided(self) -> None:
        headers = download_headers(
            "https://cn-gd.bilivideo.com/v.mp4", cookie="SESSDATA=abc"
        )
        self.assertEqual(headers["Cookie"], "SESSDATA=abc")

    def test_other_hosts_get_no_extra_headers(self) -> None:
        self.assertEqual(download_headers("https://fastcdn.mihoyo.com/v.mp4"), {})


def _fake_http_get(
    calls: list[str], *, durl_url: str | None = "https://cn.bilivideo.com/v.mp4"
):
    def http_get(url: str) -> dict:
        calls.append(url)
        if "/x/web-interface/nav" in url:
            return {
                "data": {
                    "wbi_img": {
                        "img_url": "https://i0.hdslb.com/bfs/wbi/abc123.png",
                        "sub_url": "https://i0.hdslb.com/bfs/wbi/def456.png",
                    }
                }
            }
        if "/x/web-interface/view" in url:
            return {"data": {"bvid": "BV1xx411c7mD", "cid": 279786}}
        if "/x/player/wbi/playurl" in url:
            durl = [{"url": durl_url}] if durl_url else []
            return {"code": 0, "data": {"quality": 80, "durl": durl}}
        raise AssertionError(f"unexpected URL {url}")

    return http_get


class BilibiliResolverTests(unittest.TestCase):
    def test_resolves_durl_url_anonymously_with_try_look(self) -> None:
        calls: list[str] = []
        resolver = BilibiliResolver(http_get=_fake_http_get(calls))
        url = resolver.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
        self.assertEqual(url, "https://cn.bilivideo.com/v.mp4")
        playurl = next(c for c in calls if "/playurl" in c)
        params = parse_qs(urlparse(playurl).query)
        self.assertEqual(params["qn"], [str(QN_1080P)])
        self.assertEqual(params["try_look"], ["1"])
        self.assertIn("w_rid", params)

    def test_cookie_requests_higher_quality_without_try_look(self) -> None:
        calls: list[str] = []
        resolver = BilibiliResolver(
            cookie="SESSDATA=abc", http_get=_fake_http_get(calls)
        )
        resolver.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
        playurl = next(c for c in calls if "/playurl" in c)
        params = parse_qs(urlparse(playurl).query)
        self.assertEqual(params["qn"], [str(QN_HIGH)])
        self.assertNotIn("try_look", params)

    def test_missing_durl_yields_none(self) -> None:
        calls: list[str] = []
        resolver = BilibiliResolver(http_get=_fake_http_get(calls, durl_url=None))
        self.assertIsNone(
            resolver.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
        )

    def test_unparseable_reference_yields_none_without_network(self) -> None:
        calls: list[str] = []
        resolver = BilibiliResolver(http_get=_fake_http_get(calls))
        self.assertIsNone(resolver.resolve("https://example.com/page"))
        self.assertEqual(calls, [])

    def test_wbi_keys_are_cached_across_resolves(self) -> None:
        calls: list[str] = []
        resolver = BilibiliResolver(http_get=_fake_http_get(calls))
        resolver.resolve("https://www.bilibili.com/video/BV1xx411c7mD")
        resolver.resolve("https://www.bilibili.com/video/av170001")
        nav_calls = [c for c in calls if "/nav" in c]
        self.assertEqual(len(nav_calls), 1)


if __name__ == "__main__":
    unittest.main()
