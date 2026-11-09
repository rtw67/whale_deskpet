# -*- coding: utf-8 -*-
"""路径、日志、JSON 读写。

ROOT 是项目根目录；运行时产生的东西（位置、好感存档、日志）都在 data/ 里，不进 git。
"""

import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                                  # noqa: BLE001
    pass


def data_path(name):
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, name)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def save_json(path, data):
    """先写临时文件再替换，避免中途崩溃留下半个文件。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def make_logger(filename):
    """带时间戳打到控制台，同时追加到 data/<filename>。pythonw 没有控制台也不会崩。"""
    path = data_path(filename)

    def log(msg):
        line = "[%s] %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
        if sys.stdout is not None:
            try:
                print(line, flush=True)
            except Exception:                                      # noqa: BLE001
                pass
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass

    return log


log = make_logger("pet.log")
