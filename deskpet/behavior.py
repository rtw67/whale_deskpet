# -*- coding: utf-8 -*-
"""桌宠待机时的小动作和溜达。

    b = Behavior(pet)
    每个 tick（120ms）：
        忙的时候（有提醒、举牌、菜单开着、在拖她、休息时间睡觉）  b.interrupt()
        闲的时候  r = b.step(now, t)
                  r 是 (表情, 是否镜像, 帧速度) 或 None（None = 正常发呆眨眼）

两类东西：
  小动作  原地做一会儿：吃白饭、开心、扭头、摇尾巴、伸懒腰、打哈欠、张望、挥手、
          摸鱼、坐下、跳舞、掸灰……
  移动    在「家」附近左右溜达：普通走 / 背手踱步 / 小跳 / 翻滚（滚完晕一下）。
          「家」= 你最后一次把她拖到的位置，最多离家 HOME_RANGE 像素，不会越走越远去挡东西。

图都是「有就用，没有就退回」：新动作的图放进皮肤目录就自动生效，见 sprite.py。
走路类的图只画朝右的，朝左时程序镜像；翻滚只要一张抱成球的 roll_1，程序转 4 个角度。
"""

import random
import time

HOME_RANGE = 450           # 离家最远多少像素
MOVE_MS = 40               # 移动时窗口挪位置的间隔（比动画 tick 密，走起来不卡）

# 小动作：名字 -> (表情, 持续秒数, 需要的图)。需要的图没有就不做这个动作。
# 表情写成 "idle~flip" 表示镜像着用（扭头看另一边）
ACTIONS = {
    "eat":     ("eat", 4.0, "eat"),
    "cheer":   ("happy", 1.5, "happy"),
    "turn":    ("idle~flip", 2.5, "idle"),
    "wag":     ("idle", 2.0, "idle"),          # 快速切 idle 两帧 = 摇尾巴
    "stretch": ("stretch", 2.5, "stretch"),
    "yawn":    ("yawn", 2.2, "yawn"),
    "look":    ("look", 3.0, "look"),
    "wave":    ("wave", 2.4, "wave"),
    "fish":    ("fish", 5.0, "fish"),
    "sit":     ("sit", 6.0, "sit"),
    "dance":   ("dance", 3.0, "dance"),
    "dust":    ("dust", 4.0, "dust"),
}
FAST = {"wag": 1, "dance": 3, "wave": 3, "dust": 3}   # 这几个动作帧换得快一点

# 移动方式：名字 -> (每 MOVE_MS 走几像素, 需要的图, 没图时退回的表情)
MOVES = {
    "walk":   (1.6, "walk", "idle"),
    "stroll": (0.9, "stroll", "walk"),          # 背手慢慢踱
    "hop":    (2.2, "hop", "idle"),
    "roll":   (3.2, "roll", None),              # 没有抱球图就不滚
}
# 一跳的节奏（单位 MOVE_MS）：下蹲蓄力 → 腾空（只有这段往前移） → 落地下蹲
HOP_CROUCH, HOP_AIR, HOP_LAND = 4, 12, 4
HOP_TICKS = HOP_CROUCH + HOP_AIR + HOP_LAND
HOP_HEIGHT = 18            # 跳多高（像素）


def hop_pose(k):
    """一跳里第 k 步的样子：(离地多高, 用第几帧, 这一步要不要往前移)。

    姿势跟着高度走：离地才是腾空图（hop_2），贴地时一定是下蹲图（hop_1）——
    之前腾空图配着贴地平移，看着像浮在空中滑行。
    追鼠标（ui/pet_play/chase.py）也用这个。
    """
    k %= HOP_TICKS
    if k < HOP_CROUCH or k >= HOP_CROUCH + HOP_AIR:
        return 0, 0, False
    ph = (k - HOP_CROUCH + 0.5) / HOP_AIR
    return int(HOP_HEIGHT * 4 * ph * (1 - ph)), 1, True


