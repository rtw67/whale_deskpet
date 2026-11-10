# -*- coding: utf-8 -*-
"""捉迷藏：她躲到屏幕外面，隔一会儿从左边、右边或者顶上探头出来，左看右看，过一会儿又缩回去。
在她缩回去之前点到她 = 捉到一次。一共几轮，越往后缩得越快。

探头的图（皮肤里有就用，没有就拿现有的图凑合）：
    peek_side_*.png        从屏幕左边探头：身子在画面外，只画伸出来的头和扶着边的手，
                           图的左边 = 屏幕边。右边探头用镜像。几帧轮流播（看来看去、眨眼）
    peek_side_oops_*.png   左边探头时被你点到（吓一跳）
    peek_top_*.png         从屏幕顶上倒挂着探头，图的上边 = 屏幕上边
    peek_top_oops_*.png    顶上探头时被你点到
没有这些图时：侧边露出小半个身子；顶上把站着的图转 180 度倒挂着露出脑袋。

接了多块屏幕时，不会往有屏幕的那一边躲（不然在另一块屏幕上整个人都看得见）。

配置（play 段）：hide_rounds 一共探几次头（默认 6）
"""

import ctypes
import random
import time

import tkinter as tk

from deskpet.play import MOVE_MS

NAME = "hide"
TITLE = "捉迷藏"
INVITE = "陪我玩捉迷藏好不好？我藏，你来找！"
DESC = "捉迷藏"
ICON = "search"
NEED = ("walk",)

SHOW = 0.45                # 没有探头图时：露出多少（身子的比例）
SLIDE_IN = (0.2, 0.6)     # 探出来用几秒（每次随机：有时嗖一下，有时慢慢探）
SLIDE_OUT = 0.2
# 每次探头的方式（权重）：正常探头 / 边探边沿着边挪 / 只探一点马上缩回去（虚晃一下，不算一轮）
MODES = (("normal", 5), ("sneak", 3), ("fake", 2))
AGAIN = 0.3                # 缩回去后，马上在附近再探一次的概率（以为你不会再看那儿）
PEEK_FIRST = 2.4           # 第一轮露几秒，之后每轮少一点
PEEK_STEP = 0.25
PEEK_MIN = 0.9
GAP = (1.2, 3.5)           # 藏着的时候隔几秒再探头
FLIP_EXPRS = ("look", "blink", "idle", "happy", "oops")   # 没有顶上探头图时，要转 180 度的表情

CAUGHT = ["被你找到啦！", "呀，又被发现了", "眼神好好…", "这都看得到！？"]
MISSED = ["嘿嘿，没抓到～", "太慢啦！"]


def _rot180(img):
    """转 180 度：Tk 的 copy 两个方向都给负的 subsample 就行。"""
    out = tk.PhotoImage()
    out.tk.call(out, "copy", img, "-subsample", -1, -1)
    return out


def _free_edges(sw):
    """哪几条边外面没有别的屏幕（虚拟桌面的范围和主屏比）。拿不到就当只有一块屏。"""
    try:
        gsm = ctypes.windll.user32.GetSystemMetrics
        vx, vy, vw = gsm(76), gsm(77), gsm(78)
    except Exception:                                              # noqa: BLE001
        return ["left", "right", "top"]
    edges = []
    if vx >= 0:
        edges.append("left")
    if vx + vw <= sw:
        edges.append("right")
    if vy >= 0:
        edges.append("top")
    return edges or ["right"]


def _dims(frames):
    return max(f.width() for f in frames), max(f.height() for f in frames)


