from __future__ import annotations

import unittest
from pathlib import Path

from src.downloader.paths import (
    FALLBACK_CATEGORY,
    FALLBACK_FILENAME,
    build_output_path,
    extract_news_id,
    sanitize_category,
    sanitize_filename,
)

try:  # pragma: no cover
    from hypothesis import given, settings
    from hypothesis import strategies as st

    HAS_HYPOTHESIS = True
except ImportError:  # pragma: no cover
    HAS_HYPOTHESIS = False


INVALID_FILENAME_CHARS = set('<>:"/\\|?*')


class SanitizeFilenameTests(unittest.TestCase):
    def test_plain_title_unchanged(self) -> None:
        self.assertEqual(sanitize_filename("Hello World"), "Hello World")

    def test_replaces_invalid_characters(self) -> None:
        result = sanitize_filename('a<b>c:d"e/f\\g|h?i*j')
        for char in INVALID_FILENAME_CHARS:
            self.assertNotIn(char, result)

    def test_collapses_whitespace(self) -> None:
        self.assertEqual(sanitize_filename("a    b   c"), "a b c")

    def test_tab_and_newline_are_control_chars_removed(self) -> None:

        self.assertEqual(sanitize_filename("a\tb\nc"), "abc")

    def test_strips_surrounding_spaces_and_dots(self) -> None:
        self.assertEqual(sanitize_filename("  . title . "), "title")

    def test_empty_falls_back_to_untitled(self) -> None:
        self.assertEqual(sanitize_filename(""), FALLBACK_FILENAME)

    def test_only_invalid_chars_falls_back(self) -> None:
        self.assertEqual(sanitize_filename('/\\:*?"<>|'), FALLBACK_FILENAME)

    def test_only_whitespace_falls_back(self) -> None:
        self.assertEqual(sanitize_filename("   \t\n  "), FALLBACK_FILENAME)

    def test_control_characters_stripped(self) -> None:
        self.assertEqual(sanitize_filename("a\x00b\x07c"), "abc")

    def test_nfkc_normalization(self) -> None:

        self.assertEqual(sanitize_filename("\uff21BC"), "ABC")

    def test_unicode_title_preserved(self) -> None:
        self.assertEqual(sanitize_filename("崩坏：星穹铁道"), "崩坏 星穹铁道")


class ExtractNewsIdTests(unittest.TestCase):
    def test_extracts_numeric_id(self) -> None:
        self.assertEqual(
            extract_news_id("https://sr.mihoyo.com/news/123456?foo=bar"),
            "123456",
        )

    def test_extracts_first_match(self) -> None:
        self.assertEqual(extract_news_id("https://x.com/news/42/news/99"), "42")

    def test_no_match_returns_unknown(self) -> None:
        self.assertEqual(
            extract_news_id("https://sr.mihoyo.com/article/abc"), "unknown"
        )

    def test_non_numeric_returns_unknown(self) -> None:
        self.assertEqual(extract_news_id("https://sr.mihoyo.com/news/abc"), "unknown")


