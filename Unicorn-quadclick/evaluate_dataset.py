"""Score the decoder on the g.tec SSVEP dataset.

    python evaluate_dataset.py                 # finds the .mat files in a folder above
    python evaluate_dataset.py C:\\path\\to\\ssvep

Prints three things and saves results.png next to this file:
  1. Accuracy for fixed windows: plain CCA vs. idle-corrected CCA.
  2. The live decision rule replayed over each trial (right / wrong / no answer).
  3. What that means for a full click that needs several selections in a row.

The idle baseline for each recording comes from the OTHER session of the same
subject, so nothing is tested on data it was calibrated on.
"""
from __future__ import annotations

import os
import sys

import numpy as np

from bci import config
from bci.data import default_data_folder, find_recordings, load_recording
from bci.ssvep import SSVEPDecoder, StreamFilter, harmonic_rhos

F = config.FREQS
CHANNEL_SETS = {"all 8 channels": list(range(8)),
                "3 Unicorn-like (PO7, Oz, PO8)": list(config.DATASET_UNICORN_LIKE)}
WINDOWS = (2.0, 3.0, 4.0)


def prepare(rec, ch):
    """Causally filter one recording (same filter as live) and cut idle pieces."""
    fs = rec["fs"]
    x = StreamFilter(fs, len(ch), mains=50.0)(rec["eeg"][:, ch])   # recorded in Europe
    idle = [x[a + int(0.5 * fs):b] for _, a, b in rec["rests"]]
    return x, idle


def make_decoder(fs, n_ch, idle, **kw):
    dec = SSVEPDecoder(fs, n_ch, F, mains=0, **{**config.SSVEP, "settle": 0.0, **kw})
    dec.filt = lambda c: c          # data is already filtered
    dec.calibrate(idle)
    return dec


def fixed_window_accuracy(recs, ch):
    """{window: (plain[4 recs], corrected[4 recs])} as fractions correct."""
    out = {}
    for w in WINDOWS:
        plain, corr = [], []
        for i, rec in enumerate(recs):
            fs = rec["fs"]
            n = int(w * fs)
            x, _ = prepare(rec, ch)
            _, idle = prepare(recs[i ^ 1], ch)
            dec = make_decoder(fs, len(ch), idle, windows=tuple(sorted({WINDOWS[0], w})))
            ok_p = ok_c = 0
            for f, a, _ in rec["trials"]:
                seg = x[a + int(0.15 * fs):][:n]
                ok_p += F[int(harmonic_rhos(seg, F, fs).sum(0).argmax())] == f
                ok_c += F[int(dec.scores(seg).argmax())] == f
            plain.append(ok_p / len(rec["trials"]))
            corr.append(ok_c / len(rec["trials"]))
        out[w] = (plain, corr)
    return out


def online_replay(recs, ch):
    """Run the live decision rule over every trial and every rest period."""
    rows = []
    for i, rec in enumerate(recs):
        fs = rec["fs"]
        x, _ = prepare(rec, ch)
        _, idle = prepare(recs[i ^ 1], ch)
        dec = make_decoder(fs, len(ch), idle)
        right = wrong = none = false_pos = 0
        times, rest_s = [], 0.0
        for f, a, b in rec["trials"]:
            dec.reset(settle=False)
            got = None
            for s in range(a, b, 16):
                sel = [e for e in dec.push(x[s:min(s + 16, b)]) if e[0] == "SEL"]
                if sel:
                    got = (sel[0][1], (s + 16 - a) / fs)
                    break
            if got is None:
                none += 1
            elif F[got[0]] == f:
                right += 1
                times.append(got[1])
            else:
                wrong += 1
        for _, a, b in rec["rests"]:
            a += int(0.5 * fs)
            rest_s += (b - a) / fs
            dec.reset(settle=False)
            for s in range(a, b, 16):
                if any(e[0] == "SEL" for e in dec.push(x[s:min(s + 16, b)])):
                    false_pos += 1
        rows.append(dict(name=rec["name"], right=right, wrong=wrong, none=none,
                         time=float(np.mean(times)) if times else float("nan"),
                         false_pos=false_pos, rest_s=rest_s))
    return rows


def click_simulation(p_right, p_wrong, t_sel, levels, n=20000, seed=0,
                     t_timeout=7.4, t_settle=1.0, t_undo=2.0):
    """Monte Carlo of one click that needs `levels` right selections in a row.

    A wrong selection is undone with a jaw clench (assumed to work, t_undo s).
    No answer just costs t_timeout seconds. Returns (median seconds,
    fraction of clicks finished with no wrong selection at all).
    """
    rng = np.random.default_rng(seed)
    total, clean = [], 0
    for _ in range(n):
        t, depth, errors = 0.0, 0, 0
        while depth < levels:
            u = rng.random()
            if u < p_right:
                t += t_settle + t_sel
                depth += 1
            elif u < p_right + p_wrong:
                t += t_settle + t_sel + t_undo
                errors += 1
            else:
                t += t_timeout
        total.append(t)
        clean += errors == 0
    return float(np.median(total)), clean / n


