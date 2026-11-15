"""Find the clickable things in every visible window (Windows).

Uses Windows UI Automation through the `uiautomation` package
(pip install uiautomation). Returns rectangles in PHYSICAL screen pixels.

NOT TESTED by the author on a real Windows machine: the function names were
checked against the package source, but try it on a few apps before relying
on it. If anything goes wrong it returns [] and the overlay falls back to the
pixel grid.
"""
from __future__ import annotations

import os
import time

CLICKABLE = {
    "ButtonControl", "HyperlinkControl", "MenuItemControl", "TabItemControl",
    "ListItemControl", "CheckBoxControl", "RadioButtonControl", "ComboBoxControl",
    "EditControl", "TreeItemControl", "SplitButtonControl",
}


# Facts about the most recent scan, for the overlay:
#   front_rect  = (x, y, w, h) of the window the user is working in, or None
#   front_inner = how many clickable things Windows reported INSIDE that window,
#                 not counting its title bar. A game or a picture-only program
#                 reports (almost) none.
#   text_boxes  = rectangles (same numbers as in the returned list) that are
#                 text fields, so the overlay can offer "Type here"
last_info = {"front_rect": None, "front_inner": 0, "text_boxes": set()}
TITLE_BAR = 50          # pixels at the top of a window treated as its title bar


def _collect(auto, root, rects, t_end, max_items, max_depth):
    for ctrl, _depth in auto.WalkControl(root, includeTop=False, maxDepth=max_depth):
        if time.time() > t_end or len(rects) >= max_items:
            break
        if ctrl.ControlTypeName not in CLICKABLE:
            continue
        if ctrl.IsOffscreen or not ctrl.IsEnabled:
            continue
        r = ctrl.BoundingRectangle
        if r.width() >= 6 and r.height() >= 6:
            rect = (float(r.left), float(r.top), float(r.width()), float(r.height()))
            rects.append(rect)
            if ctrl.ControlTypeName == "EditControl":
                last_info["text_boxes"].add(rect)


def _window_at(x, y):
    """Handle of the top-level window that is actually visible at a screen
    point (the same test Windows uses to decide where a click goes)."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32")
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    return int(user32.GetAncestor(hwnd, 2) or 0)          # 2 = GA_ROOT


def clickable_elements(max_items=220, max_depth=14, budget_s=3.0):
    """Clickable rectangles of EVERYTHING visible: every open window, the
    desktop icons and the taskbar. Things hidden behind another window are
    left out, so each box you see can really be clicked."""
    rects = []
    last_info.update(front_rect=None, front_inner=0, text_boxes=set())
    try:
        import uiautomation as auto
        tops = auto.GetRootControl().GetChildren()
        # An open pop-up menu (for example after a right click) is its own
        # little window. While one is open, its items are the only choices.
        try:
            for top in tops:
                if top.ClassName == "#32768" or top.ControlTypeName == "MenuControl":
                    _collect(auto, top, rects, time.time() + 0.5, max_items, 6)
            if len(rects) >= 2:
                return list(dict.fromkeys(rects))
            rects = []
        except Exception as exc:
            print(f"[elements] menu check skipped: {exc!r}", flush=True)

        front = 0
        try:
            front = auto.GetForegroundControl().NativeWindowHandle
        except Exception:
            pass
        tops.sort(key=lambda t: t.NativeWindowHandle != front)   # front window first
        t_end, hit_test = time.time() + budget_s, True
        for top in tops:
            if time.time() > t_end or len(rects) >= max_items:
                break
            try:
                if top.ProcessId == os.getpid():
                    continue
                box = top.BoundingRectangle
                if box.width() < 8 or box.height() < 8 or box.right <= 0 or box.bottom <= 0:
                    continue                                   # minimised or off screen
                hwnd = top.NativeWindowHandle
                found = []
                per_window = min(t_end, time.time() + (1.5 if hwnd == front else 0.7))
                _collect(auto, top, found, per_window, max_items - len(rects), max_depth)
                kept_before = len(rects)
                for r in found:
                    if hit_test:
                        try:                                   # hidden behind another window?
                            if _window_at(r[0] + r[2] / 2, r[1] + r[3] / 2) != hwnd:
                                continue
                        except Exception as exc:
                            print(f"[elements] cannot test what is hidden: {exc!r}", flush=True)
                            hit_test = False
                    rects.append(r)
                if hwnd == front and front:
                    inner = [r for r in rects[kept_before:]
                             if r[1] + r[3] / 2 > box.top + TITLE_BAR]
                    last_info.update(front_rect=(float(box.left), float(box.top),
                                                 float(box.width()), float(box.height())),
                                     front_inner=len(inner))
            except Exception as exc:
                print(f"[elements] skipped a window: {exc!r}", flush=True)
    except Exception as exc:               # not on Windows, package missing, COM error...
        print(f"[elements] falling back to pixel grid: {exc!r}", flush=True)
        return []
    return list(dict.fromkeys(rects))      # drop exact duplicates, keep order
