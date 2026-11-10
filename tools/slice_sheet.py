#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把精灵表（一整张大图）切成皮肤目录里的 <表情>_<序号>.png。

    python tools/slice_sheet.py skins/whale/source/sheet_source.png --out skins/whale

原图放在皮肤目录的 source/ 下时，不写 --out 也会输出到上一级（皮肤目录本身）。
鲸鱼娘这套每张图的切法见 skins/whale/README.md。

只用标准库（不需要 Pillow）：zlib 解码、Tk 写 PNG。做的事：
  1. 自己解码 PNG 拿真实透明度（Tk 只分得清「完全透明」），≥128 的算角色，连通的算一块
  2. 每块按中心点归到 cols × rows 的哪一格 —— 举牌、z、汗滴这些散件也跟着角色走
  3. 所有帧用**同一个**裁剪框（按格子内的相对位置），切换动作时人物不会跳
  4. 每 scale×scale 个像素合成一个：多数不透明就取它们的平均色，否则透明
     —— 输出只有「全透明 / 全不透明」两种像素。桌宠窗口靠一个颜色抠透明，
     半透明的边会混出粉边，所以这里必须二值化
  5. scale 可以是小数：几张图里角色画得大小不一时，用它把身高对齐

不写 --names 时按第一张精灵表约定的 12 个动作命名（见 NAMES）。
"""

import argparse
import math
import os
import struct
import sys
import time
import tkinter as tk
import zlib
from collections import deque

NAMES = ["idle_1", "idle_2", "blink_1", "talk_1",
         "alarm_1", "alarm_2", "qr_1", "happy_1",
         "sleep_1", "sleep_2", "eat_1", "oops_1"]


def read_png(path, alpha_min=128):
    """自己解码 RGBA PNG（只用 zlib），返回 (宽, 高, rgb 行列表, 不透明掩码行列表)。

    不用 Tk 读：Tk 8.6 只能告诉你「是不是完全透明」。AI 出的图背景里常有大片
    透明度 1~63 的噪点，Tk 会把它们全当成不透明，相邻的角色就被连成一大块。
    这里按真实透明度切：≥ alpha_min 才算角色。
    """
    data = open(path, "rb").read()
    if data[:8] != bytes([137, 80, 78, 71, 13, 10, 26, 10]):     # PNG 文件头
        raise SystemExit("不是 PNG 文件")
    pos, idat = 8, b""
    while pos < len(data):
        n, typ = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if typ == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", body[:10])
            if depth != 8 or ctype not in (2, 6):
                raise SystemExit("只支持 8 位 RGB / RGBA 的 PNG（这张是 位深%d 类型%d）"
                                 % (depth, ctype))
        elif typ == b"IDAT":
            idat += body
        pos += 12 + n
    bpp = 4 if ctype == 6 else 3
    stride = w * bpp
    raw = zlib.decompress(idat)
    prev = bytearray(stride)
    rgb, mask = [], []
    i = 0
    for _ in range(h):
        f = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):                      # PNG 的逐行反滤波
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            if f == 1:
                line[x] = (line[x] + a) & 255
            elif f == 2:
                line[x] = (line[x] + b) & 255
            elif f == 3:
                line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                c = prev[x - bpp] if x >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        rgb.append([(line[k], line[k + 1], line[k + 2]) for k in range(0, stride, bpp)])
        mask.append([bpp == 3 or line[k + 3] >= alpha_min for k in range(0, stride, bpp)])
    return w, h, rgb, mask


def components(mask, min_size):
    """8 邻接的连通块，返回 [(像素列表, 中心x, 中心y)]，太小的（噪点）丢掉。"""
    h, w = len(mask), len(mask[0])
    seen = [[False] * w for _ in range(h)]
    out = []
    for y in range(h):
        for x in range(w):
            if not mask[y][x] or seen[y][x]:
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            px = []
            while q:
                cx, cy = q.popleft()
                px.append((cx, cy))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < w and 0 <= ny < h and mask[ny][nx] and not seen[ny][nx]:
                            seen[ny][nx] = True
                            q.append((nx, ny))
            if len(px) >= min_size:
                out.append((px, sum(p[0] for p in px) / len(px),
                            sum(p[1] for p in px) / len(px)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--scale", type=float, default=3, help="缩小倍数，可以是小数（几张图之间对齐身高用）")
    ap.add_argument("--out", default=None, help="输出目录，默认和精灵表同目录（在 source/ 里就是上一级）")
    ap.add_argument("--alpha", type=int, default=128, help="透明度 ≥ 这个值才算角色")
    ap.add_argument("--per-row", action="store_true",
                    help="每行单独算裁剪框（各行的图大小不一样，比如探头图：一行截在左边、一行截在上边）")
    ap.add_argument("--names", default=None, help="逗号分隔的输出文件名（不含 .png），默认是桌宠的 12 个动作")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    t0 = time.time()
    w, h, rgb, mask = read_png(args.sheet, args.alpha)
    cw, chh = w / args.cols, h / args.rows
    print("读图 %dx%d，%.1f 秒" % (w, h, time.time() - t0))
    root = tk.Tk()
    root.withdraw()

    # 每格的像素（格内相对坐标）
    cells = [[] for _ in range(args.cols * args.rows)]
    for px, mx, my in components(mask, min_size=30):
        col = min(int(mx // cw), args.cols - 1)
        row = min(int(my // chh), args.rows - 1)
        ox, oy = int(col * cw), int(row * chh)
        cells[row * args.cols + col] += [(x - ox, y - oy, rgb[y][x]) for x, y in px]

    # 统一裁剪框：所有格子的并集（--per-row 时每行一个）。同一组的图大小一样，
    # 桌宠按底边居中画，大小一样换帧时才不会跳
    s = args.scale

    def box(group):
        allx = [p[0] for c in group for p in c]
        ally = [p[1] for c in group for p in c]
        x0, x1, y0, y1 = min(allx), max(allx) + 1, min(ally), max(ally) + 1
        ow, oh = int(math.ceil((x1 - x0) / s)), int(math.ceil((y1 - y0) / s))
        print("裁剪框 %dx%d -> 输出 %dx%d" % (x1 - x0, y1 - y0, ow, oh))
        return x0, y0, ow, oh

    if args.per_row:
        boxes = []
        for r in range(args.rows):
            boxes += [box(cells[r * args.cols:(r + 1) * args.cols])] * args.cols
    else:
        boxes = [box(cells)] * len(cells)

    out_dir = args.out or os.path.dirname(os.path.abspath(args.sheet))
    if os.path.basename(out_dir) == "source":            # 原图在 source/ 里：输出到皮肤目录
        out_dir = os.path.dirname(out_dir)
    names = args.names.split(",") if args.names else NAMES
    for i, name in enumerate(names[:len(cells)]):
        x0, y0, ow, oh = boxes[i]
        # 每个输出像素收集它覆盖的源像素
        buckets = {}
        for x, y, c in cells[i]:
            buckets.setdefault((int((x - x0) / s), int((y - y0) / s)), []).append(c)
        need = s * s / 2                             # 过半才算不透明（小数倍时每格源像素数不一样，按平均算）
        frame = tk.PhotoImage(width=ow, height=oh)
        rows = []
        opaque = set()
        for oy_ in range(oh):
            line = []
            for ox_ in range(ow):
                cs = buckets.get((ox_, oy_))
                if cs and len(cs) > need:
                    r = sum(c[0] for c in cs) // len(cs)
                    g = sum(c[1] for c in cs) // len(cs)
                    b = sum(c[2] for c in cs) // len(cs)
                    line.append("#%02x%02x%02x" % (r, g, b))
                    opaque.add((ox_, oy_))
                else:
                    line.append("#000000")
            rows.append("{" + " ".join(line) + "}")
        frame.put(" ".join(rows))
        for oy_ in range(oh):
            for ox_ in range(ow):
                if (ox_, oy_) not in opaque:
                    frame.transparency_set(ox_, oy_, True)
        path = os.path.join(out_dir, name + ".png")
        frame.write(path, format="png")
        print("  %-8s %5d 个像素" % (name, len(opaque)))
    root.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
