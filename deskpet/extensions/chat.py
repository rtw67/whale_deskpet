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
   对话记录每次连同前面的话一起发过去（最多带最近 40 条）。

记忆：一个话题结束（太久没说话、点「新话题」）后，后台让模型把这段聊天里值得长期记住的事
（你的称呼、在忙什么、喜欢什么、约好的事……）合并进 data/chat_memory.md，以后每次聊天都带上。
这个文件可以直接改、删；窗口上的「记忆」打开它。当前话题和聊天记录存在 data/chat_state.json，
重启后接着聊。

表情：让模型在回复最后带一个 [开心] [惊讶] 这样的标签，程序拿掉标签，换成她的动作。

通用配置：
    enabled          false
    backend          claude     claude 或 api
    model            sonnet     claude 时是 claude --model 的值；api 时 api.model 没写就用它
    claude           ""         claude 命令的路径，空 = 从 PATH 里找
    persona          ""         人设（直接写一段文字），优先级最高
    persona_file     ""         人设文件（相对项目根目录或绝对路径）
                                都没写就用皮肤目录里的 persona.md，再没有就用下面的 PERSONA
    timeout          120        一句话最多等几秒
    session_minutes  30         多久没说话就开新话题（点「新话题」也行）
    memory           true       记不记长期记忆（整理一次要多调一次模型）
    emotes           true       回复时做表情动作
"""

import json
import os
import queue
import re
import shutil
import subprocess
import threading
import tempfile
import time
import urllib.error
import urllib.request

from datetime import datetime

import tkinter as tk

from deskpet import sprite
from deskpet.card import link, panel, place_near
from deskpet.util import ROOT, data_path, load_json, save_json
from deskpet.theme import BG, BTN2_BG, BTN_BG, BTN_FG, DETAIL_FG, FONT, MSG_FG

NAME = "chat"

WEEKDAYS = "一二三四五六日"
# 皮肤里没有 persona.md 时的人设
PERSONA = ("你是住在用户电脑桌面上的桌宠「{name}」，一个蓝色头发、穿女仆装的 Q 版鲸鱼娘。"
           "说话口语化、温柔可爱，可以偶尔用「～」。回答简短，一般三四句话以内；"
           "用户要详细解释或代码时再展开。不要用 Markdown 标题和表格。")

MEMORY_PROMPT = """你在帮桌宠「{name}」整理她对用户的长期记忆。下面会给你她已有的记忆和最近几段聊天。

把聊天里值得长期记住的事合并进记忆：用户希望怎么被称呼、职业和最近在忙的事、喜欢和讨厌的东西、
近期的计划和烦恼、你们之间的约定和小梗。不要记一次性的问题细节（比如某段代码怎么写）和客套话。
新内容和已有记忆冲突时以新的为准，明显过时的删掉。和时间有关的写上日期（几月几日）。

