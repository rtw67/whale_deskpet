# -*- coding: utf-8 -*-
"""她的样子：皮肤目录（默认 skins/whale/）里的图片，没有图就用程序画的像素小团子占位。

换图规则（准备好了直接放进去，不用改代码）：
    <皮肤目录>/<表情>_<序号>.png       比如 idle_1.png、idle_2.png、alarm_1.png
    表情: idle（发呆） blink（眨眼） talk（说话） alarm（举红牌：有事要你处理） qr（要扫码）
          happy（开心） sleep（睡觉） eat（吃白饭） oops（滑跪认错）
    移动: walk（走路，4 帧） stroll（背手踱步，4 帧） hop（1 下蹲 2 腾空） roll（抱成球，1 帧）
          dizzy（滚完晕乎乎）—— 都只画朝右的，往左走程序镜像；roll 程序转出 4 个角度
    小动作: stretch yawn look wave fish sit dance dust（见 behavior.py 的 ACTIONS）
    同一个表情多张就按序号轮播。缺的表情退回 idle（举牌类会在头顶补画一块牌子）；
    连 idle 都没有就整套用程序画的占位团子。
    精灵表（一整张大图）用 tools/slice_sheet.py 切成上面这样的小图。
    PNG 用**硬边**（像素风、没有半透明边）：窗口是靠一个颜色抠透明的，
    半透明的边会混出一圈粉边。角色建议 100 像素高左右（窗口大小会跟着图走）。
"""

import glob
import os
import re

import tkinter as tk

from deskpet.util import ROOT

SKIN_DIR = os.path.join(ROOT, "skins", "whale")      # app 启动时按 config.json 的 skin 改
EXPRESSIONS = ("idle", "blink", "talk", "alarm", "qr", "happy", "sleep", "eat", "oops",
               "walk", "stroll", "hop", "roll", "dizzy",
               "stretch", "yawn", "look", "wave", "fish", "sit", "dance", "dust")

SCALE = 4              # 一个像素画成 4×4
W, H = 16, 15          # 网格大小

COLORS = {
    "o": "#3b2f2f",    # 描边
    "w": "#fff1d6",    # 身体
    "s": "#f3dcb4",    # 身体下半的阴影
    "p": "#ffb0a8",    # 腮红
    "e": "#2b2b2b",    # 眼睛 / 嘴
    "h": "#ffffff",    # 眼睛高光
}


