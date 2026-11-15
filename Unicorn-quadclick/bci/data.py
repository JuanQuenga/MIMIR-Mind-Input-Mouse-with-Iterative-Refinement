"""Loader for the g.tec SSVEP hackathon dataset (.mat files)."""
from __future__ import annotations

import glob
import os

import numpy as np
from scipy.io import loadmat


def load_recording(path: str) -> dict:
    """Returns dict(fs, eeg (n, 8), trig (n,), lda (n,), trials=[(freq, start, stop)])."""
    m = loadmat(path)
    y = m["y"]
    fs = float(np.ravel(m["fs"])[0])
    eeg, trig, lda = y[1:9].T.copy(), y[9].copy(), y[10].copy()
    edges = np.r_[0, np.flatnonzero(np.diff(trig) != 0) + 1, len(trig)]
    segs = [(float(trig[a]), int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]
    return dict(fs=fs, eeg=eeg, trig=trig, lda=lda, name=os.path.basename(path),
                trials=[s for s in segs if s[0] > 0],
                rests=[s for s in segs if s[0] == 0])


def find_recordings(folder: str) -> list[str]:
    return sorted(glob.glob(os.path.join(folder, "subject_*_fvep_led_training_*.mat")))


def default_data_folder(start: str) -> str:
    """Look for the .mat recordings near the program: in `start`, in a "data"
    folder inside it, then the same in each folder above (up to 4 levels).
    Returns the first folder that has them, else the folder above `start`."""
    folder = os.path.abspath(start)
    for _ in range(5):
        for cand in (folder, os.path.join(folder, "data"), os.path.join(folder, "ssvep")):
            if find_recordings(cand):
                return cand
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return os.path.dirname(os.path.abspath(start))
