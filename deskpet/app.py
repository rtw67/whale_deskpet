# -*- coding: utf-8 -*-
"""桌宠本体：一个透明、置顶、可拖动的小窗口，蹲在屏幕右下角。

她会：
    冒气泡     别的程序通过本地端口发来的提醒（见 link.py），点开看详情
    举牌       扩展让她举的（见 extensions/__init__.py 的 set_sign），点她 = 处理
    做小动作、溜达、邀请你玩、有好感度 / 心情 / 体力（behavior.py / play/ / stats.py）

状态优先级（从高到低）：举牌 > 要你点的气泡 > 临时气泡 > 闲着（发呆、小动作、溜达）。
左键拖动；单击 = 处理当前这条（没事时 = 摸摸她）；右键 = 泡泡菜单。
"""

import os
import random
import time
from datetime import datetime

import tkinter as tk

from deskpet import config, lines
from deskpet import sprite
from deskpet.behavior import Behavior
from deskpet.card import CLOUD, CLOUD_HINT, CLOUD_TEXT, cloud, show_card, show_detail
from deskpet.extensions import Extensions, load_all
from deskpet.link import Server
from deskpet.menu import BubbleMenu, load_icons
from deskpet.play import PlayManager, user_idle_seconds
from deskpet.stats import Stats
from deskpet.theme import FONT
from deskpet.util import ROOT, data_path, load_json, log, save_json

try:
    import winsound
except ImportError:                       # 非 Windows
    winsound = None

KEY = "#ff00ff"            # 抠透明用的颜色：窗口里这个颜色的地方是透明的
SIGN_ROOM = 34             # 头顶补画牌子要留的高度
TAIL, GAP = 10, 6          # 气泡尾巴长度、气泡和她之间的空隙
POS_PATH = data_path("pet_state.json")

PERSIST, TRANSIENT = "persist", "transient"

# 每个动作多少个 tick（120ms）换一帧：呼吸、睡觉慢一点，举牌晃得快一点
FRAME_TICKS = {"idle": 7, "sleep": 9, "alarm": 4, "eat": 5}


