"""分类器插件模块"""

from .base import ClassifierPlugin
from .rule_based import RuleBasedClassifier

__all__ = ["ClassifierPlugin", "RuleBasedClassifier"]
