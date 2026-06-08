"""The keyword rule-based classifier.

Assigns each News_Item the category of the first rule that has a keyword
contained in the item's title, falling back to the default category
``others`` when no rule keyword matches (Requirement 6.2, 6.3, 14.1;
Property 11). Items are returned grouped by category with each item carrying
its assigned category (Property 12).

Rules come from Config when supplied, otherwise from the built-in
:data:`~src.classifier.rules.DEFAULT_RULES` (Requirement 6.6).
"""

from __future__ import annotations

from ..constants import DEFAULT_CATEGORY
from ..models import NewsItem, Rule
from .base import Classifier
from .rules import DEFAULT_RULES

__all__ = ["RuleBasedClassifier"]


class RuleBasedClassifier(Classifier):
    """Classifies News_Items by first-matching keyword rule."""

    #: The name this classifier registers under in the ClassifierRegistry.
    name = "rule_based"

    def __init__(self, rules: tuple[Rule, ...] | list[Rule] | None = None) -> None:
        """Create a classifier using ``rules`` or the built-in defaults.

        Passing ``None`` (or an empty sequence) selects
        :data:`DEFAULT_RULES`; otherwise the supplied rules replace the
        defaults entirely (Requirement 6.6). Rules are stored as a tuple so the
        configured order is preserved and immutable.
        """
        self.rules: tuple[Rule, ...] = tuple(rules) if rules else DEFAULT_RULES

    def classify_one(self, title: str) -> str:
        """Return the category for a single ``title``.

        Scans the rules in order and returns the category of the first rule
        with a keyword contained in ``title``; returns
        :data:`~src.constants.DEFAULT_CATEGORY` when none match.
        """
        for rule in self.rules:
            for keyword in rule.keywords:
                if keyword in title:
                    return rule.category
        return DEFAULT_CATEGORY

    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        """Group ``items`` by their first-matching-rule category.

        Each item is assigned exactly one category and appears in exactly one
        group, so the groups partition the input (Property 12). Category groups
        appear in first-seen order, and items keep their relative order within
        a group.
        """
        result: dict[str, list[NewsItem]] = {}
        for item in items:
            category = self.classify_one(item.title)
            result.setdefault(category, []).append(item.with_category(category))
        return result