def beep():
    if winsound is None:
        return
    try:
        winsound.PlaySound("SystemExclamation", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except Exception:                                              # noqa: BLE001
        pass


class Pet:
    def __init__(self, server, ext_dirs=()):
        self.server = server
        self.log = log
        self.lines = lines
        self.cfg = config.load()
        self.root = root = tk.Tk()
        root.title("桌宠")
        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.configure(bg=KEY)
        root.wm_attributes("-transparentcolor", KEY)
        sprite.SKIN_DIR = os.path.join(ROOT, self.cfg["skin"])
        self.skin = sprite.load_skin()
        # 画布大小跟着角色走；皮肤里没画举牌动作的话，头顶留出补画牌子的地方
        sw_, sh_ = sprite.size(self.skin)
        need_sign = not (self.skin and "alarm" in self.skin and "qr" in self.skin)
        self.sign_room = SIGN_ROOM if need_sign else 0
        self.cw = max(sw_, 64) + 16
        self.base_h = sh_ + 6                   # 只有角色本身的高度：气泡按这个来算头的位置
        self.ch = self.base_h + self.sign_room
        self.head_y = self.ch - 4 - sh_          # 角色头顶的 y（不带补牌空位时的「头下方」）
        # 她的头顶在窗口里的 y：窗口不留空位时，头顶就在顶上留白 4px 的位置。
        # 别用 head_y 反推 —— 那样算出来是「脚以上、牌子以下」，气泡会贴着脚
        self.head_top = 4
        self.canvas = tk.Canvas(root, width=self.cw, height=self.ch, bg=KEY,
                                highlightthickness=0)
        self.canvas.pack()

        pos = load_json(POS_PATH, {}) or {}
        self.sw, self.sh = root.winfo_screenwidth(), root.winfo_screenheight()
        x, y = pos.get("x"), pos.get("y")
        if not (isinstance(x, int) and isinstance(y, int)
                and 0 <= x < self.sw - 20 and 0 <= y < self.sh - 20):
            x, y = self.default_pos()
        root.geometry("%dx%d+%d+%d" % (self.cw, self.ch, x, y))
        # 「家」：你最后一次把她拖到的位置。溜达只在家附近，不会越走越远去挡东西
        self.home_x = pos.get("home_x", x) if isinstance(pos.get("home_x"), int) else x
        self.home_y = pos.get("home_y", y) if isinstance(pos.get("home_y"), int) else y

        self.items = []            # 要说的话：[{kind, text, msg, at, expires, ...}]
        self.signs = {}            # 扩展让她举的牌子：{名字: {expr, text, on_click, priority, at}}
        self.recent = []           # 最近收到的提醒，右键「消息」里能重新打开
        self.happy_until = 0.0
        self.bubble = None
        self.bubble_key = None
        self.t = 0
        self.drag = None
        self.bubble_gap = TAIL
        self.bubble_item = self.bubble_canvas = self.bubble_dim = None
        self.menu = BubbleMenu(root, KEY, owner=root, log=log,
                               icons=load_icons(sprite.SKIN_DIR))
        self.behavior = Behavior(self)
        self.play = PlayManager(self)
        self.stats = Stats(log)
        self.stats.on_level_up = self.level_up
        self.greeted = False
        self.next_chatter = time.time() + random.uniform(10, 20) * 60

        dirs = list(self.cfg.get("extension_dirs") or []) + list(ext_dirs)
        self.ext = Extensions(load_all([os.path.join(ROOT, d) if not os.path.isabs(d) else d
                                        for d in dirs], log), log)
        self.ext.call("setup", self)

        # 只绑在顶层窗口上：画布上的事件会顺着冒泡到顶层，两边都绑的话一次点击触发两次
        # （右键 = 打开菜单 + 立刻收起，看起来就是没反应）
        root.bind("<ButtonPress-1>", self.on_press)
        root.bind("<B1-Motion>", self.on_motion)
        root.bind("<ButtonRelease-1>", self.on_release)
        root.bind("<Button-3>", self.on_menu)

        self.topmost(False)                      # 平时只用实际大小，不留头顶那段空位
        self.root.after(120, self.tick)
        self.root.after(200, self.poll_messages)
        self.root.after(500, self.poll)
        log("桌宠启动")

    # ------------------------------------------------------------------ 位置
    def topmost(self, grow):
        """grow=True：头顶留出空位（皮肤里没有举牌动作、要补画牌子时）。
        平时不留：窗口透明的地方虽然能看到她，但那段空位会让「她的头在哪」算错，气泡会离头很远。"""
        h = self.base_h + (self.sign_room if grow else 0)
        if h == self.ch:
            return
        bottom = self.root.winfo_y() + self.ch
        self.ch = h
        self.head_y = self.ch - 4 - (self.ch - self.sign_room - 6)
        self.canvas.configure(height=h)
        self.root.geometry("%dx%d+%d+%d" % (self.cw, h, self.root.winfo_x(),
                                            max(bottom - h, 0)))

    def default_pos(self):
        return self.sw - self.cw - 24, self.sh - self.ch - 56   # 右下角，让开任务栏

    def save_pos(self, home=False):
        """记住位置。home=True 是你拖过去的，那里就是新的「家」；她自己溜达到的不算。"""
        x, y = self.root.winfo_x(), self.root.winfo_y()
        if home:
            self.home_x, self.home_y = x, y
        save_json(POS_PATH, {"x": x, "y": y, "home_x": self.home_x, "home_y": self.home_y})

    def on_press(self, e):
        self.menu.close()
        if self.play.game is not None:                 # 玩的时候点她 = 抓到她，不拖
            self.play.on_click()
            return
        self.behavior.interrupt()
        self.drag = (e.x_root, e.y_root, self.root.winfo_x(), self.root.winfo_y(), False)

    def on_motion(self, e):
        if not self.drag:
            return
        x0, y0, wx, wy, moved = self.drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if moved or abs(dx) + abs(dy) > 4:
            self.drag = (x0, y0, wx, wy, True)
            self.root.geometry("+%d+%d" % (wx + dx, wy + dy))
            self.place_bubble()

    def on_release(self, e):
        if not self.drag:
            return
        moved = self.drag[4]
        self.drag = None
        if moved:
            self.save_pos(home=True)
        else:
            self.on_click()

    # ------------------------------------------------------------------ 收消息
    def poll_messages(self):
        for msg in self.server.drain():
            try:
                self.handle(msg)
            except Exception as exc:                               # noqa: BLE001
                log("处理消息出错: %s" % exc)
        self.root.after(200, self.poll_messages)

    def handle(self, p, quiet=False):
        now = time.time()
        if p.get("_cmd") == "event":                     # 别的程序通知她发生了什么
            name = p.get("name") or ""
            self.stats.event(name)
            self.ext.call("on_event", self, name)
            return
        if p.get("_cmd") == "play":                      # python pet.py --play
            if not self.play.invite_now(now, p.get("game")):
                self.say("现在不方便玩～", 3, fun=True)
            return
        if p.get("_cmd"):
            return
        title = p.get("title") or ""
        msg = (p.get("message") or "").strip()
        self.recent.insert(0, {"at": now, "title": title or msg[:20], "msg": p})
        del self.recent[15:]
        log("收到: %s" % title)
        if self.ext.first("on_message", self, p):       # 扩展接管了（比如变成举牌）
            return
        if p.get("sound") and not quiet:
            beep()
        text = "%s\n%s" % (title, msg.split("\n")[0][:40]) if msg else title
        seconds = int(p.get("seconds", 30) or 0)
        item = {"kind": PERSIST if seconds == 0 else TRANSIENT, "msg": p, "at": now,
                "text": text, "oops": any(w in title for w in self.cfg.get("oops_words") or [])}
        if seconds:
            # 气泡比一般弹窗多停一会儿：它不挡东西，错过了右键「消息」也能找回来
            item["expires"] = now + max(seconds, 8)
        self.items.append(item)

    def poll(self):
        """每 3 秒：重读配置，问一圈扩展。"""
        self.cfg = config.load()
        self.ext.call("poll", self, time.time())
        self.root.after(3000, self.poll)

    # ------------------------------------------------------------------ 给扩展用的
    def set_sign(self, name, expr="alarm", text=None, on_click=None, priority=0):
        """让她举牌。同名的会更新（不会重新计时）。text=None 时不冒气泡，只举牌。"""
        old = self.signs.get(name)
        self.signs[name] = {"expr": expr, "text": text, "on_click": on_click,
                            "priority": priority, "at": old["at"] if old else time.time()}

    def clear_sign(self, name):
        self.signs.pop(name, None)

    def top_sign(self):
        if not self.signs:
            return None
        return max(self.signs.values(), key=lambda s: (s["priority"], s["at"]))

    def cheer(self, seconds=2.0):
        """开心一下（举手）。"""
        self.happy_until = time.time() + seconds

    def say(self, text, seconds=6, fun=False):
        """说一句话。fun=True 是闲聊、玩的时候的台词：不算「有事」，不会把游戏、溜达打断。"""
        self.items.append({"kind": TRANSIENT, "msg": None, "at": time.time(), "text": text,
                           "expires": time.time() + seconds, "fun": fun})

    def add_invite(self, text, seconds, on_yes, on_no, on_expire):
        """带「好呀」「下次吧」按钮的邀请气泡，seconds 秒没理就过期。"""
        it = {"kind": PERSIST, "msg": None, "at": time.time(), "text": text,
              "expires": time.time() + seconds, "on_expire": on_expire,
              "buttons": [("好呀", on_yes), ("下次吧", on_no)]}
        self.items.append(it)
        return it

    def open_message(self, msg):
        """点开一条提醒：扩展要接管就交给扩展，不然用自带的详情卡片。"""
        if not self.ext.first("on_open", self, msg):
            show_detail(self, msg)

    # ------------------------------------------------------------------ 当前说什么
    def current(self):
        """现在气泡上该显示哪条：有字的牌子 > 要你点的 > 临时的，同级里新的优先。"""
        sign = self.top_sign()
        if sign and sign["text"]:
            return {"kind": "sign", "sign": sign, "text": sign["text"]}
        for kind in (PERSIST, TRANSIENT):
            its = [it for it in self.items if it["kind"] == kind]
            if its:
                return its[-1]
        return None

    def text_of(self, it):
        return it["text"]

    def on_click(self):
        if self.play.on_click():
            return
        sign = self.top_sign()
        if sign and sign["on_click"]:
            sign["on_click"]()
            return
        it = self.current()
        if it and it.get("buttons"):                    # 有邀请时点她 = 答应
            self.answer(it, it["buttons"][0][1])
            return
        if it and it.get("msg"):
            self.items.remove(it)
            self.open_message(it["msg"])
        elif it and it["kind"] != "sign":
            self.items.remove(it)
        elif self.off_duty():
            self.say("（揉眼睛）现在是休息时间啦…", 4)
        else:
            self.pet_her()

    # ------------------------------------------------------------------ 数值互动
    def pet_her(self):
        """没事时点她 = 摸摸。"""
        self.stats.event("pet")
        lv = self.stats.level()[0]
        if self.stats.today("pet") > 10:
            self.say(lines.one(lines.PET_CAPPED), 3, fun=True)
        else:
            self.say(lines.pick(lines.PET, lv), 3, fun=True)
            self.cheer(1.5)

    def feed(self):
        self.stats.event("feed")
        full = self.stats.today("feed") > 3
        self.say(lines.one(lines.FEED_FULL if full else lines.FEED), 3, fun=True)
        self.behavior.interrupt()
        self.behavior.start_action("eat", 3.5)

    def show_status(self):
        show_card(self)

    def level_up(self, lv, title):
        self.log("好感升级：Lv.%d %s" % (lv, title))
        self.say(lines.LEVEL_UP.format(title=title), 6, fun=True)
        self.cheer(3)

    def maybe_social(self, now, busy):
        """第一次见面打招呼；闲着时偶尔自言自语（很低频，不打扰工作）。"""
        if busy or self.off_duty() or self.current() is not None:
            return
        if not self.greeted:
            if user_idle_seconds() < 60:
                self.greeted = True
                self.stats.event("greet")
                if self.stats.today("greet") == 1:        # 今天第一次（重启不重复打招呼）
                    morning = time.localtime().tm_hour < 11
                    self.say(lines.one(lines.GREET_MORNING if morning else lines.GREET), 5, fun=True)
                    self.cheer(2)
            return
        if now >= self.next_chatter:
            self.next_chatter = now + random.uniform(15, 30) * 60
            if user_idle_seconds() > 120:                  # 你不在就别自言自语了
                return
            s = self.stats
            if s.energy < 20:
                text = lines.one(lines.TIRED)
            elif s.mood < 35:
                text = lines.one(lines.LOW_MOOD)
            else:
                text = lines.pick(lines.CHATTER, s.level()[0])
            self.say(text, 5, fun=True)

    # ------------------------------------------------------------------ 菜单
    def on_menu(self, e):
        """右键：身边冒一圈蓝泡泡。再右键一次收起。"""
        if self.menu.is_open:
            self.menu.close("再右键一次")
            return
        log("右键：打开菜单")
        items = [
            {"label": "消息", "tip": "最近的提醒", "cb": self.recent_entries, "sub": True},
            {"label": "玩", "tip": "一起玩", "cb": self.play_entries, "sub": True},
            {"label": "喂饭", "tip": "喂一碗白饭", "cb": self.feed},
            {"label": "状态", "tip": "好感度 / 心情 / 体力", "cb": self.show_status},
        ]
        for more in self.ext.call("menu_items", self):
            items += list(more or [])
        items += [
            {"label": "归位", "tip": "回到右下角", "cb": self.reset_pos},
            {"label": "退出", "tip": "让她下班", "cb": self.quit},
        ]
        self.root.update_idletasks()             # 窗口刚建好还没摆到位时，读到的坐标会是 0
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        side = "right" if x > self.sw // 2 else "left"
        self.menu.open(x + self.cw // 2, y + self.ch // 2, items, side)

    def play_entries(self):
        """「玩」子菜单：能玩的游戏，点了直接开始（你主动叫的，不用再发邀请）。"""
        return [{"label": m.TITLE, "tip": getattr(m, "DESC", m.TITLE),
                 "cb": lambda m=m: self.play.start_now(m)} for m in self.play.available()]

    def recent_entries(self):
        """「消息」子菜单：最近收到的提醒，泡泡上写时间，悬停看标题，点了重新打开。"""
        out = []
        for r in self.recent:                    # 最多 15 条，一圈放不下菜单会自己分页
            hm = time.strftime("%H:%M", time.localtime(r["at"]))
            out.append({"label": hm, "tip": "%s  %s" % (hm, (r["title"] or "")[:20]),
                        "cb": lambda m=r["msg"]: self.open_message(m)})
        return out

    def reset_pos(self):
        x, y = self.default_pos()
        self.behavior.interrupt()
        self.root.geometry("+%d+%d" % (x, y))
        self.save_pos(home=True)
        self.place_bubble()

    def quit(self):
        log("桌宠退出")
        self.root.destroy()

    # ------------------------------------------------------------------ 画
    def tick(self):
        self.t += 1
        now = time.time()
        expired = [it for it in self.items
                   if (it["kind"] == TRANSIENT or it.get("on_expire"))
                   and it.get("expires", 0) < now]
        for it in expired:
            self.items.remove(it)
            if it.get("on_expire"):
                it["on_expire"]()
        cur = self.current()
        sign = self.top_sign()

        dx = dy = 0
        flip, speed = False, FRAME_TICKS.get("idle", 4)
        # 「有事」：举牌、提醒、菜单、拖她、休息时间…… 闲聊、玩的时候自己说的话（fun）不算
        busy = (sign is not None or self.happy_until > now
                or (cur is not None and not cur.get("fun"))
                or self.menu.is_open or self.drag is not None
                or (self.off_duty() and not self.play.active))   # 休息时间睡觉；但你叫她玩就陪你玩
        act = None
        if busy:
            self.behavior.interrupt()
            if not (cur is not None and cur.get("buttons")):   # 等你回邀请时不算打断
                self.play.interrupt()
            self.play.note_busy(now)
        else:
            act = self.play.step(now, self.t)
            if act is None:
                act = self.behavior.step(now, self.t)
                self.play.maybe_invite(now)
        self.stats.tick(now, resting=self.behavior.move is None and not self.play.active,
                        working_hours=not self.off_duty())
        self.maybe_social(now, busy)
        if act is not None:
            expr, flip, speed = act[0], act[1], act[2] or FRAME_TICKS.get(act[0], 4)
        elif sign is not None:
            expr = sign["expr"]
            if expr == "alarm" and self.t % 25 < 6:            # 举红牌时隔一会儿抖一下
                dx = -2 if self.t % 2 else 2
        elif self.happy_until > now:
            expr = "happy"
        elif cur is not None and cur.get("oops"):
            expr = "oops"
        elif cur is not None:
            expr = "talk" if (self.t // 3) % 2 else "idle"
        elif self.off_duty():
            expr = "sleep"
        else:
            expr = "blink" if self.t % 35 in (0, 1) else "idle"
            if not self.skin:
                dy = (self.t // 6) % 2                             # 占位团子靠上下动来呼吸
        if act is None:
            speed = FRAME_TICKS.get(expr, 4)
        # speed 是「几个 tick 换一帧」；("frame", n) 表示就用第 n 帧（小跳按起跳/腾空选帧）
        frame = speed[1] if isinstance(speed, tuple) else self.t // speed
        drawn = sprite.draw(self.canvas, expr, self.cw // 2 + dx, self.ch - 4 + dy,
                            self.skin, frame, flip=flip)

        # 图里没画牌子（占位团子、或者皮肤缺这个动作）就在头顶补画一块
        self.topmost(sign is not None and self.sign_room > 0)
        self.canvas.delete("overlay")
        if sign is not None and act is None and (not self.skin or drawn != sign["expr"]):
            if sign["expr"] == "qr":
                self.draw_qr()
            else:
                self.draw_sign(dx)

        # 菜单开着时把说话气泡收起来，别叠在一起；菜单收了再按原样显示
        key = (cur.get("sign") and id(cur["sign"]) or id(cur), cur["text"]) \
            if cur and not self.menu.is_open else None
        if key != self.bubble_key:
            self.bubble_key = key
            self.show_bubble(cur if key else None)
        self.root.after(120, self.tick)

    def off_duty(self):
        """休息时间（work_start ~ work_end 以外）和周末：她在睡觉。"""
        now = datetime.now()
        if now.weekday() >= 5:
            return True
        hm = now.strftime("%H:%M")
        return not (self.cfg.get("work_start", "09:00") <= hm < self.cfg.get("work_end", "20:00"))

    def draw_sign(self, dx):
        cx, top = self.cw // 2 + dx, self.head_y - 30
        c = self.canvas
        c.create_line(cx, top + 22, cx, self.head_y + 8, fill="#3b2f2f", width=2, tags="overlay")
        c.create_rectangle(cx - 12, top, cx + 12, top + 22, fill="#e34948",
                           outline="#3b2f2f", width=2, tags="overlay")
        c.create_text(cx, top + 11, text="!", fill="#ffffff",
                      font=(FONT, 12, "bold"), tags="overlay")

    def draw_qr(self):
        cx, top = self.cw // 2, self.head_y - 30
        c = self.canvas
        c.create_rectangle(cx - 12, top, cx + 12, top + 24, fill="#ffffff",
                           outline="#3b2f2f", width=2, tags="overlay")
        pattern = ["11101", "10110", "11011", "01101", "10111"]
        for r, row in enumerate(pattern):
            for k, bit in enumerate(row):
                if bit == "1":
                    x0, y0 = cx - 10 + k * 4, top + 2 + r * 4
                    c.create_rectangle(x0, y0, x0 + 4, y0 + 4, fill="#2b2b2b",
                                       width=0, tags="overlay")

    # ------------------------------------------------------------------ 气泡
    def show_bubble(self, it):
        """说话气泡：蓝色云朵 + 白字。

        摆法：优先放在她头顶上方（尾巴朝下指着她）；上面放不下就放左边，再不行放右边，
        两种情况都**和她留出一条缝、不压在她身上**。
        窗口只建一次；她挪位置时 _layout_bubble 重算位置、重画画布，不重建窗口。
        """
        from tkinter import font as tkfont
        if self.bubble is not None:
            self.bubble.destroy()
            self.bubble = None
        self.bubble_item = None
        if it is None:
            return
        text = it["text"]
        urgent = it["kind"] == "sign"
        buttons = it.get("buttons") or []
        closable = not urgent and not buttons
        f = tkfont.Font(font=(FONT, 9, "bold") if urgent else (FONT, 9))
        lines = text.split(chr(10)) or [""]
        tw = max(f.measure(ln) for ln in lines)
        th = f.metrics("linespace") * len(lines)
        bw = int(min(max(tw + 44 + (110 if buttons else 16 if closable else 0), 120), 430))
        bh = int(th + 26)
        # 尾巴长度跟着这一侧算：朝上的尾巴会伸进「她头顶以上」那段空间，得让出来，
        # 不然算「上面放得下吗」会算错，气泡贴到她的脚边
        self.bubble_gap = max(TAIL, int(self.head_y - bh - GAP))
        self.bubble_item, self.bubble_dim = it, (bw, bh)
        self.bubble_urgent, self.bubble_buttons, self.bubble_closable = urgent, buttons, closable

        b = tk.Toplevel(self.root)
        b.overrideredirect(True)
        b.attributes("-topmost", True)
        b.configure(bg=KEY)
        b.wm_attributes("-transparentcolor", KEY)
        self.bubble_canvas = tk.Canvas(b, width=bw, height=bh + self.bubble_gap + GAP, bg=KEY,
                                       highlightthickness=0)
        self.bubble_canvas.pack()
        self.bubble = b
        self._layout_bubble()

    def _layout_bubble(self):
        """按她当前位置算气泡在哪、尾巴朝哪，然后重画。"""
        it = getattr(self, "bubble_item", None)
        if self.bubble is None or it is None:
            return
        from tkinter import font as tkfont
        bw, bh = self.bubble_dim
        px, py, pw, ph = self.root.winfo_x(), self.root.winfo_y(), self.cw, self.ch
        # 她的头和脸在哪（不是窗口/脚）：气泡要贴着这里
        face_top = py + self.head_top + 18
        face_mid = py + self.head_top + self.base_h * 0.45
        gap = getattr(self, "bubble_gap", TAIL)
        above_y = face_top - bh - GAP - gap
        left_x = px - bw - GAP - TAIL
        right_x = px + pw + GAP + TAIL
        if above_y >= 0:                            # 头顶放得下：放头顶正中
            side = "above"
            bx = min(max(px + pw // 2 - bw // 2, 4), self.sw - bw - 4)
            by = above_y
        elif left_x >= 0:                           # 放不下就往左，气泡和她头齐平
            side, bx, by = "left", left_x, min(max(face_mid - bh / 2, 4), self.sh - bh - 4)
        elif right_x + bw <= self.sw:
            side, bx, by = "right", right_x, min(max(face_mid - bh / 2, 4), self.sh - bh - 4)
        else:                                       # 屏幕太挤，只好压一点
            side = "left"
            bx, by = max(self.sw - bw - 4, 4), min(max(face_mid - bh / 2, 4), self.sh - bh - 4)

        # 重画会把文字控件重建一遍；走的时候每秒调 25 次，只有位置真的变了才重画
        now = time.time()
        if (getattr(self, "_bub_at", None) == (bx, by)
                and now - getattr(self, "_bub_draw_at", 0) < 2.0):
            return
        self._bub_at = (bx, by)
        self._bub_draw_at = now
        if side == "above":
            tipx = min(max(px + pw * 0.45 - bx, 30), bw - 30)       # 尾巴落在她头顶
            tail = (tipx, bh - 6, tipx, bh + GAP + gap, 8)
        elif side == "left":                        # 尾巴指向她的脸
            tipy = min(max(face_mid - by, 20), bh - 20)
            tail = (bw - 6, tipy, bw + TAIL - 1, tipy, 7)
        else:
            tipy = min(max(face_mid - by, 20), bh - 20)
            tail = (6, tipy, 1, tipy, 7)

        c = self.bubble_canvas
        c.delete("all")
        cloud(c, 4, 4, bw - 4, bh - 4, tail=tail)
        lbl = tk.Label(c, text=it["text"], bg=CLOUD, fg=CLOUD_TEXT,
                       font=(FONT, 9, "bold") if self.bubble_urgent else (FONT, 9),
                       justify="left", anchor="w", cursor="hand2")
        c.create_window(20, bh / 2, window=lbl, anchor="w")
        widgets = [lbl]
        if self.bubble_buttons:
            n = len(self.bubble_buttons)
            for k, (label, cb) in enumerate(self.bubble_buttons):
                bt = tk.Button(c, text=label, bg="#ffffff", fg=CLOUD, relief="flat", bd=0,
                               activebackground="#e6f1ff", activeforeground=CLOUD,
                               padx=8, pady=1, font=(FONT, 9), cursor="hand2",
                               command=lambda it=it, cb=cb: self.answer(it, cb))
                c.create_window(bw - 18, bh / 2 + (k - (n - 1) / 2.0) * 26, window=bt, anchor="e")
                widgets.append(bt)
        elif self.bubble_closable:
            x = tk.Label(c, text="×", bg=CLOUD, fg=CLOUD_HINT, font=(FONT, 11), cursor="hand2")
            c.create_window(bw - 14, 16, window=x, anchor="e")
            x.bind("<Button-1>", lambda e, it=it: self.dismiss(it))
        for w in widgets:
            w.bind("<Button-1>", lambda e, it=it: self.click_bubble(it))
        self.bubble.geometry("%dx%d+%d+%d" % (bw, bh + gap + GAP, bx, by))

    def place_bubble(self, height=None):
        """她挪了位置（拖动、溜达）：气泡跟着重摆一次。"""
        self._layout_bubble()

    def bubble_side(self):
        """气泡放在她左边还是右边（屏幕放得下的话左）。"""
        return self.root.winfo_x() > 200

    def answer(self, it, cb):
        if it in self.items:
            self.items.remove(it)
            cb()

    def click_bubble(self, it):
        if it["kind"] == "sign":
            if it["sign"]["on_click"]:
                it["sign"]["on_click"]()
            return
        if it in self.items:
            self.items.remove(it)
            if it.get("msg"):
                self.open_message(it["msg"])

    def dismiss(self, it):
        if it in self.items:
            self.items.remove(it)

    def place_bubble(self, height=None):
        if self.bubble is None:
            return
        self.bubble.update_idletasks()
        bw = self.bubble.winfo_reqwidth()
        bh = height or self.bubble.winfo_reqheight()
        x, y = self.root.winfo_x(), self.root.winfo_y()
        bx = x - bw + 10 if x - bw + 10 > 0 else x + self.cw - 10
        by = max(min(y + self.ch - bh + 10, self.sh - bh - 10), 0)
        self.bubble.geometry("+%d+%d" % (bx, by))


def main(ext_dirs=()):
    cfg = config.load()
    server = Server(int(cfg["port"]))
    if not server.start():
        return 0                     # 已经有一只在了
    pet = Pet(server, ext_dirs)
    pet.root.mainloop()
    return 0
