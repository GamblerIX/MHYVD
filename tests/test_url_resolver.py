from __future__ import annotations

import random
import unittest

from src.downloader.url_resolver import (
    MEDIA_EXTENSIONS,
    MEDIA_URL_RE,
    dedupe_media_urls,
    normalize_media_url,
)

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    _HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    _HAS_HYPOTHESIS = False


def _is_valid(candidate: str) -> bool:
    return normalize_media_url(candidate) is not None


class NormalizeMediaUrlTests(unittest.TestCase):
    def test_trims_surrounding_whitespace(self) -> None:
        self.assertEqual(
            normalize_media_url("  https://host/video.mp4  "),
            "https://host/video.mp4",
        )

    def test_fixes_protocol_relative_scheme(self) -> None:
        self.assertEqual(
            normalize_media_url("//host/video.mp4"),
            "https://host/video.mp4",
        )

    def test_accepts_all_media_extensions(self) -> None:
        for ext in MEDIA_EXTENSIONS:
            with self.subTest(ext=ext):
                url = f"https://host/clip{ext}"
                self.assertEqual(normalize_media_url(url), url)

    def test_accepts_mov_extension(self) -> None:

        url = "https://fastcdn.mihoyo.com/content-v2/hkrpg/163575/abc_123.mov"
        self.assertEqual(normalize_media_url(url), url)

    def test_accepts_webm_and_m4v_extensions(self) -> None:
        for ext in (".webm", ".m4v"):
            with self.subTest(ext=ext):
                url = f"https://host/clip{ext}"
                self.assertEqual(normalize_media_url(url), url)

    def test_rejects_mov_snapshot_thumbnail(self) -> None:

        url = (
            "https://fastcdn.mihoyo.com/content-v2/hkrpg/163575/abc_123.mov"
            "?x-oss-process=video%2Fsnapshot%2Ct_0%2Cf_jpg%2Ch_600%2Cm_fast"
        )
        self.assertIsNone(normalize_media_url(url))

    def test_accepts_http_and_https(self) -> None:
        self.assertEqual(normalize_media_url("http://host/v.mkv"), "http://host/v.mkv")
        self.assertEqual(
            normalize_media_url("https://host/v.flv"), "https://host/v.flv"
        )

    def test_extension_check_is_case_insensitive(self) -> None:
        url = "https://host/Video.MP4"
        self.assertEqual(normalize_media_url(url), url)

    def test_keeps_query_string_for_valid_media(self) -> None:
        url = "https://host/v.mp4?token=abc123"
        self.assertEqual(normalize_media_url(url), url)

    def test_rejects_empty_and_whitespace(self) -> None:
        self.assertIsNone(normalize_media_url(""))
        self.assertIsNone(normalize_media_url("   "))

    def test_rejects_non_http_scheme(self) -> None:
        self.assertIsNone(normalize_media_url("ftp://host/v.mp4"))
        self.assertIsNone(normalize_media_url("file:///tmp/v.mp4"))

    def test_rejects_missing_scheme(self) -> None:
        self.assertIsNone(normalize_media_url("host/v.mp4"))

    def test_rejects_non_media_extension(self) -> None:
        self.assertIsNone(normalize_media_url("https://host/page.html"))
        self.assertIsNone(normalize_media_url("https://host/image.jpg"))
        self.assertIsNone(normalize_media_url("https://host/noext"))

    def test_rejects_oss_snapshot_thumbnail(self) -> None:
        url = "https://oss.host/v.mp4?x-oss-process=video/snapshot,t_1000,m_fast"
        self.assertIsNone(normalize_media_url(url))

    def test_rejects_oss_snapshot_case_insensitive(self) -> None:
        url = "https://oss.host/v.mp4?x-oss-process=video/SNAPSHOT,t_1"
        self.assertIsNone(normalize_media_url(url))

    def test_allows_non_snapshot_oss_process(self) -> None:
        url = "https://oss.host/v.mp4?x-oss-process=video/transcode"
        self.assertEqual(normalize_media_url(url), url)

    def test_rejects_non_string_input(self) -> None:
        self.assertIsNone(normalize_media_url(None))  # type: ignore[arg-type]