def plot(acc, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid, surface = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
    series = {"Idle-corrected (ours)": "#2a78d6", "Plain CCA": "#eb6834"}
    fig, axes = plt.subplots(2, 2, figsize=(9, 6.2), sharex=True, sharey=True,
                             facecolor=surface)
    for r, (chname, by_w) in enumerate(acc.items()):
        for c, subj in enumerate(("Subject 1", "Subject 2")):
            ax = axes[r, c]
            ax.set_facecolor(surface)
            for k, (label, color) in enumerate(series.items()):
                ys = [100 * np.mean(by_w[w][1 - k][2 * c:2 * c + 2]) for w in WINDOWS]
                ax.plot(WINDOWS, ys, color=color, lw=2, marker="o", ms=6,
                        markeredgecolor=surface, markeredgewidth=1.5, label=label,
                        zorder=3 - k)
                va = "bottom" if k == 0 else "top"
                ax.annotate(f"{ys[-1]:.0f}%", (WINDOWS[-1], ys[-1]),
                            xytext=(0, 7 if k == 0 else -7), textcoords="offset points",
                            ha="center", va=va, fontsize=9, color=ink)
            ax.set_title(f"{subj} · {chname}", fontsize=10, color=ink, loc="left")
            ax.set_ylim(40, 108)
            ax.set_xticks(WINDOWS, [f"{w:.0f} s" for w in WINDOWS])
            ax.set_yticks([50, 75, 100], ["50%", "75%", "100%"])
            ax.axhline(25, color=muted, lw=1, ls=":")
            ax.grid(axis="y", color=grid, lw=1)
            ax.tick_params(colors=muted, length=0, labelsize=9)
            for s in ax.spines.values():
                s.set_visible(False)
    axes[0, 0].legend(frameon=False, fontsize=9, loc="lower left", labelcolor=ink)
    fig.suptitle("Correct target picked, by length of EEG window (g.tec SSVEP dataset, "
                 "40 trials per panel)", fontsize=11, color=ink, x=0.02, ha="left")
    fig.supxlabel("EEG window used for the decision", fontsize=9, color=muted)
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    fig.savefig(path, dpi=150, facecolor=surface)


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    folder = sys.argv[1] if len(sys.argv) > 1 else default_data_folder(here)
    paths = find_recordings(folder)
    if len(paths) != 4:
        sys.exit(f"Expected the 4 subject_*_fvep_led_training_*.mat files in {folder}")
    recs = [load_recording(p) for p in paths]

    print("1) FIXED WINDOW: % of 20 trials correct  [S1 run1, S1 run2, S2 run1, S2 run2]")
    acc = {}
    for chname, ch in CHANNEL_SETS.items():
        acc[chname] = fixed_window_accuracy(recs, ch)
        print(f"   {chname}")
        for w, (plain, corr) in acc[chname].items():
            fmt = lambda v: " ".join(f"{100 * a:4.0f}" for a in v) + f"  mean {100 * np.mean(v):3.0f}"
            print(f"     {w:.0f} s   plain CCA: {fmt(plain)}   idle-corrected: {fmt(corr)}")

    print("\n2) LIVE DECISION RULE replayed over each 7.4 s trial "
          f"(thr_score={config.SSVEP['thr_score']}, thr_margin={config.SSVEP['thr_margin']})")
    sims = {}
    for chname, ch in CHANNEL_SETS.items():
        rows = online_replay(recs, ch)
        print(f"   {chname}")
        for s, name in ((0, "Subject 1"), (2, "Subject 2")):
            r = rows[s:s + 2]
            right, wrong, none = (sum(x[k] for x in r) for k in ("right", "wrong", "none"))
            t = float(np.nanmean([x["time"] for x in r]))
            fp, rest = sum(x["false_pos"] for x in r), sum(x["rest_s"] for x in r)
            sims[(chname, name)] = (right / 40, wrong / 40, t)
            print(f"     {name}: right {right}/40, wrong {wrong}/40, no answer {none}/40, "
                  f"mean time to answer {t:.1f} s; false selections while idle: "
                  f"{fp} in {rest:.0f} s")

    print("\n3) WHOLE CLICK (simulated from the rates above; undo by jaw clench assumed reliable)")
    for (chname, name), (pr, pw, t) in sims.items():
        for levels, what in ((3, "3 selections (about 64 buttons, element mode)"),
                             (5, "5 selections (pixel grid on a full-HD screen)")):
            med, clean = click_simulation(pr, pw, t, levels)
            print(f"     {name}, {chname}: {what}: median {med:.0f} s per click, "
                  f"{100 * clean:.0f}% need no undo")

    out = os.path.join(here, "results.png")
    plot(acc, out)
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
