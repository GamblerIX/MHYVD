"""Tests for the pure download path helpers in ``src.downloader.paths``.

Covers unit/example cases plus property-based tests for Property 15
(output-path construction) from the design document.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from src.downloader.paths import (
    FALLBACK_FILENAME,
    build_output_path,
    extract_news_id,
    sanitize_filename,
)

try:  # pragma: no cover - exercised only when hypothesis is installed
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
        # \t and \n are Unicode control chars (category Cc), stripped before
        # whitespace collapsing rather than treated as separators.
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
        # Fullwidth 'A' (U+FF21) normalises to ASCII 'A'.
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


@unittest.skipUnless(HAS_HYPOTHESIS, "hypothesis is not installed")
class SanitizeFilenamePropertyTests(unittest.TestCase):
    """Property 15 — sanitized titles are safe and non-empty.

    **Validates: Requirements 7.3**
    """

    @settings(max_examples=500)
    @given(st.text())
    def test_no_invalid_chars_and_non_empty(self, title: str) -> None:
        result = sanitize_filename(title)
        # Never empty.
        self.assertTrue(result)
        # Contains none of the invalid filename characters.
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
        # Constrain category/output_dir to non-empty, separator-free pieces so
        # the resulting Path has a predictable shape.
        output_dir = (output_dir or "out").replace("/", "_").replace("\\", "_")
        category = (category or "videos").replace("/", "_").replace("\\", "_")
        # news_id is digits-or-"unknown" in practice; keep it separator-free
        # so the composed filename stays a single path component.
        news_id = news_id.replace("/", "_").replace("\\", "_")
        path = build_output_path(output_dir, category, title, news_id)
        expected_name = f"{sanitize_filename(title)} [{news_id}].mp4"
        self.assertEqual(path.name, expected_name)
        self.assertEqual(path.parent, Path(output_dir) / category)
        # The sanitized portion of the filename never contains invalid chars.
        self.assertFalse(INVALID_FILENAME_CHARS.intersection(sanitize_filename(title)))


if __name__ == "__main__":
    unittest.main()
