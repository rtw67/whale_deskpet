# -*- coding: utf-8 -*-
"""聊天：右键「聊天」弹一个小窗口和她聊天。默认关着，config.json 里打开。只聊天，她不会读写文件、跑命令。

两种接法（backend）：

1. claude（默认）—— 后台调本机的 Claude Code（claude -p），用的是 cc 自己登录的账号 / 配置：

    "chat": {"enabled": true, "model": "sonnet"}

   --tools "" 关掉所有工具；--system-prompt 换掉 cc 默认的系统提示词（那里面全是写代码、
   用工具的说明），只留人设；同一个话题用 --resume 接上下文。

2. api —— 不用装 cc，直接调 HTTP 接口，地址和 key 写在配置里。两种格式：

    "chat": {"enabled": true, "backend": "api", "api": {
        "format": "anthropic",                  Anthropic Messages 格式（POST <base_url>/v1/messages）
        "base_url": "https://api.anthropic.com",
        "key": "sk-ant-...",
        "model": "claude-sonnet-5-5"}}

    "chat": {"enabled": true, "backend": "api", "api": {
        "format": "openai",                     OpenAI 兼容格式（POST <base_url>/chat/completions），
        "base_url": "https://api.deepseek.com", DeepSeek、通义、Kimi、本地 Ollama 这类都是这个
        "key": "sk-...",
        "model": "deepseek-chat"}}

   api 段里还能写：
    key_env      ""     key 不想写进文件就放环境变量，这里写变量名
    headers      {}     额外的请求头，比如代理要的 {"Token": "..."}
    max_tokens   4096
   anthropic 格式没写 base_url / key / headers 时，跟 Claude Code 一样读环境变量
   ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY / ANTHROPIC_CUSTOM_HEADERS（每行一个「名字: 值」）。
   对话记录存在内存里，每次连同前面的话一起发过去（最多带最近 40 条）。

通用配置：
    enabled          false
    backend          claude     claude 或 api
    model            sonnet     claude 时是 claude --model 的值；api 时 api.model 没写就用它
    claude           ""         claude 命令的路径，空 = 从 PATH 里找
    persona          ""         人设，空 = 用下面的 PERSONA
    timeout          120        一句话最多等几秒
    session_minutes  30         多久没说话就开新话题（点「新话题」也行）
"""

import json
import os
import queue
import shutil
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.request

import tkinter as tk

from deskpet.card import link, panel, place_near
from deskpet.theme import BG, BTN2_BG, BTN_BG, BTN_FG, DETAIL_FG, FONT, MSG_FG

NAME = "chat"

PERSONA = ("你是住在用户电脑桌面上的桌宠「{name}」，一个蓝色头发、穿女仆装的 Q 版鲸鱼娘。"
           "说话口语化、温柔可爱，可以偶尔用「～」。回答简短，一般三四句话以内；"
           "用户要详细解释或代码时再展开。不要用 Markdown 标题和表格。")

ME_FG = "#8ec5ff"
MAX_HISTORY = 40
# conv：当前话题。claude 时是会话 id，api 时是发过的消息列表；None = 新话题
_s = {"conv": None, "last": 0.0, "busy": False, "win": None, "log": [], "unread": False}
_q = queue.Queue()


def _cfg(pet):
    return pet.cfg.get("chat") or {}


def setup(pet):
    pet.stats.register_event("chat", 1, 2, 0, 10, "聊天")
    _drain(pet)


def menu_items(pet):
    if not _cfg(pet).get("enabled"):
        return []
    return [{"label": "聊天", "icon": "chat", "tip": "和她聊天", "cb": lambda: open_window(pet)}]


def on_open(pet, msg):
    if msg.get("source") != "chat":
        return False
    open_window(pet)
    return True


# ---------------------------------------------------------------------- 调 claude
def _command(c):
    """找 claude。npm 装的在 Windows 上是 claude.cmd：直接用 node 跑 cli.js，免得 cmd 把参数里的 [] "" 搞乱。"""
    exe = c.get("claude") or shutil.which("claude")
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        d = os.path.dirname(exe)
        js = os.path.join(d, "node_modules", "@anthropic-ai", "claude-code", "cli.js")
        node = os.path.join(d, "node.exe") if os.path.exists(os.path.join(d, "node.exe")) else shutil.which("node")
        if os.path.exists(js) and node:
            return [node, js]
    return [exe]


def _ask(pet, text, conv):
    """后台线程里跑：问一句，把 (回复, 新的 conv, 出错信息) 放进队列。"""
    c = _cfg(pet)
    persona = c.get("persona") or PERSONA.format(name=pet.cfg.get("name", "鲸鱼娘"))
    if c.get("backend") == "api":
        try:
            reply, conv = _ask_api(c, persona, text, conv or [])
            _q.put((reply, conv, None))
        except Exception as e:                                     # noqa: BLE001
            _q.put((None, conv, str(e)[:300] or e.__class__.__name__))
        return
    _ask_claude(c, persona, text, conv)


