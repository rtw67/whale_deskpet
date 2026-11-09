#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""桌宠入口。

    pythonw pet.py                      启动（已经有一只在跑就什么都不做）
    pythonw pet.py --ext-dir D:/my_ext   额外加载一个扩展目录（可以写多次）
    python pet.py --say "构建完成"      给正在跑的她发一条提醒（测试用）
    python pet.py --play [chase]        让正在跑的她发一个游玩邀请
"""

import argparse
import sys

from deskpet import config
from deskpet.link import alive, send


def main():
    ap = argparse.ArgumentParser(description="桌宠")
    ap.add_argument("--ext-dir", action="append", default=[], help="额外的扩展目录")
    ap.add_argument("--say", metavar="TEXT", help="给正在跑的她发一条提醒")
    ap.add_argument("--play", nargs="?", const="", metavar="GAME", help="让她发游玩邀请")
    args = ap.parse_args()

    port = int(config.load()["port"])
    if args.say is not None or args.play is not None:
        if not alive(port):
            print("桌宠没在跑")
            return 1
        if args.say is not None:
            send({"title": args.say, "message": "", "seconds": 8}, port)
        else:
            send({"_cmd": "play", "game": args.play or None}, port)
        return 0

    from deskpet.app import main as run
    return run(args.ext_dir)


if __name__ == "__main__":
    sys.exit(main())
