# -*- coding: utf-8 -*-
"""追鼠标：她朝你的鼠标指针跑，追到了开心一下接着追；玩一阵就累了，打个哈欠坐下歇会儿。

点她一下 = 你抓到她了，游戏结束。
配置（play 段）：chase_seconds 玩多久会累（默认 45）
"""

import time

from deskpet.behavior import HOP_AIR, HOP_TICKS, hop_pose
from deskpet.play import MOVE_MS, move_pet

NAME = "chase"
TITLE = "追鼠标"
INVITE = "好无聊…要不要陪我玩追鼠标？"
DESC = "追鼠标：她来追你的鼠标，点她就算抓到"
NEED = ("walk",)

SPEED = 6.0                # 每 MOVE_MS 跑几像素（约 150 像素/秒）
CATCH_DIST = 36            # 离指针多近算追到
FAR = 260                  # 离得远就蹦着追


class Play:
    def __init__(self, pet, cfg):
        self.pet = pet
        self.duration = float(cfg.get("chase_seconds", 45))
        self.phase = "chase"           # chase / caught / tired / rest / done
        self.phase_until = 0.0
        self.dir = 1
        self.far = False
        self.catches = 0
        self.alive = False
        self.wait_away = False         # 刚追到：等指针跑远点再追，别原地反复「抓到」
        self.moving = False
        self.hop_k = 0                 # 离得远时蹦着追：在一跳里的第几步（0 = 在地上）

    # ------------------------------------------------------------------ 生命周期
    def start(self):
        now = time.time()
        self.end_at = now + self.duration
        self.x, self.y = float(self.pet.root.winfo_x()), float(self.pet.root.winfo_y())
        self.alive = True
        self.pet.say("来追我呀——不对，是我来追你！", 3, fun=True)
        self.pet.root.after(MOVE_MS, self._move)

    def stop(self):
        self.alive = False

    def on_click(self):
        if self.phase in ("chase", "caught"):
            self.pet.say("呜…被你抓到了！", 3, fun=True)
            self._tired(time.time(), caught_by_you=True)

    # ------------------------------------------------------------------ 每帧
    def step(self, now, t):
        # 到点就累 —— 不管正在追还是正在开心（之前只在「追」里判断，指针不动时会一直玩下去）
        if self.phase in ("chase", "caught") and now >= self.end_at:
            self._tired(now)
        if self.phase == "caught":
            if now < self.phase_until:
                return ("happy", False, 4)
            self.phase = "chase"
        if self.phase == "chase":
            if not self.moving:
                return ("idle", self.dir < 0, 7)            # 在指针旁边等它跑远
            if self.hop_k and "hop" in self.pet.skin:
                # 姿势跟着跳的高度走：贴地下蹲、离地腾空（之前一直是腾空图贴地平移，像在飘）
                return ("hop", self.dir < 0, ("frame", hop_pose(self.hop_k)[1]))
            return ("walk", self.dir < 0, 2)
        if self.phase == "tired":
            if now < self.phase_until:
                return ("yawn" if "yawn" in self.pet.skin else "idle", False, 6)
            self.phase, self.phase_until = "rest", now + 5
            self.pet.say("玩累了…歇会儿", 5, fun=True)
        if self.phase == "rest":
            if now < self.phase_until:
                return ("sit" if "sit" in self.pet.skin else "idle", False, 6)
            self.phase = "done"
            self.pet.log("追鼠标：追到 %d 次" % self.catches)
        return None

    # ------------------------------------------------------------------ 内部
    def _tired(self, now, caught_by_you=False):
        self.alive = False
        self.phase = "tired"
        self.phase_until = now + (1.5 if caught_by_you else 2.5)

    def _move(self):
        """MOVE_MS 一次：往指针跑。她的头顶对准指针（不是脚），看着像在扑过去。"""
        if not self.alive or self.phase != "chase":
            if self.alive:
                self.pet.root.after(MOVE_MS, self._move)
            return
        px, py = self.pet.root.winfo_pointerxy()
        tx = px - self.pet.cw / 2
        ty = py - self.pet.head_y - 6
        dx, dy = tx - self.x, ty - self.y
        dist = (dx * dx + dy * dy) ** 0.5
        if self.wait_away:
            if dist < CATCH_DIST * 3:
                self.moving = False
                self.pet.root.after(MOVE_MS, self._move)
                return
            self.wait_away = False
        if dist < CATCH_DIST:
            self.wait_away = True
            self.moving = False
            if self.hop_k:                                   # 半空中追到的：先落回地上
                self.hop_k = 0
                move_pet(self.pet, self.x, self.y)
            self.catches += 1
            self.phase, self.phase_until = "caught", time.time() + 1.0
            if self.catches in (1, 3, 6):
                self.pet.say(("抓到啦！", "又抓到了～", "你跑不掉的！")[(1, 3, 6).index(self.catches)],
                             2, fun=True)
        else:
            self.moving = True
            self.far = dist > FAR
            # 远了就蹦着追：一跳做完（回到地上）才决定下一步继续蹦还是改走
            if self.hop_k or (self.far and "hop" in self.pet.skin):
                self.hop_k = (self.hop_k + 1) % HOP_TICKS
                lift, _, in_air = hop_pose(self.hop_k)
                if in_air:                                   # 只在空中往前移
                    step = SPEED * 1.4 * HOP_TICKS / HOP_AIR
                    self.x += dx / dist * step
                    self.y += dy / dist * step
            else:
                lift = 0
                self.x += dx / dist * SPEED
                self.y += dy / dist * SPEED
            if abs(dx) > 2 and not (self.hop_k and hop_pose(self.hop_k)[2]):
                self.dir = 1 if dx > 0 else -1               # 空中不转身
            self.x, self.y = move_pet(self.pet, self.x, self.y)
            if lift:                                         # 跳的高度只体现在画面上，不改追的路线
                move_pet(self.pet, self.x, self.y - lift)
        self.pet.root.after(MOVE_MS, self._move)