def _body():
    """椭圆身体：里面填色，贴边的一圈是描边，下半截加一点阴影。"""
    cx, cy, rx, ry = 7.5, 8.2, 7.3, 6.4
    inside = {(x, y) for x in range(W) for y in range(H)
              if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0}
    px = {}
    for (x, y) in inside:
        edge = any((x + dx, y + dy) not in inside
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        px[(x, y)] = "o" if edge else ("s" if y >= 12 else "w")
    return px


_BODY = _body()


def pixels(expr):
    """某个表情的像素表 {(x, y): 颜色代号}。"""
    px = dict(_BODY)
    for p in ((3, 10), (4, 10), (11, 10), (12, 10)):          # 腮红
        px[p] = "p"
    if expr == "blink":
        for p in ((4, 8), (5, 8), (10, 8), (11, 8)):
            px[p] = "e"
    elif expr == "alarm":                                     # 瞪大眼 + 张嘴
        for x0 in (4, 10):
            for p in ((x0, 7), (x0 + 1, 7), (x0, 8), (x0 + 1, 8)):
                px[p] = "e"
            px[(x0, 7)] = "h"
        for p in ((7, 10), (8, 10), (7, 11), (8, 11)):
            px[p] = "e"
    else:
        for x0 in (5, 10):                                    # 豆豆眼
            px[(x0, 7)] = "e"
            px[(x0, 8)] = "e"
        if expr == "talk":                                    # 张嘴
            for p in ((7, 10), (8, 10), (7, 11), (8, 11)):
                px[p] = "e"
        else:                                                 # 小 w 嘴
            for p in ((6, 10), (7, 11), (8, 11), (9, 10)):
                px[p] = "e"
    return px


def load_skin():
    """读皮肤目录（SKIN_DIR）下的图片，返回 {表情: [PhotoImage, ...]}。

    没有 idle 就当没有皮肤（返回空 dict），整套用占位 —— 一半图片一半占位太违和。
    必须在 Tk 根窗口建好之后调用。
    """
    out = {}
    for expr in EXPRESSIONS:
        # 只认 <动作>_<数字>.png：精灵表原图之类的（比如 idle_source.png）别被当成一帧
        files = sorted(f for f in glob.glob(os.path.join(SKIN_DIR, "%s_*.png" % expr))
                       if re.fullmatch(r"%s_\d+\.png" % expr, os.path.basename(f)))
        frames = []
        for f in files:
            try:
                frames.append(tk.PhotoImage(file=f))
            except tk.TclError:
                continue
        if frames:
            out[expr] = frames
    if "roll" in out:
        # 翻滚：一张抱成球的图，转出 0/90/180/270 四帧（往右滚是顺时针）
        ball = out["roll"][0]
        r90 = rotate90(ball)
        out["roll"] = [ball, r90, rotate90(r90), rotate90(rotate90(r90))]
    return out if "idle" in out else {}


def mirror(img):
    """左右镜像。Tk 的 copy 支持负的 subsample。"""
    out = tk.PhotoImage()
    out.tk.call(out, "copy", img, "-subsample", -1, 1)
    return out


def rotate90(img):
    """顺时针转 90 度。一次性的（加载时），慢一点无所谓。"""
    w, h = img.width(), img.height()
    rows = img.tk.splitlist(img.tk.call(img, "data"))
    px = [img.tk.splitlist(r) for r in rows]
    out = tk.PhotoImage(width=h, height=w)
    # 新图 (x', y') = 原图 (y', h-1-x')
    data = " ".join("{" + " ".join(px[h - 1 - nx][ny] for nx in range(h)) + "}"
                    for ny in range(w))
    out.put(data)
    for ny in range(w):
        for nx in range(h):
            if img.transparency_get(ny, h - 1 - nx):
                out.transparency_set(nx, ny, True)
    return out


_MIRRORS = {}


def _mirrored(img):
    key = str(img)
    if key not in _MIRRORS:
        _MIRRORS[key] = mirror(img)
    return _MIRRORS[key]


def size(skin):
    """角色的宽高（像素）：有皮肤取所有帧里最大的，没有就是占位团子的大小。"""
    if not skin:
        return W * SCALE, H * SCALE
    frames = [f for fs in skin.values() for f in fs]
    return max(f.width() for f in frames), max(f.height() for f in frames)


def draw(canvas, expr, cx, bottom, skin=None, tick=0, flip=False):
    """在 canvas 上画一帧：底边中点在 (cx, bottom)。图元都带 "sprite" 标签，方便整帧擦掉。

    有皮肤时缺的表情退回 idle。flip=True 左右镜像（往左走、扭头）。
    返回实际画的表情，调用方据此决定要不要补画牌子。
    """
    canvas.delete("sprite")
    if skin:
        if expr not in skin:
            expr = "idle"
        frames = skin[expr]
        img = frames[tick % len(frames)]
        if flip:
            img = _mirrored(img)
        canvas.create_image(cx, bottom, image=img, anchor="s", tags="sprite")
        return expr
    if expr not in ("idle", "blink", "talk", "alarm"):
        expr = "idle"
    ox, oy = cx - W * SCALE // 2, bottom - H * SCALE
    for (x, y), c in pixels(expr).items():
        x0, y0 = ox + x * SCALE, oy + y * SCALE
        canvas.create_rectangle(x0, y0, x0 + SCALE, y0 + SCALE,
                                fill=COLORS[c], width=0, tags="sprite")
    return expr
