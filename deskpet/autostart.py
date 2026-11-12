# -*- coding: utf-8 -*-
"""开机自启：在 Windows 的「启动」文件夹里放一个 DeskPet.vbs（不弹黑框地跑 pythonw pet.py）。

开的时候用的是「现在这只」的启动方式：同一个 Python、同样的 --ext-dir，
这样开机拉起来的她和现在这只一模一样（别的程序也会拉起她时，谁先谁后都一样）。
"""

import os
import sys

from deskpet.util import ROOT

STARTUP = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu",
                       "Programs", "Startup")
PATH = os.path.join(STARTUP, "DeskPet.vbs")


def enabled():
    return os.path.exists(PATH)


def _pythonw():
    exe = sys.executable
    d, name = os.path.split(exe)
    if name.lower() == "python.exe" and os.path.exists(os.path.join(d, "pythonw.exe")):
        return os.path.join(d, "pythonw.exe")
    return exe


def enable(ext_dirs=()):
    args = [_pythonw(), os.path.join(ROOT, "pet.py")]
    for d in ext_dirs:
        args += ["--ext-dir", d]
    cmd = " ".join('"%s"' % a for a in args)

    def vbs(s):                                    # VBS 字符串：两头加引号，里面的引号写两遍
        return '"%s"' % s.replace('"', '""')

    text = ('Set sh = CreateObject("WScript.Shell")\n'
            "sh.CurrentDirectory = %s\n"
            "sh.Run %s, 0, False\n" % (vbs(ROOT), vbs(cmd)))
    os.makedirs(STARTUP, exist_ok=True)
    with open(PATH, "w", encoding="utf-16") as fh:   # 带 BOM 的 UTF-16：路径里有中文也不乱
        fh.write(text)


def disable():
    if os.path.exists(PATH):
        os.remove(PATH)
