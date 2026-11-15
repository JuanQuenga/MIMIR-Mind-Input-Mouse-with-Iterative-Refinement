"""Jaw-clench detector.

A clench is muscle activity (EMG), not a brain signal: a burst of 30-100 Hz
energy that shows up on every channel at once and is many times larger than
EEG. We track the high-frequency energy, learn what "relaxed" looks like, and
report a clench when the energy stays far above that for long enough.

NOTE: the g.tec datasets contain no jaw clenches, so this has only been
tested on synthetic bursts. Check the threshold on the real headset.
"""
from __future__ import annotations

import numpy as np
from scipy import signal


class JawClenchDetector:
    """push(chunk) -> list of "CLENCH_START" | "CLENCH_SHORT" | "CLENCH_LONG"."""

    def __init__(self, fs, n_ch, mains=60.0, band=(30.0, 100.0), win=0.15, k=6.0,
                 hold=0.30, long=0.90, refractory=1.0, baseline=5.0):
        hi = min(band[1], fs / 2 - 5)
        sos = [signal.butter(4, [band[0], hi], btype="band", fs=fs, output="sos")]
        if mains and band[0] < mains < hi:
            sos.append(signal.butter(2, [mains - 3, mains + 3], btype="bandstop",
                                     fs=fs, output="sos"))
        self.sos = np.vstack(sos)
        self.zi = np.zeros((self.sos.shape[0], 2, n_ch))
        self.fs, self.k = fs, k
        self.win_n = max(1, int(win * fs))                # moving-average length
        self._tail = np.zeros(self.win_n - 1)             # last powers of the previous chunk
        self.hold_n, self.long_n = int(hold * fs), int(long * fs)
        self.refr_n, self.base_n = int(refractory * fs), int(baseline * fs)
        self.threshold = None
        self._base = []
        self._above = 0          # samples continuously above threshold
        self._state = "idle"     # idle -> active -> (long_sent) -> idle
        self._refr = 0
        self._warm = int(0.5 * fs)

    @property
    def active(self) -> bool:
        return self._state != "idle"

    def set_baseline(self, envelope_values):
        v = np.asarray(envelope_values)
        med = np.median(v)
        mad = 1.4826 * np.median(np.abs(v - med))
        self.threshold = max(med + self.k * mad, 3.0 * med)

    def push(self, chunk) -> list:
        x, self.zi = signal.sosfilt(self.sos, np.asarray(chunk, float), axis=0, zi=self.zi)
        power = np.median(x ** 2, axis=1)     # median: one bad electrode can't fire it
        padded = np.concatenate([self._tail, power])
        self._tail = padded[len(padded) - (self.win_n - 1):]
        csum = np.concatenate([[0.0], np.cumsum(padded)])
        envelope = np.sqrt((csum[self.win_n:] - csum[:-self.win_n]) / self.win_n)
        events = []
        for e in envelope:
            if self._warm:                    # skip the filter's start-up transient
                self._warm -= 1
                continue
            if self.threshold is None:        # still learning the relaxed level
                self._base.append(e)
                if len(self._base) >= self.base_n:
                    self.set_baseline(self._base)
                continue
            if self._refr:
                self._refr -= 1
                continue
            if self._state == "idle":
                self._above = self._above + 1 if e > self.threshold else 0
                if self._above >= self.hold_n:
                    self._state = "active"
                    events.append("CLENCH_START")
            else:
                self._above += 1
                if self._state == "active" and self._above >= self.long_n:
                    self._state = "long_sent"
                    events.append("CLENCH_LONG")
                if e < 0.5 * self.threshold:  # released
                    if self._state == "active":
                        events.append("CLENCH_SHORT")
                    self._state, self._above, self._refr = "idle", 0, self.refr_n
        return events
