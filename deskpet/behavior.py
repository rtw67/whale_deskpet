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

import math
import random
import time

HOME_RANGE = 260           # 离家最远多少像素（横向）
HOME_RISE = 110            # 最多比家高多少像素（往上溜达，不会往下钻进任务栏）
TRIP_LEGS = (1, 4)         # 一趟溜达分几段：走一段、停一下、再走
CROSS_CHANCE = 0.08        # 偶尔来一趟「路过」：横穿大半个屏幕再回家
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
        if self.move and self.move.get("pause"):
            # 两段之间歇脚：有动作就做动作，没有就站着（朝着刚才走的方向）
            if self.action and now < self.action["until"]:
                return self.action["expr"], self.action["flip"], FAST.get(self.action["name"])
            return ("idle", self.move["dir"] < 0, 7)
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

    def show(self, expr, duration):
        """摆一会儿某个表情（不在 ACTIONS 里的也行，比如聊天时的吓一跳）。皮肤里没这张图就算了。"""
        if self.has(expr):
            self.interrupt()
            self.action = {"name": expr, "expr": expr, "flip": False, "until": time.time() + duration}

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
        """规划一趟溜达：几个随机的落脚点，走一段停一下，最后不一定回到原地。

        之前每趟都是「在一条水平线上随便挑个 x 直线走过去」，加上家贴着屏幕边，
        看起来永远是同一条线来回 —— 现在落脚点是二维的、分好几段、每段走法和路线都不一样。
        """
        stats = getattr(self.pet, "stats", None)
        if stats and not stats.can_wander():
            return False                                     # 累了，不想动
        if not self._styles():
            return False
        p = self.pet
        x, y = float(p.root.winfo_x()), float(p.root.winfo_y())
        lo_x, hi_x, lo_y, hi_y = self._area()
        if hi_x - lo_x < 120:
            return False
        if random.random() < self._cross_chance():
            # 路过：先走到区域另一头，再回到家附近
            far = lo_x if x - lo_x > hi_x - x else hi_x
            stops = [(far, y), (random.uniform(lo_x, hi_x), self.pet.home_y)]
        else:
            stops, cx, cy = [], x, y
            for _ in range(random.randint(*TRIP_LEGS)):
                for _ in range(12):
                    tx, ty = random.uniform(lo_x, hi_x), random.uniform(lo_y, hi_y)
                    if abs(tx - cx) + abs(ty - cy) >= 90:
                        break
                stops.append((tx, ty))
                cx, cy = tx, ty
        self.move = {"stops": stops, "x": x, "y": y}
        self._next_leg()
        p.root.after(MOVE_MS, self._tick_move)
        return True

    def _cross_chance(self):
        """「路过」的概率：活动范围本来就不大的话（家贴着屏幕边、或者调小了范围），基本不横穿。"""
        p = self.pet
        c = p.cfg.get("cross_chance")
        if c is not None:
            return float(c)
        lo_x, hi_x, _, _ = self._area()
        return CROSS_CHANCE if hi_x - lo_x >= 500 else 0.0

    def _styles(self):
        return [st for st, (_, need, fallback) in MOVES.items()
                if self.has(need) or (fallback and self.has(fallback))]

    def _area(self):
        """能溜达的范围：家附近，但家贴着屏幕边时整体往里挪，两边都有地方走。"""
        p = self.pet
        min_x, max_x = 10, p.sw - p.cw - 10
        rng = float(p.cfg.get("home_range", HOME_RANGE))
        lo, hi = p.home_x - rng, p.home_x + rng
        if lo < min_x:
            hi, lo = min(max_x, hi + (min_x - lo)), min_x
        if hi > max_x:
            lo, hi = max(min_x, lo - (hi - max_x)), max_x
        base = min(p.home_y, p.sh - p.ch - 40)
        # 左右范围和高度都能在 config.json 里调：home_range / home_rise
        rise = float(p.cfg.get("home_rise", HOME_RISE))
        return lo, hi, max(10, base - rise), base

    def _next_leg(self):
        """开始下一段：换个走法，路线带一点弧度。"""
        m = self.move
        tx, ty = m["stops"].pop(0)
        styles = self._styles()
        weights = [3 if self.has(MOVES[st][1]) else 1 for st in styles]
        dist = ((tx - m["x"]) ** 2 + (ty - m["y"]) ** 2) ** 0.5
        if dist > 350:                                        # 远的时候不背手慢慢踱
            weights = [w * (0.3 if st == "stroll" else 1) for st, w in zip(styles, weights)]
        style = random.choices(styles, weights)[0]
        m.update(style=style, sx=m["x"], sy=m["y"], tx=tx, ty=ty, dist=max(dist, 1.0),
                 done=0.0, k=0, dir=1 if tx >= m["x"] else -1,
                 bend=random.uniform(-0.25, 0.25) * min(dist, 300))   # 弧线鼓出去多少

    def _tick_move(self):
        m = self.move
        if m is None:
            return
        if m.get("pause", 0) > 0:                            # 两段之间停一下（step 里放动作）
            m["pause"] -= 1
            if m["pause"] == 0:
                self.action = None
                self._next_leg()
            self.pet.root.after(MOVE_MS, self._tick_move)
            return
        speed = MOVES[m["style"]][0]
        m["k"] += 1
        lift = 0
        if m["style"] == "hop":
            # 只在空中往前移，下蹲和落地时原地不动；平均速度和设定的一样
            lift, _, moving = hop_pose(m["k"])
            if moving:
                m["done"] += speed * HOP_TICKS / HOP_AIR
        else:
            m["done"] += speed
        if (m["style"] in ("walk", "stroll") and not self.has(m["style"])
                and not (m["style"] == "stroll" and self.has("walk"))):
            # 还没有走路图：拿站着的图走会像在平移滑行，加一点一颠一颠的
            lift = 2 if (m["k"] // 5) % 2 else 0
        # 沿着一条略弯的线走：直线插值 + 垂直方向鼓出 bend * sin
        f = min(m["done"] / m["dist"], 1.0)
        dx, dy = m["tx"] - m["sx"], m["ty"] - m["sy"]
        off = m["bend"] * math.sin(math.pi * f)
        nx, ny = -dy / m["dist"], dx / m["dist"]
        lo_x, hi_x, lo_y, hi_y = self._area()
        # 弧线鼓出去也不能越界：往下会压到任务栏，往上会离家太远
        m["x"] = max(lo_x, min(hi_x, m["sx"] + dx * f + nx * off))
        m["y"] = max(lo_y, min(hi_y, m["sy"] + dy * f + ny * off))
        done = f >= 1.0
        if done and m["style"] == "hop" and m["k"] % HOP_TICKS:
            done = False                                     # 跳到一半不停，整跳做完再停
        self.pet.root.geometry("+%d+%d" % (int(m["x"]), int(m["y"]) - lift))
        self.pet.place_bubble()
        if done:
            self.pet.root.geometry("+%d+%d" % (int(m["x"]), int(m["y"])))
            if m["stops"]:
                # 段间停一下：有时张望 / 扭头，有时就站着
                m["pause"] = random.randint(15, 60)          # 0.6 ~ 2.4 秒
                if random.random() < 0.6:
                    self._start_action(time.time(), random.choice(["look", "turn", "wave"]))
                self.pet.root.after(MOVE_MS, self._tick_move)
                return
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
        self.pet.root.geometry("+%d+%d" % (int(m["x"]), int(m["y"])))
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
