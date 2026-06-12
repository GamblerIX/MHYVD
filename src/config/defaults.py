from __future__ import annotations

from pathlib import Path
from typing import Any

DEFAULT_RULES: list[dict[str, Any]] = [
    {"category": "videos/pv/character", "keywords": ["角色 PV", "角色PV"]},
    {"category": "videos/pv/version", "keywords": ["版本 PV", "版本PV"]},
    {"category": "videos/pv/starrytour", "keywords": ["千星纪游 PV", "千星纪游PV"]},
    {"category": "videos/pv/goldenepic", "keywords": ["黄金史诗 PV", "黄金史诗PV"]},
    {"category": "videos/pv/improvtour", "keywords": ["即兴巡演 PV", "即兴巡演PV"]},
    {"category": "videos/pv/mythprologue", "keywords": ["神话开篇 PV", "神话开篇PV"]},
    {"category": "videos/pv/ancientode", "keywords": ["太古颂歌 PV", "太古颂歌PV"]},
    {"category": "videos/pv/collab", "keywords": ["联动 PV", "联动PV"]},
    {"category": "videos/pv/salvation", "keywords": ["救世 PV", "救世PV"]},
    {
        "category": "videos/pv/dreamfinale",
        "keywords": ["美梦谢幕 PV", "美梦谢幕PV", "美梦预告 PV", "美梦预告PV"],
    },
    {"category": "videos/pv/story", "keywords": ["剧情 PV", "剧情PV"]},
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


DEFAULT_CONFIG: dict[str, Any] = {
    "source_key": "honkai-star-rail/cn",
    "classifier": "rule_based",
    "output_dir": "downloads",
    "concurrency": 1,
    "retry_count": 3,
    "timeout": 3000,
    "bilibili_cookie": None,
    "upload": {
        "webdav": {
            "url": "",
            "username": "",
            "password": "",
            "remote_dir": "MHYVD",
        },
        "gdrive": {
            "client_secret_path": "",
            "token_path": "~/.config/mhyvd/gdrive-token.json",
            "folder_name": "MHYVD",
        },
    },
    "rules": DEFAULT_RULES,
}


DEFAULT_CONFIG_PATH: Path = (
    Path(__file__).resolve().parents[2] / "config" / "default.yaml"
)


def default_config() -> dict[str, Any]:
    import copy

    return copy.deepcopy(DEFAULT_CONFIG)


__all__ = [
    "DEFAULT_RULES",
    "DEFAULT_CONFIG",
    "DEFAULT_CONFIG_PATH",
    "default_config",
]