class Play:
    def __init__(self, pet, cfg):
        self.pet = pet
        self.rounds = int(cfg.get("hide_rounds", 6))
        self.round = 0
        self.catches = 0               # 捉到几次（玩完按这个加好感）
        self.phase = "intro"           # intro / hidden / in / peek / out / caught / reveal / done
        self.phase_until = 0.0
        self.alive = False
        self.edge = None
        self.along = 0.5
        self.mode = "normal"
        self.again = False
        self.added = []                # 临时加进皮肤的表情，玩完删掉
        self.anim = None               # 正在滑：{"from", "to", "t0", "dur"}

    # ------------------------------------------------------------------ 生命周期
    def start(self):
        p = self.pet
        skin = p.skin or {}
        self.edges = _free_edges(p.sw)
        self.art_side = "peek_side" in skin
        self.art_top = "peek_top" in skin
        if not self.art_top:
            for e in FLIP_EXPRS:
                if e in skin:
                    skin["hide_top_" + e] = [_rot180(f) for f in skin[e]]
                    self.added.append("hide_top_" + e)
        # 站着的身子在窗口里的位置：底边居中、离底 4 像素（和 sprite.draw 一致）
        w = _dims(skin.get("look") or skin["idle"])[0] if skin else p.cw - 16
        h = p.base_h - 6
        self.body = (p.cw / 2 - w / 2, p.ch - 4 - h, w, h)   # x, y, 宽, 高（窗口内）
        self.alive = True
        p.say("我藏好啦，来找我～", 2.5, fun=True)
        self.phase, self.phase_until = "intro", time.time() + 2.0
        p.root.after(MOVE_MS, self._tick)

    def stop(self):
        self.alive = False
        self._cleanup()

    def on_click(self):
        if self.phase in ("in", "peek"):
            if self.mode == "fake":                        # 虚晃的时候被点到：也算一轮
                self.round += 1
                self.mode = "normal"
            self.catches += 1
            self.anim = None
            self.pet.say(random.choice(CAUGHT), 2, fun=True)
            self.phase, self.phase_until = "caught", time.time() + 1.3

    # ------------------------------------------------------------------ 每帧（画面）
    def step(self, now, t):
        if self.phase == "done":
            self._cleanup()
            self.pet.log("捉迷藏：%d 轮捉到 %d 次" % (self.rounds, self.catches))
            return None
        if self.phase == "reveal":
            return ("happy" if self.catches * 2 >= self.rounds else "sit", False, 6)
        if self.phase == "intro":
            return ("wave" if "wave" in self.pet.skin else "happy", False, 5)
        skin = self.pet.skin
        caught = self.phase == "caught"
        right = self.edge == "right"
        # 探头图：平时停在第一帧（张望），隔一阵换第二帧眨一下眼
        blink = ("frame", 1 if t % 30 >= 26 else 0)
        if self.edge == "top" and self.art_top:
            if caught and "peek_top_oops" in skin:
                return ("peek_top_oops", False, 4)
            return ("peek_top", False, blink)
        if self.edge in ("left", "right") and self.art_side:
            if caught and "peek_side_oops" in skin:
                return ("peek_side_oops", right, 4)
            return ("peek_side", right, blink)
        # 凑合版：左看右看、偶尔眨眼；顶上用转过 180 度的图
        if caught:
            e = "oops" if "oops" in skin else "happy"
        else:
            e = "blink" if t % 18 in (0, 1) else "look" if (t // 10) % 2 else "idle"
        if self.edge == "top":
            return ("hide_top_" + e if "hide_top_" + e in skin else "idle", False, 5)
        return (e, right ^ (not caught and (t // 10) % 2 == 1), 5)

    # ------------------------------------------------------------------ 内部（节奏）
    def _tick(self):
        if not self.alive:
            return
        now = time.time()
        if self.anim:
            a = self.anim
            k = min((now - a["t0"]) / a["dur"], 1.0)
            e = 1 - (1 - k) ** 2                                 # 先快后慢
            self._place(a["from"][0] + (a["to"][0] - a["from"][0]) * e,
                        a["from"][1] + (a["to"][1] - a["from"][1]) * e)
            if k >= 1:
                self.anim = None
        elif now >= self.phase_until:
            self._next(now)
        self.pet.root.after(MOVE_MS, self._tick)

    def _next(self, now):
        """当前这一段到点了：进下一段。"""
        ph = self.phase
        if ph == "intro":                                  # 打完招呼：躲起来
            self.edge = random.choice(self.edges)
            self._place(*self._spot(hidden=True))
            self.phase, self.phase_until = "hidden", now + random.uniform(*GAP)
        elif ph == "hidden":                               # 挑一条边、一种探法
            if self.again:                                 # 刚缩回去又在旁边探出来
                self.again = False
                self.along = min(max(self.along + random.uniform(-0.12, 0.12), 0), 1)
            else:
                self.edge = random.choice(self.edges)
                self.along = random.random()
            self.mode = random.choices([m for m, _ in MODES], [w for _, w in MODES])[0]
            if self.mode == "fake":
                dur, frac = 0.15, 0.5                      # 嗖地探出一半
            else:
                self.round += 1
                dur, frac = random.uniform(*SLIDE_IN), 1.0
            self._place(*self._spot(hidden=True))
            self._slide(self._spot(hidden=False, frac=frac), dur)
            self.phase, self.phase_until = "in", now + dur
        elif ph == "in":                                   # 探出来了：待一会儿，越往后越短
            if self.mode == "fake":
                stay = 0.4
            else:
                stay = max(PEEK_FIRST - PEEK_STEP * (self.round - 1), PEEK_MIN)
            if self.mode == "sneak":                       # 边看边沿着边挪一段
                self.along = min(max(self.along + random.choice((-1, 1)) * random.uniform(0.06, 0.15), 0), 1)
                self._slide(self._spot(hidden=False), stay)
            self.phase, self.phase_until = "peek", now + stay
        elif ph in ("peek", "caught"):                     # 没被点到 / 被捉到了：缩回去
            if ph == "peek" and self.mode != "fake" and random.random() < 0.5:
                self.pet.say(random.choice(MISSED), 1.5, fun=True)
            self._slide(self._spot(hidden=True), SLIDE_OUT)
            self.phase, self.phase_until = "out", now + SLIDE_OUT
        elif ph == "out":
            if self.round >= self.rounds:
                self._reveal(now)
            elif self.mode == "fake" or random.random() < AGAIN:
                # 虚晃一下之后、或者「以为你不会再看那儿」：很快在附近又探出来
                self.again = True
                self.phase, self.phase_until = "hidden", now + random.uniform(0.4, 1.0)
            else:
                self.phase, self.phase_until = "hidden", now + random.uniform(*GAP)
        elif ph == "reveal":
            self.phase = "done"
            self.alive = False

    def _reveal(self, now):
        """最后一轮完了：从最后那条边跑出来，站在屏幕里报战绩。"""
        p = self.pet
        bx, by, bw, bh = self.body
        y = 60 + (p.sh - 160 - p.ch) * self.along
        if self.edge == "left":
            x = 12 - bx
        elif self.edge == "right":
            x = p.sw - 12 - bx - bw
        else:
            x, y = 40 + (p.sw - 80 - p.cw) * self.along, 12 - by
        self.edge = None
        self._place(x, y)
        if self.catches == self.rounds:
            text = "全被你找到了…你作弊了吧！"
        elif self.catches == 0:
            text = "一次都没找到我，嘿嘿～"
        else:
            text = "%d 次里找到我 %d 次！" % (self.rounds, self.catches)
        p.say(text, 3.5, fun=True)
        self.phase, self.phase_until = "reveal", now + 3.5

    # ------------------------------------------------------------------ 内部（位置）
    def _spot(self, hidden, frac=1.0):
        """当前这条边上，探出来（或者完全藏起来）时窗口的左上角。

        图都是底边居中画在窗口里的，所以先算出图在窗口里占哪一块（x0, y0, 宽, 高），
        再让「露出来的那部分」正好在屏幕里。
        """
        p = self.pet
        side = self.edge in ("left", "right")
        art = self.art_side if side else self.art_top
        if art:
            iw, ih = _dims(p.skin["peek_side" if side else "peek_top"])
            x0, y0, w, h = p.cw / 2 - iw / 2, p.ch - 4 - ih, iw, ih
            show_w, show_h = w, h                          # 探头图整张都是露出来的部分
        else:
            x0, y0, w, h = self.body
            show_w, show_h = w * SHOW, h * SHOW
        if side:
            y = 60 + (p.sh - 160 - p.ch) * self.along      # 别贴着顶和任务栏
            show = 0 if hidden else show_w * frac
            # 凑合版和探头图都是「靠近屏幕的那一侧」露出来；右边用的是镜像
            x = show - (x0 + w) if self.edge == "left" else p.sw - show - x0
            return x, y
        x = 40 + (p.sw - 80 - p.cw) * self.along
        show = 0 if hidden else show_h * frac
        # 探头图本来就是倒挂着画的、凑合版是转了 180 度：都是图的下面那截（头）露出来
        return x, show - (y0 + h)

    def _slide(self, to, dur):
        x, y = self.pet.root.winfo_x(), self.pet.root.winfo_y()
        self.anim = {"from": (x, y), "to": to, "t0": time.time(), "dur": dur}

    def _place(self, x, y):
        # 不用 move_pet：它会把窗口夹在屏幕里，这里就是要一半在外面
        self.pet.root.geometry("+%d+%d" % (int(x), int(y)))
        self.pet.place_bubble()

    def _cleanup(self):
        skin = self.pet.skin or {}
        for name in self.added:
            skin.pop(name, None)
        self.added = []
        # 被打断时人可能还在屏幕外：先拉回屏幕里，回家的路才走得到
        p = self.pet
        x, y = p.root.winfo_x(), p.root.winfo_y()
        cx = min(max(x, 0), p.sw - p.cw)
        cy = min(max(y, 0), p.sh - p.ch)
        if (cx, cy) != (x, y):
            p.root.geometry("+%d+%d" % (cx, cy))
