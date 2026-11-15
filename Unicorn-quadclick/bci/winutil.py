"""The Windows-only bits: global hotkeys, the real mouse click, and which
window is in front. Everything here uses plain ctypes (no extra packages).

On other systems the hotkeys are simply unavailable and the click falls back
to pyautogui.

NOT TESTED by the author on a real Windows machine.
"""
from __future__ import annotations

import sys
import threading
import time

IS_WINDOWS = sys.platform == "win32"

# (virtual-key code, command for the overlay, name shown to the user)
# All of them are pressed together with Ctrl+Alt.
HOTKEYS = [
    (0x31, "KEY 1", "1"), (0x32, "KEY 2", "2"), (0x33, "KEY 3", "3"), (0x34, "KEY 4", "4"),
    (0x08, "UNDO", "Backspace"), (0x24, "HOME", "Home"),
    (0x50, "PAUSE", "P"), (0x4D, "MODE", "M"), (0x42, "CHOICES", "B"),
    (0xDB, "SOFTER", "["), (0xDD, "STRONGER", "]"),
    (0x51, "QUIT", "Q"),
]


def start_hotkeys(on_command):
    """Register Ctrl+Alt+<key> for every entry in HOTKEYS.

    on_command(cmd) is called from a background thread, so it must only do
    something thread-safe (the overlay puts the command on a queue).
    Returns the names of keys that could not be registered (already taken by
    another program), or None when hotkeys are not available at all.
    """
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY = 0x0001, 0x0002, 0x4000, 0x0312
    failed, ready = [], threading.Event()

    def loop():
        # Hotkeys belong to the thread that registers them, so register here.
        for i, (vk, _cmd, name) in enumerate(HOTKEYS):
            if not user32.RegisterHotKey(None, i + 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                failed.append(name)
        ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY and 1 <= msg.wParam <= len(HOTKEYS):
                on_command(HOTKEYS[msg.wParam - 1][1])

    threading.Thread(target=loop, daemon=True, name="quadclick-hotkeys").start()
    ready.wait(2.0)
    return failed


def click(x: int, y: int, kind: str = "left"):
    """Click at screen position (x, y) in physical pixels.
    kind: "left", "double" or "right"."""
    if IS_WINDOWS:
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        down, up = (0x0008, 0x0010) if kind == "right" else (0x0002, 0x0004)
        user32.SetCursorPos(int(x), int(y))
        time.sleep(0.03)
        for i in range(2 if kind == "double" else 1):
            if i:
                time.sleep(0.08)
            user32.mouse_event(down, 0, 0, 0, 0)
            time.sleep(0.03)
            user32.mouse_event(up, 0, 0, 0, 0)
    else:
        import pyautogui
        if kind == "double":
            pyautogui.doubleClick(int(x), int(y))
        else:
            pyautogui.click(int(x), int(y), button="right" if kind == "right" else "left")


def foreground_window():
    """An id for the window the user is working in, or None if unknown."""
    if not IS_WINDOWS:
        return None
    import ctypes
    return int(ctypes.WinDLL("user32").GetForegroundWindow() or 0)
