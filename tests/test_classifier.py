"""Tests for the classification layer (``src/classifier``).

Covers:
- ``rules.DEFAULT_RULES`` shape and ordering (ported original rules).
- ``ClassifierRegistry`` name -> class registration and construction.
- ``RuleBasedClassifier`` first-match-or-default assignment.
- Property 11 (first-match-or-default) and Property 12 (partition with
  accurate counts) via Hypothesis.
"""

from __future__ import annotations

import unittest

from hypothesis import given
from hypothesis import strategies as st

from src.classifier.base import Classifier
from src.classifier.registry import ClassifierRegistry, UnknownClassifierError
from src.classifier.rule_based import RuleBasedClassifier
from src.classifier.rules import DEFAULT_RULES
from src.constants import DEFAULT_CATEGORY
from src.models import NewsItem, Rule
from src.registry import RegistryKeyError


# --------------------------------------------------------------------------- #
# rules.py
# --------------------------------------------------------------------------- #
class DefaultRulesTest(unittest.TestCase):
    def test_default_rules_are_rule_instances_with_tuple_keywords(self) -> None:
        self.assertGreater(len(DEFAULT_RULES), 0)
        for rule in DEFAULT_RULES:
            self.assertIsInstance(rule, Rule)
            self.assertIsInstance(rule.keywords, tuple)
            self.assertGreater(len(rule.keywords), 0)

    def test_default_rules_preserve_original_priority_order(self) -> None:
        # The first rule must be the character PV rule, matching the original
        # CLASSIFICATION_RULES ordering.
        self.assertEqual(DEFAULT_RULES[0].category, "videos/pv/character")
        self.assertIn("角色 PV", DEFAULT_RULES[0].keywords)


# --------------------------------------------------------------------------- #
# registry.py
# --------------------------------------------------------------------------- #
class _AllOthersClassifier(Classifier):
    """A trivial classifier used to exercise registry construction."""

    def __init__(self, label: str = DEFAULT_CATEGORY) -> None:
        self.label = label

    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        return {self.label: [i.with_category(self.label) for i in items]}


class ClassifierRegistryTest(unittest.TestCase):
    def test_register_and_create(self) -> None:
        registry = ClassifierRegistry()
        registry.register("rule_based", RuleBasedClassifier)
        instance = registry.create("rule_based")
        self.assertIsInstance(instance, RuleBasedClassifier)

    def test_create_forwards_kwargs(self) -> None:
        registry = ClassifierRegistry()
        registry.register("trivial", _AllOthersClassifier)
        instance = registry.create("trivial", label="music")
        self.assertIsInstance(instance, _AllOthersClassifier)
        self.assertEqual(instance.label, "music")  # type: ignore[attr-defined]

    def test_is_registered_and_names(self) -> None:
        registry = ClassifierRegistry()
        self.assertFalse(registry.is_registered("rule_based"))
        registry.register("rule_based", RuleBasedClassifier)
        self.assertTrue(registry.is_registered("rule_based"))
        self.assertIn("rule_based", registry)
        self.assertEqual(registry.names(), ["rule_based"])
        self.assertEqual(len(registry), 1)

    def test_create_unknown_raises_naming_key_without_construction(self) -> None:
        registry = ClassifierRegistry()
        with self.assertRaises(UnknownClassifierError) as ctx:
            registry.create("missing")
        self.assertIn("missing", str(ctx.exception))
        # UnknownClassifierError is a RegistryKeyError / KeyError subclass.
        self.assertIsInstance(ctx.exception, RegistryKeyError)
        self.assertIsInstance(ctx.exception, KeyError)


