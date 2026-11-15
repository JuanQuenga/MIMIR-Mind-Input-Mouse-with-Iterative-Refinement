"""The on-screen part: flickering boxes that narrow down to one click.

    python overlay.py --demo --keys-only   # practice screen with fake buttons
    python overlay.py --keys-only          # REAL desktop, driven by hotkeys
    python overlay.py                      # REAL desktop, driven by the decoder too

How one click goes:
  1. The screen is cut into boxes. Boxes with nothing clickable in them are
     left out. Pick the box that holds what you want; repeat.
  2. When only a few candidates are left, the view is ENLARGED.
  3. At the last step every remaining candidate gets its own box.
  4. The view zooms back out and asks: Left click / Double click / Right
     click / Cancel.

On the real desktop it is a see-through layer over everything. It starts
PAUSED: nothing flickers and nothing can be clicked until you press
Ctrl+Alt+P. Hotkeys (hold Ctrl+Alt, Windows only):
    1 2 3 4 = pick the box with that number     Backspace = undo
    Home = start over       P = pause / resume  Q = quit
    B = two choices <-> four choices            M = real buttons <-> pixel grid
    [ ] = softer / stronger flicker
In --demo the same keys work without Ctrl+Alt (Esc = start over).

Decoder commands arrive on UDP port 5005 (see bci/engine.py); the layout is
announced on port 5006.

WARNING: this flickers at 9-15 Hz. Flicker in this range can trigger seizures
in people with photosensitive epilepsy. Do not use it with or near anyone who
has that condition.
"""
from __future__ import annotations

import argparse
import math
import queue
import random
import sys
import time
from collections import namedtuple

from PySide6.QtCore import QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from bci import config, splitter, winutil
from bci.net import Link

VERSION = "v6"      # shown on screen, so you can tell which copy is running
FADE_S = 0.6        # s for the flicker to fade in after each change
MAX_ZOOM = 6.0      # never enlarge real buttons more than this
FINAL_BOX = 150.0   # the last step's boxes are at least this big (pixels)

ACTIONS = [("left", "Left click"), ("double", "Double click"),
           ("right", "Right click"), ("cancel", "Cancel")]
# Which flicker speeds to use when fewer than four boxes are shown at the last
# step: keep them as far apart as possible.
SPREAD = {1: (0,), 2: (0, 3), 3: (0, 2, 3), 4: (0, 1, 2, 3)}

# One flickering box.  idx = which flicker speed, rect = where it is drawn,
# key = number to press, label = text inside (menu only), what = what picking
# it does: ("area", rect, elements) | ("element", el) | ("group", names) |
# ("action", name)
Box = namedtuple("Box", "idx rect key label what")


