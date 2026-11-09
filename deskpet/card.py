# -*- coding: utf-8 -*-
"""两张小卡片：右键「状态」（好感度、心情、体力、今天的互动），以及提醒的详情。

点卡片收起；状态卡片 10 秒后自己收起。
"""

from datetime import date

import tkinter as tk

from deskpet.theme import BG, BORDER, DETAIL_FG, FONT, MSG_FG, TITLE_FG

TRACK = "#2a3040"          # 进度条底槽
# 每根条一个颜色；条旁边都写着名字和数值，颜色不是唯一的区分方式
AFFECTION = "#e87ba4"
MOOD = "#eda100"
ENERGY = "#1baf7a"
W = 260                    # 卡片宽
BAR_W = 150


def show_card(pet):
    s = pet.stats
    lv, title, start, nxt = s.level()
    win = tk.Toplevel(pet.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BORDER)
    card = tk.Frame(win, bg=BG)
    card.pack(padx=2, pady=2)

    days = (date.today() - date.fromisoformat(s.first_seen)).days + 1
    tk.Label(card, text="%s  Lv.%d %s" % (pet.cfg.get("name", "鲸鱼娘"), lv, title), bg=BG, fg=TITLE_FG,
             font=(FONT, 11, "bold")).pack(anchor="w", padx=14, pady=(12, 0))
    tk.Label(card, text="认识第 %d 天" % days, bg=BG, fg=DETAIL_FG,
             font=(FONT, 8)).pack(anchor="w", padx=14, pady=(0, 8))

    if nxt:
        frac = (s.affection - start) / float(nxt - start)
        aff_text = "%d / %d" % (s.affection, nxt)
    else:
        frac, aff_text = 1.0, "%d（满级）" % s.affection
    _bar(card, "好感", frac, aff_text, AFFECTION)
    _bar(card, "心情", s.mood / 100, "%d %s" % (s.mood, s.mood_word()), MOOD)
    _bar(card, "体力", s.energy / 100, "%d %s" % (s.energy, s.energy_word()), ENERGY)

    today = "今天：摸摸 %d 次 · 陪玩 %d 局 · 喂饭 %d 次" % (
        s.today("pet"), s.today("play_done"), s.today("feed"))
    tk.Label(card, text=today, bg=BG, fg=DETAIL_FG, font=(FONT, 8)
             ).pack(anchor="w", padx=14, pady=(8, 2))
    if nxt:
        hint = "再涨 %d 点好感升到「%s」" % (nxt - s.affection, _next_title(lv))
    else:
        hint = "已经是最高等级啦"
    tk.Label(card, text=hint, bg=BG, fg=DETAIL_FG, font=(FONT, 8)
             ).pack(anchor="w", padx=14, pady=(0, 12))

    # 放在她旁边：她在右半边就放左边
    win.update_idletasks()
    cw, ch = win.winfo_reqwidth(), win.winfo_reqheight()
    x, y = pet.root.winfo_x(), pet.root.winfo_y()
    cx = x - cw - 8 if x > pet.sw // 2 else x + pet.cw + 8
    cy = max(min(y + pet.ch - ch, pet.sh - ch - 50), 4)
    win.geometry("+%d+%d" % (cx, cy))

    def close(e=None):
        if win.winfo_exists():
            win.destroy()

    for w in [win, card] + list(card.winfo_children()):
        w.bind("<Button-1>", close)
    win.after(10000, close)
    return win


def _next_title(lv):
    from deskpet.stats import LEVELS
    return LEVELS[lv][1] if lv < len(LEVELS) else ""


def _bar(parent, name, frac, text, color):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=14, pady=3)
    tk.Label(row, text=name, bg=BG, fg=MSG_FG, font=(FONT, 9), width=4,
             anchor="w").pack(side="left")
    c = tk.Canvas(row, width=BAR_W, height=10, bg=BG, highlightthickness=0)
    c.pack(side="left", padx=(2, 8))
    c.create_rectangle(0, 2, BAR_W, 9, fill=TRACK, width=0)
    fill = max(0, min(1, frac)) * BAR_W
    if fill > 0:
        c.create_rectangle(0, 2, fill, 9, fill=color, width=0)
    tk.Label(row, text=text, bg=BG, fg=DETAIL_FG, font=(FONT, 8)).pack(side="left")


