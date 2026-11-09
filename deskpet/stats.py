# -*- coding: utf-8 -*-
"""桌宠的数值：好感度、心情、体力。

原则：她陪你工作，数值是加分项，不是负担 ——
不惩罚、不会饿死、不需要你每天照顾。数值只影响她的心情、动作和台词，并随好感度解锁内容。

    stats = Stats(log)
    stats.event("pet")                    # 发生了什么，按 EVENTS 表加减
    stats.tick(now, resting=True)         # 每个 tick 调：心情回归、体力恢复、跨天重置
    stats.level() -> (等级, 称号, 本级起点, 下一级起点)

存在 data/pet_stats.json。加新的加分项：往 EVENTS 里加一行，在合适的地方调 stats.event(名字)；
扩展用 stats.register_event(...) 注册自己的事件。
别的程序要通知她，发 {"_cmd": "event", "name": ...}，见 deskpet/link.py。
"""

import json
import time
from datetime import datetime

from deskpet.util import data_path, save_json

STATS_PATH = data_path("pet_stats.json")

# 好感度等级：(起点, 称号)
LEVELS = [(0, "陌生"), (50, "熟悉"), (150, "信赖"), (350, "亲密"), (700, "挚友"),
          (1200, "最喜欢你了")]

MOOD_BASE = 60             # 心情没事时慢慢回到这里
MOOD_DRIFT_MIN = 10        # 每多少分钟往基准回 1 点
LONELY_HOURS = 2           # 上班时间多久没人理她，心情掉一点
ENERGY_RECOVER_MIN = 1     # 歇着时每多少分钟恢复 1 点体力

# 事件：名字 -> (好感, 心情, 体力, 每天最多算几次（None 不限）, 说明)
EVENTS = {
    "pet":            (1, 3, 0, 10, "摸摸"),
    "feed":           (1, 10, 15, 3, "喂白饭"),
    "invite_yes":     (2, 5, 0, None, "答应游玩邀请"),
    "invite_ignored": (0, -8, 0, None, "邀请没理"),
    "play_done":      (5, 20, -15, 4, "陪玩一局"),
    "greet":          (2, 5, 0, 1, "今天第一次见面"),
    "lonely":         (0, -5, 0, None, "很久没人理"),
    "move":           (0, 0, -1, None, "溜达"),
}


def _today():
    return datetime.now().strftime("%Y-%m-%d")


