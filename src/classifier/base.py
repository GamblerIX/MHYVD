from __future__ import annotations

from abc import ABC, abstractmethod

from ..models import NewsItem

__all__ = ["Classifier"]


class Classifier(ABC):
    @abstractmethod
    def classify(self, items: list[NewsItem]) -> dict[str, list[NewsItem]]:
        raise NotImplementedError