class BuildOutputPathTests(unittest.TestCase):
    def test_basic_path_construction(self) -> None:
        result = build_output_path("downloads", "videos/pv", "My Title", "123")
        self.assertEqual(result, Path("downloads") / "videos/pv" / "My Title [123].mp4")

    def test_accepts_path_output_dir(self) -> None:
        result = build_output_path(Path("/tmp/out"), "others", "Clip", "7")
        self.assertEqual(result, Path("/tmp/out") / "others" / "Clip [7].mp4")

    def test_sanitizes_title_in_path(self) -> None:
        result = build_output_path("downloads", "videos", "bad/name:here", "9")
        self.assertEqual(result.name, "bad name here [9].mp4")

    def test_empty_title_uses_fallback(self) -> None:
        result = build_output_path("downloads", "videos", "", "9")
        self.assertEqual(result.name, f"{FALLBACK_FILENAME} [9].mp4")

    def test_extension_derived_from_video_url(self) -> None:
        result = build_output_path(
            "downloads",
            "videos/pv",
            "My Title",
            "123",
            video_url="https://fastcdn.mihoyo.com/x/abc_123.mov",
        )
        self.assertEqual(result.name, "My Title [123].mov")

    def test_extension_ignores_query_string(self) -> None:
        result = build_output_path(
            "downloads",
            "videos",
            "Clip",
            "7",
            video_url="https://h/v.mp4?token=abc",
        )
        self.assertEqual(result.name, "Clip [7].mp4")

    def test_unknown_extension_defaults_to_mp4(self) -> None:

        result = build_output_path(
            "downloads", "videos", "Clip", "7", video_url="https://h/stream"
        )
        self.assertEqual(result.name, "Clip [7].mp4")

    def test_no_video_url_defaults_to_mp4(self) -> None:
        result = build_output_path("downloads", "videos", "Clip", "7")
        self.assertEqual(result.name, "Clip [7].mp4")


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class SanitizeCategoryTests(unittest.TestCase):
    def test_plain_category_unchanged(self) -> None:
        self.assertEqual(
            sanitize_category("videos/pv/character"), "videos/pv/character"
        )

    def test_parent_traversal_segments_dropped(self) -> None:
        self.assertEqual(sanitize_category("../../etc"), "etc")

    def test_dot_segments_dropped(self) -> None:
        self.assertEqual(sanitize_category("videos/./pv"), "videos/pv")

    def test_leading_separator_dropped(self) -> None:
        self.assertEqual(sanitize_category("/videos/pv"), "videos/pv")

    def test_backslash_treated_as_separator(self) -> None:
        self.assertEqual(sanitize_category("..\\videos"), "videos")

    def test_all_dots_segment_dropped(self) -> None:
        self.assertEqual(sanitize_category(".../videos"), "videos")

    def test_pure_traversal_falls_back(self) -> None:
        self.assertEqual(sanitize_category("../.."), FALLBACK_CATEGORY)

    def test_empty_falls_back(self) -> None:
        self.assertEqual(sanitize_category(""), FALLBACK_CATEGORY)


class BuildOutputPathCategoryTests(unittest.TestCase):
    def test_traversal_category_stays_inside_output_dir(self) -> None:
        result = build_output_path("downloads", "../../etc", "Clip", "7")
        self.assertEqual(result.parent, Path("downloads") / "etc")

    def test_pure_traversal_category_uses_fallback(self) -> None:
        result = build_output_path("downloads", "../..", "Clip", "7")
        self.assertEqual(result.parent, Path("downloads") / FALLBACK_CATEGORY)


class SanitizeFilenamePropertyTests(unittest.TestCase):
    @settings(max_examples=500)
    @given(st.text())
    def test_no_invalid_chars_and_non_empty(self, title: str) -> None:
        result = sanitize_filename(title)

        self.assertTrue(result)

        self.assertFalse(INVALID_FILENAME_CHARS.intersection(result))

    @settings(max_examples=500)
    @given(st.text())
    def test_no_control_characters(self, title: str) -> None:
        import unicodedata

        result = sanitize_filename(title)
        for char in result:
            self.assertFalse(
                unicodedata.category(char).startswith("C"),
                f"control char {char!r} leaked through",
            )

    @settings(max_examples=300)
    @given(st.text(), st.text(), st.text(), st.text())
    def test_build_output_path_shape(
        self, output_dir: str, category: str, title: str, news_id: str
    ) -> None:

        output_dir = (output_dir or "out").replace("/", "_").replace("\\", "_")
        category = (category or "videos").replace("/", "_").replace("\\", "_")

        news_id = news_id.replace("/", "_").replace("\\", "_")
        path = build_output_path(output_dir, category, title, news_id)
        expected_name = f"{sanitize_filename(title)} [{news_id}].mp4"
        self.assertEqual(path.name, expected_name)
        self.assertEqual(path.parent, Path(output_dir) / sanitize_category(category))

        self.assertFalse(INVALID_FILENAME_CHARS.intersection(sanitize_filename(title)))


if __name__ == "__main__":
    unittest.main()
