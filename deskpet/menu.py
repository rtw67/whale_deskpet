# -*- coding: utf-8 -*-
"""桌宠的右键菜单：在她身边冒出一圈蓝色泡泡，可以一层套一层。

    menu = BubbleMenu(root, key_color, owner=她的窗口, log=..., icons=load_icons(...))
    menu.open(cx, cy, items, side)      # cx, cy 是她在屏幕上的中心点

每个泡泡是一个 dict（也兼容老写法的 tuple）：
    {"label": "消息",                   泡泡上的字，**2~3 个字**（有图标时不显示，也别拿它当说明用）
     "tip": "构建完成",                  悬停时外侧标签的说明，也是 2~3 个字，默认 = label
     "cb": 回调,                         普通项：点了先收起菜单再执行；None = 灰掉不能点
     "sub": True,                        子菜单项：cb 返回下一层的泡泡列表
     "icon": "job"}                      可选：用皮肤里的 menu_job.png 当图标
    老写法 (文字, 回调) / (文字, 回调, True) 也行。

点子菜单项：这一圈缩回她身上，再冒出下一圈；下一圈的第一个是「返回」。层数不限。
一圈最多 MAX_ITEMS 个，放不下自动分页：最后一个变「下一页」，翻过去后第一个功能位是「上一页」。
泡泡排成弧线：她在屏幕右半边就往左上展开，左半边就往右上展开。

收起：点了普通项 / 点到别处 / 再右键她一次 / 8 秒没碰。
窗口用抠色透明，泡泡之外的地方点击会直接穿透到下面的窗口。

「点到别处」不能靠窗口失焦来判断：右键她的时候 Windows 会把焦点交给她的窗口，
菜单刚弹出来就会收到失焦、立刻又收回去（看起来就是右键没反应）。
所以菜单开着时直接每 50ms 看一眼鼠标键，按下时指针不在泡泡上、也不在她身上，才收起。
"""

import ctypes
import math
import os

import tkinter as tk

from deskpet.theme import BG, FONT

BUBBLE = "#2f7fd6"         # 泡泡蓝（和她头发同一个色系）
BUBBLE_HOVER = "#4a9cf0"
BUBBLE_EDGE = "#d4ebff"
SHINE = "#bfe0ff"          # 左上角的高光
DANGER = "#3b4a63"         # 「退出」「返回」用深灰蓝，和功能泡泡分开
DANGER_HOVER = "#556580"
DISABLED = "#6b7586"
TEXT = "#ffffff"

R = 160                    # 弧线半径
D = 50                     # 泡泡直径
SPAN = 140                 # 弧线张开的角度（8 个泡泡时相邻间距约 56，比直径大一点，不挤）
MAX_ITEMS = 8              # 一圈最多几个（含「返回」），再多就挤了
AUTO_CLOSE_MS = 8000
POP_FRAMES = 7             # 冒出来的帧数（16ms 一帧）
FOLD_FRAMES = 5            # 缩回去的帧数

# 泡泡图标：<皮肤目录>/menu_<名字>.png，悬停用 menu_<名字>_hover.png（大一号）。
# 泡泡项里写 "icon": "名字" 就用那个图标；没写的按下面这张表用文字找；都没有就用代码画的泡泡。
# 皮肤里自带的备用图标：msg play feed status home exit back prev next job work perf daily qr
# dnd refresh calendar today chat alarm timer gift trophy outfit sleep sound mute more ok close
# add delete search folder log power save team help fish dice gear start pause music
ICON_KEYS = {"消息": "msg", "玩": "play", "喂饭": "feed", "状态": "status", "归位": "home",
             "退出": "exit", "返回": "back", "上一页": "prev", "下一页": "next"}
DARK_LABELS = ("退出", "返回")


def load_icons(skin_dir):
    """返回 {图标名: (普通图, 悬停图)}，把皮肤目录里所有 menu_*.png 都读进来。
    必须在 Tk 根窗口建好之后调用。
    """
    out = {}
    if not os.path.isdir(skin_dir):
        return out
    for f in os.listdir(skin_dir):
        if not (f.startswith("menu_") and f.endswith(".png")) or f.endswith("_hover.png"):
            continue
        key = f[5:-4]
        hover = os.path.join(skin_dir, "menu_%s_hover.png" % key)
        try:
            img = tk.PhotoImage(file=os.path.join(skin_dir, f))
            out[key] = (img, tk.PhotoImage(file=hover) if os.path.exists(hover) else img)
        except tk.TclError:
            continue
    return out


