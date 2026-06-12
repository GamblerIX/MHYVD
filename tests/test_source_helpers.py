from __future__ import annotations

import unittest
from urllib.parse import urljoin, urlparse

from hypothesis import given, settings
from hypothesis import strategies as st

from src.sources.base import (
    absolutize_href,
    build_news_items,
    filter_resume_cached,
    should_continue_load_more,
)


class _FakeCache:
    def __init__(self, urls: set[str]) -> None:
        self._urls = set(urls)

    def contains(self, url: str) -> bool:
        return url in self._urls


class AbsolutizeHrefTests(unittest.TestCase):
    def test_relative_href_against_base(self) -> None:
        self.assertEqual(
            absolutize_href("https://sr.mihoyo.com", "/news/123"),
            "https://sr.mihoyo.com/news/123",
        )

    def test_absolute_href_preserved(self) -> None:
        self.assertEqual(
            absolutize_href("https://sr.mihoyo.com", "https://other.com/x"),
            "https://other.com/x",
        )

    @settings(max_examples=300)
    @given(
        base=st.sampled_from(
            [
                "https://sr.mihoyo.com",
                "https://sr.mihoyo.com/news?nav=news",
                "https://hsr.hoyoverse.com/en-us/news",
                "http://example.org/a/b/c",
            ]
        ),
        href=st.one_of(
            st.text(max_size=40),
            st.sampled_from(
                [
                    "/news/123",
                    "news/456",
                    "../up",
                    "https://abs.com/p",
                    "//proto-relative.com/x",
                    "?q=1",
                    "#frag",
                    "",
                ]
            ),
        ),
    )
    def test_property_equals_urljoin(self, base: str, href: str) -> None:
        try:
            expected = urljoin(base, href)
        except ValueError:
            expected = href
        self.assertEqual(absolutize_href(base, href), expected)

    def test_malformed_href_returned_unchanged(self) -> None:
        self.assertEqual(absolutize_href("https://sr.mihoyo.com", "//["), "//[")


class BuildNewsItemsTests(unittest.TestCase):
    BASE = "https://sr.mihoyo.com"

    def test_empty_input_yields_empty_list(self) -> None:
        self.assertEqual(build_news_items(self.BASE, []), [])

    def test_relative_hrefs_absolutized(self) -> None:
        items = build_news_items(self.BASE, [("A", "/news/1"), ("B", "/news/2")])
        self.assertEqual(
            [i.url for i in items],
            ["https://sr.mihoyo.com/news/1", "https://sr.mihoyo.com/news/2"],
        )

    def test_duplicate_title_dropped(self) -> None:
        items = build_news_items(self.BASE, [("A", "/news/1"), ("A", "/news/2")])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].url, "https://sr.mihoyo.com/news/1")

    def test_duplicate_url_dropped(self) -> None:
        items = build_news_items(self.BASE, [("A", "/news/1"), ("B", "/news/1")])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "A")

    def test_empty_title_or_href_skipped(self) -> None:
        items = build_news_items(
            self.BASE, [("", "/news/1"), ("B", ""), ("C", "/news/3")]
        )
        self.assertEqual([i.title for i in items], ["C"])

    def test_first_seen_order_preserved(self) -> None:
        items = build_news_items(
            self.BASE, [("A", "/1"), ("B", "/2"), ("A", "/3"), ("C", "/4")]
        )
        self.assertEqual([i.title for i in items], ["A", "B", "C"])

    _PATH_SEGMENTS = st.lists(
        st.text(
            alphabet=st.characters(whitelist_categories=("L", "N")),
            min_size=1,
            max_size=8,
        ),
        min_size=1,
        max_size=4,
    )
    _RELATIVE_HREFS = _PATH_SEGMENTS.map(lambda segs: "/" + "/".join(segs))
    _ABSOLUTE_HREFS = st.builds(
        lambda host, segs: f"https://{host}/" + "/".join(segs),
        st.sampled_from(["sr.mihoyo.com", "hsr.hoyoverse.com", "example.com"]),
        _PATH_SEGMENTS,
    )
    _HREFS = st.one_of(_RELATIVE_HREFS, _ABSOLUTE_HREFS, st.just(""))

    @settings(max_examples=400)
    @given(
        base=st.sampled_from(
            ["https://sr.mihoyo.com", "https://hsr.hoyoverse.com/en-us/news"]
        ),
        pairs=st.lists(
            st.tuples(st.text(max_size=12), _HREFS),
            max_size=30,
        ),
    )
    def test_property_unique_absolute(
        self, base: str, pairs: list[tuple[str, str]]
    ) -> None:
        items = build_news_items(base, pairs)
        titles = [i.title for i in items]
        urls = [i.url for i in items]

        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(urls), len(set(urls)))

        for url in urls:
            parsed = urlparse(url)
            self.assertTrue(parsed.scheme, f"no scheme in {url!r}")
            self.assertTrue(parsed.netloc, f"no netloc in {url!r}")

        for item in items:
            self.assertTrue(item.title)
            self.assertTrue(item.url)

    def test_property_empty_never_raises(self) -> None:

        self.assertEqual(build_news_items(self.BASE, iter(())), [])