def show_detail(pet, msg):
    """点开一条提醒、又没有扩展接管时：一张卡片显示标题和正文，有 url 就给个打开按钮。"""
    import webbrowser
    win = tk.Toplevel(pet.root)
    win.overrideredirect(True)
    win.attributes("-topmost", True)
    win.configure(bg=BORDER)
    card = tk.Frame(win, bg=BG)
    card.pack(padx=2, pady=2)
    tk.Label(card, text=msg.get("title") or "", bg=BG, fg=TITLE_FG, font=(FONT, 10, "bold"),
             wraplength=320, justify="left", anchor="w").pack(fill="x", padx=14, pady=(12, 4))
    body = (msg.get("message") or "").strip()
    if body:
        tk.Label(card, text=body, bg=BG, fg=MSG_FG, font=(FONT, 9), wraplength=320,
                 justify="left", anchor="w").pack(fill="x", padx=14)
    row = tk.Frame(card, bg=BG)
    row.pack(fill="x", padx=14, pady=(10, 12))

    def close(e=None):
        if win.winfo_exists():
            win.destroy()

    if msg.get("url"):
        tk.Button(row, text="打开链接", bg="#3b82f6", fg="#ffffff", relief="flat", bd=0,
                  padx=10, pady=2, font=(FONT, 9), cursor="hand2",
                  command=lambda: (webbrowser.open(msg["url"]), close())).pack(side="left")
    tk.Button(row, text="关闭", bg="#39415a", fg=MSG_FG, relief="flat", bd=0, padx=10, pady=2,
              font=(FONT, 9), cursor="hand2", command=close).pack(side="right")
    win.update_idletasks()
    cw, ch = win.winfo_reqwidth(), win.winfo_reqheight()
    x, y = pet.root.winfo_x(), pet.root.winfo_y()
    cx = x - cw - 8 if x > pet.sw // 2 else x + pet.cw + 8
    cy = max(min(y + pet.ch - ch, pet.sh - ch - 50), 4)
    win.geometry("+%d+%d" % (cx, cy))
    return win


# ---------------------------------------------------------------------- 云朵气泡
CLOUD = "#2f7fd6"          # 和右键泡泡同一个蓝
CLOUD_EDGE = "#d4ebff"
CLOUD_TEXT = "#ffffff"
CLOUD_HINT = "#dcecff"


def bubble_size(text, buttons=False, closable=False, font_px=17):
    """按文字长短估一个云朵大小（多行文字按最宽的一行算）。

    font_px 是实际字高（雅黑 9 号约 17 像素）：中文按一个字一个 font_px、
    英文数字按 0.55 估，再加左右留白。
    """
    lines = text.split("\n") if text else [""]
    wide = max(sum(font_px if ord(c) > 0x2E80 else font_px * 0.55 for c in ln) for ln in lines)
    w = max(wide + 52, 130)
    h = 34 + (font_px + 6) * len(lines)
    if buttons:
        w += 110
    elif closable:
        w += 16
    return int(min(w, 400)), int(h)


def cloud(canvas, x0, y0, x1, y1, tail=None, fill=CLOUD, outline=CLOUD_EDGE, width=2):
    """在画布上画一朵云：用一圈鼓包当遮罩，拼出一整朵（描边在下面一层，先画大的深色再画小的）。

    tail: 尾巴尖的位置 (x, y)；None 就不画尾巴。
    """
    w, h = x1 - x0, y1 - y0
    r = max(min(h / 2.0, 26), 14)                 # 鼓包别太大，不然云朵变成几个大圆
    bumps = []
    n = max(4, int(w / (r * 1.15)))
    for i in range(n + 1):                       # 上下两排鼓包交错，边缘看起来是瓣状的
        cx = x0 + r + (w - 2 * r) * (i / float(n))
        bumps.append((cx, y0 + r * 0.62, r * 0.78))
        if i < n:
            bumps.append((x0 + r + (w - 2 * r) * ((i + 0.5) / n), y0 + h - r * 0.62, r * 0.82))
    # 两头各一个圆，把左右封住
    bumps += [(x0 + r * 0.75, y0 + h / 2, h / 2 - 2), (x1 - r * 0.75, y0 + h / 2, h / 2 - 2)]
    if tail:
        bumps.append((tail[0], tail[1], 7))

    def draw(grow, color):
        items = []
        for cx, cy, rr in bumps:
            items.append(canvas.create_oval(cx - rr - grow, cy - rr - grow,
                                            cx + rr + grow, cy + rr + grow,
                                            fill=color, outline=""))
        return items

    draw(width, outline)                         # 先画大一圈的描边色
    return draw(0, fill)                         # 再画本体