def _ask_claude(c, persona, text, sid):
    cmd = _command(c)
    if not cmd:
        _q.put((None, sid, "没找到 claude 命令，先装 Claude Code，或者改用 backend: api"))
        return
    args = cmd + ["-p", "--model", str(c.get("model") or "sonnet"), "--tools", "",
                  "--output-format", "json", "--system-prompt", persona]
    if sid:
        args += ["--resume", sid]
    # 在仓库外面的空目录里跑：不会被当成哪个项目，读不到 CLAUDE.md 和项目记忆
    cwd = os.path.join(tempfile.gettempdir(), "deskpet-chat")
    os.makedirs(cwd, exist_ok=True)
    try:
        r = subprocess.run(args, input=text.encode("utf-8"), cwd=cwd, capture_output=True,
                           timeout=float(c.get("timeout", 120)),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = r.stdout.decode("utf-8", "replace")
        try:
            d = json.loads(out)
        except ValueError:
            err = (r.stderr.decode("utf-8", "replace") or out).strip()
            _q.put((None, sid, err[:300] or "claude 没有返回内容"))
            return
        if d.get("is_error"):
            _q.put((None, sid, str(d.get("result") or "出错了")[:300]))
        else:
            _q.put(((d.get("result") or "").strip(), d.get("session_id") or sid, None))
    except subprocess.TimeoutExpired:
        _q.put((None, sid, "等太久了，没回音"))
    except Exception as e:                                         # noqa: BLE001
        _q.put((None, sid, str(e)))


def _ask_api(c, persona, text, history):
    """直接调 HTTP 接口问一句，返回 (回复, 带上这一问一答的消息列表)。出错直接 raise。"""
    api = c.get("api") or {}
    fmt = api.get("format") or "anthropic"
    env = os.environ.get
    base = api.get("base_url") or (env("ANTHROPIC_BASE_URL") or "https://api.anthropic.com"
                                   if fmt == "anthropic" else None)
    if not base:
        raise RuntimeError("chat.api 里没写 base_url")
    key = api.get("key") or env(api.get("key_env") or
                                ("ANTHROPIC_API_KEY" if fmt == "anthropic" else "OPENAI_API_KEY")) or ""
    headers = {"Content-Type": "application/json"}
    if fmt == "anthropic" and "headers" not in api:
        for line in (env("ANTHROPIC_CUSTOM_HEADERS") or "").splitlines():
            name, _, value = line.partition(":")
            if name.strip() and value.strip():
                headers[name.strip()] = value.strip()
    headers.update(api.get("headers") or {})
    model = api.get("model") or c.get("model") or ""
    if model.endswith("[1m]"):                        # cc 的写法（开 1M 上下文），真正的模型名不带它
        model = model[:-4]
    max_tokens = int(api.get("max_tokens", 4096))
    msgs = (history + [{"role": "user", "content": text}])[-MAX_HISTORY:]
    while msgs and msgs[0]["role"] != "user":         # 截断后得从用户的话开头
        msgs = msgs[1:]

    base = base.rstrip("/")
    if fmt == "anthropic":
        url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        headers.update({"x-api-key": key, "anthropic-version": "2023-06-01"})
        body = {"model": model, "max_tokens": max_tokens, "system": persona, "messages": msgs}
    elif fmt == "openai":
        url = base + "/chat/completions"
        if key:
            headers["Authorization"] = "Bearer " + key
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": persona}] + msgs}
    else:
        raise RuntimeError("chat.api.format 只能是 anthropic 或 openai")

    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=float(c.get("timeout", 120))) as r:
            d = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            err = json.loads(raw).get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else str(err)
        except ValueError:
            msg = raw
        raise RuntimeError("接口报错 %d：%s" % (e.code, (msg or raw)[:200]))
    except urllib.error.URLError as e:
        raise RuntimeError("连不上 %s：%s" % (url, e.reason))

    if fmt == "anthropic":
        if d.get("stop_reason") == "refusal":
            raise RuntimeError("模型拒绝回答这个问题")
        # 新模型会带 thinking 块，只要 text
        reply = "".join(b.get("text", "") for b in d.get("content") or [] if b.get("type") == "text")
    else:
        reply = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    reply = reply.strip()
    if not reply:
        raise RuntimeError("接口没有返回内容")
    return reply, msgs + [{"role": "assistant", "content": reply}]


def send(pet, text):
    text = text.strip()
    if not text or _s["busy"]:
        return
    now = time.time()
    if now - _s["last"] > float(_cfg(pet).get("session_minutes", 30)) * 60:
        _s["conv"] = None
    _s["last"] = now
    _s["busy"] = True
    _s["log"].append(("me", text))
    pet.log("聊天：发了一句（%d 字）" % len(text))
    pet.set_sign("chat", expr="look", text=None, on_click=lambda: open_window(pet), priority=-1)
    threading.Thread(target=_ask, args=(pet, text, _s["conv"]), daemon=True).start()
    _render()


