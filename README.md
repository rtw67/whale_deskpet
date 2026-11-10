# desktop-pet 桌宠

一个蹲在 Windows 桌面右下角的小桌宠：会**替你的程序冒气泡提醒**、会**举牌要你处理事情**，
闲着时做小动作、四处溜达、偶尔邀请你一起玩，还有好感度 / 心情 / 体力。
自带一套 DeepSeek 社区同人形象「鲸鱼娘」皮肤。

纯 Python 标准库（tkinter），**不需要 pip install 任何东西**。

[English below](#english)

## 功能

- **提醒**：任何程序往本地端口发一行 JSON，她就冒气泡；点她看详情，右键「消息」能翻看最近 15 条。
- **举牌**：扩展可以让她举红牌 / 二维码牌，直到你处理完（比如"有任务分配给你，点我确认"）。
- **待机**：发呆、眨眼、伸懒腰、打哈欠、挥手、摸鱼、跳舞……隔一阵在「家」附近溜达：随机几个落脚点、走一段歇一下，走法（走、背手踱步、小跳、翻滚）和路线每段都不一样，偶尔横穿屏幕「路过」。
- **一起玩**：闲得久了会邀请你玩「追鼠标」或「捉迷藏」（她从屏幕边探头，缩回去之前点到她算捉到）；也可以右键「玩」主动开始。玩法是插件，可以自己加。
- **好感度 / 心情 / 体力**：摸摸、喂饭、陪玩都会涨好感，好感越高解锁越多台词。只加分、不惩罚、不需要每天照顾。
- **聊天**（默认关）：右键「聊天」和她说话。可以接本机的 Claude Code，也可以在配置里直接填接口地址和 key（Anthropic 格式或 OpenAI 兼容格式，DeepSeek 之类都行）。只聊天，不会动你的文件。配置写法见 [`deskpet/extensions/chat.py`](deskpet/extensions/chat.py) 开头。
- **右键泡泡菜单**：多层、自动分页、像素风图标。
- **云朵气泡**：蓝色云朵形状、白字，大小随文字自动收放，小尾巴指向她。
- **休息时间**：下班和周末她会睡觉（时间可配）。

## 快速开始

需要 Windows + Python 3.8 以上（自带 tkinter）。

```
git clone https://github.com/rtw67/whale_deskpet.git
cd whale_deskpet
pythonw pet.py          # 或者双击 pet.bat
```

- 左键拖动她换位置（会记住，那里就是她的「家」）；单击 = 处理当前这条，没事时 = 摸摸她；长按 = 看状态。
- 右键：消息、互动（玩 / 喂饭 / 状态）、工作（装扩展时）、归位、退出。
- 配置：复制 `config.example.json` 为 `config.json` 再改，存盘几秒内生效。运行数据在 `data/`。

## 给她发提醒

往 `127.0.0.1:47823` 发一行 UTF-8 JSON，发完就关：

```python
from deskpet.link import send
send({"title": "构建完成", "message": "主干 #123 通过", "seconds": 8})
```

不想依赖这个包也行，协议就是一行 JSON：

```python
import json, socket
with socket.create_connection(("127.0.0.1", 47823)) as s:
    s.sendall(json.dumps({"title": "下载完成"}, ensure_ascii=False).encode() + b"\n")
```

```powershell
$c = New-Object Net.Sockets.TcpClient("127.0.0.1", 47823)
$w = New-Object IO.StreamWriter($c.GetStream()); $w.WriteLine('{"title":"备份完成","seconds":5}'); $w.Close()
```

| 字段 | 说明 |
|---|---|
| `title` / `message` | 气泡上的字 |
| `seconds` | 几秒后气泡消失，`0` = 一直留着等你点（默认 30） |
| `sound` | `true` = 响一声 |
| `url` | 详情卡片上给一个「打开链接」按钮 |
| 其他字段 | 原样保留，点开时交给扩展处理 |

控制命令：`{"_cmd": "play"}` 让她发游玩邀请；`{"_cmd": "event", "name": "..."}` 记一个好感事件。
命令行测试：`python pet.py --say "你好"`、`python pet.py --play`。只连不发 = 探她在不在。

## 扩展

把你的程序真正"接"进来：写一个 `.py` 放进 `deskpet/extensions/`，或者放到任意目录、
用 `--ext-dir 目录` / `config.json` 的 `extension_dirs` 加载。可以：

- `poll(pet, now)` 每 3 秒看看外面的状态，`pet.set_sign(...)` / `pet.clear_sign(...)` 让她举牌 / 放下
- `on_message(pet, msg)` 收到提醒时接管（比如变成举牌）
- `on_open(pet, msg)` 点开提醒时用你自己的窗口打开
- `menu_items(pet)` 往右键菜单加泡泡（可以带子菜单、用皮肤里的图标）
- `setup(pet)` 里注册自己的好感事件、加台词

完整约定见 [`deskpet/extensions/__init__.py`](deskpet/extensions/__init__.py)，
示例见 [`deskpet/extensions/water.py`](deskpet/extensions/water.py)（喝水提醒，默认关着）。

**玩法**也是插件：在 `deskpet/play/` 加一个文件，约定见 [`deskpet/play/__init__.py`](deskpet/play/__init__.py)，
[`chase.py`](deskpet/play/chase.py) 是模板。

## 换皮肤

`config.json` 的 `skin` 指向一个目录，里面放 `<表情>_<序号>.png`（idle_1.png、walk_1.png……）
和菜单图标 `menu_<名字>.png`。缺的表情会退回 idle，整个目录没图就用程序画的像素团子。
用 `tools/slice_sheet.py` 可以把一整张精灵表切成这些小图，见 [`skins/whale/README.md`](skins/whale/README.md)。

## 授权

- 代码：[MIT](LICENSE)
- `skins/whale/` 里的鲸鱼娘图片：**CC BY-NC-SA 4.0**（署名、非商业、相同方式共享），
  DeepSeek 社区同人形象，与 DeepSeek 官方无关。署名和来源见 [`skins/whale/README.md`](skins/whale/README.md)。

---

<a id="english"></a>

# desktop-pet (English)

A little desktop pet that sits in the bottom-right corner of your Windows desktop. She **pops up
notifications for your programs**, **holds up a sign until you deal with something**, idles around
with little animations, wanders, occasionally invites you to play, and has affection / mood / energy.
Ships with a "whale girl" skin (DeepSeek community fan art).

Pure Python standard library (tkinter) — **no pip install needed**.

## Features

- **Notifications** — any program sends one line of JSON to a local port and she shows a speech bubble.
  Click her for details; right-click → Messages to browse the last 15.
- **Signs** — extensions can make her hold up a red "!" sign or a QR-code sign until you handle it.
- **Idle life** — blinking, stretching, yawning, waving, dancing…; she wanders near her home spot
  (walk, stroll with hands behind her back, hop, roll).
- **Play** — after a long idle stretch she may invite you to play *chase the cursor* or *hide-and-seek*
  (she peeks in from a screen edge — click her before she ducks back); or start a game from the menu.
  Games are plugins.
- **Affection / mood / energy** — petting, feeding and playing raise affection and unlock more lines.
  Positive only: no penalties, no daily chores.
- **Chat** (off by default) — right-click → Chat to talk to her, either through your local Claude Code
  or straight to an API set in the config (Anthropic or OpenAI-compatible format, e.g. DeepSeek).
  Chat only — no file access. See the top of [`deskpet/extensions/chat.py`](deskpet/extensions/chat.py).
- **Bubble menu** — multi-level, auto-paginated, pixel-art icons.
- **Cloud speech bubbles** — blue cloud shape with white text, sized to the text, with a little tail pointing at her.
- **Rest hours** — she sleeps outside working hours and on weekends (configurable).

## Quick start

Windows + Python 3.8+ (with tkinter).

```
git clone https://github.com/rtw67/whale_deskpet.git
cd whale_deskpet
pythonw pet.py          # or double-click pet.bat
```

Drag her to move (that spot becomes her home). Click = handle the current item / pet her. Long-press = status card.
Right-click for the menu. Copy `config.example.json` to `config.json` to configure; runtime data lives in `data/`.

## Sending notifications

Send one line of UTF-8 JSON to `127.0.0.1:47823`, then close the connection:

```python
from deskpet.link import send
send({"title": "Build finished", "message": "main #123 passed", "seconds": 8})
```

Fields: `title`, `message`, `seconds` (0 = stay until clicked, default 30), `sound`, `url`;
extra fields are passed to extensions when the message is opened.
Commands: `{"_cmd": "play"}`, `{"_cmd": "event", "name": "..."}`.
CLI: `python pet.py --say "hello"`, `python pet.py --play`. Connecting without sending = liveness probe.

## Extensions

Drop a `.py` into `deskpet/extensions/`, or load a directory with `--ext-dir DIR` / `extension_dirs`
in `config.json`. Hooks (all optional): `setup`, `poll` (every 3 s; use `pet.set_sign` / `pet.clear_sign`),
`on_message`, `on_open`, `on_event`, `menu_items`. See
[`deskpet/extensions/__init__.py`](deskpet/extensions/__init__.py) and the example
[`water.py`](deskpet/extensions/water.py). Games live in `deskpet/play/` — see
[`deskpet/play/__init__.py`](deskpet/play/__init__.py).

## Skins

Point `skin` in `config.json` at a directory of `<expression>_<n>.png` frames and `menu_<name>.png` icons.
`tools/slice_sheet.py` slices a whole sprite sheet into frames (stdlib only). See
[`skins/whale/README.md`](skins/whale/README.md).

## License

- Code: [MIT](LICENSE)
- Whale-girl artwork in `skins/whale/`: **CC BY-NC-SA 4.0**. Fan art of a DeepSeek community character;
  not affiliated with or endorsed by DeepSeek. Credits in [`skins/whale/README.md`](skins/whale/README.md).
