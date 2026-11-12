# -*- coding: utf-8 -*-
"""免打扰：手动开（右键「免打扰」），或者有程序全屏时自动开（看视频、投屏、打游戏）。

免打扰的时候她：不冒气泡、不溜达、不邀请你玩、不自言自语、提醒不响；
新来的提醒先攒着，结束后再一条条冒出来。全屏时整个人藏起来，退出全屏再出来。
"""

import ctypes
import os
from ctypes import wintypes

# 桌面、任务栏：它们「盖满屏幕」不算全屏
SHELL_CLASSES = ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd")
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


def _user32():
    """自己的一份 user32（设了 64 位句柄的返回类型），不去改全局 windll.user32 的函数原型。"""
    u = ctypes.WinDLL("user32")
    u.GetForegroundWindow.restype = wintypes.HWND
    u.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    u.MonitorFromWindow.restype = wintypes.HMONITOR
    u.MonitorFromPoint.argtypes = (wintypes.POINT, wintypes.DWORD)
    u.MonitorFromPoint.restype = wintypes.HMONITOR
    u.GetMonitorInfoW.argtypes = (wintypes.HMONITOR, ctypes.POINTER(MONITORINFO))
    u.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
    u.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    u.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    return u


try:
    _u = _user32()
except Exception:                                                  # noqa: BLE001  非 Windows
    _u = None


def fullscreen_at(x, y):
    """前台窗口是不是全屏盖住了 (x, y) 所在的那块屏幕。桌面、任务栏、她自己的窗口不算。

    最大化的普通窗口不算（它让开了任务栏，盖不满整块屏幕）。拿不到信息就当不是。
    """
    if _u is None:
        return False
    try:
        hwnd = _u.GetForegroundWindow()
        if not hwnd:
            return False
        pid = wintypes.DWORD()
        _u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return False
        buf = ctypes.create_unicode_buffer(64)
        _u.GetClassNameW(hwnd, buf, 64)
        if buf.value in SHELL_CLASSES:
            return False
        mon = _u.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        # 别的屏幕在全屏，她这块屏幕不用躲
        if mon != _u.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST):
            return False
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(mi)
        if not _u.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
        r = wintypes.RECT()
        _u.GetWindowRect(hwnd, ctypes.byref(r))
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    except Exception:                                              # noqa: BLE001
        return False