class FilterResumeCachedTests(unittest.TestCase):
    BASE = "https://sr.mihoyo.com"

    def test_none_cache_preserves_all(self) -> None:
        items = build_news_items(self.BASE, [("A", "/1"), ("B", "/2")])
        self.assertEqual(filter_resume_cached(items, None), items)

    def test_cached_urls_excluded(self) -> None:
        items = build_news_items(self.BASE, [("A", "/1"), ("B", "/2")])
        cache = _FakeCache({"https://sr.mihoyo.com/1"})
        filtered = filter_resume_cached(items, cache)
        self.assertEqual([i.title for i in filtered], ["B"])

    @settings(max_examples=400)
    @given(
        pairs=st.lists(
            st.tuples(
                st.text(min_size=1, max_size=8),
                st.integers(min_value=0, max_value=50).map(lambda n: f"/news/{n}"),
            ),
            max_size=30,
        ),
        cached_ids=st.sets(st.integers(min_value=0, max_value=50), max_size=20),
    )
    def test_property_resume_filter(
        self, pairs: list[tuple[str, str]], cached_ids: set[int]
    ) -> None:
        items = build_news_items(self.BASE, pairs)
        cached_urls = {f"https://sr.mihoyo.com/news/{n}" for n in cached_ids}
        cache = _FakeCache(cached_urls)

        filtered = filter_resume_cached(items, cache)
        filtered_urls = {i.url for i in filtered}

        self.assertTrue(filtered_urls.isdisjoint(cached_urls))

        expected = [i for i in items if i.url not in cached_urls]
        self.assertEqual(filtered, expected)


class ShouldContinueLoadMoreTests(unittest.TestCase):
    def test_continues_when_all_conditions_hold(self) -> None:
        self.assertTrue(should_continue_load_more(0, 10, 0.0, 100.0, True))

    def test_stops_at_max_interactions(self) -> None:
        self.assertFalse(should_continue_load_more(10, 10, 0.0, 100.0, True))

    def test_stops_at_budget(self) -> None:
        self.assertFalse(should_continue_load_more(0, 10, 100.0, 100.0, True))

    def test_stops_when_no_new_items(self) -> None:
        self.assertFalse(should_continue_load_more(0, 10, 0.0, 100.0, False))

    @settings(max_examples=500)
    @given(
        interactions=st.integers(min_value=0, max_value=1000),
        max_interactions=st.integers(min_value=0, max_value=1000),
        elapsed=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False),
        budget=st.floats(min_value=0.0, max_value=10000.0, allow_nan=False),
        new_items_loaded=st.booleans(),
    )
    def test_property_termination(
        self,
        interactions: int,
        max_interactions: int,
        elapsed: float,
        budget: float,
        new_items_loaded: bool,
    ) -> None:
        expected = (
            interactions < max_interactions and elapsed < budget and new_items_loaded
        )
        self.assertEqual(
            should_continue_load_more(
                interactions, max_interactions, elapsed, budget, new_items_loaded
            ),
            expected,
        )


if __name__ == "__main__":
    unittest.main()