class DedupeMediaUrlsTests(unittest.TestCase):
    def test_empty_input_returns_empty(self) -> None:
        self.assertEqual(dedupe_media_urls([]), [])

    def test_drops_invalid_candidates(self) -> None:
        candidates = [
            "https://host/a.mp4",
            "not a url",
            "ftp://host/b.mp4",
            "https://host/page.html",
        ]
        self.assertEqual(dedupe_media_urls(candidates), ["https://host/a.mp4"])

    def test_preserves_first_seen_order(self) -> None:
        candidates = [
            "https://host/b.mp4",
            "https://host/a.mp4",
            "https://host/c.mkv",
        ]
        self.assertEqual(dedupe_media_urls(candidates), candidates)

    def test_dedupes_after_normalization(self) -> None:
        candidates = [
            "  https://host/a.mp4 ",
            "//host/a.mp4",
            "https://host/a.mp4",
        ]
        self.assertEqual(dedupe_media_urls(candidates), ["https://host/a.mp4"])

    def test_keeps_only_first_of_duplicate_group(self) -> None:
        candidates = [
            "https://host/a.mp4",
            "https://host/b.mp4",
            "https://host/a.mp4",
            "https://host/b.mp4",
        ]
        self.assertEqual(
            dedupe_media_urls(candidates),
            ["https://host/a.mp4", "https://host/b.mp4"],
        )


class MediaUrlRegexTests(unittest.TestCase):
    def test_matches_mov_in_html(self) -> None:
        html = '<video src="https://fastcdn.mihoyo.com/x/abc_123.mov"></video>'
        self.assertEqual(
            MEDIA_URL_RE.findall(html),
            ["https://fastcdn.mihoyo.com/x/abc_123.mov"],
        )

    def test_matches_webm_and_m4v_in_html(self) -> None:
        html = "a https://h/v.webm b https://h/v.m4v c"
        self.assertEqual(
            MEDIA_URL_RE.findall(html),
            ["https://h/v.webm", "https://h/v.m4v"],
        )


class Property14MediaUrlNormalizationAndDedupe(unittest.TestCase):
    def _assert_property(self, candidates: list[str]) -> None:
        result = dedupe_media_urls(candidates)

        for url in result:
            self.assertEqual(normalize_media_url(url), url)

        self.assertEqual(len(result), len(set(result)))

        expected: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = normalize_media_url(candidate)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            expected.append(normalized)
        self.assertEqual(result, expected)

        valid_normalized = {
            normalize_media_url(c)
            for c in candidates
            if normalize_media_url(c) is not None
        }
        self.assertEqual(set(result), valid_normalized)

    if _HAS_HYPOTHESIS:

        @settings(max_examples=300)
        @given(
            st.lists(
                st.one_of(
                    st.builds(
                        lambda scheme, host, name, ext: (
                            f"{scheme}://{host}/{name}{ext}"
                        ),
                        st.sampled_from(["http", "https"]),
                        st.sampled_from(["host", "a.b.com", "cdn.example"]),
                        st.text(
                            alphabet="abcXYZ0_-",
                            min_size=1,
                            max_size=6,
                        ),
                        st.sampled_from([".mp4", ".mkv", ".flv", ".MP4"]),
                    ),
                    st.builds(
                        lambda name: f"//host/{name}.mp4",
                        st.text(alphabet="abc012", min_size=1, max_size=5),
                    ),
                    st.just("https://oss/v.mp4?x-oss-process=video/snapshot,t_1"),
                    st.sampled_from(
                        [
                            "https://host/page.html",
                            "ftp://host/v.mp4",
                            "host/v.mp4",
                            "",
                            "   ",
                            "not a url",
                        ]
                    ),
                ),
                max_size=12,
            )
        )
        def test_property_hypothesis(self, candidates: list[str]) -> None:
            self._assert_property(candidates)

    else:

        def test_property_random_fallback(self) -> None:
            rng = random.Random(20240607)
            pool = [
                "https://host/a.mp4",
                "http://host/b.mkv",
                "https://cdn.example/c.flv",
                "//host/d.mp4",
                "  https://host/a.mp4  ",
                "https://host/Video.MP4",
                "https://host/v.mp4?token=1",
                "https://oss/v.mp4?x-oss-process=video/snapshot,t_1",
                "https://host/page.html",
                "ftp://host/v.mp4",
                "host/v.mp4",
                "",
                "   ",
                "not a url",
            ]
            for _ in range(500):
                size = rng.randint(0, 12)
                candidates = [rng.choice(pool) for _ in range(size)]
                self._assert_property(candidates)


if __name__ == "__main__":
    unittest.main()
