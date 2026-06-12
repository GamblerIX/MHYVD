from __future__ import annotations

from ..constants import DEFAULT_CATEGORY
from ..models import NewsItem, Rule
from .base import Classifier
from .rules import DEFAULT_RULES

__all__ = ["RuleBasedClassifier"]


class RuleBasedClassifier(Classifier):
    name = "rule_based"

    def __init__(self, rules: tuple[Rule, ...] | list[Rule] | None = None) -> None:
        self.rules: tuple[Rule, ...] = tuple(rules) if rules else DEFAULT_RULES

    def classify_one(self, title: str) -> str:
        for rule in self.rules:
            for keyword in rule.keywords:
                if keyword in title:
                    return rule.category
        return DEFAULT_CATEGORY

    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        result: dict[str, list[NewsItem]] = {}
        for item in items:
            category = self.classify_one(item.title)
            result.setdefault(category, []).append(item.with_category(category))
        return result
