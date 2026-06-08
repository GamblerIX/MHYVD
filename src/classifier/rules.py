"""Default classification rules.

Ports the legacy ``CLASSIFICATION_RULES`` from
``bak/plugins/classifier/rule_based.py`` into the new ``Rule`` model
(:class:`src.models.Rule`), which stores keywords as an immutable tuple so the
defaults themselves are immutable.

Rules are evaluated in order: the first rule that has a keyword contained in a
News_Item title wins (see :class:`src.classifier.rule_based.RuleBasedClassifier`
and Property 11). When Config supplies its own rules, they replace these
defaults entirely (Requirement 6.6).
"""

from __future__ import annotations

from ..models import Rule

__all__ = ["DEFAULT_RULES"]

#: The built-in classification rules, ported from the legacy
#: ``CLASSIFICATION_RULES`` list. Order is significant — earlier rules take
#: precedence on a keyword match (Requirement 6.2, 14.1).
DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(category="videos/pv/character", keywords=("角色 PV",)),
    Rule(category="videos/pv/version", keywords=("版本 PV",)),
    Rule(category="videos/pv/starrytour", keywords=("千星纪游 PV",)),
    Rule(category="videos/pv/goldenepic", keywords=("黄金史诗 PV",)),
    Rule(category="videos/pv/improvtour", keywords=("即兴巡演 PV",)),
    Rule(category="videos/pv/mythprologue", keywords=("神话开篇 PV",)),
    Rule(category="videos/pv/ancientode", keywords=("太古颂歌 PV",)),
    Rule(category="videos/pv/collab", keywords=("联动 PV",)),
    Rule(category="videos/pv/salvation", keywords=("救世 PV",)),
    Rule(
        category="videos/pv/dreamfinale",
        keywords=("美梦谢幕 PV", "美梦预告 PV"),
    ),
    Rule(category="videos/pv/story", keywords=("剧情 PV",)),
    Rule(category="videos/pv/others", keywords=("PV：", "PV——", "PV ：")),
    Rule(category="videos/op", keywords=("OP：", "OP——", "OP ：")),
    Rule(category="videos/ep", keywords=("EP：", "EP——", "EP ：")),
    Rule(category="videos/musicmv", keywords=("音乐 MV", "MV——", "主题曲 MV")),
    Rule(
        category="videos/animation",
        keywords=(
            "动画短片",
            "特别动画",
            "系列动画",
            "宣传动画",
            "动画 CM",
            "开场动画",
            "星旅一瞬",
        ),
    ),
    Rule(category="videos/approachsr", keywords=("走近星穹",)),
    Rule(
        category="videos/others",
        keywords=(
            "正片上线",
            "录播",
            "演唱会动画",
            "前瞻特别节目",
            "特别节目",
            "公益",
        ),
    ),
    Rule(
        category="music",
        keywords=(
            "听歌领",
            "上线音乐平台",
            "音乐专辑",
            "专辑上线",
            "音乐活动",
        ),
    ),
    Rule(
        category="activity",
        keywords=(
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
        ),
    ),
)
