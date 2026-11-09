# -*- coding: utf-8 -*-
"""别的程序怎么给她发消息：往 127.0.0.1:<port> 发一条 JSON，发完就关。

    from deskpet.link import send, alive
    send({"title": "构建完成", "message": "主干 #123 通过", "seconds": 8})

不想依赖这个包的话，协议很简单，自己写也就几行（见 README）：
    连上端口 → 写一行 UTF-8 JSON → 关闭连接。只连不写 = 探一下她在不在。

消息字段：
    title / message      气泡上的字
    seconds              几秒后气泡自动消失；0 = 一直留着等你点（默认 30）
    sound                true = 响一声
    其他字段原样保留，点开提醒时交给扩展处理（见 extensions/__init__.py 的 on_open）

控制命令（不是提醒，不进「最近消息」）：
    {"_cmd": "play", "game": "chase"}      让她发一个游玩邀请
    {"_cmd": "event", "name": "..."}       记一个好感事件（扩展注册的事件名也行）
"""

import json
import queue
import socket
import threading

DEFAULT_PORT = 47823
MAX_BYTES = 1024 * 1024


def alive(port=DEFAULT_PORT):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1.0):
            return True
    except OSError:
        return False


def send(payload, port=DEFAULT_PORT):
    """发一条消息。她没开就返回 False（调用方自己决定要不要退回别的提醒方式）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2.0) as s:
            s.sendall(data)
        return True
    except OSError:
        return False


class Server:
    """桌宠这边：占住端口（单实例锁），后台线程收消息放进队列，界面线程用 drain() 取。

    连接必须马上收：Windows 上等待队列满了，新连接不是被拒绝而是卡到超时，
    别人探活就会误判她不在。所以开后台线程专门 accept，不靠界面的定时器。
    """

    def __init__(self, port=DEFAULT_PORT):
        self.port = port
        self.q = queue.Queue()
        self.sock = None

    def start(self):
        """占不到端口（已经有一只在了）返回 False。"""
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", self.port))
            s.listen(64)
        except OSError:
            s.close()
            return False
        self.sock = s
        threading.Thread(target=self._serve, daemon=True, name="pet-port").start()
        return True

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._read, args=(conn,), daemon=True).start()

    def _read(self, conn):
        buf = b""
        try:
            conn.settimeout(3)
            while len(buf) < MAX_BYTES:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
        except OSError:
            pass
        finally:
            conn.close()
        for line in buf.decode("utf-8", "replace").splitlines():
            line = line.strip()
            if not line:
                continue                 # 只连不写：探活
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if isinstance(msg, dict):
                self.q.put(msg)

    def drain(self):
        out = []
        while True:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                return out
