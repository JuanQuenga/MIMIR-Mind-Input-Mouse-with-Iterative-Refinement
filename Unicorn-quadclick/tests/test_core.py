"""Run with:  python -m pytest tests   (or: python tests/test_core.py)"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bci import config, splitter                      # noqa: E402
from bci.clench import JawClenchDetector              # noqa: E402
from bci.engine import Engine                         # noqa: E402

FS = 250.0


def fake_eeg(seconds, n_ch=8, freq=None, amp=4.0, seed=0, t0=0.0):
    """Pink-ish noise (~10 uV) with an optional sine 'SSVEP' on every channel."""
    rng = np.random.default_rng(seed)
    n = int(seconds * FS)
    x = np.cumsum(rng.normal(0, 1, (n, n_ch)), axis=0)
    x = x - np.convolve(x.mean(1), np.ones(125) / 125, "same")[:, None]
    x += rng.normal(0, 6, (n, n_ch))
    if freq:
        t = t0 + np.arange(n) / FS
        x += amp * np.sin(2 * np.pi * freq * t)[:, None] * rng.uniform(0.5, 1.5, n_ch)
    return x


def feed(engine, x, chunk=25):
    out = []
    for s in range(0, len(x), chunk):
        out += engine.push(x[s:s + chunk])
    return out


def test_engine_calibrates_then_selects_each_target():
    for i, f in enumerate(config.FREQS):
        eng = Engine(FS, 8, ssvep_channels=(4, 5, 6, 7), calib_seconds=12)
        cmds = feed(eng, fake_eeg(12.2, seed=i))
        assert "READY" in cmds and not any(c.startswith("SEL") for c in cmds)
        cmds = feed(eng, fake_eeg(8, freq=f, seed=10 + i, t0=12.2))
        sels = [c for c in cmds if c.startswith("SEL")]
        assert sels and all(int(c.split()[1]) == i for c in sels), (f, sels)


def test_engine_stays_quiet_on_idle_data():
    eng = Engine(FS, 8, ssvep_channels=(4, 5, 6, 7), calib_seconds=12)
    cmds = feed(eng, fake_eeg(72, seed=3))
    assert sum(c.startswith("SEL") for c in cmds) <= 1


def test_active_subset_limits_choices():
    eng = Engine(FS, 8, ssvep_channels=(4, 5, 6, 7), calib_seconds=12)
    feed(eng, fake_eeg(12.2, seed=1))
    eng.handle("LAYOUT 1 0 0 0 10 10 2 0 10 10 10")      # only targets 0 and 2 shown
    cmds = feed(eng, fake_eeg(8, freq=config.FREQS[1], seed=2, t0=12.2))
    assert not any(c.startswith("SEL 1") or c.startswith("SEL 3") for c in cmds)


def burst(x, start, dur, gain=80.0, seed=5):
    rng = np.random.default_rng(seed)
    a, b = int(start * FS), int((start + dur) * FS)
    x = x.copy()
    x[a:b] += rng.normal(0, gain, (b - a, 1)) + rng.normal(0, gain / 4, (b - a, x.shape[1]))
    return x


def test_clench_short_and_long():
    det = JawClenchDetector(FS, 8, **config.CLENCH)
    x = fake_eeg(20, seed=7)
    x = burst(x, 8.0, 0.5)            # short clench
    x = burst(x, 12.0, 1.6, seed=6)   # long clench
    x[int(16 * FS)] += 400            # a single-sample electrode pop: must be ignored
    ev = []
    for s in range(0, len(x), 25):
        ev += det.push(x[s:s + 25])
    assert ev == ["CLENCH_START", "CLENCH_SHORT", "CLENCH_START", "CLENCH_LONG"], ev


def test_clench_ignores_one_noisy_channel():
    det = JawClenchDetector(FS, 8, **config.CLENCH)
    x = fake_eeg(15, seed=8)
    rng = np.random.default_rng(1)
    x[int(8 * FS):int(10 * FS), 3] += rng.normal(0, 300, int(2 * FS))
    ev = []
    for s in range(0, len(x), 25):
        ev += det.push(x[s:s + 25])
    assert ev == [], ev


def test_split_pixel_mode_quadrants():
    regs = splitter.split((0, 0, 1920, 1080))
    assert [r[0] for r in regs] == [0, 1, 2, 3]
    assert regs[3][1] == (960.0, 540.0, 960.0, 540.0)


def _walk_all(mode, n=64, seed=0):
    rng = np.random.default_rng(seed)
    els = [(float(rng.uniform(0, 1800)), float(rng.uniform(0, 1000)), 60.0, 24.0)
           for _ in range(n)]
    depths = []
    for target in els:
        area, cur, depth = (0, 0, 1920, 1080), els, 0
        while len(cur) > 1:
            regs = splitter.split(area, cur, mode=mode)
            assert 2 <= len(regs) <= 4
            assert sum(len(r[2]) for r in regs) == len(cur)       # nobody lost
            _, area, cur = next(r for r in regs if target in r[2])
            depth += 1
        assert cur == [target]
        depths.append(depth)
    return depths


def test_split_balanced_reaches_every_button():
    d = _walk_all("balanced")
    assert max(d) <= 4 and np.mean(d) <= 3.2, (max(d), np.mean(d))


def test_split_equal_reaches_every_button():
    d = _walk_all("equal")
    assert max(d) <= 6 and np.mean(d) <= 4.2, (max(d), np.mean(d))


def test_split_equal_boxes_are_equal():
    els = [(100, 100, 60, 24), (1500, 120, 60, 24), (200, 800, 60, 24), (1600, 900, 60, 24),
           (900, 100, 60, 24)]
    regs = splitter.split((0, 0, 1920, 1080), els, mode="equal")
    assert {(r[1][2], r[1][3]) for r in regs} == {(960.0, 540.0)}
    # a button belongs to the quadrant holding its middle (930, 112 -> upper left)
    assert (900, 100, 60, 24) in regs[0][2]


def test_split_equal_skips_empty_quadrants():
    els = [(100, 100, 60, 24), (100, 800, 60, 24)]          # both on the left
    regs = splitter.split((0, 0, 1920, 1080), els, mode="equal")
    assert [r[0] for r in regs] == [0, 2]


def test_split_two_elements_and_stacked_column():
    a, b = (10, 10, 50, 20), (300, 10, 50, 20)
    regs = splitter.split((0, 0, 400, 100), [a, b])
    assert [(r[0], r[2]) for r in regs] == [(0, [a]), (1, [b])]
    col = [(10, y, 50, 20) for y in (10, 60, 110)]
    regs = splitter.split((0, 0, 100, 200), col)
    assert [r[0] for r in regs] == [0, 2] and sum(len(r[2]) for r in regs) == 3


def test_two_choice_split_reaches_every_button():
    rng = np.random.default_rng(2)
    els = [(float(rng.uniform(0, 1800)), float(rng.uniform(0, 1000)), 60.0, 24.0)
           for _ in range(40)]
    depths = []
    for target in els:
        area, cur, depth = (0, 0, 1920, 1080), els, 0
        while len(cur) > 1:
            regs = splitter.split(area, cur, k=2, pair=(0, 3))
            assert len(regs) == 2 and [r[0] for r in regs] == [0, 3]
            assert all(r[2] for r in regs)                        # no empty box is shown
            assert sum(len(r[2]) for r in regs) == len(cur)
            _, area, cur = next(r for r in regs if target in r[2])
            depth += 1
        depths.append(depth)
    assert max(depths) <= 9, max(depths)


def test_cells_give_each_element_its_own_space():
    els = [(100, 100, 60, 24), (300, 110, 60, 24), (120, 400, 60, 24), (500, 420, 60, 24)]
    out = splitter.cells((0, 0, 800, 600), els)
    assert [e for _, e in out] == els                             # reading order
    for cell, e in out:
        assert splitter.contains(cell, splitter.centre(e))
        assert sum(splitter.contains(cell, splitter.centre(o)) for o in els) == 1
    same = [(10, 10, 40, 40), (10, 10, 40, 40)]                    # stacked exactly
    assert len(splitter.cells((0, 0, 800, 600), same)) == 2


def test_bounds_stay_inside_and_keep_shape():
    els = [(1800, 1040, 40, 30), (1860, 1040, 40, 30)]            # two taskbar icons
    x, y, w, h = splitter.bounds(els, inside=(0, 0, 1920, 1080), aspect=16 / 9)
    assert x >= 0 and y >= 0 and x + w <= 1920 + 1e-6 and y + h <= 1080 + 1e-6
    assert abs(w / h - 16 / 9) < 0.01
    assert all(splitter.contains((x, y, w, h), splitter.centre(e)) for e in els)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
