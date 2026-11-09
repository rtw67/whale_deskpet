# -*- coding: utf-8 -*-
"""扩展：让别的程序 / 你自己的脚本接进桌宠，而不用改框架代码。

扩展从两个地方加载：
    deskpet/extensions/*.py          内置（以 _ 开头的文件不加载）
    config.json 的 extension_dirs    以及启动参数 --ext-dir，里面每个 .py 都是一个扩展

每个扩展是一个模块，下面这些都是可选的（用到哪个写哪个）：

    NAME = "water"

    def setup(pet): ...
        启动时调一次。可以在这里：
            pet.stats.register_event("名字", 好感, 心情, 体力, 每天上限或None, "说明")
            pet.lines.add_chatter(最低好感等级, ["台词", ...])

    def poll(pet, now): ...
        每 3 秒调一次。可以看看外面的状态，决定要不要让她举牌：
            pet.set_sign("名字", expr="alarm", text="气泡上的话", on_click=函数, priority=10)
            pet.clear_sign("名字")
        expr 是她举牌时的表情：alarm（红牌「!」）、qr（二维码牌）或皮肤里有的任何表情。
        有牌子时她不溜达、不玩，点她 = 调 on_click。

    def on_message(pet, msg): ...
        收到一条消息（别的程序发来的提醒）时先问扩展，返回 True = 我处理了，框架就不再冒气泡。

    def on_open(pet, msg): ...
        你点开一条提醒时先问扩展，返回 True = 我负责打开了（比如弹自己的详情窗口）。
        都不处理的话，框架用自带的详情卡片显示 title / message。

    def on_event(pet, name): ...
        收到 {"_cmd": "event"} 加完好感之后调，可以让她说句话。

    def menu_items(pet): ...
        返回要加到右键第一层的泡泡（写法见 deskpet/menu.py），放在「归位」前面。

pet 上能用的：pet.say(文字, 秒数, fun=True) / pet.cheer(秒数) / pet.stats / pet.lines /
pet.cfg（config.json） / pet.log(文字)。任何一个扩展出错只记日志，不会把她搞挂。
"""

import importlib.util
import os
import sys
import traceback

HOOKS = ("setup", "poll", "on_message", "on_open", "on_event", "menu_items")


def _load_file(path):
    name = "deskpet_ext_" + os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def load_all(extra_dirs, log):
    dirs = [os.path.dirname(os.path.abspath(__file__))] + [d for d in extra_dirs if d]
    out = []
    for d in dirs:
        if not os.path.isdir(d):
            log("扩展目录不存在：%s" % d)
            continue
        for f in sorted(os.listdir(d)):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            path = os.path.join(d, f)
            try:
                mod = _load_file(path)
            except Exception:                                      # noqa: BLE001
                log("扩展加载失败 %s:\n%s" % (path, traceback.format_exc()))
                continue
            if any(hasattr(mod, h) for h in HOOKS):
                out.append(mod)
                log("加载扩展：%s" % getattr(mod, "NAME", f))
    return out


class Extensions:
    """把所有扩展包一层：挨个调，出错只记日志。"""

    def __init__(self, mods, log):
        self.mods = mods
        self.log = log

    def call(self, hook, *args):
        """调所有扩展的某个钩子，返回结果列表。"""
        out = []
        for m in self.mods:
            fn = getattr(m, hook, None)
            if fn is None:
                continue
            try:
                out.append(fn(*args))
            except Exception:                                      # noqa: BLE001
                self.log("扩展 %s.%s 出错:\n%s" % (getattr(m, "NAME", m.__name__), hook,
                                                 traceback.format_exc()))
        return out

    def first(self, hook, *args):
        """挨个调，有一个返回 True 就停（on_message / on_open 用）。"""
        for m in self.mods:
            fn = getattr(m, hook, None)
            if fn is None:
                continue
            try:
                if fn(*args):
                    return True
            except Exception:                                      # noqa: BLE001
                self.log("扩展 %s.%s 出错:\n%s" % (getattr(m, "NAME", m.__name__), hook,
                                                 traceback.format_exc()))
        return False
