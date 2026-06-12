from __future__ import annotations

from ..models import Rule

__all__ = ["DEFAULT_RULES"]


DEFAULT_RULES: tuple[Rule, ...] = (
    Rule(category="videos/pv/character", keywords=("角色 PV", "角色PV")),
    Rule(category="videos/pv/version", keywords=("版本 PV", "版本PV")),
    Rule(category="videos/pv/starrytour", keywords=("千星纪游 PV", "千星纪游PV")),
    Rule(category="videos/pv/goldenepic", keywords=("黄金史诗 PV", "黄金史诗PV")),
    Rule(category="videos/pv/improvtour", keywords=("即兴巡演 PV", "即兴巡演PV")),
    Rule(category="videos/pv/mythprologue", keywords=("神话开篇 PV", "神话开篇PV")),
    Rule(category="videos/pv/ancientode", keywords=("太古颂歌 PV", "太古颂歌PV")),
    Rule(category="videos/pv/collab", keywords=("联动 PV", "联动PV")),
    Rule(category="videos/pv/salvation", keywords=("救世 PV", "救世PV")),
    Rule(
        category="videos/pv/dreamfinale",
        keywords=("美梦谢幕 PV", "美梦谢幕PV", "美梦预告 PV", "美梦预告PV"),
    ),
    Rule(category="videos/pv/story", keywords=("剧情 PV", "剧情PV")),
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