class Stats:
    def __init__(self, log=None):
        self.log = log or (lambda m: None)
        d = {}
        try:
            with open(STATS_PATH, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            pass
        self.affection = int(d.get("affection", 0))
        self.mood = float(d.get("mood", MOOD_BASE))
        self.energy = float(d.get("energy", 100))
        self.day = d.get("day", _today())
        self.counts = d.get("counts", {})        # 今天每种事件算了几次
        self.last_touch = float(d.get("last_touch", time.time()))   # 你最后一次跟她互动
        self.first_seen = d.get("first_seen", _today())
        self._last_tick = time.time()
        self._mood_acc = self._energy_acc = 0.0
        self.on_level_up = None                  # 升级回调 (等级, 称号)
        self._new_day_check()

    @staticmethod
    def register_event(name, affection, mood=0, energy=0, daily_cap=None, desc=""):
        """扩展注册自己的事件。同名的会覆盖。"""
        EVENTS[name] = (affection, mood, energy, daily_cap, desc or name)

    # ------------------------------------------------------------------ 读
    def level(self):
        """(等级 1 起, 称号, 本级起点, 下一级起点或 None)"""
        idx = 0
        for i, (start, _) in enumerate(LEVELS):
            if self.affection >= start:
                idx = i
        nxt = LEVELS[idx + 1][0] if idx + 1 < len(LEVELS) else None
        return idx + 1, LEVELS[idx][1], LEVELS[idx][0], nxt

    def today(self, name):
        return int(self.counts.get(name, 0))

    # ------------------------------------------------------------------ 写
    def event(self, name, bonus=0):
        """记一个事件，返回实际加了多少好感（到了每日上限就是 0）。"""
        if name not in EVENTS:
            return 0
        self._new_day_check()
        aff, mood, energy, cap, desc = EVENTS[name]
        capped = cap is not None and self.today(name) >= cap
        self.counts[name] = self.today(name) + 1
        if name not in ("move", "lonely", "invite_ignored"):
            self.last_touch = time.time()
        gained = 0 if capped else aff + int(bonus)
        before = self.level()[0]
        self.affection += gained
        # 心情、体力不受每日上限限制（喂第四碗她照样开心，只是不涨好感了）
        self.mood = max(0.0, min(100.0, self.mood + mood))
        self.energy = max(0.0, min(100.0, self.energy + energy))
        if gained:
            self.log("好感 +%d（%s），现在 %d" % (gained, desc, self.affection))
        after = self.level()
        if after[0] > before and self.on_level_up:
            self.on_level_up(after[0], after[1])
        self.save()
        return gained

    def tick(self, now, resting, working_hours):
        """working_hours: 现在是不是在她「醒着」的时间（config 的 work_start / work_end）。"""
        """每个 tick 调一次。resting: 她现在没在动（发呆、坐着、睡觉）。"""
        dt = now - self._last_tick
        self._last_tick = now
        if dt <= 0 or dt > 600:                  # 电脑睡眠醒来之类，别一下补太多
            return
        self._new_day_check()
        # 心情慢慢回到基准
        self._mood_acc += dt / 60.0 / MOOD_DRIFT_MIN
        if self._mood_acc >= 1:
            step, self._mood_acc = int(self._mood_acc), self._mood_acc % 1
            if self.mood > MOOD_BASE:
                self.mood = max(MOOD_BASE, self.mood - step)
            elif self.mood < MOOD_BASE:
                self.mood = min(MOOD_BASE, self.mood + step)
        # 歇着时恢复体力
        if resting:
            self._energy_acc += dt / 60.0 / ENERGY_RECOVER_MIN
            if self._energy_acc >= 1:
                step, self._energy_acc = int(self._energy_acc), self._energy_acc % 1
                self.energy = min(100.0, self.energy + step)
        # 上班时间很久没人理：有点寂寞（只掉心情，不扣好感）
        if working_hours and now - self.last_touch > LONELY_HOURS * 3600:
            self.event("lonely")
            self.last_touch = now                # 下一次再等两小时

    def save(self):
        save_json(STATS_PATH, {
            "affection": self.affection, "mood": round(self.mood, 1),
            "energy": round(self.energy, 1), "day": self.day, "counts": self.counts,
            "last_touch": self.last_touch, "first_seen": self.first_seen,
        })

    def _new_day_check(self):
        today = _today()
        if self.day != today:
            self.day = today
            self.counts = {}
            self.energy = 100.0                  # 睡了一觉，体力回满
            self.mood = max(self.mood, MOOD_BASE)
            self.save()

    # ------------------------------------------------------------------ 影响
    def mood_word(self):
        m = self.mood
        return "超开心" if m >= 85 else "开心" if m >= 65 else "还行" if m >= 45 \
            else "有点闷" if m >= 25 else "不开心"

    def energy_word(self):
        e = self.energy
        return "精神满满" if e >= 70 else "还好" if e >= 40 else "有点累" if e >= 15 else "累瘫了"

    def action_weights(self):
        """按心情调整小动作的权重：开心多跳舞挥手，闷闷的多坐着打哈欠。"""
        m, e = self.mood, self.energy
        w = {}
        if m >= 70:
            w.update(dance=3, wave=3, cheer=2, fish=2)
        elif m < 40:
            w.update(sit=3, yawn=2, look=2, dance=0.3, cheer=0.3)
        if e < 30:
            w.update(sit=4, yawn=3, dance=0.2, stretch=2)
        return w

    def can_wander(self):
        return self.energy >= 25

    def can_play(self):
        return self.energy >= 15

    def play_scale(self):
        """体力越少，玩得越短（最短一半）。"""
        return 0.5 + 0.5 * min(self.energy, 100) / 100

    def invite_scale(self):
        """寂寞的时候更想找你玩。"""
        return 1.6 if self.mood < 40 else 1.0
