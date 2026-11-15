"""How the current area is divided into up to four regions.

Region index = position = flicker frequency:
    0 upper left, 1 upper right, 2 lower left, 3 lower right

Pixel mode (no element list): four equal quadrants.

Element mode (list of clickable rectangles), two ways:
  "equal"    four equal quadrants; each button belongs to the quadrant that
             holds its MIDDLE. Quadrants with no buttons are not shown. Equal
             sizes are easier on the eyes, and fairer to the decoder (a bigger
             flicker gives a bigger brain signal).
  "balanced" the cuts go BETWEEN buttons at the median, so each pick removes
             about three quarters of them. Fewer picks, but uneven box sizes.
"""
from __future__ import annotations

Rect = tuple  # (x, y, w, h)


def centre(r):
    return (r[0] + r[2] / 2.0, r[1] + r[3] / 2.0)


def contains(r, pt):
    return r[0] <= pt[0] < r[0] + r[2] and r[1] <= pt[1] < r[1] + r[3]


def _cut(elements, axis):
    """Split elements in two at the median along axis (0 = x, 1 = y).

    Returns (first_half, second_half, cut_position) or None if they can't be
    separated along this axis (all centres equal)."""
    es = sorted(elements, key=lambda e: centre(e)[axis])
    mid = len(es) // 2
    lo, hi = centre(es[mid - 1])[axis], centre(es[mid])[axis]
    if hi - lo < 1e-6:        # ties at the median: look for the nearest gap
        vals = [centre(e)[axis] for e in es]
        gaps = [i for i in range(1, len(es)) if vals[i] - vals[i - 1] > 1e-6]
        if not gaps:
            return None
        mid = min(gaps, key=lambda i: abs(i - len(es) / 2))
        lo, hi = vals[mid - 1], vals[mid]
    return es[:mid], es[mid:], (lo + hi) / 2.0


def quadrants(area: Rect):
    x, y, w, h = area
    hw, hh = w / 2.0, h / 2.0
    return [(x, y, hw, hh), (x + hw, y, w - hw, hh),
            (x, y + hh, hw, h - hh), (x + hw, y + hh, w - hw, h - hh)]


def split(area: Rect, elements=None, mode: str = "equal", k: int = 4, pair=(0, 3),
          keep_empty: bool = False):
    """Returns a list of (index, rect, elements_inside).

    k = 4: up to four boxes (index = position, see the top of this file).
    k = 2: two boxes, side by side or stacked, with indices `pair`.
    Boxes with no elements in them are left out, unless keep_empty is set:
    then the area is always cut into equal boxes and every box is returned
    (used for the first step, so the whole screen stays reachable).
    """
    if keep_empty and elements:
        if k == 2:
            axis = 0 if area[2] >= area[3] else 1
            mid = (area[0] + area[2] / 2.0, area[1] + area[3] / 2.0)[axis]
            a, b = _halves(area, axis)
            return [(pair[0], a, [e for e in elements if centre(e)[axis] < mid]),
                    (pair[1], b, [e for e in elements if centre(e)[axis] >= mid])]
        mx, my = area[0] + area[2] / 2.0, area[1] + area[3] / 2.0
        groups = [[], [], [], []]
        for e in elements:
            cx, cy = centre(e)
            groups[(cx >= mx) + 2 * (cy >= my)].append(e)
        return [(i, q, g) for i, (q, g) in enumerate(zip(quadrants(area), groups))]
    if k == 2:
        return _split2(area, elements, mode, pair)
    x, y, w, h = area
    if not elements:                                   # pixel mode
        return [(i, q, []) for i, q in enumerate(quadrants(area))]

    if len(elements) == 1:
        return [(0, area, list(elements))]

    if mode == "equal":
        mx, my = x + w / 2.0, y + h / 2.0
        groups = [[], [], [], []]
        for e in elements:
            cx, cy = centre(e)
            groups[(cx >= mx) + 2 * (cy >= my)].append(e)
        out = [(i, q, g) for i, (q, g) in enumerate(zip(quadrants(area), groups)) if g]
        if len(out) >= 2:
            return out
        # every button sits in one quadrant: equal boxes would be a wasted
        # pick, so this level falls back to cutting between the buttons
    return _balanced(area, elements)


def _balanced(area: Rect, elements):
    x, y, w, h = area

    cx = _cut(elements, 0)
    if cx is None:                                     # one column: top / bottom
        top, bottom, cy = _cut(elements, 1) or (elements[:1], elements[1:], y + h / 2.0)
        return [(0, (x, y, w, cy - y), top), (2, (x, cy, w, y + h - cy), bottom)]

    left, right, xc = cx
    out = []
    for col, (els, rx, rw) in enumerate(((left, x, xc - x), (right, xc, x + w - xc))):
        cy = _cut(els, 1) if len(els) > 1 else None
        if cy is None:                                 # whole column is one region
            out.append((col, (rx, y, rw, h), els))
        else:
            top, bottom, yc = cy
            out.append((col, (rx, y, rw, yc - y), top))
            out.append((col + 2, (rx, yc, rw, y + h - yc), bottom))
    return sorted(out)