每条一行，以「- 」开头，总共不超过 20 条。只输出记忆列表本身，不要任何别的话。
一条值得记的都没有时，输出「（无）」。"""

# 回复末尾的表情标签 -> (表情, 摆几秒)。None = 不做动作
EMOTES = {"开心": ("happy", 2.5), "兴奋": ("dance", 3.0), "挥手": ("wave", 2.4),
          "惊讶": ("oops", 2.0), "难过": ("sit", 4.0), "困": ("yawn", 2.2),
          "思考": ("look", 3.0), "平常": None}
EMOTE_NOTE = ("## 表情\n"
              "每次回复的最后另起一行，写一个方括号标签表示你说这话时的表情，从这几个里选："
              + " ".join("[%s]" % k for k in EMOTES) +
              "。只写一个。标签会被程序拿掉、换成你在桌面上的动作，用户看不到它。")
ACTION_RE = re.compile(r"\[\[\s*([^\]:：\s]+?)\s*[:：]\s*(.+?)\s*\]\]")
EMOTE_RE = re.compile(r"\s*[\[【［]\s*([^\]】］\s]{1,4})\s*[\]】］]\s*$")

ME_FG = "#8ec5ff"
MAX_HISTORY = 40
MAX_LOG = 200              # 窗口里留多少条（存盘的也是这么多）
MAX_PENDING = 5            # 最多攒几段没整理进记忆的话题
MEMORY_MAX = 2000          # 记忆文件最多多少字
STATE_FILE = "chat_state.json"
MEMORY_FILE = "chat_memory.md"

# conv：当前话题。claude 时是会话 id，api 时是发过的消息列表；None = 新话题
# topic：当前话题里说过的话 [[谁, 话], ...]，话题结束时交给记忆整理
_s = {"conv": None, "last": 0.0, "busy": False, "win": None, "log": [], "topic": [], "unread": False}
_q = queue.Queue()
_pending = []              # 结束了、还没整理进记忆的话题 [{"date", "lines"}]
_plock = threading.Lock()  # 管 _pending（主线程和后台线程都会动）
_wlock = threading.Lock()  # 后台调模型一次只跑一个：先整理记忆，再回话


def _cfg(pet):
    return pet.cfg.get("chat") or {}


def setup(pet):
    pet.stats.register_event("chat", 1, 2, 0, 10, "聊天")
    _load()
    _drain(pet)


def poll(pet, now):
    # 太久没说话：这个话题算结束了，趁空闲整理进记忆
    c = _cfg(pet)
    if (c.get("enabled") and _s["topic"] and not _s["busy"]
            and now - _s["last"] > float(c.get("session_minutes", 30)) * 60):
        _end_topic(pet)


def menu_items(pet):
    if not _cfg(pet).get("enabled"):
        return []
    return [{"label": "聊天", "icon": "chat", "tip": "和她聊天", "cb": lambda: open_window(pet)}]


def on_open(pet, msg):
    if msg.get("source") != "chat":
        return False
    open_window(pet)
    return True


# ---------------------------------------------------------------------- 存盘
def _load():
    d = load_json(data_path(STATE_FILE), {}) or {}
    _s["conv"] = d.get("conv")
    _s["last"] = float(d.get("last") or 0)
    _s["log"] = [tuple(x) for x in d.get("log") or []]
    _s["topic"] = d.get("topic") or []
    with _plock:
        _pending[:] = d.get("pending") or []


def _save():
    with _plock:
        pending = list(_pending)
    try:
        save_json(data_path(STATE_FILE), {"conv": _s["conv"], "last": _s["last"],
                                          "log": [list(x) for x in _s["log"][-MAX_LOG:]],
                                          "topic": _s["topic"], "pending": pending})
    except OSError:
        pass


def _read_memory():
    try:
        with open(data_path(MEMORY_FILE), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _open_memory():
    path = data_path(MEMORY_FILE)
    if not os.path.exists(path):
        open(path, "w", encoding="utf-8").close()
    os.startfile(path)


# ---------------------------------------------------------------------- 人设
def _persona(pet):
    """人设正文。在主线程里调。

    人设里的 {name} 换成她的名字（用 replace，人设正文里可以随便出现别的大括号）。
    """
    c = _cfg(pet)
    text = c.get("persona")
    if not text:
        path = c.get("persona_file") or os.path.join(sprite.SKIN_DIR, "persona.md")
        if not os.path.isabs(path):
            path = os.path.join(ROOT, path)
        try:
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = PERSONA
    return text.replace("{name}", pet.cfg.get("name", "鲸鱼娘")).rstrip()


def _state_note(pet):
    """附在最后的「你现在的状态」，让她说话跟桌宠里的数值对得上。在主线程里调（要读 pet.stats）。"""
    s = pet.stats
    _, title, _, _ = s.level()
    now = datetime.now()
    try:
        days = (now.date() - datetime.strptime(s.first_seen, "%Y-%m-%d").date()).days + 1
    except (TypeError, ValueError):
        days = 1
    lines = ["## 你现在的状态",
             "- 好感等级：%s（和用户认识第 %d 天）" % (title, days),
             "- 心情：%s" % s.mood_word(),
             "- 体力：%s" % s.energy_word(),
             "- 现在：周%s %s" % (WEEKDAYS[now.weekday()], now.strftime("%H:%M"))]
    if pet.off_duty():
        lines.append("- 现在是你的休息时间，你本来在睡觉，被叫醒来聊天")
    # 别的扩展补充的（天气、待办……）
    for more in pet.ext.call("chat_context", pet):
        if more:
            lines.append(str(more).strip())
    return "\n".join(lines)


def _system(c, persona, state):
    """拼出完整的系统提示词：人设、记忆、表情说明、状态。记忆在后台线程里整理完才读。"""
    parts = [persona]
    mem = _read_memory() if c.get("memory", True) else ""
    if mem:
        parts.append("## 你记得的事\n以前和用户聊天时记下的。自然地用上就好，"
                     "不要一条条念出来，也不要说「根据记忆」：\n" + mem)
    if c.get("emotes", True):
        parts.append(EMOTE_NOTE)
    parts.append(state)
    return "\n\n".join(parts)


def _actions(pet):
    """扩展登记的「她能做的事」（chat_actions 钩子）：[{"tag", "desc", "run"}]。"""
    out = []
    for acts in pet.ext.call("chat_actions", pet):
        out += [a for a in acts or [] if a.get("tag") and a.get("run")]
    return out


def _actions_note(acts):
    if not acts:
        return ""
    return ("\n\n## 你能帮用户做的事\n"
            "需要的时候，在回复里单独起一行写 [[名字: 内容]]，程序会去做，这一行用户看不到；"
            "做没做成程序会告诉用户，你正常说话就好：\n" +
            "\n".join("- [[%s: ...]]：%s" % (a["tag"], a.get("desc", "")) for a in acts))


def _do_actions(pet, reply):
    """找出回复里的 [[名字: 内容]]，拿掉，交给对应的扩展去做。返回 (正文, [结果说明])。"""
    acts = {a["tag"]: a for a in _actions(pet)}
    notes = []

    def run(m):
        a = acts.get(m.group(1))
        if not a:
            return m.group(0)                  # 不认识的：原样留着
        try:
            r = a["run"](m.group(2).strip())
        except Exception as e:                                     # noqa: BLE001
            r = "没做成：%s" % e
        if r:
            notes.append(str(r))
        return ""

    reply = ACTION_RE.sub(run, reply)
    return re.sub(r"\n{3,}", "\n\n", reply).strip(), notes


def _emote(reply):
    """拿掉回复末尾的表情标签，返回 (正文, 标签)。没有标签时标签是 None。"""
    m = EMOTE_RE.search(reply)
    if m and m.group(1) in EMOTES:
        return reply[:m.start()].rstrip(), m.group(1)
    return reply, None


# ---------------------------------------------------------------------- 调模型
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


def _call(c, system, text, conv):
    """问一句，返回 (回复, 新的 conv)。出错 raise。"""
    if c.get("backend") == "api":
        return _ask_api(c, system, text, conv or [])
    return _ask_claude(c, system, text, conv)


def _work(c, name, text, conv, persona, state):
    """后台线程：先把攒下的话题整理进记忆，再回这句话（text 为 None 时只整理）。"""
    with _wlock:
        if c.get("memory", True):
            _fold(c, name)
        if text is None:
            return
        try:
            reply, conv = _call(c, _system(c, persona, state), text, conv)
            _q.put({"kind": "reply", "reply": reply, "conv": conv})
        except Exception as e:                                     # noqa: BLE001
            _q.put({"kind": "reply", "err": str(e)[:300] or e.__class__.__name__, "conv": conv})


def _fold(c, name):
    """把 _pending 里的话题和已有记忆一起交给模型，换成新的记忆。失败了留着下次再试。"""
    with _plock:
        topics = list(_pending)
    if not topics:
        return
    chat = "\n\n".join("【%s 的聊天】\n" % t["date"] +
                       "\n".join(("用户：" if who == "me" else "她：") + said[:500]
                                 for who, said in t["lines"])
                       for t in topics)[-12000:]
    prompt = "已有的记忆：\n%s\n\n最近的聊天：\n%s" % (_read_memory() or "（还没有）", chat)
    try:
        mem = _call(c, MEMORY_PROMPT.replace("{name}", name), prompt, None)[0].strip()
    except Exception as e:                                         # noqa: BLE001
        _q.put({"kind": "log", "text": "聊天：整理记忆没成功，下次再试（%s）" % str(e)[:200]})
        return
    mem = mem.strip("`").strip()
    if mem in ("（无）", "(无)", "无"):
        mem = ""
    if len(mem) > MEMORY_MAX:
        mem = mem[:MEMORY_MAX].rsplit("\n", 1)[0]
    try:
        with open(data_path(MEMORY_FILE), "w", encoding="utf-8") as fh:
            fh.write(mem + "\n" if mem else "")
    except OSError as e:
        _q.put({"kind": "log", "text": "聊天：记忆文件写不进去（%s）" % e})
        return
    with _plock:
        del _pending[:len(topics)]
    _q.put({"kind": "memory", "text": "聊天：%d 段话题整理进记忆了（%d 条）" %
            (len(topics), mem.count("\n") + 1 if mem else 0)})


def _ask_claude(c, system, text, sid):
    cmd = _command(c)
    if not cmd:
        raise RuntimeError("没找到 claude 命令，先装 Claude Code，或者改用 backend: api")
    args = cmd + ["-p", "--model", str(c.get("model") or "sonnet"), "--tools", "",
                  "--output-format", "json", "--system-prompt", system]
    if sid:
        args += ["--resume", sid]
    # 在仓库外面的空目录里跑：不会被当成哪个项目，读不到 CLAUDE.md 和项目记忆
    cwd = os.path.join(tempfile.gettempdir(), "deskpet-chat")
    os.makedirs(cwd, exist_ok=True)
    try:
        r = subprocess.run(args, input=text.encode("utf-8"), cwd=cwd, capture_output=True,
                           timeout=float(c.get("timeout", 120)),
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise RuntimeError("等太久了，没回音")
    out = r.stdout.decode("utf-8", "replace")
    try:
        d = json.loads(out)
    except ValueError:
        err = (r.stderr.decode("utf-8", "replace") or out).strip()
        raise RuntimeError(err[:300] or "claude 没有返回内容")
    if d.get("is_error"):
        raise RuntimeError(str(d.get("result") or "出错了")[:300])
    return (d.get("result") or "").strip(), d.get("session_id") or sid


def _ask_api(c, system, text, history):
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
        body = {"model": model, "max_tokens": max_tokens, "system": system, "messages": msgs}
    elif fmt == "openai":
        url = base + "/chat/completions"
        if key:
            headers["Authorization"] = "Bearer " + key
        body = {"model": model, "max_tokens": max_tokens,
                "messages": [{"role": "system", "content": system}] + msgs}
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


# ---------------------------------------------------------------------- 话题
def _end_topic(pet):
    """当前话题结束：说过话的交给记忆整理（空闲时马上在后台整理），下一句开新话题。"""
    c = _cfg(pet)
    topic, _s["topic"], _s["conv"] = _s["topic"], [], None
    if c.get("memory", True) and any(who == "her" for who, _ in topic):
        with _plock:
            _pending.append({"date": datetime.fromtimestamp(_s["last"] or time.time()).strftime("%m-%d"),
                             "lines": topic})
            del _pending[:-MAX_PENDING]
        if not _s["busy"]:
            threading.Thread(target=_work, args=(c, pet.cfg.get("name", "鲸鱼娘"), None, None, None, None),
                             daemon=True).start()
    _save()


def send(pet, text):
    text = text.strip()
    if not text or _s["busy"]:
        return
    c = _cfg(pet)
    now = time.time()
    if now - _s["last"] > float(c.get("session_minutes", 30)) * 60:
        _end_topic(pet)
    _s["last"] = now
    _s["busy"] = True
    _s["log"].append(("me", text))
    _s["topic"].append(["me", text])
    pet.log("聊天：发了一句（%d 字）" % len(text))
    pet.set_sign("chat", expr="look", text=None, on_click=lambda: open_window(pet), priority=-1)
    threading.Thread(target=_work, args=(c, pet.cfg.get("name", "鲸鱼娘"), text, _s["conv"],
                                         _persona(pet) + _actions_note(_actions(pet)), _state_note(pet)),
                     daemon=True).start()
    _save()
    _render()


def _drain(pet):
    """主线程里每 0.2 秒看一眼后台有没有消息（Tk 只能在主线程里动）。"""
    try:
        while True:
            d = _q.get_nowait()
            if d["kind"] != "reply":
                pet.log(d["text"])
                _save()
                continue
            err = d.get("err")
            _s["busy"] = False
            _s["last"] = time.time()
            pet.clear_sign("chat")
            if err:
                pet.log("聊天出错：%s" % err)
                _s["log"].append(("err", err))
            else:
                _s["conv"] = d["conv"]
                reply, notes = _do_actions(pet, d["reply"])
                reply, tag = _emote(reply)
                _s["log"].append(("her", reply))
                _s["topic"].append(["her", reply])
                for n in notes:
                    _s["log"].append(("note", n))
                pet.stats.event("chat")
                if tag is None:
                    pet.cheer(1.5)
                elif EMOTES[tag] and _alive():
                    pet.behavior.show(*EMOTES[tag])
            _save()
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
        _end_topic(pet)
        _s["log"] = []
        _save()
        _render()

    top, card, head = panel(pet, "和%s聊天" % pet.cfg.get("name", "鲸鱼娘"), hide)
    link(head, "新话题", reset)
    if _cfg(pet).get("memory", True):
        link(head, "记忆", _open_memory)

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
    for who, t in _s["log"][-MAX_LOG:]:
        if who == "me":
            txt.insert("end", "你\n", "who")
            txt.insert("end", t + "\n", "me")
        elif who == "note":
            txt.insert("end", "（%s）\n" % t, "wait")
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