def _mouse_down():
    """左键或右键现在是不是按着（全局，不管点在哪个程序上）。"""
    try:
        gks = ctypes.windll.user32.GetAsyncKeyState
        return bool(gks(0x01) & 0x8000 or gks(0x02) & 0x8000)
    except Exception:                                              # noqa: BLE001
        return False


def _norm(item):
    if isinstance(item, dict):
        it = dict(item)
    else:
        it = {"label": item[0], "cb": item[1], "sub": len(item) > 2 and bool(item[2])}
    it.setdefault("tip", it["label"])
    it.setdefault("sub", False)
    return it


def _dark(it):
    return it["label"] in DARK_LABELS or it.get("back")


class BubbleMenu:
    def __init__(self, root, key, owner=None, log=None, icons=None):
        """owner: 她自己的窗口。点在她身上不算「点到别处」，交给她自己的事件处理。
        icons: load_icons() 的结果；有图标的泡泡画图，没有的用代码画。
        """
        self.log = log or (lambda msg: None)
        self.icons = icons or {}
        self.root = root
        self.key = key
        self.owner = owner or root
        self.win = None
        self.canvas = None
        self.stack = []            # 每一层 {"items", "page", "sub"}，最后一个是当前这层
        self.targets = []          # 当前这层每个泡泡的最终位置 [(x, y, item)]
        self.animating = False
        self.timer = None
        self.watching = False
        self.was_down = True

    @property
    def is_open(self):
        return self.win is not None

    @property
    def depth(self):
        return len(self.stack)

    # ------------------------------------------------------------------ 打开 / 收起
    def open(self, cx, cy, items, side="right"):
        """side: 她在屏幕哪半边（决定往哪边展开）。"""
        self.close()
        self.size = 2 * (R + D + 130)             # 多留一大圈给悬停时的文字标签（透明的，不挡点击）
        self.side = side
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=self.key)
        win.wm_attributes("-transparentcolor", self.key)
        win.geometry("%dx%d+%d+%d" % (self.size, self.size,
                                      cx - self.size // 2, cy - self.size // 2))
        c = tk.Canvas(win, width=self.size, height=self.size, bg=self.key, highlightthickness=0)
        c.pack()
        self.win, self.canvas = win, c
        self.stack = [{"items": [_norm(i) for i in items], "page": 0, "sub": False}]
        self._pop(self._visible())
        self._arm()

    def close(self, reason=""):
        if self.win is not None and reason:
            self.log("菜单收起：%s" % reason)
        if self.timer is not None:
            try:
                self.root.after_cancel(self.timer)
            except tk.TclError:
                pass
            self.timer = None
        if self.win is not None:
            self.win.destroy()
            self.win = self.canvas = None
        self.stack, self.targets = [], []

    # ------------------------------------------------------------------ 层级
    def _enter(self, item):
        """点了子菜单项：这一圈缩回去，下一圈冒出来（第一个是「返回」）。"""
        children = [_norm(i) for i in (item["cb"]() or [])]
        if not children:
            children = [_norm({"label": "空", "tip": "这里还没有东西", "cb": None})]
        self.stack.append({"items": children, "page": 0, "sub": True})
        self._refresh()

    def _back(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self._refresh()

    def _turn(self, delta):
        self.stack[-1]["page"] += delta
        self._refresh()

    def _refresh(self):
        """当前这圈缩回去，按 stack 顶上那层（和它的页码）重新冒出来。"""
        self._fold(lambda: self._pop(self._visible()))
        self._arm()

    def _pages(self, level):
        """把这一层的项分页。第一页之后要留一个「上一页」，不是最后一页要留一个「下一页」。"""
        items = level["items"]
        cap = MAX_ITEMS - (1 if level["sub"] else 0)            # 子菜单要留「返回」
        if len(items) <= cap:
            return [items]
        pages, i = [], 0
        while i < len(items):
            room = cap - (1 if pages else 0)
            if len(items) - i <= room:
                pages.append(items[i:])
                break
            room -= 1
            pages.append(items[i:i + room])
            i += room
        return pages

    def _visible(self):
        """当前这层、当前这页实际要画的泡泡（带上返回 / 上一页 / 下一页）。"""
        level = self.stack[-1]
        pages = self._pages(level)
        level["page"] = max(0, min(level["page"], len(pages) - 1))
        p, n = level["page"], len(pages)
        out = []
        if level["sub"]:
            out.append(_norm({"label": "返回", "tip": "回到上一层", "cb": self._back, "nav": True,
                              "back": True}))
        if p > 0:
            out.append(_norm({"label": "上一页", "tip": "上一页（%d/%d）" % (p, n),
                              "cb": lambda: self._turn(-1), "nav": True}))
        out += pages[p]
        if p < n - 1:
            out.append(_norm({"label": "下一页", "tip": "下一页（%d/%d）" % (p + 2, n),
                              "cb": lambda: self._turn(1), "nav": True}))
        return out

    # ------------------------------------------------------------------ 动画
    def _layout(self, items):
        o = self.size / 2
        center = 135 if self.side == "right" else 45            # 左上 / 右上
        n = len(items)
        # 少的时候别摊太开：按 8 个时的间距排，整体还是以左上 / 右上为中心
        step = SPAN / (MAX_ITEMS - 1)
        span = step * (n - 1)
        start = center + span / 2
        out = []
        for i, it in enumerate(items):
            if len(it["label"]) > 3:          # 名字只能是两三个字
                self.log("泡泡名太长：%s（提示：%s）" % (it["label"], it["tip"]))
            a = math.radians(start - i * step)
            out.append((o + R * math.cos(a), o - R * math.sin(a), it))
        return out

    def _pop(self, items):
        """从她身上一个接一个冒出来。"""
        c, o = self.canvas, self.size / 2
        if c is None:
            return
        self.targets = self._layout(items)
        self.animating = True
        n = len(self.targets)

        def frame(k):
            if self.canvas is not c:
                return
            c.delete("all")
            for i, (tx, ty, it) in enumerate(self.targets):
                p = min(max((k - i * 0.6) / POP_FRAMES, 0), 1)
                if p <= 0:
                    continue
                e = 1 - (1 - p) ** 3                             # 先快后慢
                self._bubble(c, i, o + (tx - o) * e, o + (ty - o) * e,
                             D * (0.4 + 0.6 * e), it, final=(p >= 1))
            if k < POP_FRAMES + n * 0.6:
                c.after(16, frame, k + 1)
            else:
                self.animating = False

        frame(1)

    def _fold(self, then):
        """当前这圈缩回她身上，缩完调 then()。"""
        c, o = self.canvas, self.size / 2
        if c is None:
            return
        old = self.targets
        self.animating = True

        def frame(k):
            if self.canvas is not c:
                return
            c.delete("all")
            e = 1 - k / FOLD_FRAMES
            if e > 0:
                for i, (tx, ty, it) in enumerate(old):
                    self._bubble(c, i, o + (tx - o) * e, o + (ty - o) * e,
                                 D * (0.4 + 0.6 * e), it, final=False)
                c.after(16, frame, k + 1)
            else:
                then()

        frame(1)

    # ------------------------------------------------------------------ 画一个泡泡
    def _bubble(self, c, i, x, y, d, it, final):
        tag = "b%d" % i
        label = it["label"]
        icon = self._icon(it)
        if icon:
            # 图标泡泡：Tk 缩放不了图片，飞的路上就是图本身
            c.create_image(x, y, image=icon[0], tags=tag)
        else:
            fill = DISABLED if it.get("cb") is None else DANGER if _dark(it) else BUBBLE
            r = d / 2
            c.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline=BUBBLE_EDGE,
                          width=2, tags=tag)
            c.create_oval(x - r * 0.62, y - r * 0.68, x - r * 0.18, y - r * 0.3,
                          fill=SHINE, outline="", tags=tag)
            if d > D * 0.8:
                text = label
                size = 9
                if len(text) > 3 and text.isascii():             # 时间、数字：小一号放一行
                    size = 8
                elif len(text) > 3:                              # 中文放不下：折成两行
                    text = text[:3] + "\n" + text[3:6]
                c.create_text(x, y + 2, text=text, fill=TEXT, font=(FONT, size, "bold"),
                              justify="center", tags=tag)
        if final and it.get("cb") is not None:
            self._hover(c, tag, it, x, y)
            # 点击：图标泡泡和画出来的泡泡都要绑（之前只绑过画的那一支，换图标后全点不动）
            c.tag_bind(tag, "<Button-1>", lambda e, it=it: self._click(it))

    def _hover(self, c, tag, it, x, y):
        """悬停：变大变亮，外侧（背对她的方向）出一个深色标签写完整说明。"""
        icon = self._icon(it)
        o = self.size / 2
        items = c.find_withtag(tag)

        def enter(e):
            if self.animating:
                return
            if icon:
                c.itemconfigure(items[0], image=icon[1])
            else:
                c.itemconfigure(items[0], fill=DANGER_HOVER if _dark(it) else BUBBLE_HOVER)
                c.scale(tag, x, y, 1.12, 1.12)
            c.configure(cursor="hand2")
            dx, dy = x - o, y - o
            n = math.hypot(dx, dy) or 1
            t = c.create_text(0, 0, text=it["tip"], fill=TEXT, font=(FONT, 9), tags="cap")
            x0, y0, x1, y1 = c.bbox(t)
            # 标签沿径向往外放，长的标签多推一点，免得压到泡泡上
            dist = D / 2 + 14 + abs(dx / n) * (x1 - x0) / 2 + abs(dy / n) * (y1 - y0) / 2
            c.move(t, x + dx / n * dist, y + dy / n * dist)
            x0, y0, x1, y1 = c.bbox(t)
            # 她贴着屏幕边时，外侧的标签会伸出屏幕：往回挪到屏幕里
            wx, wy = self.win.winfo_rootx(), self.win.winfo_rooty()
            sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
            shift_x = min(0, sw - 12 - (wx + x1)) or max(0, 12 - (wx + x0))
            shift_y = min(0, sh - 12 - (wy + y1)) or max(0, 12 - (wy + y0))
            if shift_x or shift_y:
                c.move(t, shift_x, shift_y)
                x0, y0, x1, y1 = c.bbox(t)
            c.create_rectangle(x0 - 8, y0 - 3, x1 + 8, y1 + 3, fill=BG, outline=BUBBLE_EDGE,
                               tags="cap")
            c.tag_raise(t)

        def leave(e):
            if icon:
                c.itemconfigure(items[0], image=icon[0])
            elif c.coords(items[0]):
                c.itemconfigure(items[0], fill=DANGER if _dark(it) else BUBBLE)
                c.scale(tag, x, y, 1 / 1.12, 1 / 1.12)
            c.configure(cursor="")
            c.delete("cap")

        c.tag_bind(tag, "<Enter>", enter)
        c.tag_bind(tag, "<Leave>", leave)

    def _icon(self, it):
        return self.icons.get(it.get("icon") or ICON_KEYS.get(it["label"], ""))

    def _click(self, it):
        if self.animating:
            return
        if it.get("sub"):
            self._enter(it)
        elif it.get("nav"):                       # 返回 / 翻页：菜单不收起
            it["cb"]()
        else:
            # 先收起再执行：「退出」会把整个窗口销毁，收起放在后面就会去碰已经没了的窗口
            self.close()
            self.root.after(10, it["cb"])

    # ------------------------------------------------------------------ 点到别处
    def _arm(self):
        """点到别处就收、一段时间没碰也收（每进一层重新计时）。"""
        if self.timer is not None:
            self.root.after_cancel(self.timer)
        self.timer = self.root.after(AUTO_CLOSE_MS, lambda: self.close("超时"))
        if not self.watching:
            self.watching = True
            self.was_down = True          # 打开菜单的那一下右键还按着，不算
            self.root.after(50, self._watch)

    def _watch(self):
        if self.win is None:
            self.watching = False
            return
        down = _mouse_down()
        if down and not self.was_down:                 # 刚按下去的那一刻
            x, y = self.root.winfo_pointerxy()
            if not (self._on_bubble(x, y) or self._inside(self.owner, x, y)):
                self.close("点到别处 (%d,%d)" % (x, y))
                self.watching = False
                return
        self.was_down = down
        self.root.after(50, self._watch)

    @staticmethod
    def _inside(w, x, y):
        try:
            return (w.winfo_rootx() <= x < w.winfo_rootx() + w.winfo_width()
                    and w.winfo_rooty() <= y < w.winfo_rooty() + w.winfo_height())
        except tk.TclError:
            return False

    def _on_bubble(self, x, y):
        """指针下面是不是一个泡泡（泡泡之间的透明空隙不算）。"""
        if self.win is None or not self._inside(self.win, x, y):
            return False
        lx, ly = x - self.win.winfo_rootx(), y - self.win.winfo_rooty()
        return bool(self.canvas.find_overlapping(lx, ly, lx, ly))