# --------------------------------------------------------------------------- #
# rule_based.py — example-based
# --------------------------------------------------------------------------- #
class RuleBasedClassifierExampleTest(unittest.TestCase):
    def test_uses_defaults_when_no_rules_supplied(self) -> None:
        self.assertEqual(RuleBasedClassifier().rules, DEFAULT_RULES)
        self.assertEqual(RuleBasedClassifier(None).rules, DEFAULT_RULES)
        self.assertEqual(RuleBasedClassifier([]).rules, DEFAULT_RULES)

    def test_uses_config_supplied_rules(self) -> None:
        rules = [Rule(category="custom", keywords=("special",))]
        classifier = RuleBasedClassifier(rules)
        self.assertEqual(classifier.rules, tuple(rules))
        self.assertEqual(classifier.classify_one("a special title"), "custom")

    def test_first_matching_rule_wins(self) -> None:
        rules = [
            Rule(category="first", keywords=("PV",)),
            Rule(category="second", keywords=("PV",)),
        ]
        classifier = RuleBasedClassifier(rules)
        self.assertEqual(classifier.classify_one("角色 PV 上线"), "first")

    def test_no_match_returns_default_category(self) -> None:
        classifier = RuleBasedClassifier()
        self.assertEqual(
            classifier.classify_one("this matches nothing at all"),
            DEFAULT_CATEGORY,
        )

    def test_classify_groups_and_sets_category(self) -> None:
        classifier = RuleBasedClassifier()
        items = [
            NewsItem(title="角色 PV：星", url="https://x/news/1"),
            NewsItem(title="完全无关的标题", url="https://x/news/2"),
        ]
        grouped = classifier.classify(items)
        self.assertEqual(set(grouped), {"videos/pv/character", DEFAULT_CATEGORY})
        self.assertEqual(
            grouped["videos/pv/character"][0].category, "videos/pv/character"
        )
        self.assertEqual(grouped[DEFAULT_CATEGORY][0].category, DEFAULT_CATEGORY)

    def test_classify_empty_list_returns_empty_dict(self) -> None:
        self.assertEqual(RuleBasedClassifier().classify([]), {})

    def test_default_rules_match_original_examples(self) -> None:
        classifier = RuleBasedClassifier()
        cases = {
            "新版本 PV 公开": "videos/pv/version",
            "OP：起飞": "videos/op",
            "主题曲 MV 上线": "videos/musicmv",
            "特别动画发布": "videos/animation",
            "走近星穹铁道": "videos/approachsr",
            "音乐专辑上线音乐平台": "music",
            "版本更新说明": "activity",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classifier.classify_one(title), expected)

    def test_real_hsr_titles_classify_to_specific_pv_categories(self) -> None:
        """HSR-CN titles run ``版本PV`` / ``角色PV`` etc. with no space before
        ``PV``; the rules must match that real on-site form, not just the
        space-separated variant. Regression for the bug where every specific PV
        fell through to ``videos/pv/others`` or the generic ``others``.
        """
        classifier = RuleBasedClassifier()
        cases = {
            "《崩坏：星穹铁道》3.7版本PV 「成为昨日的明天」": "videos/pv/version",
            "《崩坏：星穹铁道》阿格莱雅角色PV——「致命浪漫」": "videos/pv/character",
            "《崩坏：星穹铁道》白厄角色PV 「日冕」": "videos/pv/character",
            "《崩坏：星穹铁道》黄金史诗PV 「再见，昔涟」": "videos/pv/goldenepic",
            "《崩坏：星穹铁道》即兴巡演PV 「吉凶之外」": "videos/pv/improvtour",
            "《崩坏：星穹铁道》神话开篇PV 「诸神尽喑之歌」": "videos/pv/mythprologue",
            "《崩坏：星穹铁道》救世PV 「开拓者」": "videos/pv/salvation",
            "《崩坏：星穹铁道》美梦谢幕PV 「致意」": "videos/pv/dreamfinale",
            "《崩坏：星穹铁道》千星纪游PV 「飞镝追星」": "videos/pv/starrytour",
            "《崩坏：星穹铁道》× Fate[UBW] 联动PV 「相见『很』晚」": "videos/pv/collab",
        }
        for title, expected in cases.items():
            with self.subTest(title=title):
                self.assertEqual(classifier.classify_one(title), expected)


# --------------------------------------------------------------------------- #
# rule_based.py — property-based
# --------------------------------------------------------------------------- #
# Keyword/category alphabet kept small so generated titles realistically
# contain (or avoid) keywords. Categories are distinct labels.
_keywords = st.text(alphabet="abcde", min_size=1, max_size=4)
_categories = st.text(alphabet="XYZW", min_size=1, max_size=3)


@st.composite
def _rule_lists(draw: st.DrawFn) -> list[Rule]:
    n = draw(st.integers(min_value=0, max_value=6))
    rules: list[Rule] = []
    for i in range(n):
        kws = draw(st.lists(_keywords, min_size=1, max_size=3))
        rules.append(Rule(category=f"cat{i}-{draw(_categories)}", keywords=tuple(kws)))
    return rules


class RuleBasedClassifierPropertyTest(unittest.TestCase):
    """Property tests for the rule-based classifier."""

    @given(rules=_rule_lists(), title=st.text(alphabet="abcdef ", max_size=20))
    def test_first_match_or_default(self, rules: list[Rule], title: str) -> None:
        """Property 11: classification is first-match-or-default.

        Validates: Requirements 6.2, 6.3, 14.1
        """
        classifier = RuleBasedClassifier(rules)
        result = classifier.classify_one(title)

        # Compute the expected category by an independent first-match scan.
        expected = DEFAULT_CATEGORY
        for rule in rules:
            if any(kw in title for kw in rule.keywords):
                expected = rule.category
                break

        self.assertEqual(result, expected)

        # If the result is not the default, some keyword of the chosen rule
        # must actually be contained in the title.
        if result != DEFAULT_CATEGORY:
            chosen = next(r for r in rules if r.category == result)
            self.assertTrue(any(kw in title for kw in chosen.keywords))

    @given(
        rules=_rule_lists(),
        titles=st.lists(st.text(alphabet="abcdef ", max_size=20), max_size=25),
    )
    def test_partition_with_accurate_counts(
        self, rules: list[Rule], titles: list[str]
    ) -> None:
        """Property 12: classification partitions items with accurate counts.

        Validates: Requirements 6.1, 6.5
        """
        classifier = RuleBasedClassifier(rules)
        items = [
            NewsItem(title=t, url=f"https://x/news/{i}") for i, t in enumerate(titles)
        ]
        grouped = classifier.classify(items)

        # The groups partition the input: total count is preserved and each
        # group's items all carry that group's category.
        total = sum(len(v) for v in grouped.values())
        self.assertEqual(total, len(items))
        for category, group in grouped.items():
            for item in group:
                self.assertEqual(item.category, category)

        # Per-category counts (what Pipeline_Result records) match group sizes,
        # and every original item is represented exactly once (by URL).
        counts = {c: len(g) for c, g in grouped.items()}
        self.assertEqual(sum(counts.values()), len(items))
        seen_urls = [item.url for group in grouped.values() for item in group]
        self.assertCountEqual(seen_urls, [i.url for i in items])


if __name__ == "__main__":
    unittest.main()
