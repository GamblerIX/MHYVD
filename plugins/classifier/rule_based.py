"""
基于规则的分类器
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from collections import defaultdict

from core.models import NewsItem
from plugins.classifier.base import ClassifierPlugin
from core.plugin import PluginMetadata, PluginRegistry

logger = logging.getLogger("classifier.rule_based")

DEFAULT_CATEGORY = "others"


@dataclass(frozen=True)
class Rule:
    """分类规则"""

    category: str
    keywords: List[str]


CLASSIFICATION_RULES: List[Rule] = [
    Rule(category="videos/pv/character", keywords=["角色 PV"]),
    Rule(category="videos/pv/version", keywords=["版本 PV"]),
    Rule(category="videos/pv/starrytour", keywords=["千星纪游 PV"]),
    Rule(category="videos/pv/goldenepic", keywords=["黄金史诗 PV"]),
    Rule(category="videos/pv/improvtour", keywords=["即兴巡演 PV"]),
    Rule(category="videos/pv/mythprologue", keywords=["神话开篇 PV"]),
    Rule(category="videos/pv/ancientode", keywords=["太古颂歌 PV"]),
    Rule(category="videos/pv/collab", keywords=["联动 PV"]),
    Rule(category="videos/pv/salvation", keywords=["救世 PV"]),
    Rule(
        category="videos/pv/dreamfinale",
        keywords=["美梦谢幕 PV", "美梦预告 PV"],
    ),
    Rule(category="videos/pv/story", keywords=["剧情 PV"]),
    Rule(category="videos/pv/others", keywords=["PV：", "PV——", "PV ："]),
    Rule(category="videos/op", keywords=["OP：", "OP——", "OP ："]),
    Rule(category="videos/ep", keywords=["EP：", "EP——", "EP ："]),
    Rule(category="videos/musicmv", keywords=["音乐 MV", "MV——", "主题曲 MV"]),
    Rule(
        category="videos/animation",
        keywords=[
            "动画短片",
            "特别动画",
            "系列动画",
            "宣传动画",
            "动画 CM",
            "开场动画",
            "星旅一瞬",
        ],
    ),
    Rule(category="videos/approachsr", keywords=["走近星穹"]),
    Rule(
        category="videos/others",
        keywords=[
            "正片上线",
            "录播",
            "演唱会动画",
            "前瞻特别节目",
            "特别节目",
            "公益",
        ],
    ),
    Rule(
        category="music",
        keywords=[
            "听歌领",
            "上线音乐平台",
            "音乐专辑",
            "专辑上线",
            "音乐活动",
        ],
    ),
    Rule(
        category="activity",
        keywords=[
            "活动跃迁",
            "活动说明",
            "双倍掉落",
            "三倍掉落",
            "限时双倍",
            "限时三倍",
            "激励计划",
            "版本更新说明",
            "预下载",
            "更新预告",
            "更新维护预告",
            "无名勋礼",
            "商店更新",
            "商店上新",
            "新增关卡",
            "任务说明",
            "专题展示页",
            "循星归程",
            "差分宇宙",
            "跃迁概率公示",
        ],
    ),
]


class RuleBasedClassifier(ClassifierPlugin):
    """基于规则的新闻分类器"""

    metadata = PluginMetadata(
        name="rule_based",
        version="1.0.0",
        description="基于关键词规则的新闻分类器",
    )

    def __init__(self, rules: Optional[List[Rule]] = None, **kwargs):
        self.rules = rules or CLASSIFICATION_RULES

    def _classify_one(self, title: str) -> str:
        """对单条新闻进行分类"""
        for rule in self.rules:
            for keyword in rule.keywords:
                if keyword in title:
                    return rule.category
        return DEFAULT_CATEGORY

    async def classify(
        self, items: List[NewsItem], **kwargs
    ) -> Dict[str, List[NewsItem]]:
        """
        对新闻列表进行分类

        Args:
            items: 新闻条目列表

        Returns:
            按类别分组的新闻字典
        """
        result: Dict[str, List[NewsItem]] = defaultdict(list)

        for item in items:
            category = self._classify_one(item.title)
            categorized_item = item.with_category(category)
            result[category].append(categorized_item)

        for category, items_list in result.items():
            logger.info("  %-35s → %3d 条", category, len(items_list))

        return dict(result)


PluginRegistry.register("rule_based", RuleBasedClassifier)
