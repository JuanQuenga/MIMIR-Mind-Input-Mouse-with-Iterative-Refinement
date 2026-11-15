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
#   text_boxes  = rectangles (same numbers as in the returned list) that are
#                 text fields, so the overlay can offer "Type here"
last_info = {"text_boxes": set()}


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
            if _takes_text(auto, ctrl):
                last_info["text_boxes"].add(rect)


def _takes_text(auto, ctrl) -> bool:
    """Is this something you type into? Plain text fields always are. Search
    boxes on web pages and address bars are often reported as "combo boxes",
    so those count when Windows says their value can be changed."""
    try:
        kind = ctrl.ControlTypeName
        if kind == "EditControl":
            return True
        if kind in ("ComboBoxControl", "DocumentControl", "GroupControl", "CustomControl"):
            pattern = ctrl.GetPattern(auto.PatternId.ValuePattern)
            return bool(pattern) and not pattern.IsReadOnly
    except Exception:
        pass
    return False


def focused_takes_text() -> bool:
    """After a click: did the typing cursor land in something you type into?
    Works however the spot was found (Windows list or pixel grid)."""
    try:
        import uiautomation as auto
        ctrl = auto.GetFocusedControl()
        return ctrl is not None and ctrl.ProcessId != os.getpid() and _takes_text(auto, ctrl)
    except Exception as exc:
        print(f"[elements] could not check the typing cursor: {exc!r}", flush=True)
        return False


def focused_text():
    """What the field with the typing cursor holds: (text, selected part).
    Either is None when Windows will not say."""
    try:
        import uiautomation as auto
        ctrl = auto.GetFocusedControl()
        if ctrl is None or ctrl.ProcessId == os.getpid():
            return None, None
        value = selected = None
        try:
            pattern = ctrl.GetPattern(auto.PatternId.ValuePattern)
            if pattern:
                value = pattern.Value
        except Exception:
            pass
        try:
            pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
            if pattern:
                selected = "".join(r.GetText(-1) for r in pattern.GetSelection())
        except Exception:
            pass
        return value, selected
    except Exception as exc:
        print(f"[elements] could not read the text field: {exc!r}", flush=True)
        return None, None


def completion_added(before, typed, now, selected) -> bool:
    """Did the field add its own guess after what was typed? Address bars do:
    type "you" and it becomes "youtube.com" with the added part highlighted,
    and Enter would then go there instead of using what was typed.
    before/now: the field's text before and after typing."""
    if not typed:
        return False
    if selected:                                   # nothing we type leaves a highlight
        return bool(now) and now.endswith(selected)
    if not now or len(now) <= len(typed) or not now.lower().startswith(typed.lower()):
        return False
    extra = now[len(typed):]                       # text that was already after the cursor?
    return not (before or "").endswith(extra)


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
    last_info.update(text_boxes=set())
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
                for r in found:
                    if hit_test:
                        try:                                   # hidden behind another window?
                            if _window_at(r[0] + r[2] / 2, r[1] + r[3] / 2) != hwnd:
                                continue
                        except Exception as exc:
                            print(f"[elements] cannot test what is hidden: {exc!r}", flush=True)
                            hit_test = False
                    rects.append(r)
            except Exception as exc:
                print(f"[elements] skipped a window: {exc!r}", flush=True)
    except Exception as exc:               # not on Windows, package missing, COM error...
        print(f"[elements] falling back to pixel grid: {exc!r}", flush=True)
        return []
    return list(dict.fromkeys(rects))      # drop exact duplicates, keep order