class Behavior:
    def __init__(self, pet):
        self.pet = pet
        self.action = None         # {"name", "expr", "flip", "until"}
        self.move = None           # {"style", "x", "target", "dir", "base_y", "k"}
        self.next_action = time.time() + random.uniform(6, 12)
        self.next_move = time.time() + random.uniform(20, 40)

    # ------------------------------------------------------------------ 外部调用
    def interrupt(self):
        """有事了：原地停下，别动。"""
        self.action = None
        if self.move:
            self._stop_move(save=True)

    def step(self, now, t):
        cfg = self.pet.cfg
        if self.move:
            return self._move_frame(t)
        if self.action:
            if now < self.action["until"]:
                return self.action["expr"], self.action["flip"], FAST.get(self.action["name"])
            self.action = None
        if cfg.get("wander", True) and now >= self.next_move:
            self.next_move = now + random.uniform(*cfg.get("wander_gap", [40, 120]))
            if self._start_move():
                return self._move_frame(t)
        if now >= self.next_action:
            self.next_action = now + random.uniform(*cfg.get("action_gap", [8, 20]))
            self._start_action(now)
        return None

    # ------------------------------------------------------------------ 小动作
    def has(self, expr):
        return expr in (self.pet.skin or {})

    def start_action(self, name, duration=None):
        """外面要她马上做个动作（比如喂饭时吃白饭）。"""
        self._start_action(time.time(), name, duration)

    def _start_action(self, now, name=None, duration=None):
        names = [n for n, (_, _, need) in ACTIONS.items() if self.has(need)]
        if not names:
            return
        if name not in names:
            # 按心情 / 体力加权：开心多跳舞挥手，闷闷的、累了多坐着打哈欠（见 stats.py）
            stats = getattr(self.pet, "stats", None)
            w = stats.action_weights() if stats else {}
            name = random.choices(names, [w.get(n, 1) for n in names])[0]
        expr, dur, _ = ACTIONS[name]
        dur = duration or dur
        flip = expr.endswith("~flip")
        expr = expr.replace("~flip", "")
        if name == "look" and random.random() < 0.5:
            flip = True                                      # 往另一边张望
        self.action = {"name": name, "expr": expr, "flip": flip, "until": now + dur}

    # ------------------------------------------------------------------ 移动
    def _start_move(self):
        stats = getattr(self.pet, "stats", None)
        if stats and not stats.can_wander():
            return False                                     # 累了，不想动
        styles = [s for s, (_, need, fallback) in MOVES.items()
                  if self.has(need) or (fallback and self.has(fallback))]
        if not styles:
            return False
        # 有专门的图的走法优先；还没出图的时候普通走、小跳最常见
        weights = [3 if self.has(MOVES[s][1]) else 1 for s in styles]
        style = random.choices(styles, weights)[0]

        p = self.pet
        x, y = p.root.winfo_x(), p.root.winfo_y()
        home = p.home_x if p.home_x is not None else x
        lo = max(10, home - HOME_RANGE)
        hi = min(p.sw - p.cw - 10, home + HOME_RANGE)
        if hi - lo < 120:
            return False
        for _ in range(10):
            target = random.uniform(lo, hi)
            if abs(target - x) >= 100:
                break
        else:
            return False
        self.move = {"style": style, "x": float(x), "target": target,
                     "dir": 1 if target > x else -1, "base_y": y, "k": 0}
        p.root.after(MOVE_MS, self._tick_move)
        return True

    def _tick_move(self):
        m = self.move
        if m is None:
            return
        speed = MOVES[m["style"]][0]
        m["k"] += 1
        y = m["base_y"]
        if m["style"] == "hop":
            # 只在空中往前移，下蹲和落地时原地不动；平均速度和设定的一样
            lift, _, moving = hop_pose(m["k"])
            if moving:
                m["x"] += speed * HOP_TICKS / HOP_AIR * m["dir"]
            y = m["base_y"] - lift
        else:
            m["x"] += speed * m["dir"]
        if (m["style"] in ("walk", "stroll") and not self.has(m["style"])
              and not (m["style"] == "stroll" and self.has("walk"))):
            # 还没有走路图：拿站着的图走会像在平移滑行，加一点一颠一颠的
            y = m["base_y"] - (2 if (m["k"] // 5) % 2 else 0)
        done = (m["x"] - m["target"]) * m["dir"] >= 0
        if done and m["style"] == "hop" and m["k"] % HOP_TICKS:
            done = False                                     # 跳到一半不停，整跳做完再停
        self.pet.root.geometry("+%d+%d" % (int(m["x"]), y))
        self.pet.place_bubble()
        if done:
            style = m["style"]
            self._stop_move(save=True)
            if getattr(self.pet, "stats", None):
                self.pet.stats.event("move")                 # 溜达一趟花一点体力
            # 滚完晕一下；走完有时停下来张望
            now = time.time()
            if style == "roll" and self.has("dizzy"):
                self.action = {"name": "dizzy", "expr": "dizzy", "flip": False, "until": now + 2.5}
            elif random.random() < 0.5:
                self._start_action(now, random.choice(["look", "turn", "wave", "cheer"]))
            return
        self.pet.root.after(MOVE_MS, self._tick_move)

    def _stop_move(self, save):
        m, self.move = self.move, None
        if m is None:
            return
        self.pet.root.geometry("+%d+%d" % (int(m["x"]), m["base_y"]))
        if save:
            self.pet.save_pos(home=False)

    def _move_frame(self, t):
        """移动中这一帧画什么：(表情, 是否镜像, 帧速度)。图都是朝右的，往左走就镜像。"""
        m = self.move
        style = m["style"]
        flip = m["dir"] < 0
        need, fallback = MOVES[style][1], MOVES[style][2]
        if style == "hop":
            _, frame, _ = hop_pose(m["k"])
            if self.has("hop"):
                return ("hop", flip, ("frame", frame))     # hop_1 下蹲，hop_2 腾空
            return ("idle", flip, 2)
        if style == "roll":
            return ("roll", flip, 1)
        if self.has(need):
            return (need, flip, 2 if style == "walk" else 3)
        if fallback == "walk" and self.has("walk"):
            return ("walk", flip, 3)
        return (fallback, flip, 2)
