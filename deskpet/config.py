# -*- coding: utf-8 -*-
"""配置：项目根目录的 config.json（不进 git，照着 config.example.json 写），缺的项用默认值。

每次 reload() 都重读文件，改完存盘几秒内生效。
"""

import copy
import os

from deskpet.util import ROOT, load_json

CONFIG_PATH = os.path.join(ROOT, "config.json")

DEFAULTS = {
    "name": "鲸鱼娘",              # 她叫什么（状态卡片上显示）
    "port": 47823,                 # 本地端口：单实例锁 + 别的程序给她发提醒
    "skin": "skins/whale",         # 形象目录（相对项目根目录）
    "extension_dirs": [],          # 额外的扩展目录，见 deskpet/extensions/__init__.py
    "work_start": "09:00",         # 这个时间段以外、以及周末，她在睡觉
    "work_end": "20:00",
    "wander": True,                # 闲着时溜达
    "home_range": 260,             # 溜达范围：离家左右各多少像素
    "home_rise": 110,              # 最多比家高多少像素
    "wander_gap": [40, 120],       # 多少秒溜达一次
    "action_gap": [8, 20],         # 多少秒做一个小动作
    "oops_words": ["失败", "出错", "错误", "过期"],    # 提醒标题带这些字，她会滑跪
    "fullscreen_quiet": True,      # 有程序全屏（看视频、投屏、打游戏）时藏起来，提醒攒着
    "play": {
        "enabled": True,
        "idle_minutes": 30,
        "chance": 0.35,
        "cooldown_minutes": 60,
        "invite_seconds": 25,
        "chase_seconds": 45,
    },
}


def _merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    return _merge(DEFAULTS, load_json(CONFIG_PATH, {}) or {})
