"""
icon_finder.py - the "icon selection" from the team's other build (BCI-Project,
bci_selection.py), fitted into MIMIR as a second way of finding what can be
clicked.  Start the overlay with  --finder icons  to use it.

What it does differently from bci/elements.py:
  * asks Windows for every clickable thing in one cached query per window
    (fast), and decides what is hidden from the stacking order of the windows;
  * windows that tell Windows little about themselves (games, custom-drawn
    programs) also get a LOCAL vision pass on a screenshot: compact
    high-contrast shapes (icons, buttons) and, if the optional "winsdk"
    package is installed, words read by Windows' own text recognition.
    Nothing is sent anywhere.

The scanner below (constants, Target, vision pass, UIScanner) is their code,
unchanged except that it no longer needs PyQt6.  Their labels are kept in the
data but MIMIR never draws them: the boxes stay free of text.
The part at the bottom makes it answer like bci/elements.py.
"""
from __future__ import annotations

import ctypes
import math
import os
import re
import sys
import time
from ctypes import wintypes
from dataclasses import dataclass

IS_WIN = sys.platform == "win32"
user32 = ctypes.WinDLL("user32") if IS_WIN else None

CLICK_PX = 40          # a spatial cell this small (physical px) is clicked instead of zoomed

VIS_TEXT, VIS_ICON = -1, -2   # pseudo control types of elements found by the vision pass
CTRL_NAMES = {50000: "Button", 50002: "CheckBox", 50003: "ComboBox", 50004: "Edit", 50005: "Hyperlink",
              50007: "ListItem", 50011: "MenuItem", 50013: "RadioButton", 50019: "TabItem",
              50031: "SplitButton", 50020: "Text", 50006: "Image", 50024: "TreeItem", 50015: "Slider",
              50029: "DataItem", 50035: "HeaderItem", 50018: "Tab", VIS_TEXT: "Text", VIS_ICON: "Icon"}
CTRL_PRIOR = {50000: 1.0, 50031: 1.0, 50004: 1.1, 50011: 1.0, 50019: 0.9, 50003: 0.8, 50005: 0.8,
              50002: 0.7, 50013: 0.7, 50007: 0.6, 50024: 0.6, 50015: 0.6, 50029: 0.5, 50035: 0.4,
              VIS_TEXT: 0.6, VIS_ICON: 0.55}
VISION_MIN_UIA = 25    # --vision auto: a window exposing fewer accessible controls than this is also read visually
VISION_MAX = 300       # visual elements kept per window
VISION_WINDOWS = 3     # windows read visually per scan (each costs a text-recognition pass)
ORIGIN_PRIOR = {"menu": 2.5, "popup": 2.5, "fg": 1.5, "win": 0.8, "tray": 1.0, "desktop": 0.8,
                "tray_launch": 1.0, "desktop_launch": 0.9}
DESKTOP_CLASSES = ("Progman", "WorkerW")
SHELL_FOLDERS = {"recycle bin": "shell:RecycleBinFolder", "this pc": "shell:MyComputerFolder",
                 "network": "shell:NetworkPlacesFolder", "control panel": "shell:ControlPanelFolder"}
WS_POPUP, WS_CAPTION = 0x80000000, 0x00C00000
TOOLTIP_CLASSES = ("tooltips_class32", "SysShadow", "Xaml_WindowedPopupClass_Shadow")
MENU_NEAR_PX = 400     # a new popup window this close to the last click is treated as its menu

CLICK_LABELS = {"left": "LEFT CLICK", "double": "DOUBLE CLICK", "middle": "MIDDLE CLICK",
                "right": "RIGHT CLICK", "undo": "\u21a9 BACK"}
# Binary click-type stage, laid out left-to-right in CLICK_ORDER so every split is spatial:
#   0 -> {left, double}   1 -> {{middle, back}, right}
CLICK_LAYOUT = (("left", "double"), (("middle", "undo"), "right"))
CLICK_ORDER = ("left", "double", "middle", "undo", "right")
CLICK_PRIOR = {"left": 0.45, "double": 0.15, "middle": 0.07, "right": 0.25, "undo": 0.08}
# skip the click-type stage for these and use this click: menu items, launcher tiles
DIRECT_ORIGINS = {"menu": "left", "tray_launch": "left", "desktop_launch": "double"}
LAUNCH_ORIGINS = ("tray_launch", "desktop_launch")
KEYWORDS = ("ok", "send", "save", "open", "search", "next", "submit", "play", "yes", "continue",
            "accept", "start", "new", "reply", "post", "go", "enter", "done")