class Overlay(QWidget):
    def __init__(self, args):
        super().__init__()
        self.args = args
        self.demo = args.demo
        self.real = not args.demo
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        if self.real:             # float above everything and let clicks fall through
            flags |= (Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput
                      | Qt.WindowType.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowFlags(flags)
        if not self.demo:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        screen = QApplication.primaryScreen()
        geo = screen.geometry()
        self.dpr = screen.devicePixelRatio()
        if args.size:
            w, h = (int(v) for v in args.size.lower().split("x"))
            self.setGeometry(geo.x(), geo.y(), w, h)
        else:
            self.setGeometry(geo)
        self.root = (0.0, 0.0, float(self.width()), float(self.height()))

        # --keys-only: don't listen for decoder commands at all, so a decoder or
        # replay left running in another window can't drive this screen.
        self.link = Link(send_port=config.STATE_PORT,
                         listen_port=None if args.keys_only else config.CMD_PORT)
        self.k = args.choices             # 4 or 2 boxes per step
        self.use_elements = not args.pixel
        self.last_alive = 0.0
        self.scores = [0.0] * 4
        self.calib = None                 # seconds left, or None
        self.flash = None                 # (rect, until) green confirmation box
        self.hits = self.misses = 0
        self.click_started = time.perf_counter()
        self.last_click_s = None
        self.buttons, self.target = [], None
        self.paused = self.real           # the real desktop starts paused
        self.paused_at = None             # None = the very first pause: keep the help up
        self.contrast = max(0.2, min(1.0, args.contrast))
        self.layout_t = time.perf_counter()
        self.busy = False                 # a real click is in progress
        self.note = None                  # (text, until): short on-screen message
        self.n_found = 0                  # real buttons found by the last scan
        self.front = None                 # window that was in front at the last scan
        self.front_checked = 0.0
        self.frames, self.fps_t = 0, time.perf_counter()
        self.local = queue.SimpleQueue()  # commands from the global hotkeys
        self.hotkeys_ok = False
        self.shot = None                  # picture of the screen, for enlarging
        self.menu = None                  # dict(pt, rect, group) while choosing the click type
        self.zoom = None                  # (source rect, scale, where it is drawn)
        self.zoom_img = None
        self.boxes = []
        self.stack = [(self.root, None)]
        if self.demo:
            self.make_demo_buttons(args.buttons)
        else:
            failed = winutil.start_hotkeys(self.local.put)
            self.hotkeys_ok = failed is not None
            if failed:
                print("These hotkeys are taken by another program: Ctrl+Alt+"
                      + ", Ctrl+Alt+".join(failed), flush=True)
            if failed is None:
                print("Global hotkeys only work on Windows. Use send_cmd.py here.", flush=True)
        self.start_over()

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self.tick)
        self.timer.start(8)

    # ---- what can be clicked ----------------------------------------------
    def make_demo_buttons(self, n):
        rnd = random.Random(self.args.seed)
        cols = math.ceil(math.sqrt(n * self.width() / self.height()))
        rows = math.ceil(n / cols)
        cw, ch = self.width() / cols, (self.height() - 80) / rows
        cells = [(c, r) for r in range(rows) for c in range(cols)]
        rnd.shuffle(cells)
        self.buttons = []
        for c, r in sorted(cells[:n]):
            bw, bh = min(140, cw * 0.6), min(44, ch * 0.5)
            x = c * cw + rnd.uniform(4, cw - bw - 4)
            y = 60 + r * ch + rnd.uniform(4, ch - bh - 4)
            self.buttons.append((x, y, bw, bh))
        self.rnd = rnd
        self.target = rnd.choice(self.buttons)

    def scan(self):
        """Take a picture of the screen and list what can be clicked.
        Returns the list of element rectangles, or None for the pixel grid."""
        if self.demo:
            self.shot = QPixmap(self.size())
            p = QPainter(self.shot)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            self.draw_demo(p)
            p.end()
            return list(self.buttons) if self.use_elements else None
        if self.paused:
            return None
        was_visible = self.isVisible()
        if was_visible:                               # keep ourselves out of the picture
            self.hide()
            QApplication.processEvents()
            time.sleep(0.15)
        try:
            shot = self.grab_screen()
            self.shot = None if shot is None or shot.isNull() else shot
        except Exception as exc:
            print(f"screen picture failed: {exc!r}", flush=True)
            self.shot = None
        els = None
        if self.use_elements:
            from bci.elements import clickable_elements
            self.front = winutil.foreground_window()
            els = [(x / self.dpr, y / self.dpr, w / self.dpr, h / self.dpr)
                   for x, y, w, h in clickable_elements()]
            els = [e for e in els if splitter.contains(self.root, splitter.centre(e))]
            self.n_found = len(els)
            if len(els) < 2:
                self.say("No buttons found here, using the pixel grid")
                els = None
        if was_visible:
            self.show()
        return els

    def grab_screen(self):
        return QApplication.primaryScreen().grabWindow(0)

    def say(self, text, seconds=2.5):
        self.note = (text, time.perf_counter() + seconds)
        print(text, flush=True)

    # ---- building the current view -----------------------------------------
    def start_over(self):
        self.menu = None
        self.stack = [(self.root, self.scan())]
        self.layout_changed()

    def to_view(self, r):
        """Screen rectangle -> where it is drawn (differs only when enlarged)."""
        if not self.zoom:
            return tuple(r)
        (zx, zy, _, _), s, (dx, dy, _, _) = self.zoom
        return (dx + (r[0] - zx) * s, dy + (r[1] - zy) * s, r[2] * s, r[3] * s)

    def set_zoom(self, region, max_scale):
        """Enlarge `region` to fill the window (if that makes it bigger)."""
        W, H = self.width(), self.height()
        top = 52.0                                    # leave room for the message bar
        s = min((W - 16) / region[2], (H - top - 8) / region[3], max_scale)
        self.zoom, self.zoom_img = None, None
        if s < 1.15:
            return
        dw, dh = region[2] * s, region[3] * s
        dest = ((W - dw) / 2.0, top + (H - top - 8 - dh) / 2.0, dw, dh)
        self.zoom = (tuple(region), s, dest)
        if self.shot is not None:
            r = self.shot.width() / float(W)          # picture pixels per window pixel
            piece = self.shot.copy(QRect(int(region[0] * r), int(region[1] * r),
                                         max(1, int(region[2] * r)), max(1, int(region[3] * r))))
            img = piece.scaled(max(1, int(dw)), max(1, int(dh)),
                               Qt.AspectRatioMode.IgnoreAspectRatio,
                               Qt.TransformationMode.SmoothTransformation)
            img.setDevicePixelRatio(1.0)
            self.zoom_img = img

    def layout_changed(self):
        was_enlarged = self.zoom is not None
        self.zoom, self.zoom_img = None, None
        W, H = self.root[2], self.root[3]
        pair = config.BINARY_PAIR
        if self.menu:
            self.boxes = self.menu_boxes()
        else:
            area, els = self.stack[-1]
            n = len(els) if els else 0
            aspect = (W - 16) / (H - 60)
            if els and n <= self.k:
                # LAST STEP: enlarged, one box around each remaining element
                region = splitter.bounds(els, inside=self.root, aspect=aspect)
                self.set_zoom(region, MAX_ZOOM)
                idxs = SPREAD[n] if self.k == 4 else pair[:n]
                self.boxes = []
                for i, (cell, el) in enumerate(splitter.cells(region, els)):
                    self.boxes.append(Box(idxs[i], self.element_box(el, cell), i + 1, "",
                                          ("element", el)))
            else:
                if els and n <= self.k * self.k:
                    # ONE STEP BEFORE: enlarged, cut into boxes as usual
                    area = splitter.bounds(els, inside=self.root, aspect=aspect)
                    self.set_zoom(area, MAX_ZOOM)
                elif not els and area[2] * area[3] <= W * H / 16.0 + 1:
                    self.set_zoom(area, 40.0)         # pixel grid: enlarge small areas
                regs = splitter.split(area, els, mode=self.args.split, k=self.k, pair=pair)
                self.boxes = [Box(idx, self.to_view(rect),
                                  (idx + 1) if self.k == 4 else (i + 1), "",
                                  ("area", rect, sub))
                              for i, (idx, rect, sub) in enumerate(regs)]
        if was_enlarged or self.zoom or self.menu:   # the picture moved: an outline of
            self.flash = None                         # the old box would be misleading
        self.scores = [0.0] * 4
        self.layout_t = time.perf_counter()          # restart the fade-in
        self.announce()
        self.update()

    def element_box(self, el, cell):
        """Box around one element: padded, at least FINAL_BOX big, but never
        reaching into a neighbour's cell."""
        x, y, w, h = self.to_view(el)
        cx, cy = x + w / 2.0, y + h / 2.0
        w, h = max(w + 24, FINAL_BOX), max(h + 24, FINAL_BOX)
        bx, by, bw, bh = self.to_view(cell)
        x0, y0 = max(cx - w / 2.0, bx + 3), max(cy - h / 2.0, by + 3)
        x1, y1 = min(cx + w / 2.0, bx + bw - 3), min(cy + h / 2.0, by + bh - 3)
        return (x0, y0, max(8.0, x1 - x0), max(8.0, y1 - y0))

    def menu_boxes(self):
        pair = config.BINARY_PAIR
        if self.k == 4:
            return [Box(i, q, i + 1, label, ("action", name))
                    for i, (q, (name, label)) in enumerate(zip(splitter.quadrants(self.root), ACTIONS))]
        x, y, w, h = self.root
        halves = [(x, y, w / 2.0, h), (x + w / 2.0, y, w / 2.0, h)]
        if self.menu["group"] is None:                # two choices: first pick a pair
            groups = [ACTIONS[:2], ACTIONS[2:]]
            return [Box(pair[i], halves[i], i + 1, "  or  ".join(lbl for _, lbl in g),
                        ("group", [nm for nm, _ in g])) for i, g in enumerate(groups)]
        names = self.menu["group"]
        labels = dict(ACTIONS)
        return [Box(pair[i], halves[i], i + 1, labels[nm], ("action", nm))
                for i, nm in enumerate(names)]

    @property
    def regions(self):                                # (speed index, rect, what) per box
        return [(b.idx, b.rect, b.what) for b in self.boxes]

    def announce(self):
        parts = [f"LAYOUT {len(self.stack) - 1}"]
        for b in self.boxes:
            x, y, w, h = b.rect
            parts.append(f"{b.idx} {x:.0f} {y:.0f} {w:.0f} {h:.0f}")
        self.link.send(" ".join(parts))
        if self.target:                               # tell the simulated user where to look
            look = (-1.0, -1.0)
            if self.menu:                             # the box that leads to "Left click"
                for b in self.boxes:
                    if b.what == ("action", "left") or (b.what[0] == "group" and "left" in b.what[1]):
                        look = splitter.centre(b.rect)
            else:
                area, els = self.stack[-1]
                c = splitter.centre(self.target)
                if (self.target in els) if els else splitter.contains(area, c):
                    look = splitter.centre(self.to_view(self.target))
            self.link.send(f"TARGET {look[0]:.0f} {look[1]:.0f}")

    # ---- picking ---------------------------------------------------------------
    def select(self, index):
        """Pick the box that flickers at speed number `index` (decoder)."""
        self.choose(next((b for b in self.boxes if b.idx == index), None))

    def press(self, key):
        """Pick the box labelled `key` (keyboard / hotkeys)."""
        self.choose(next((b for b in self.boxes if b.key == key), None))

    def choose(self, box):
        if box is None or self.calib is not None or self.paused or self.busy:
            return
        self.flash = (box.rect, time.perf_counter() + 0.35)
        kind = box.what[0]
        if kind == "area":
            _, rect, els = box.what
            if els and len(els) == 1:                 # only one thing in there
                self.open_menu(els[0], splitter.centre(els[0]))
            elif not els and splitter.is_final(rect, None, self.args.min_size):
                self.open_menu(None, splitter.centre(rect))
            else:
                self.stack.append((rect, els))
                self.layout_changed()
        elif kind == "element":
            self.open_menu(box.what[1], splitter.centre(box.what[1]))
        elif kind == "group":
            self.menu["group"] = box.what[1]
            self.layout_changed()
        elif kind == "action":
            pt, name = self.menu["pt"], box.what[1]
            self.menu = None
            if name == "cancel":
                self.say("Cancelled", 1.5)
                self.link.send("CANCEL")
                self.start_over()
            else:
                self.click(pt, name)

    def open_menu(self, rect, pt):
        if self.args.no_menu:
            self.click(pt, "left")
            return
        self.menu = dict(pt=pt, rect=rect, group=None)
        self.layout_changed()

    def undo(self):
        if self.paused or self.busy:
            return
        if self.menu:
            if self.menu["group"] is not None:
                self.menu["group"] = None
            else:
                self.menu = None
            self.layout_changed()
        elif len(self.stack) > 1:
            self.stack.pop()
            self.layout_changed()

    def toggle_pause(self):
        self.paused = not self.paused
        self.paused_at = time.perf_counter()
        self.link.send("PAUSE" if self.paused else "RESUME")
        if not self.paused:
            self.click_started = time.perf_counter()
            self.start_over()                         # fresh scan, decoder starts fresh

    def click(self, pt, kind="left"):
        took = time.perf_counter() - self.click_started
        self.last_click_s, self.click_started = took, time.perf_counter()
        result = "-"
        if self.demo:
            ok = splitter.contains(self.target, pt)
            self.hits, self.misses = self.hits + ok, self.misses + (not ok)
            result = "hit" if ok else "miss"
            self.target = self.rnd.choice([b for b in self.buttons if b != self.target])
        self.link.send(f"CLICK {pt[0]:.0f} {pt[1]:.0f} {result} {took:.1f} {kind}")
        print(f"{kind} click at ({pt[0]:.0f}, {pt[1]:.0f}) {result} after {took:.1f} s", flush=True)
        if self.demo or self.args.dry_run:
            self.start_over()
            return
        self.busy = True                              # ignore picks until it is done
        self.hide()                                   # get out of the way first
        QTimer.singleShot(150, lambda: self.real_click(pt, kind))

    def real_click(self, pt, kind):
        try:
            winutil.click(int(pt[0] * self.dpr), int(pt[1] * self.dpr), kind)
        except Exception as exc:
            print(f"click failed: {exc!r}", flush=True)
        QTimer.singleShot(500, self.after_click)

    def after_click(self):
        self.busy = False
        self.start_over()                             # scans while still hidden
        self.show()

    def toggle_mode(self):
        self.use_elements = not self.use_elements
        self.start_over()
        if self.use_elements and self.n_found >= 2:
            self.say(f"Real buttons: {self.n_found} found")
        elif not self.use_elements:
            self.say("Pixel grid")

    def toggle_choices(self):
        self.k = 2 if self.k == 4 else 4
        self.menu = None
        self.stack = self.stack[:1]
        self.layout_changed()
        self.say("Two choices per step" if self.k == 2 else "Four choices per step")

    def change_contrast(self, step):
        self.contrast = max(0.2, min(1.0, round(self.contrast + step, 1)))
        self.say(f"Flicker strength {int(round(self.contrast * 100))}%", 1.5)

    # ---- input ---------------------------------------------------------------
    def on_command(self, msg):
        p = msg.split()
        if not p:
            return
        idle = not self.paused and not self.busy
        if p[0] == "SEL":
            self.select(int(p[1]))
        elif p[0] == "KEY":
            self.press(int(p[1]))
        elif p[0] in ("CLENCH_SHORT", "UNDO"):
            self.undo()
        elif p[0] == "HOME":
            if idle:
                self.start_over()
        elif p[0] == "PAUSE":
            if not self.busy:
                self.toggle_pause()
        elif p[0] == "MODE":
            if idle and self.calib is None:
                self.toggle_mode()
        elif p[0] == "CHOICES":
            if idle:
                self.toggle_choices()
        elif p[0] == "SOFTER":
            self.change_contrast(-0.1)
        elif p[0] == "STRONGER":
            self.change_contrast(+0.1)
        elif p[0] == "CLENCH_LONG" and not self.busy:  # on the full screen: pause
            if self.paused or (len(self.stack) == 1 and not self.menu):
                self.toggle_pause()
            else:                                     # deeper: back to full screen
                self.start_over()
        elif p[0] == "SCORE":
            self.scores = [float(v) for v in p[1:5]]
        elif p[0] == "CALIB":
            self.calib = int(p[1])
        elif p[0] == "READY":
            self.calib = None
            self.click_started = time.perf_counter()
            self.layout_changed()
        elif p[0] == "HELLO":
            self.announce()
        elif p[0] == "QUIT":
            self.close()

    def keyPressEvent(self, ev):                      # demo screen only
        k = ev.key()
        keys = {Qt.Key.Key_Backspace: "UNDO", Qt.Key.Key_Escape: "HOME",
                Qt.Key.Key_Home: "HOME", Qt.Key.Key_Q: "QUIT", Qt.Key.Key_P: "PAUSE",
                Qt.Key.Key_B: "CHOICES", Qt.Key.Key_M: "MODE",
                Qt.Key.Key_BracketLeft: "SOFTER", Qt.Key.Key_Minus: "SOFTER",
                Qt.Key.Key_BracketRight: "STRONGER", Qt.Key.Key_Equal: "STRONGER"}
        if Qt.Key.Key_1 <= k <= Qt.Key.Key_4:
            self.on_command(f"KEY {k - Qt.Key.Key_1 + 1}")
        elif k in keys:
            self.on_command(keys[k])

    def tick(self):
        while not self.local.empty():                 # global hotkeys
            self.on_command(self.local.get())
        for msg in self.link.poll():                  # decoder
            self.on_command(msg)
        now = time.perf_counter()
        # Real buttons: if the user switched to another window, scan it.
        if (self.real and self.use_elements and not self.paused and not self.busy
                and self.isVisible() and len(self.stack) == 1 and not self.menu
                and now - self.front_checked > 0.7):
            self.front_checked = now
            if winutil.foreground_window() != self.front:
                self.start_over()
        if now - self.fps_t > 5.0:                    # is the drawing keeping up?
            fps = self.frames / (now - self.fps_t)
            self.frames, self.fps_t = 0, now
            if self.real and not self.paused and self.calib is None and fps < 45:
                print(f"Drawing at only {fps:.0f} frames per second: the 12 and 15 Hz "
                      "boxes may not flicker cleanly. Close heavy programs or try --fill 0.",
                      flush=True)
        if now - self.last_alive > 1.0:               # lets the replay notice
            self.last_alive = now                     # when this window is gone
            self.link.send("ALIVE")
        self.update()

    def closeEvent(self, ev):
        self.link.send("BYE")
        super().closeEvent(ev)

    # ---- drawing ---------------------------------------------------------------
    def paintEvent(self, _):
        now = time.perf_counter()
        self.frames += 1
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        flickering = self.calib is None and not self.paused
        zoomed = flickering and self.zoom is not None
        if self.demo:
            if zoomed:
                p.fillRect(self.rect(), QColor(12, 12, 14))
            else:
                self.draw_demo(p)
        else:                                         # start from fully see-through
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(self.rect(), QColor(12, 12, 14, 242) if zoomed else QColor(0, 0, 0, 0))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if zoomed:                                    # the enlarged piece of the screen
            dest = QRectF(*self.zoom[2])
            if self.zoom_img is not None:
                p.drawPixmap(dest, self.zoom_img, QRectF(self.zoom_img.rect()))
            p.setPen(QPen(QColor(90, 90, 95), 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(dest)

        if flickering:
            if not zoomed:
                # dim everything that is not a choice right now
                rest = QPainterPath()
                rest.addRect(QRectF(self.rect()))
                shown = QPainterPath()
                for b in self.boxes:
                    shown.addRect(QRectF(*b.rect))
                p.fillPath(rest.subtracted(shown), QColor(0, 0, 0, 120))
                if self.real and not self.menu and self.stack[-1][1]:
                    p.setPen(QPen(QColor(0, 200, 255, 160), 1))   # outline the candidates
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    for e in self.stack[-1][1]:
                        p.drawRect(QRectF(*e))

            # fade in over FADE_S after every change: no sudden full flicker
            depth = self.contrast * min(1.0, (now - self.layout_t) / FADE_S)
            for b in self.boxes:
                x, y, w, h = b.rect
                lum = 0.5 + 0.5 * depth * math.sin(2 * math.pi * config.FREQS[b.idx] * now)
                g = int(255 * lum)
                t = max(5.0, min(24.0, 0.08 * min(w, h)))
                p.fillRect(QRectF(x, y, w, h), QColor(255, 255, 255, int(self.args.fill * lum)))
                p.setPen(QPen(QColor(g, g, g, 210), t))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(QRectF(x + t / 2, y + t / 2, w - t, h - t))
                frac = max(0.0, min(1.0, self.scores[b.idx] / config.SSVEP["thr_score"]))
                if frac > 0 and w > 4 * t:            # evidence bar
                    p.fillRect(QRectF(x + 1.5 * t, y + 1.5 * t, (w - 3 * t) * frac, 6),
                               QColor(40, 220, 120, 230))
                self.draw_tag(p, x + t + 4, y + t + 4, str(b.key))
                if b.label:
                    self.draw_label(p, QRectF(x, y, w, h), b.label)

            if self.menu:                             # show what is about to be clicked
                ring = self.menu["rect"] or (self.menu["pt"][0] - 16, self.menu["pt"][1] - 16, 32, 32)
                p.setPen(QPen(QColor(255, 200, 0), 4))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(QRectF(ring[0] - 6, ring[1] - 6, ring[2] + 12, ring[3] + 12), 8, 8)

        if self.flash and now < self.flash[1]:
            p.setPen(QPen(QColor(40, 220, 120), 6))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(*self.flash[0]))

        p.setFont(QFont("Segoe UI", 13))
        text = ""
        if self.calib is not None:
            text = f"Calibrating: relax your jaw and look at the dot ({self.calib} s)"
            p.setBrush(QColor(255, 60, 60))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QRectF(self.width() / 2 - 9, self.height() / 2 - 9, 18, 18))
        elif self.paused and self.real and self.tucked_away(now):
            text = ""                                 # out of the way: see the small tag below
        elif self.paused and self.real:
            text = "QuadClick is paused · hold a jaw clench or press Ctrl+Alt+P to start"
        elif self.paused:
            text = "Paused · press P (or hold a jaw clench) to carry on"
        elif self.note and now < self.note[1]:
            text = self.note[0]
        elif self.menu:
            text = "What should happen at the yellow mark?"
        elif self.demo:
            last = f" · last click {self.last_click_s:.1f} s" if self.last_click_s else ""
            text = f"Look at the green button · hits {self.hits} · misses {self.misses}{last}"
        elif zoomed:
            text = "Enlarged view"
        if text:
            box = QRectF(self.width() / 2 - 330, 8, 660, 34)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 200))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(255, 255, 255))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

        p.setFont(QFont("Segoe UI", 10))
        choices = "two choices" if self.k == 2 else "four choices"
        if self.demo:
            self.draw_hint(p, QRectF(8, self.height() - 30, 560, 22),
                           [f"{VERSION} · {choices} (B) · P pause · "
                            f"[ ] flicker {int(round(self.contrast * 100))}% · Backspace undo · Q quit"])
        elif self.paused and self.calib is None and self.tucked_away(now):
            # Paused for a while (watching a video, reading): leave the screen
            # clear except for a small reminder in the corner.
            self.draw_hint(p, QRectF(self.width() - 268, self.height() - 76, 260, 22),
                           ["Paused · hold a jaw clench to resume"])
        elif self.paused and self.calib is None:      # real desktop: how to drive it
            mode = "real buttons" if self.use_elements else "pixel grid"
            lines = [f"QuadClick {VERSION} · {mode} · {choices} · hold Ctrl+Alt and press:",
                     "1  2  3  4      pick the box with that number",
                     "Backspace      undo the last pick          Home      start over",
                     "B      two choices / four choices          M      real buttons / pixel grid",
                     "[  ]      softer / stronger flicker",
                     "P      pause or resume                             Q      quit"]
            if not self.hotkeys_ok:
                lines.append("Hotkeys are not available on this system: use send_cmd.py")
            self.draw_hint(p, QRectF(self.width() / 2 - 330, 50, 660, 20 * len(lines) + 12), lines)
        p.end()

    def tucked_away(self, now):
        """True once a pause has lasted 5 s (never for the start-up pause)."""
        return self.paused_at is not None and now - self.paused_at > 5.0

    def draw_tag(self, p, x, y, text):
        p.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 200))
        p.drawRoundedRect(QRectF(x, y, 24, 24), 6, 6)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRectF(x, y, 24, 24), Qt.AlignmentFlag.AlignCenter, text)

    def draw_label(self, p, rect, text):
        p.setFont(QFont("Segoe UI", 26, QFont.Weight.Bold))
        w = min(rect.width() - 40, 60 + 17 * len(text))
        pill = QRectF(rect.center().x() - w / 2, rect.center().y() - 34, w, 68)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 215))
        p.drawRoundedRect(pill, 14, 14)
        p.setPen(QColor(255, 255, 255))
        p.drawText(pill, Qt.AlignmentFlag.AlignCenter, text)

    def draw_hint(self, p, box, lines):
        p.setFont(QFont("Segoe UI", 10))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QColor(225, 225, 225))
        for i, line in enumerate(lines):
            p.drawText(QRectF(box.x() + 10, box.y() + 6 + 20 * i, box.width() - 20, 20),
                       Qt.AlignmentFlag.AlignVCenter | (Qt.AlignmentFlag.AlignHCenter
                       if len(lines) == 1 else Qt.AlignmentFlag.AlignLeft), line)

    def draw_demo(self, p):
        p.fillRect(QRectF(0, 0, self.width(), self.height()), QColor(28, 28, 30))
        p.setFont(QFont("Segoe UI", 10))
        for i, bt in enumerate(self.buttons):
            is_target = bt == self.target
            p.setPen(QPen(QColor(110, 110, 115), 1))
            p.setBrush(QColor(30, 170, 90) if is_target else QColor(58, 58, 62))
            p.drawRoundedRect(QRectF(*bt), 6, 6)
            p.setPen(QColor(255, 255, 255))
            p.drawText(QRectF(*bt), Qt.AlignmentFlag.AlignCenter,
                       "CLICK ME" if is_target else f"Button {i + 1}")


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--demo", action="store_true", help="practice screen with fake buttons; never clicks for real")
    ap.add_argument("--buttons", type=int, default=40, help="number of fake buttons in --demo")
    ap.add_argument("--choices", type=int, choices=(2, 4), default=4, help="boxes per step: 4 (default) or 2")
    ap.add_argument("--pixel", action="store_true", help="start with the plain pixel grid instead of real buttons")
    ap.add_argument("--no-menu", action="store_true", help="skip the click-type menu: always left click")
    ap.add_argument("--dry-run", action="store_true", help="print clicks instead of clicking")
    ap.add_argument("--keys-only", action="store_true", help="ignore the decoder; keyboard control only")
    ap.add_argument("--min-size", type=float, default=60, help="pixel grid: stop once a box is this small")
    ap.add_argument("--fill", type=int, default=70, help="0-255, how strongly the inside of a box flickers (0 = frame only)")
    ap.add_argument("--contrast", type=float, default=1.0, help="0.2-1.0 flicker strength; lower is gentler but a weaker signal")
    ap.add_argument("--split", choices=("equal", "balanced"), default="equal",
                    help="equal = same-size boxes (default); balanced = cut between buttons, fewer picks but uneven boxes")
    ap.add_argument("--size", help="window size like 1280x720 (default: whole screen)")
    ap.add_argument("--seed", type=int, default=1)
    return ap.parse_args(argv)


def main():
    args = parse_args()
    print("WARNING:" + __doc__.split("WARNING:")[1].rstrip(), flush=True)
    app = QApplication(sys.argv[:1])
    win = Overlay(args)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
