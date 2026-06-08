"""The ``Classifier`` abstract base class.

A Classifier groups a list of :class:`~src.models.NewsItem` into categories.
Classification is pure logic (no I/O), so the contract is synchronous: given a
list of items it returns a mapping of category to the items assigned to it.

Concrete implementations (for example
:class:`~src.classifier.rule_based.RuleBasedClassifier`) decide how a category
is chosen per item, but every implementation must assign exactly one category
to each item (Requirement 6.1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import NewsItem

__all__ = ["Classifier"]


class Classifier(ABC):
    """Contract for assigning categories to News_Items."""

    @abstractmethod
    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        """Group ``items`` by the category assigned to each one.

        Each input item must appear in exactly one category group, so the
        total number of items across all groups equals ``len(items)``
        (Requirement 6.1, Property 12). Returned items carry their assigned
        category (via :meth:`NewsItem.with_category`).
        """
        raise NotImplementedError
