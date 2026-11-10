# -*- coding: utf-8 -*-
"""桌宠的互动玩法。加新玩法 = 在这个目录里加一个 .py，不用改别处。

流程：她闲了很久（而且你人在电脑前）→ 随机挑一个玩法发邀请（持续时间内点气泡或点她 = 答应）
      → 没理她就过期 → 答应了就开始玩 → 玩完（或者被提醒打断）走回家。

每个玩法文件约定：

    NAME = "chase"
    TITLE = "追鼠标"
    INVITE = "好无聊…要不要陪我玩追鼠标？"     # 邀请气泡上的话
    DESC = "追你鼠标"                              # 可选：右键「玩」里悬停时的说明（2~3 个字最好）
    ICON = "chase"                                 # 可选：右键「玩」里的图标，皮肤里的 menu_<ICON>.png
    NEED = ("walk",)                            # 需要哪些图，没有就不会被挑中

    class Play:
        def __init__(self, pet, cfg): ...        # cfg = config.json 的 pet.play 段
        def start(self): ...
        def step(self, now, t):                  # 每个 tick（120ms）调一次
            返回 (表情, 是否镜像, 帧速度)；返回 None 表示玩完了
        def stop(self): ...                      # 被打断（来提醒了），收拾干净
        def on_click(self): ...                  # 可选：玩的时候你点了她

    玩法里要挪她的窗口用 move_pet(pet, x, y)；要说话用 pet.say(文字, 秒数, fun=True)
    —— fun=True 的气泡不算「有事」，不会把游戏本身打断。

配置（config.json 的 play 段，默认值见 deskpet/config.py）：
    enabled          true         关掉就不再邀请
    idle_minutes     30           她连续空闲这么久才可能邀请
    chance           0.35         满足条件时每分钟邀请的概率
    cooldown_minutes 60           邀请过一次（不管答不答应）多久之内不再邀请
    invite_seconds   25           邀请多久没理就过期
"""

import ctypes
import importlib
import os
import pkgutil
import random
import time

MOVE_MS = 40


def load_all():
    out = []
    here = os.path.dirname(os.path.abspath(__file__))
    for info in pkgutil.iter_modules([here]):
        if info.name.startswith("_"):
            continue
        try:
            mod = importlib.import_module("%s.%s" % (__name__, info.name))
        except Exception:                                          # noqa: BLE001
            continue
        if hasattr(mod, "NAME") and hasattr(mod, "Play"):
            out.append(mod)
    return out


def user_idle_seconds():
    """你多久没碰鼠标键盘了（秒）。拿不到就当你在。"""
    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
    try:
        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        return (ctypes.windll.kernel32.GetTickCount() - info.dwTime) / 1000.0
    except Exception:                                              # noqa: BLE001
        return 0.0


def move_pet(pet, x, y):
    """挪她的窗口（夹在屏幕里），气泡跟着走。"""
    x = max(0, min(int(x), pet.sw - pet.cw))
    y = max(0, min(int(y), pet.sh - pet.ch))
    pet.root.geometry("+%d+%d" % (x, y))
    pet.place_bubble()
    return x, y