ACTION_PRIOR = {"apps": 0.9, "back": 0.6, "scroll_down": 0.8, "scroll_up": 0.5, "pause": 0.25, "mode": 0.12,
                "exit": 0.03}


@dataclass(eq=False)
class Target:
    label: str
    x: float                 # centre, physical pixels
    y: float
    w: float = 40.0
    h: float = 30.0
    kind: str = "ui"         # ui | zone | cell | action | undo | click
    action: str = ""
    ctrl: int = 0
    origin: str = ""
    hwnd: int = 0
    box: tuple | None = None
    prior: float = 1.0
    p: float = 0.0
    click_at: tuple | None = None   # real screen point when the target is drawn somewhere else (launcher tile)
    launch: str = ""                # file / shell: path that opens this item without clicking it

    @property
    def key(self):
        return f"{self.label.lower()}|{self.ctrl}"

    @property
    def visual(self):
        return self.ctrl in (VIS_TEXT, VIS_ICON)


_TASKBAR_NOISE = re.compile(r"\s*-\s*\d+ running windows?|\s+pinned$", re.IGNORECASE)


def clean_label(name):
    """'Google Chrome - 1 running window pinned' -> 'Google Chrome'."""
    return _TASKBAR_NOISE.sub("", " ".join((name or "").split())).strip()


def desktop_shortcuts():
    """Icon name (lower case, with and without extension) -> file on the user's / public desktop."""
    home = os.path.expanduser("~")
    dirs = [os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop"),
            os.path.join(os.environ.get("PUBLIC", r"C:\Users\Public"), "Desktop")]
    out = {}
    for d in dirs:
        try:
            names = os.listdir(d)
        except OSError:
            continue
        for n in names:
            if n.lower() == "desktop.ini":
                continue
            path = os.path.join(d, n)
            out.setdefault(n.lower(), path)
            out.setdefault(os.path.splitext(n)[0].lower(), path)
    return out


# ----------------------------------------------------------------------------------------------
# Vision pass: finds clickable things in apps that expose little or nothing to UIAutomation
# (custom-drawn UIs like MusicBee, games, canvases) by looking at the pixels.
# ----------------------------------------------------------------------------------------------
try:
    import numpy as np
    from scipy import ndimage
except ImportError:
    np = ndimage = None

VIS_EDGE = 22          # grey-level step that counts as an edge
VIS_MIN_W, VIS_MIN_H = 14, 10
VIS_MAX_W, VIS_MAX_H = 640, 150


class ScreenGrabber:
    """GDI copy of the screen as an (h, w, 4) BGRA array.  The overlay excludes its own windows
    from capture (SetWindowDisplayAffinity), so this sees the apps underneath it."""

    def __init__(self):
        g, u = ctypes.WinDLL("gdi32"), ctypes.WinDLL("user32")   # private handles: own 64-bit prototypes
        vp, i = ctypes.c_void_p, ctypes.c_int
        for f, res, args in ((u.GetDC, vp, [vp]), (u.ReleaseDC, i, [vp, vp]), (g.CreateCompatibleDC, vp, [vp]),
                             (g.CreateCompatibleBitmap, vp, [vp, i, i]), (g.SelectObject, vp, [vp, vp]),
                             (g.BitBlt, i, [vp, i, i, i, i, vp, i, i, ctypes.c_uint]),
                             (g.GetDIBits, i, [vp, vp, ctypes.c_uint, ctypes.c_uint, vp, vp, ctypes.c_uint]),
                             (g.DeleteObject, i, [vp]), (g.DeleteDC, i, [vp])):
            f.restype, f.argtypes = res, args
        self.g, self.u = g, u

    def grab(self, w, h):
        g, u = self.g, self.u
        hdc = u.GetDC(None)
        mdc = g.CreateCompatibleDC(hdc)
        bmp = g.CreateCompatibleBitmap(hdc, w, h)
        old = g.SelectObject(mdc, bmp)
        try:
            g.BitBlt(mdc, 0, 0, w, h, hdc, 0, 0, 0x00CC0020 | 0x40000000)    # SRCCOPY | CAPTUREBLT
            info = (ctypes.c_int32 * 11)(40, w, -h, 1 | (32 << 16))           # top-down 32-bit BI_RGB
            img = np.empty((h, w, 4), np.uint8)
            rows = g.GetDIBits(mdc, bmp, 0, h, img.ctypes.data, info, 0)
        finally:
            g.SelectObject(mdc, old)
            g.DeleteObject(bmp)
            g.DeleteDC(mdc)
            u.ReleaseDC(None, hdc)
        return img if rows == h else None


