"""Drive the overlay with REAL recorded brain data: no headset needed.

    python overlay.py --demo                    # terminal 1
    python replay_dataset.py                    # terminal 2

A "simulated user" watches where the overlay's green target is. Whichever
region the target is in, it plays back a recorded trial from the g.tec SSVEP
dataset in which the subject was really looking at that flicker frequency.
The data goes through exactly the same Engine the live headset uses, so the
overlay, decision rule and command flow can all be developed without hardware.

Options:
    --subject 1|2      which subject's recordings to use (2 is the hard one)
    --unicorn          only use the 3 channels a Unicorn also has
    --speed 4          play back faster than real time
    --target 900,400   aim at a fixed screen point (when the overlay isn't in --demo)
"""
from __future__ import annotations

import argparse
import os
import random
import time

import numpy as np

from bci import config, splitter
from bci.data import default_data_folder, find_recordings, load_recording
from bci.engine import Engine
from bci.net import Link


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--data", default=default_data_folder(here),
                    help="folder with the .mat files (default: searched for near this program)")
    ap.add_argument("--subject", type=int, default=1, choices=(1, 2))
    ap.add_argument("--unicorn", action="store_true")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--target", help="x,y in overlay coordinates")
    ap.add_argument("--clicks", type=int, default=0, help="stop after this many clicks (0 = never)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    paths = [p for p in find_recordings(args.data) if f"subject_{args.subject}_" in p]
    if len(paths) != 2:
        raise SystemExit(f"Could not find the two subject_{args.subject} .mat files in {args.data}")
    calib_rec, test_rec = load_recording(paths[0]), load_recording(paths[1])
    fs = test_rec["fs"]
    ch = list(config.DATASET_UNICORN_LIKE) if args.unicorn else list(range(8))
    rnd = random.Random(args.seed)
    chunk = 16                                   # samples per push (62.5 ms)

    engine = Engine(fs, len(ch), mains=50.0)     # dataset was recorded on 50 Hz mains
    link = Link(send_port=config.CMD_PORT, listen_port=config.STATE_PORT)
    link.send("HELLO")

    idle = np.vstack([calib_rec["eeg"][a + int(0.5 * fs):b] for _, a, b in calib_rec["rests"]])
    trials = {f: [test_rec["eeg"][a:b] for g, a, b in test_rec["trials"] if g == f]
              for f in config.FREQS}

    regions, target = [], None
    if args.target:
        target = tuple(float(v) for v in args.target.split(","))
    clicks, t_next = 0, time.perf_counter()
    last = np.zeros(8)                           # last sample played, per channel
    heard = None                                 # when the overlay was last heard from

    def stream(samples, stop_on_layout=True):
        """Play samples in (scaled) real time. Returns True if the layout changed."""
        nonlocal regions, target, clicks, t_next, last, heard
        # Recordings are spliced together here. Shift each piece so it starts
        # where the previous one ended; otherwise the jump looks like a muscle
        # burst to the clench detector.
        samples = samples - samples[0] + last
        for s in range(0, len(samples), chunk):
            changed = False
            for msg in link.poll():
                p = msg.split()
                heard = time.perf_counter()
                if p[0] == "BYE":
                    raise SystemExit("The overlay was closed, so the replay is stopping too.")
                if p[0] == "LAYOUT":
                    engine.handle(msg)
                    v = [float(x) for x in p[2:]]
                    regions = [(int(v[i]), tuple(v[i + 1:i + 5])) for i in range(0, len(v), 5)]
                    changed = True
                elif p[0] == "TARGET" and not args.target:
                    target = (float(p[1]), float(p[2]))
                elif p[0] == "CLICK":
                    clicks += 1
                    print("overlay:", msg, flush=True)
            last = samples[min(s + chunk, len(samples)) - 1]
            for cmd in engine.push(samples[s:s + chunk][:, ch]):
                link.send(cmd)
                if not cmd.startswith(("SCORE", "CALIB")):
                    print("engine: ", cmd, flush=True)
            t_next += chunk / fs / args.speed
            time.sleep(max(0.0, t_next - time.perf_counter()))
            if heard and time.perf_counter() - heard > 5.0:
                raise SystemExit("Lost contact with the overlay, so the replay is stopping.")
            if changed and stop_on_layout:
                return True
        return False

    print(f"Calibrating on {config.CALIB_SECONDS:.0f} s of recorded rest data...", flush=True)
    stream(idle[:int((config.CALIB_SECONDS + 0.5) * fs)], stop_on_layout=False)
    if not regions:
        link.send("HELLO")
        print("Waiting for the overlay (start it with: python overlay.py --demo)", flush=True)
    while not args.clicks or clicks < args.clicks:
        looking_at = next((i for i, r in regions if target and splitter.contains(r, target)), None)
        if looking_at is None:                   # nothing to look at: play rest data
            changed = stream(idle[:int(1.5 * fs)])
            if not regions:
                link.send("HELLO")
            elif target and not changed:         # a wrong pick zoomed in on the wrong
                print("sim user: wrong region, undo", flush=True)   # place: "clench"
                link.send("CLENCH_SHORT")
                stream(idle[:int(0.25 * fs)])
            continue
        stream(rnd.choice(trials[config.FREQS[looking_at]]))
    link.send("QUIT") if args.clicks else None


if __name__ == "__main__":
    main()