class PlayManager:
    def __init__(self, pet):
        self.pet = pet
        self.mods = load_all()
        self.game = None
        self.invite = None             # 邀请气泡那条 item
        self.returning = None          # 走回家：{"x", "y", "tx", "ty"}
        now = time.time()
        self.last_busy = now           # 她最后一次「有事」的时间
        self.next_check = now + 60
        self.cooldown_until = now + 10 * 60     # 刚启动的十分钟不邀请

    # ------------------------------------------------------------------ 状态
    @property
    def cfg(self):
        return self.pet.cfg.get("play") or {}

    @property
    def active(self):
        return self.game is not None or self.returning is not None

    def available(self):
        return [m for m in self.mods
                if all(n in (self.pet.skin or {}) for n in getattr(m, "NEED", ()))]

    def note_busy(self, now):
        self.last_busy = now

    # ------------------------------------------------------------------ 邀请
    def maybe_invite(self, now):
        """闲了很久、你人在、冷却过了、运气到了 —— 就发个邀请。每分钟最多判断一次。"""
        c = self.cfg
        if not c.get("enabled", True) or self.invite or self.active or now < self.next_check:
            return
        self.next_check = now + 60
        if now - self.last_busy < float(c.get("idle_minutes", 30)) * 60:
            return
        if now < self.cooldown_until or user_idle_seconds() > 120:
            return
        stats = getattr(self.pet, "stats", None)
        if stats and not stats.can_play():
            return                                           # 累瘫了，不邀请
        chance = float(c.get("chance", 0.35)) * (stats.invite_scale() if stats else 1)
        if random.random() > chance:
            return
        self.invite_now(now)

    def invite_now(self, now=None, name=None):
        now = now or time.time()
        mods = self.available()
        if name:
            mods = [m for m in mods if m.NAME == name] or mods
        if not mods or self.invite or self.active:
            return False
        mod = random.choice(mods)
        self.cooldown_until = now + float(self.cfg.get("cooldown_minutes", 60)) * 60
        self.invite = self.pet.add_invite(
            mod.INVITE, float(self.cfg.get("invite_seconds", 25)),
            on_yes=lambda: self._yes(mod), on_expire=self.expire)
        self.pet.log("发出邀请：%s" % mod.TITLE)
        return True

    def start_now(self, mod):
        """右键「玩」里点的：你主动叫的，直接开始，不发邀请。"""
        if self.game is not None:
            self.pet.say("已经在玩啦～", 2, fun=True)
            return
        stats = getattr(self.pet, "stats", None)
        if stats and not stats.can_play():
            self.pet.say("太累了……让我歇会儿再陪你玩", 4, fun=True)
            return
        if self.invite is not None and self.invite in self.pet.items:
            self.pet.items.remove(self.invite)
        self.invite = None
        self.returning = None
        # 刚陪你玩过，一会儿别又自己跑来邀请
        self.cooldown_until = time.time() + float(self.cfg.get("cooldown_minutes", 60)) * 60
        self.accept(mod)

    def _yes(self, mod):
        if getattr(self.pet, "stats", None):
            self.pet.stats.event("invite_yes")
        self.accept(mod)

    def accept(self, mod):
        self.invite = None
        self.pet.log("开始玩：%s" % mod.TITLE)
        self.pet.behavior.interrupt()
        cfg = dict(self.cfg)
        stats = getattr(self.pet, "stats", None)
        if stats:
            # 体力越少玩得越短；各玩法自己的时长键都按这个比例缩
            for k in [k for k in cfg if k.endswith("_seconds") and k != "invite_seconds"] or []:
                cfg[k] = float(cfg[k]) * stats.play_scale()
            cfg.setdefault("chase_seconds", 45 * stats.play_scale())
        self.game = mod.Play(self.pet, cfg)
        self.game.start()

    def expire(self):
        self.invite = None
        self.pet.log("邀请没人理，过期了")
        if getattr(self.pet, "stats", None):
            self.pet.stats.event("invite_ignored")
        self.pet.say("那下次再玩吧～", 4, fun=True)

    # ------------------------------------------------------------------ 进行中
    def interrupt(self):
        """来提醒了：游戏马上停。回家的路等闲下来再走。"""
        if self.game is not None:
            self.pet.log("游戏被打断")
            self.game.stop()
            self.game = None
            self._plan_return()

    def on_click(self):
        if self.game is not None and hasattr(self.game, "on_click"):
            self.game.on_click()
            return True
        return False

    def step(self, now, t):
        """有游戏 / 在回家路上就返回这一帧，否则 None。"""
        if self.game is not None:
            r = self.game.step(now, t)
            if r is not None:
                return r
            self.pet.log("玩完了，回家")
            if getattr(self.pet, "stats", None):
                # 玩完一局（不是被打断的）：追到越多，好感多加一点（最多 +3）
                self.pet.stats.event("play_done", bonus=min(getattr(self.game, "catches", 0), 3))
            self.game = None
            self._plan_return()
        if self.returning is not None:
            return self._return_step()
        return None

    # ------------------------------------------------------------------ 回家
    def _plan_return(self):
        x, y = self.pet.root.winfo_x(), self.pet.root.winfo_y()
        tx, ty = self.pet.home_x, self.pet.home_y
        if abs(tx - x) < 4 and abs(ty - y) < 4:
            return
        self.returning = {"x": float(x), "y": float(y), "tx": tx, "ty": ty}

    def _return_step(self):
        r = self.returning
        dx, dy = r["tx"] - r["x"], r["ty"] - r["y"]
        dist = (dx * dx + dy * dy) ** 0.5
        speed = 9.0                                  # 每 tick 120ms 走 9 像素
        if dist <= speed:
            move_pet(self.pet, r["tx"], r["ty"])
            self.returning = None
            self.pet.save_pos(home=False)
            return None
        r["x"] += dx / dist * speed
        r["y"] += dy / dist * speed
        move_pet(self.pet, r["x"], r["y"])
        return ("walk" if "walk" in self.pet.skin else "idle", dx < 0, 2)