def _drain(pet):
    """主线程里每 0.2 秒看一眼有没有回复（Tk 只能在主线程里动）。"""
    try:
        while True:
            reply, conv, err = _q.get_nowait()
            _s["busy"] = False
            _s["last"] = time.time()
            pet.clear_sign("chat")
            if err:
                pet.log("聊天出错：%s" % err)
                _s["log"].append(("err", err))
            else:
                _s["conv"] = conv
                _s["log"].append(("her", reply))
                pet.stats.event("chat")
                pet.cheer(1.5)
            if _alive():
                _render()
            else:
                # 窗口关了：冒个气泡，点开接着看
                _s["unread"] = True
                pet.items.append({"kind": "persist", "msg": {"source": "chat"}, "at": time.time(),
                                  "text": "回你啦，点我看～" if not err else "刚才没回上来…点我看看"})
    except queue.Empty:
        pass
    pet.root.after(200, lambda: _drain(pet))


# ---------------------------------------------------------------------- 窗口
def _alive():
    w = _s["win"]
    return w is not None and w["top"].winfo_exists()


def open_window(pet):
    pet.items[:] = [it for it in pet.items if (it.get("msg") or {}).get("source") != "chat"]
    _s["unread"] = False
    if _alive():
        _s["win"]["top"].deiconify()
        _s["win"]["entry"].focus_force()
        return

    def hide():
        top.withdraw()                     # 只是藏起来，记录留着

    def reset():
        if _s["busy"]:
            return
        _s["conv"], _s["log"] = None, []
        _render()

    top, card, head = panel(pet, "和%s聊天" % pet.cfg.get("name", "鲸鱼娘"), hide)
    link(head, "新话题", reset)

    box = tk.Frame(card, bg=BG)
    box.pack(fill="both", expand=True, padx=10)
    txt = tk.Text(box, width=40, height=16, bg=BG, fg=MSG_FG, font=(FONT, 9), wrap="char",
                  relief="flat", bd=0, highlightthickness=0, padx=2, pady=2, cursor="arrow")
    sb = tk.Scrollbar(box, command=txt.yview)
    txt.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y")
    txt.pack(side="left", fill="both", expand=True)
    txt.tag_configure("me", foreground=ME_FG, spacing1=8)
    txt.tag_configure("her", foreground=MSG_FG, spacing1=8)
    txt.tag_configure("who", foreground=DETAIL_FG, font=(FONT, 8), spacing1=8)
    txt.tag_configure("err", foreground="#f28b82", spacing1=8)
    txt.tag_configure("wait", foreground=DETAIL_FG, spacing1=8)

    row = tk.Frame(card, bg=BG)
    row.pack(fill="x", padx=10, pady=(6, 10))
    entry = tk.Entry(row, bg="#2a3040", fg=MSG_FG, insertbackground=MSG_FG, relief="flat",
                     font=(FONT, 10))
    entry.pack(side="left", fill="x", expand=True, ipady=4)
    btn = tk.Button(row, text="发送", bg=BTN_BG, fg=BTN_FG, relief="flat", bd=0, padx=10,
                    font=(FONT, 9), cursor="hand2", activebackground=BTN_BG, activeforeground=BTN_FG)
    btn.pack(side="right", padx=(6, 0))

    def go(e=None):
        t = entry.get()
        if t.strip() and not _s["busy"]:
            entry.delete(0, "end")
            send(pet, t)
        return "break"

    btn.configure(command=go)
    entry.bind("<Return>", go)
    entry.bind("<Escape>", lambda e: hide())

    _s["win"] = {"top": top, "txt": txt, "entry": entry, "btn": btn}
    _render()
    place_near(pet, top)
    top.after(50, entry.focus_force)


def _render():
    if not _alive():
        return
    w = _s["win"]
    txt = w["txt"]
    txt.configure(state="normal")
    txt.delete("1.0", "end")
    if not _s["log"]:
        txt.insert("end", "想聊点什么？回车发送，Esc 收起。\n", "wait")
    for who, t in _s["log"]:
        if who == "me":
            txt.insert("end", "你\n", "who")
            txt.insert("end", t + "\n", "me")
        elif who == "her":
            txt.insert("end", "她\n", "who")
            txt.insert("end", t + "\n", "her")
        else:
            txt.insert("end", "（%s）\n" % t, "err")
    if _s["busy"]:
        txt.insert("end", "她在想……\n", "wait")
    txt.configure(state="disabled")
    txt.see("end")
    w["btn"].configure(state="disabled" if _s["busy"] else "normal",
                       bg=BTN2_BG if _s["busy"] else BTN_BG)
