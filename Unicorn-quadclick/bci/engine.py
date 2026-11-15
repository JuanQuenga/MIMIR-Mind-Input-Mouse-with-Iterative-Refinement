"""Turns raw EEG chunks into commands for the overlay.

    engine = Engine(fs=250, n_ch=8, ssvep_channels=(4, 5, 6, 7))
    for cmd in engine.push(chunk):       # chunk: (samples, channels) in microvolts
        send(cmd)                        # e.g. "SEL 2 4.1", "CLENCH_SHORT"

Commands out:
    CALIB <seconds left>   start-up: user relaxes and looks at the centre dot
    READY                  calibration finished
    SCORE a b c d          live evidence per target (for the on-screen bars)
    SEL <index> <margin>   the user picked target <index>
    CLENCH_SHORT           undo one level
    CLENCH_LONG            back to the full screen
Messages in (from the overlay, via handle()):
    LAYOUT <level> <i x y w h>...   the screen changed; restart evidence
"""
from __future__ import annotations

import numpy as np

from . import config
from .clench import JawClenchDetector
from .ssvep import SSVEPDecoder


class Engine:
    def __init__(self, fs, n_ch, ssvep_channels=None, mains=config.MAINS_HZ,
                 freqs=config.FREQS, calib_seconds=config.CALIB_SECONDS,
                 ssvep_kwargs=None, clench_kwargs=None, use_clench=True):
        self.fs = fs
        self.ch = list(ssvep_channels) if ssvep_channels is not None else list(range(n_ch))
        self.ssvep = SSVEPDecoder(fs, len(self.ch), freqs, mains=mains,
                                  **{**config.SSVEP, **(ssvep_kwargs or {})})
        ck = {**config.CLENCH, **(clench_kwargs or {})}
        ck["baseline"] = min(ck["baseline"], calib_seconds - 1.0)
        self.clench = JawClenchDetector(fs, n_ch, mains=mains, **ck) if use_clench else None
        self._calib_left = int(calib_seconds * fs)
        self._last_calib_msg = None

    @property
    def calibrating(self) -> bool:
        return self._calib_left > 0

    def handle(self, msg: str):
        """Message from the overlay."""
        parts = msg.split()
        if parts and parts[0] == "LAYOUT":
            idx = [int(v) for v in parts[2::5]]
            self.ssvep.set_active(idx)
            self.ssvep.reset(settle=True)

    def push(self, chunk) -> list[str]:
        chunk = np.atleast_2d(np.asarray(chunk, dtype=float))
        out = []
        clench_events = self.clench.push(chunk) if self.clench else []

        if self.calibrating:
            self.ssvep.push_calibration(chunk[:, self.ch])
            self._calib_left -= len(chunk)
            left = max(0, int(np.ceil(self._calib_left / self.fs)))
            if self.calibrating and left != self._last_calib_msg:
                self._last_calib_msg = left
                out.append(f"CALIB {left}")
            if not self.calibrating:
                self.ssvep.finish_calibration()
                out.append("READY")
            return out

        for ev in clench_events:
            if ev == "CLENCH_START":
                self.ssvep.reset(settle=True)
            else:
                out.append(ev)
        if self.clench and self.clench.active:
            return out          # muscle noise swamps the EEG: don't decode it

        for ev in self.ssvep.push(chunk[:, self.ch]):
            if ev[0] == "SCORE":
                out.append("SCORE " + " ".join(f"{v:.2f}" for v in ev[1]))
            else:
                out.append(f"SEL {ev[1]} {ev[2]:.2f}")
        return out
