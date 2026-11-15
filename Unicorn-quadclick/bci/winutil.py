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
    (0x54, "TYPE", "T"),
    (0x44, "SNAP", "D"),
    (0x4F, "SCREENSHOT", "O"),
    (0x43, "STYLE", "C"),
    (0xDB, "SOFTER", "["), (0xDD, "STRONGER", "]"),
    (0x51, "QUIT", "Q"),
]
# Optional direct-key triggers for 1-4 (top row + numpad) without Ctrl+Alt.
BARE_HOTKEYS = [
    (0x31, "KEY 1", "1"), (0x32, "KEY 2", "2"), (0x33, "KEY 3", "3"), (0x34, "KEY 4", "4"),
    (0x61, "KEY 1", "Num1"), (0x62, "KEY 2", "Num2"), (0x63, "KEY 3", "Num3"), (0x64, "KEY 4", "Num4"),
]
# Always-available bare shortcut while unpaused (all modes).
QUICK_HOTKEYS = [
    (0x4F, "SCREENSHOT", "O"),
]
ALL_BARE_HOTKEYS = BARE_HOTKEYS + QUICK_HOTKEYS
WM_SET_BARE = 0x042A
BARE_ID_BASE = 101
_hotkey_tid = None
_bare_enabled = False


def start_hotkeys(on_command, bare_keys: bool = False, start_active: bool = False):
    """Register Ctrl+Alt+<key> for every entry in HOTKEYS, and optionally allow
    toggling bare 1-4 hotkeys (without Ctrl+Alt) via set_bare_keys().

    on_command(cmd) is called from a background thread, so it must only do
    something thread-safe (the overlay puts the command on a queue).
    Returns the names of keys that could not be registered (already taken by
    another program), or None when hotkeys are not available at all.
    """
    global _hotkey_tid, _bare_enabled
    if not IS_WINDOWS:
        return None
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.RegisterHotKey.restype = wintypes.BOOL
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.UnregisterHotKey.restype = wintypes.BOOL
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                    wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                   wintypes.UINT, wintypes.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT, WM_HOTKEY = 0x0001, 0x0002, 0x4000, 0x0312
    failed, ready = [], threading.Event()
    _hotkey_tid = None
    _bare_enabled = bool(bare_keys)

    def loop():
        global _hotkey_tid
        _hotkey_tid = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # Ensure this thread's message queue exists before PostThreadMessageW can run.
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        bare_registered = set()

        def _set_bare(active: bool):
            bad = []
            items = ALL_BARE_HOTKEYS if bare_keys else QUICK_HOTKEYS
            base = BARE_ID_BASE if bare_keys else BARE_ID_BASE + len(BARE_HOTKEYS)
            for idx, (vk, _cmd, name) in enumerate(items):
                hk_id = base + idx
                if active and hk_id not in bare_registered:
                    if user32.RegisterHotKey(None, hk_id, MOD_NOREPEAT, vk):
                        bare_registered.add(hk_id)
                    elif bare_keys and vk in (0x31, 0x32, 0x33, 0x34):
                        bad.append(name)
                elif not active and hk_id in bare_registered:
                    user32.UnregisterHotKey(None, hk_id)
                    bare_registered.discard(hk_id)
            return bad

        # Hotkeys belong to the thread that registers them, so register here.
        for i, (vk, _cmd, name) in enumerate(HOTKEYS):
            if not user32.RegisterHotKey(None, i + 1, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, vk):
                failed.append(name)
        failed.extend(n for n in _set_bare(True) if n not in failed)
        if not start_active:
            _set_bare(False)
        ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                if 1 <= msg.wParam <= len(HOTKEYS):
                    on_command(HOTKEYS[msg.wParam - 1][1])
                elif BARE_ID_BASE <= msg.wParam < BARE_ID_BASE + len(ALL_BARE_HOTKEYS):
                    on_command(ALL_BARE_HOTKEYS[msg.wParam - BARE_ID_BASE][1])
            elif msg.message == WM_SET_BARE:
                _set_bare(bool(msg.wParam))

    threading.Thread(target=loop, daemon=True, name="quadclick-hotkeys").start()
    ready.wait(2.0)
    return failed


