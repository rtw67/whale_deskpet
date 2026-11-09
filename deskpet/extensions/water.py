# -*- coding: utf-8 -*-
"""示例扩展：喝水提醒。默认关着，config.json 里加 "water": {"enabled": true} 打开。

演示了扩展的几种用法：注册好感事件、加台词、定时举牌、往右键菜单加泡泡。
写自己的扩展可以照着抄，约定见 extensions/__init__.py。

    "water": {"enabled": true, "every_minutes": 60}
"""

import time

NAME = "water"

_state = {"last": None}


def _cfg(pet):
    return pet.cfg.get("water") or {}


def setup(pet):
    pet.stats.register_event("drink", 1, 5, 5, 8, "喝水")
    pet.lines.add_chatter(2, ["今天喝够八杯水了吗？"])
    _state["last"] = time.time()


def poll(pet, now):
    c = _cfg(pet)
    if not c.get("enabled") or pet.off_duty():
        pet.clear_sign("water")
        return
    if now - _state["last"] >= float(c.get("every_minutes", 60)) * 60:
        # 举红牌；点她 = 喝过了
        pet.set_sign("water", expr="alarm", text="该喝水啦！\n喝完点我一下",
                     on_click=lambda: drank(pet), priority=1)


def drank(pet):
    _state["last"] = time.time()
    pet.clear_sign("water")
    pet.stats.event("drink")
    pet.say("咕嘟咕嘟～好习惯！", 3, fun=True)
    pet.cheer(2)


def menu_items(pet):
    if not _cfg(pet).get("enabled"):
        return []
    return [{"label": "喝水", "tip": "我刚喝过水", "icon": "timer", "cb": lambda: drank(pet)}]
