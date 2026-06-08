"""Built-in default configuration for MHYVD.

``DEFAULT_CONFIG`` provides a complete, self-contained configuration so that
every required value (Source_Key, classifier selection, output directory,
concurrency, retry count, timeout) has a sensible fallback even when the user
configuration file omits it (Requirement 9.5, Property 24).

The classification ``rules`` are expressed as plain mappings
(``{"category": ..., "keywords": [...]}``) so they round-trip cleanly through
YAML. They are ported from the legacy ``CLASSIFICATION_RULES`` and consumed by
the classifier layer, which converts them into :class:`~src.models.Rule`
objects.

``DEFAULT_CONFIG_PATH`` is the location the :class:`~src.config.settings.Config`
loader uses when no explicit configuration path is supplied (Requirement 9.2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: The default classification rules, ported from the legacy
#: ``CLASSIFICATION_RULES``. Order matters: the classifier assigns the category
#: of the first rule whose keyword appears in a title.
DEFAULT_RULES: list[dict[str, Any]] = [
    {"category": "videos/pv/character", "keywords": ["角色 PV"]},
    {"category": "videos/pv/version", "keywords": ["版本 PV"]},
    {"category": "videos/pv/starrytour", "keywords": ["千星纪游 PV"]},
    {"category": "videos/pv/goldenepic", "keywords": ["黄金史诗 PV"]},
    {"category": "videos/pv/improvtour", "keywords": ["即兴巡演 PV"]},
    {"category": "videos/pv/mythprologue", "keywords": ["神话开篇 PV"]},
    {"category": "videos/pv/ancientode", "keywords": ["太古颂歌 PV"]},
    {"category": "videos/pv/collab", "keywords": ["联动 PV"]},
    {"category": "videos/pv/salvation", "keywords": ["救世 PV"]},
    {
        "category": "videos/pv/dreamfinale",
        "keywords": ["美梦谢幕 PV", "美梦预告 PV"],
    },
    {"category": "videos/pv/story", "keywords": ["剧情 PV"]},
    {"category": "videos/pv/others", "keywords": ["PV：", "PV——", "PV ："]},
    {"category": "videos/op", "keywords": ["OP：", "OP——", "OP ："]},
    {"category": "videos/ep", "keywords": ["EP：", "EP——", "EP ："]},
    {"category": "videos/musicmv", "keywords": ["音乐 MV", "MV——", "主题曲 MV"]},
    {
        "category": "videos/animation",
        "keywords": [
            "动画短片",
            "特别动画",
            "系列动画",
            "宣传动画",
            "动画 CM",
            "开场动画",
            "星旅一瞬",
        ],
    },
    {"category": "videos/approachsr", "keywords": ["走近星穹"]},
    {
        "category": "videos/others",
        "keywords": [
            "正片上线",
            "录播",
            "演唱会动画",
            "前瞻特别节目",
            "特别节目",
            "公益",
        ],
    },
    {
        "category": "music",
        "keywords": [
            "听歌领",
            "上线音乐平台",
            "音乐专辑",
            "专辑上线",
            "音乐活动",
        ],
    },
    {
        "category": "activity",
        "keywords": [
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
    },
]

#: The complete built-in configuration. Every required value is present so the
#: merged configuration always satisfies the required-value contract.
DEFAULT_CONFIG: dict[str, Any] = {
    "source_key": "honkai-star-rail/cn",
    "classifier": "rule_based",
    "output_dir": "downloads",
    "concurrency": 1,
    "retry_count": 3,
    "timeout": 60,
    "rules": DEFAULT_RULES,
}

#: Default location of the user configuration file, used when no explicit path
#: is provided. Resolved relative to the ``new/`` project root (two levels up
#: from this module: ``config/`` -> ``src/`` -> ``new/``... ``config/`` package
#: lives under ``src``, so the project root is three parents up).
DEFAULT_CONFIG_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "default.yaml"
)


def default_config() -> dict[str, Any]:
    """Return a deep copy of :data:`DEFAULT_CONFIG`.

    A copy is returned so callers can merge user values over the defaults
    without mutating the shared module-level dictionary.
    """
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


__all__ = [
    "DEFAULT_RULES",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_PATH",
    "default_config",
]