def set_bare_keys(active: bool):
    """Enable or release bare hotkeys (O, plus 1-4 when enabled) on the running hotkey thread."""
    if not IS_WINDOWS or not _hotkey_tid:
        return False
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostThreadMessageW.restype = wintypes.BOOL
    return bool(user32.PostThreadMessageW(_hotkey_tid, WM_SET_BARE, 1 if active else 0, 0))


def wait_for_modifiers(timeout=2.0):
    """Wait until Ctrl, Alt and Shift are let go. Otherwise a click or typed
    letter that follows a Ctrl+Alt hotkey would arrive as Ctrl+Alt+something."""
    if not IS_WINDOWS:
        return
    import ctypes
    user32 = ctypes.WinDLL("user32")
    t_end = time.time() + timeout
    while time.time() < t_end:
        if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x10, 0x11, 0x12)):
            return
        time.sleep(0.03)


def _press(vk=0, scan=0, flags=0):
    """One key going down and up again, sent to whatever has the keyboard."""
    import ctypes
    from ctypes import wintypes
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):      # only here so INPUT has its real size
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _U(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    pair = (INPUT * 2)(INPUT(type=1, u=_U(ki=KEYBDINPUT(vk, scan, flags, 0, 0))),
                       INPUT(type=1, u=_U(ki=KEYBDINPUT(vk, scan, flags | 0x0002, 0, 0))))
    user32.SendInput(2, pair, ctypes.sizeof(INPUT))


def press_key(name: str):
    """Press one named key: "enter" or "delete"."""
    if not IS_WINDOWS:
        import pyautogui
        pyautogui.press(name)
        return
    wait_for_modifiers()
    if name == "delete":
        _press(vk=0x2E, flags=0x0001)             # extended key: the real Delete, not numpad
    else:
        _press(vk={"enter": 0x0D}[name])


def type_text(text: str, enter: bool = False):
    """Type text into whatever program has the keyboard focus."""
    if not IS_WINDOWS:
        import pyautogui
        pyautogui.write(text)
        if enter:
            pyautogui.press("enter")
        return
    wait_for_modifiers()
    for ch in text:
        if ch == "\n":
            _press(vk=0x0D)
        else:
            raw = ch.encode("utf-16-le")          # one or two 16-bit units
            for i in range(0, len(raw), 2):
                _press(scan=int.from_bytes(raw[i:i + 2], "little"), flags=0x0004)
        time.sleep(0.012)
    if enter:
        time.sleep(0.05)
        _press(vk=0x0D)


def click(x: int, y: int, kind: str = "left"):
    """Click at screen position (x, y) in physical pixels.
    kind: "left", "double" or "right"."""
    if IS_WINDOWS:
        import ctypes
        wait_for_modifiers(1.5)
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


def scroll(notches: int):
    """Turn the mouse wheel `notches` steps (positive = up) over the middle of
    the window in front, so the scroll goes to that window and not to
    whatever the mouse happened to be over."""
    if not IS_WINDOWS:
        import pyautogui
        pyautogui.scroll(notches)
        return
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.mouse_event.argtypes = [wintypes.DWORD] * 4 + [ctypes.c_size_t]   # a downward turn is negative
    sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    x, y = sw // 2, sh // 2                         # no usable window: middle of the screen
    hwnd = user32.GetForegroundWindow()
    r = wintypes.RECT()
    if hwnd and user32.GetWindowRect(hwnd, ctypes.byref(r)):
        l, t = max(r.left, 0), max(r.top, 0)        # the part that is on the screen
        rr, b = min(r.right, sw), min(r.bottom, sh)
        if rr - l > 100 and b - t > 100:
            x, y = (l + rr) // 2, (t + b) // 2
    wait_for_modifiers(1.5)
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)
    user32.mouse_event(0x0800, 0, 0, int(120 * notches) & 0xFFFFFFFF, 0)


def foreground_window():
    """An id for the window the user is working in, or None if unknown."""
    if not IS_WINDOWS:
        return None
    import ctypes
    return int(ctypes.WinDLL("user32").GetForegroundWindow() or 0)