def is_final(rect: Rect, elements, min_size: float) -> bool:
    """Small enough to click? One element left, or (pixel mode) a tiny box."""
    if elements:
        return len(elements) == 1
    return max(rect[2], rect[3]) <= min_size


def _halves(area: Rect, axis: int, at=None):
    x, y, w, h = area
    if axis == 0:
        c = x + w / 2.0 if at is None else at
        return (x, y, c - x, h), (c, y, x + w - c, h)
    c = y + h / 2.0 if at is None else at
    return (x, y, w, c - y), (x, c, w, y + h - c)


def _split2(area: Rect, elements, mode, pair):
    x, y, w, h = area
    axis = 0 if w >= h else 1                       # cut across the longer side
    if not elements:                                # pixel mode
        a, b = _halves(area, axis)
        return [(pair[0], a, []), (pair[1], b, [])]
    if len(elements) == 1:
        return [(pair[0], area, list(elements))]
    if mode == "equal":
        mid = (x + w / 2.0, y + h / 2.0)[axis]
        first = [e for e in elements if centre(e)[axis] < mid]
        second = [e for e in elements if centre(e)[axis] >= mid]
        if first and second:
            a, b = _halves(area, axis)
            return [(pair[0], a, first), (pair[1], b, second)]
    for ax in (axis, 1 - axis):                     # cut between the buttons
        cut = _cut(elements, ax)
        if cut:
            first, second, at = cut
            a, b = _halves(area, ax, at)
            return [(pair[0], a, first), (pair[1], b, second)]
    a, b = _halves(area, axis)                      # identical positions: just split the list
    return [(pair[0], a, elements[:1]), (pair[1], b, elements[1:])]


def cells(area: Rect, elements):
    """Give every element its own private rectangle inside `area`.

    Returns [(cell_rect, element)] in reading order (top row first). Used for
    the last step, where each remaining element gets its own box.
    """
    def rec(a, els):
        if len(els) <= 1:
            return [(a, e) for e in els]
        spread = [max(centre(e)[ax] for e in els) - min(centre(e)[ax] for e in els)
                  for ax in (0, 1)]
        for ax in ((0, 1) if spread[0] >= spread[1] else (1, 0)):
            cut = _cut(els, ax)
            if cut:
                first, second, at = cut
                ra, rb = _halves(a, ax, at)
                return rec(ra, first) + rec(rb, second)
        ra, rb = _halves(a, 0)                      # identical positions
        return rec(ra, els[:1]) + rec(rb, els[1:])

    out = rec(area, list(elements))
    row_h = max(1.0, min(e[3] for _, e in out))
    return sorted(out, key=lambda ce: (round(centre(ce[1])[1] / row_h), centre(ce[1])[0]))


def bounds(elements, pad_frac=0.12, pad_px=20.0, inside: Rect = None, aspect=None):
    """Rectangle around all elements with some margin, optionally widened to a
    given width/height ratio and kept inside `inside`."""
    x0 = min(e[0] for e in elements)
    y0 = min(e[1] for e in elements)
    x1 = max(e[0] + e[2] for e in elements)
    y1 = max(e[1] + e[3] for e in elements)
    px, py = (x1 - x0) * pad_frac + pad_px, (y1 - y0) * pad_frac + pad_px
    x0, y0, x1, y1 = x0 - px, y0 - py, x1 + px, y1 + py
    if aspect:
        w, h = x1 - x0, y1 - y0
        if w / h < aspect:                           # too tall: widen
            grow = (h * aspect - w) / 2.0
            x0, x1 = x0 - grow, x1 + grow
        else:                                        # too wide: make taller
            grow = (w / aspect - h) / 2.0
            y0, y1 = y0 - grow, y1 + grow
    if inside:
        ix, iy, iw, ih = inside
        w, h = min(x1 - x0, iw), min(y1 - y0, ih)
        x0 = min(max(x0, ix), ix + iw - w)
        y0 = min(max(y0, iy), iy + ih - h)
        x1, y1 = x0 + w, y0 + h
    return (x0, y0, x1 - x0, y1 - y0)


def leaves(elements, screen_area: float, keep=(), max_share: float = 0.25):
    """Drop the rectangles that are really containers.

    Programs report panels, lists and whole pages as clickable along with the
    buttons inside them. A big container is filed under the box that holds its
    MIDDLE, which can be far from the part of it you are looking at, and it
    hides the fact that the small things inside are what you want. So:
      - anything covering more than max_share of the screen goes, and
      - anything that has two or more other elements' middles inside it goes.
    Rectangles in `keep` (text boxes) are never dropped.
    """
    keep = set(keep)
    out = []
    for e in elements:
        if e in keep:
            out.append(e)
            continue
        if e[2] * e[3] > max_share * screen_area:
            continue
        inside = sum(1 for o in elements
                     if o is not e and o[2] * o[3] < e[2] * e[3] and contains(e, centre(o)))
        if inside >= 2:
            continue
        out.append(e)
    return out
