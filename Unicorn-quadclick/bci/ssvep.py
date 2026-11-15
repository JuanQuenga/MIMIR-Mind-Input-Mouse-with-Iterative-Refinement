"""SSVEP decoding: which flicker frequency is the user looking at?

Method: canonical correlation analysis (CCA). For each candidate frequency
we build a sine/cosine reference and ask how well any mix of the EEG channels
can be made to correlate with it. We do that at the flicker frequency and at
twice the frequency (the 2nd harmonic), which gives two numbers per target.

Plain CCA is biased toward 9-10 Hz, because everyone's resting "alpha" rhythm
lives there. So each number is compared with what it looks like when the user
is NOT looking at a target (a short calibration at start-up) and turned into
a z-score. On the g.tec dataset (3 s window, 8 channels) this lifted the weak
subject from 73% to 90% correct. No per-target training is needed.
"""
from __future__ import annotations

import numpy as np
from scipy import signal


class StreamFilter:
    """Causal band-pass + mains notch that keeps its state between chunks."""

    def __init__(self, fs, n_ch, band=(6.0, 40.0), mains=60.0):
        sos = [signal.butter(4, band, btype="band", fs=fs, output="sos")]
        if mains and mains < fs / 2 - 2:
            sos.append(signal.butter(2, [mains - 2, mains + 2], btype="bandstop",
                                     fs=fs, output="sos"))
        self.sos = np.vstack(sos)
        self.zi = np.zeros((self.sos.shape[0], 2, n_ch))
        self._primed = False

    def __call__(self, chunk: np.ndarray) -> np.ndarray:
        if not self._primed:   # start from steady state to avoid a big transient
            self.zi = signal.sosfilt_zi(self.sos)[:, :, None] * chunk[0][None, None, :]
            self._primed = True
        out, self.zi = signal.sosfilt(self.sos, chunk, axis=0, zi=self.zi)
        return out


def harmonic_rhos(x: np.ndarray, freqs, fs: float) -> np.ndarray:
    """Features for a window x (n, ch): array (2, n_freqs).

    Row 0 = correlation at each flicker frequency, row 1 = at twice it.
    """
    n = x.shape[0]
    t = np.arange(n) / fs
    x = x - x.mean(axis=0)
    qx, _ = np.linalg.qr(x)
    out = np.zeros((2, len(freqs)))
    for h in (1, 2):
        for i, f in enumerate(freqs):
            y = np.stack([np.sin(2 * np.pi * h * f * t), np.cos(2 * np.pi * h * f * t)], 1)
            qy, _ = np.linalg.qr(y - y.mean(axis=0))
            out[h - 1, i] = min(np.linalg.svd(qx.T @ qy, compute_uv=False)[0], 1.0)
    return out


class SSVEPDecoder:
    """Online decoder. Calibrate on idle data, then feed chunks.

    push(chunk) -> list of events, each one of
        ("SCORE", [score per target])       every `step` seconds
        ("SEL", index, margin)              when the decision rule fires

    A score is "how many standard deviations above idle" (fundamental +
    2nd harmonic added together), so 0 means "looks like idle".
    """

    def __init__(self, fs, n_ch, freqs, mains=60.0, windows=(2.0, 3.0, 4.0),
                 step=0.25, thr_score=4.5, thr_margin=2.0, n_agree=2, settle=1.0):
        self.fs, self.freqs = fs, tuple(freqs)
        self.win_n = sorted(int(w * fs) for w in windows)
        self.step_n = max(1, int(step * fs))
        self.thr_score, self.thr_margin, self.n_agree = thr_score, thr_margin, n_agree
        self.settle_n = int(settle * fs)
        self.filt = StreamFilter(fs, n_ch, mains=mains)
        self.buf = np.zeros((0, n_ch))
        self.base = {}                 # window length -> (mean, std), each (2, F)
        self._calib = []
        self.reset(settle=False)

    # ---- calibration -----------------------------------------------------
    def push_calibration(self, chunk):
        """Feed idle data (user looking at the screen, not at a target)."""
        self._calib.append(self.filt(np.asarray(chunk, dtype=float)))

    def finish_calibration(self):
        seg = np.vstack(self._calib)
        self._calib = []
        self.calibrate([seg[int(self.fs):]])     # drop 1 s of filter settling

    def calibrate(self, segments):
        """segments: list of FILTERED idle arrays (n, ch). Sets the baseline.

        The baseline is measured at the shortest window, where a short
        calibration gives the most independent samples, and scaled to the
        longer ones (chance correlation shrinks like 1/sqrt(length); checked
        against the dataset's 10 s rest periods).
        """
        n0 = self.win_n[0]
        feats = [harmonic_rhos(seg[s:s + n0], self.freqs, self.fs)
                 for seg in segments
                 for s in range(0, len(seg) - n0 + 1, self.step_n)]
        if len(feats) < 15:
            raise ValueError("Not enough idle data to calibrate (need about %.0f s)"
                             % (n0 / self.fs + 4))
        feats = np.array(feats)
        mu, sd = feats.mean(0), feats.std(0) + 1e-3
        for n in self.win_n:
            k = np.sqrt(n0 / n)
            self.base[n] = (mu * k, sd * k)

    # ---- online use ------------------------------------------------------
    def reset(self, settle=True):
        """Forget collected data (call whenever the screen layout changes)."""
        self.buf = self.buf[:0]
        self._skip = self.settle_n if settle else 0
        self._since_eval = 0
        self._streak = (-1, 0)

    def set_active(self, indices):
        """Only these target indices are on screen (for 2- or 3-way splits)."""
        self.active = tuple(indices) if indices else None

    active = None

    def scores(self, x):
        """z-scored evidence per target for a FILTERED window x."""
        n = max(m for m in self.win_n if m <= len(x))
        mu, sd = self.base[n]
        z = (harmonic_rhos(x[-n:], self.freqs, self.fs) - mu) / sd
        return z.sum(axis=0)

    def push(self, chunk) -> list:
        x = self.filt(np.asarray(chunk, dtype=float))
        events = []
        if self._skip:
            take = min(self._skip, len(x))
            self._skip -= take
            x = x[take:]
        if not len(x):
            return events
        self.buf = np.vstack([self.buf, x])[-self.win_n[-1]:]
        self._since_eval += len(x)
        if len(self.buf) < self.win_n[0] or self._since_eval < self.step_n:
            return events
        self._since_eval = 0

        sc = self.scores(self.buf)
        events.append(("SCORE", [round(float(v), 2) for v in sc]))
        cand = list(self.active) if self.active else list(range(len(sc)))
        order = sorted(cand, key=lambda i: -sc[i])
        best = order[0]
        margin = sc[best] - (sc[order[1]] if len(order) > 1 else 0.0)
        if sc[best] >= self.thr_score and margin >= self.thr_margin:
            self._streak = (best, self._streak[1] + 1 if self._streak[0] == best else 1)
        else:
            self._streak = (-1, 0)
        if self._streak[1] >= self.n_agree:
            events.append(("SEL", best, round(float(margin), 2)))
            self.reset(settle=True)
        return events