def find_visual_elements(img, scale=2):
    """(l, t, r, b, strength) of compact, high-contrast blobs (buttons, icons, words) in ``img`` pixels.
    Long straight lines (panel borders, separators, grid lines) are removed first so they don't fuse
    neighbouring controls, and blobs sitting in busy texture (photos, game scenery) are dropped."""
    a = img[::scale, ::scale, :3].astype(np.float32)
    grey = a[..., 0] * 0.114 + a[..., 1] * 0.587 + a[..., 2] * 0.299
    grad = np.zeros_like(grey)
    grad[:, 1:] = np.abs(np.diff(grey, axis=1))
    grad[1:, :] = np.maximum(grad[1:, :], np.abs(np.diff(grey, axis=0)))
    edge = grad > VIS_EDGE
    run = max(20, 100 // scale)
    ef = edge.astype(np.float32)
    for axis in (0, 1):   # binary opening with a 1 x run line, in O(N) whatever the run length
        line = ndimage.uniform_filter1d(ef, run, axis=axis) > 0.999
        edge &= ~ndimage.maximum_filter1d(line, run, axis=axis)
    mask = ndimage.binary_dilation(ndimage.binary_closing(edge, np.ones((3, 5), bool)), np.ones((3, 3), bool))
    lab, _ = ndimage.label(mask)
    sat = np.pad(edge.astype(np.int32).cumsum(0).cumsum(1), ((1, 0), (1, 0)))
    H, W = edge.shape

    def count(t, l, b, r):
        t, l, b, r = max(0, t), max(0, l), min(H, b), min(W, r)
        return int(sat[b, r] - sat[t, r] - sat[b, l] + sat[t, l]), max(1, (b - t) * (r - l))

    out = []
    for sl in ndimage.find_objects(lab):
        t, b, l, r = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        w, h = (r - l) * scale, (b - t) * scale
        if not (VIS_MIN_W <= w <= VIS_MAX_W and VIS_MIN_H <= h <= VIS_MAX_H):
            continue
        n_in, a_in = count(t, l, b, r)
        if n_in / a_in < 0.04:
            continue
        m = max(3, (b - t) // 2)
        n_all, a_all = count(t - m, l - m, b + m, r + m)
        if (n_all - n_in) / max(1, a_all - a_in) > 0.12:
            continue   # textured surroundings: part of a picture, not a control
        out.append((l * scale, t * scale, r * scale, b * scale, n_in / a_in * float(grad[sl].mean())))
    return out


def inside(pt, box):
    return box[0] <= pt[0] < box[2] and box[1] <= pt[1] < box[3]


class TextReader:
    """Windows' built-in OCR (Windows.Media.Ocr through the optional ``winsdk`` package)."""

    def __init__(self):
        self.engine = None
        try:
            from winsdk.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.security.cryptography import CryptographicBuffer
            self.engine = OcrEngine.try_create_from_user_profile_languages()
            self._bitmap = lambda data, w, h: SoftwareBitmap.create_copy_from_buffer(
                CryptographicBuffer.create_from_byte_array(data), BitmapPixelFormat.BGRA8, w, h)
        except Exception:
            self.engine = None

    def phrases(self, img):
        """(text, l, t, r, b) per run of words on a line; a gap wider than one line height splits a run
        (so toolbar labels and table columns become separate targets)."""
        import asyncio
        h, w = img.shape[:2]
        bmp = self._bitmap(np.ascontiguousarray(img).tobytes(), w, h)

        async def recognise():
            return await self.engine.recognize_async(bmp)

        out = []
        for line in asyncio.run(recognise()).lines:
            run = []
            for word in line.words:
                r = word.bounding_rect
                box = (r.x, r.y, r.x + r.width, r.y + r.height)
                if run and box[0] - run[-1][1][2] > max(r.height, run[-1][1][3] - run[-1][1][1]):
                    out.append(self._join(run))
                    run = []
                run.append((word.text, box))
            if run:
                out.append(self._join(run))
        return out

    @staticmethod
    def _join(run):
        return (" ".join(t for t, _ in run), min(b[0] for _, b in run), min(b[1] for _, b in run),
                max(b[2] for _, b in run), max(b[3] for _, b in run))


# ----------------------------------------------------------------------------------------------
# UI Automation scanner
# ----------------------------------------------------------------------------------------------
class UIScanner:
    MAX_PER_WINDOW = 150
    MAX_TOTAL = 360

    def __init__(self, screen_w, screen_h):
        self.sw, self.sh = screen_w, screen_h
        self.uia = None
        self.error = ""
        self.grabber = self.reader = None
        self.vision_ms = 0.0
        if IS_WIN:
            self._init_uia()
            if np is not None:
                self.grabber = ScreenGrabber()
                self.reader = TextReader()

    def _init_uia(self):
        try:
            import comtypes
            import comtypes.client
            try:
                comtypes.CoInitializeEx(comtypes.COINIT_APARTMENTTHREADED)
            except OSError:
                pass
            from comtypes.automation import VARIANT
            comtypes.client.GetModule("UIAutomationCore.dll")
            from comtypes.gen.UIAutomationClient import IUIAutomation
            self.uia = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}", interface=IUIAutomation)
            types = [50000, 50002, 50003, 50004, 50005, 50007, 50011, 50013, 50019, 50031, 50024, 50015,
                     50029, 50035]
            conds = [self.uia.CreatePropertyCondition(30003, VARIANT(t)) for t in types]
            # anything that says it can be invoked / toggled / selected / expanded, whatever its type
            conds += [self.uia.CreatePropertyCondition(p, VARIANT(True)) for p in (30031, 30041, 30036, 30028)]
            cond = conds[0]
            for c in conds[1:]:
                cond = self.uia.CreateOrCondition(cond, c)
            self.cond = cond
            req = self.uia.CreateCacheRequest()
            for prop in (30001, 30005, 30003, 30022, 30010):   # rect, name, type, offscreen, enabled
                req.AddProperty(prop)
            self.cache_req = req
        except Exception as e:
            self.error = f"UIAutomation unavailable ({e}); spatial zones only"
            self.uia = None

    @staticmethod
    def _cloaked(hwnd):
        try:
            val = ctypes.c_int(0)
            ctypes.windll.dwmapi.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(val), 4)
            return val.value != 0
        except Exception:
            return False

    def _zorder(self, exclude):
        """Visible top-level windows, top of the z-order first."""
        wins = []
        cls_buf = ctypes.create_unicode_buffer(256)

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def cb(hwnd, _):
            if hwnd in exclude or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                return True
            ex = user32.GetWindowLongW(hwnd, -20)
            if ex & 0x20:            # WS_EX_TRANSPARENT: click-through overlays never occlude
                return True
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            if r.right - r.left < 8 or r.bottom - r.top < 8 or r.right <= 0 or r.bottom <= 0:
                return True
            # layered + no-activate = HUD overlay (NVIDIA, Lenovo taskbar strip, other BCI overlays): it never
            # hides what is under it; small ones are kept only because some apps draw their menus this way
            hud = bool(ex & 0x80000 and ex & 0x08000000)
            if hud and (r.right - r.left) * (r.bottom - r.top) > 0.5 * self.sw * self.sh:
                return True
            if r.left >= self.sw or r.top >= self.sh or self._cloaked(hwnd):
                return True
            user32.GetClassNameW(hwnd, cls_buf, 256)
            wins.append({"hwnd": hwnd, "rect": (r.left, r.top, r.right, r.bottom), "cls": cls_buf.value, "hud": hud,
                         "title": user32.GetWindowTextLengthW(hwnd) > 0, "owner": user32.GetWindow(hwnd, 4),
                         "style": user32.GetWindowLongW(hwnd, -16) & 0xFFFFFFFF})
            return True

        user32.EnumWindows(cb, 0)
        return wins

    @staticmethod
    def _is_new_popup(w, pre, near):
        """A caption-less popup window that appeared after our last click, next to the click point."""
        if pre is None or w["hwnd"] in pre or not w["style"] & WS_POPUP:
            return False
        if (w["style"] & WS_CAPTION) == WS_CAPTION or w["cls"] in TOOLTIP_CLASSES:
            return False
        if near is None:
            return True
        l, t, r, b = w["rect"]
        dx = max(l - near[0], 0, near[0] - r)
        dy = max(t - near[1], 0, near[1] - b)
        return math.hypot(dx, dy) < MENU_NEAR_PX

    def scan(self, exclude=(), zones=True, pre=None, menu_hwnds=(), near=None, vision="auto"):
        """``pre``: top-level windows that existed before the last click (None = not watching);
        ``menu_hwnds``: windows already known to be open menus;
        ``vision``: "auto" reads windows with few accessible controls visually, "on" every app window."""
        exclude = set(int(h) for h in exclude)
        menu_hwnds = set(menu_hwnds)
        targets: list[Target] = []
        centres = []
        self.vision_ms = 0.0
        if self.uia is not None and IS_WIN:
            wins = self._zorder(exclude)
            fg = user32.GetForegroundWindow()
            plan = []
            for z, w in enumerate(wins):
                if w["cls"] == "#32768" or w["hwnd"] in menu_hwnds or self._is_new_popup(w, pre, near):
                    plan.append((z, "menu"))
                elif w["hud"]:
                    continue
                elif w["hwnd"] == fg:
                    plan.append((z, "fg"))
                elif fg and w["owner"] == fg:
                    plan.append((z, "popup"))
                elif w["cls"] in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
                    plan.append((z, "tray"))
                elif w["cls"] == "Progman":
                    plan.append((z, "desktop"))
            others = [z for z, w in enumerate(wins) if w["title"] and not w["hud"] and z not in [p[0] for p in plan]
                      and (w["rect"][2] - w["rect"][0]) > 150 and (w["rect"][3] - w["rect"][1]) > 100
                      and w["cls"] not in DESKTOP_CLASSES]
            plan += [(z, "win") for z in others[:4]]
            plan.sort(key=lambda p: p[1] == "desktop")   # desktop last: it is only what shows through
            look = []
            for z, origin in plan:
                above = [wins[i]["rect"] for i in range(z)
                         if wins[i]["cls"] not in DESKTOP_CLASSES and not wins[i]["hud"]]
                n = self._scan_window(wins[z]["hwnd"], origin, above, targets, centres)
                if (origin in ("fg", "popup", "menu", "win") and (vision == "on" or n < VISION_MIN_UIA)
                        and self._visible_fraction(wins[z]["rect"], above) > 0.15):
                    look.append((z, origin, above))
                if len(targets) >= self.MAX_TOTAL:
                    break
            if vision != "off" and look and self.grabber is not None:
                t0 = time.perf_counter()
                img = self.grabber.grab(self.sw, self.sh)
                if img is not None:
                    for z, origin, above in look[:VISION_WINDOWS]:
                        self._vision_window(img, wins[z], origin, above, targets, centres)
                self.vision_ms = (time.perf_counter() - t0) * 1000
        if zones:
            cols, rows = 6, 4
            for r in range(rows):
                for c in range(cols):
                    gx = self.sw * (c + 0.5) / cols
                    gy = self.sh * 0.06 + self.sh * 0.9 * (r + 0.5) / rows
                    if not any(math.hypot(gx - sx, gy - sy) < 95 for sx, sy in centres):
                        targets.append(Target(f"Zone {chr(65 + c)}{r + 1}", gx, gy, 84, 40, kind="zone"))
        return targets

    def _elements(self, hwnd):
        """(name, control type, left, top, right, bottom) of enabled, on-screen interactable elements."""
        try:
            arr = self.uia.ElementFromHandle(hwnd).FindAllBuildCache(4, self.cond, self.cache_req)
        except Exception:
            return
        if not arr:
            return
        for i in range(arr.Length):
            try:
                el = arr.GetElement(i)
                if el.CachedIsOffscreen or not el.CachedIsEnabled:
                    continue
                r = el.CachedBoundingRectangle
                l, t, rr, b = r.left, r.top, r.right, r.bottom
                name, ctrl = el.CachedName, el.CachedControlType
            except Exception:
                continue
            w, h = rr - l, b - t
            if w < 8 or h < 8 or (w > self.sw * 0.85 and h > self.sh * 0.85):
                continue
            if not (0 <= l + w / 2 < self.sw and 0 <= t + h / 2 < self.sh):
                continue
            yield clean_label(name), ctrl, l, t, rr, b

    def _scan_window(self, hwnd, origin, above, targets, centres):
        added = 0
        for name, ctrl, l, t, rr, b in self._elements(hwnd):
            if added >= self.MAX_PER_WINDOW:
                break
            w, h = rr - l, b - t
            cx, cy = l + w / 2, t + h / 2
            if any(a[0] <= cx < a[2] and a[1] <= cy < a[3] for a in above):
                continue   # hidden behind a window that is higher in the z-order
            if any(abs(cx - sx) < 16 and abs(cy - sy) < 16 for sx, sy in centres):
                continue
            label = name or CTRL_NAMES.get(ctrl, "Target")
            if len(label) > 24:
                label = label[:22] + ".."
            centres.append((cx, cy))
            targets.append(Target(label, cx, cy, w, h, kind="ui", ctrl=ctrl, origin=origin, hwnd=hwnd))
            added += 1
        return added

    def _visible_fraction(self, rect, above, n=12):
        l, t, r, b = max(0, rect[0]), max(0, rect[1]), min(self.sw, rect[2]), min(self.sh, rect[3])
        if r <= l or b <= t:
            return 0.0
        pts = [(l + (r - l) * (i + 0.5) / n, t + (b - t) * (j + 0.5) / n) for i in range(n) for j in range(n)]
        return sum(not any(inside(p, a) for a in above) for p in pts) / len(pts)

    def _vision_window(self, img, win, origin, above, targets, centres):
        """Text phrases (OCR) and icon-like blobs in the visible part of ``win`` that UIAutomation missed."""
        l, t, r, b = win["rect"]
        l, t, r, b = max(0, l), max(0, t), min(self.sw, r), min(self.sh, b)
        if r - l < 40 or b - t < 30:
            return
        crop = img[t:b, l:r]
        hwnd = win["hwnd"]
        known = [(k.x - k.w / 2, k.y - k.h / 2, k.x + k.w / 2, k.y + k.h / 2) for k in targets
                 if k.hwnd == hwnd and k.w * k.h < 0.25 * self.sw * self.sh]
        phrases = []
        if self.reader is not None and self.reader.engine is not None:
            try:
                # tiny lower-case scraps ("te", "rl") are misreads of text on coloured backgrounds; dropping
                # them lets the blob detector mark that spot instead.  Short words like "OK" / "Go" / "X" stay.
                phrases = [(txt, pl + l, pt + t, pr + l, pb + t) for txt, pl, pt, pr, pb in self.reader.phrases(crop)
                           if any(ch.isalnum() for ch in txt) and not (len(txt.strip()) <= 2 and txt.islower())]
            except Exception as e:
                self.error = f"text recognition failed: {e}"
        try:
            blobs = find_visual_elements(crop) if ndimage is not None else []
        except Exception as e:
            blobs, self.error = [], f"vision pass failed: {e}"
        icons = []
        pb = np.array([p[1:] for p in phrases], float).reshape(-1, 4)
        pcx, pcy = (pb[:, 0] + pb[:, 2]) / 2, (pb[:, 1] + pb[:, 3]) / 2
        for bl, bt, br, bb, _ in sorted(blobs, key=lambda x: -x[4]):
            box = (bl + l, bt + t, br + l, bb + t)
            area = (box[2] - box[0]) * (box[3] - box[1])
            ov = (np.clip(np.minimum(pb[:, 2], box[2]) - np.maximum(pb[:, 0], box[0]), 0, None)
                  * np.clip(np.minimum(pb[:, 3], box[3]) - np.maximum(pb[:, 1], box[1]), 0, None))
            if ((ov > 0.3 * area) | ((pcx >= box[0]) & (pcx < box[2]) & (pcy >= box[1]) & (pcy < box[3]))).any():
                continue   # the recognised text already covers it
            icons.append(("", VIS_ICON, box))
        # icons first (strongest first, at most a third of the budget) so text-heavy lists can't crowd out
        # unlabelled buttons like play / pause; then the text in reading order
        items = icons[:VISION_MAX // 3] + [(txt, VIS_TEXT, box) for txt, *box in phrases]
        added = 0
        for txt, ctrl, (bl, bt, br, bb) in items:
            if added >= VISION_MAX:
                break
            cx, cy = (bl + br) / 2, (bt + bb) / 2
            if any(inside((cx, cy), a) for a in above) or any(inside((cx, cy), k) for k in known):
                continue
            if any(abs(cx - sx) < 14 and abs(cy - sy) < 14 for sx, sy in centres):
                continue
            label = clean_label(txt) or "Icon"
            if len(label) > 24:
                label = label[:22] + ".."
            centres.append((cx, cy))
            targets.append(Target(label, cx, cy, br - bl, bb - bt, kind="ui", ctrl=ctrl, origin=origin, hwnd=hwnd))
            added += 1

    def _launch_items(self, wins):
        """Every taskbar button and desktop icon, whether or not it is covered, for the APPS launcher.
        Desktop icons carry the shortcut path so they can be opened while hidden behind windows."""
        out = []
        for w in wins:
            if w["cls"] == "Shell_TrayWnd":
                for name, ctrl, l, t, r, b in self._elements(w["hwnd"]):
                    if ctrl == 50000 and name:
                        out.append(Target(name, (l + r) / 2, (t + b) / 2, r - l, b - t, kind="launch",
                                          ctrl=ctrl, origin="tray_launch", hwnd=w["hwnd"]))
        desk = user32.FindWindowW("Progman", None)
        if desk:
            paths = desktop_shortcuts()
            for name, ctrl, l, t, r, b in self._elements(desk):
                path = paths.get(name.lower()) or SHELL_FOLDERS.get(name.lower(), "")
                if ctrl == 50007 and name:
                    out.append(Target(name, (l + r) / 2, (t + b) / 2, r - l, b - t, kind="launch", ctrl=ctrl,
                                      origin="desktop_launch", hwnd=desk, launch=path))
        return out


# ----------------------------------------------------------------------------------------------
# MIMIR side: the same answers bci/elements.py gives
# ----------------------------------------------------------------------------------------------
EDIT = 50004
last_info = {"text_boxes": set()}
vision = "auto"          # "auto": only windows Windows knows little about, "on": every window, "off"
_scanner = None


def _rect(t):
    return (float(t.x - t.w / 2), float(t.y - t.h / 2), float(t.w), float(t.h))


def to_rects(targets):
    """Targets -> (rectangles, text-box rectangles).  While a pop-up menu is open
    its items are the only choices, as in bci/elements.py."""
    targets = [t for t in targets if t.kind == "ui"]
    menu = [t for t in targets if t.origin == "menu"]
    if len(menu) >= 2:
        targets = menu
    return (list(dict.fromkeys(_rect(t) for t in targets)),
            {_rect(t) for t in targets if t.ctrl == EDIT})


def clickable_elements():
    """Clickable rectangles (x, y, w, h in physical pixels) of everything visible."""
    global _scanner
    last_info.update(text_boxes=set())
    if not IS_WIN:
        print("[icon_finder] needs Windows, falling back to pixel grid", flush=True)
        return []
    try:
        if _scanner is None:
            _scanner = UIScanner(user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))
            reads = _scanner.reader is not None and _scanner.reader.engine is not None
            print("[icon_finder] ready; vision pass: "
                  + ("off (numpy/scipy missing)" if _scanner.grabber is None else
                     "shapes + text" if reads else "shapes only (pip install winsdk adds text)"), flush=True)
        _scanner.error = ""
        targets = _scanner.scan(zones=False, vision=vision)
        if _scanner.error:
            print(f"[icon_finder] {_scanner.error}", flush=True)
        rects, text_boxes = to_rects(targets)
        last_info.update(text_boxes=text_boxes)
        if _scanner.vision_ms:
            print(f"[icon_finder] {len(rects)} things, vision pass {_scanner.vision_ms:.0f} ms", flush=True)
        return rects
    except Exception as exc:
        print(f"[icon_finder] falling back to pixel grid: {exc!r}", flush=True)
        return []
