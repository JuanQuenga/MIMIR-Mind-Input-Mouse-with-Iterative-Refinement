"""LIVE: Unicorn Hybrid Black -> g.Pype -> decoder -> overlay.

    python overlay.py                 # terminal 1 (add --demo to practise first)
    python run_live_gpype.py          # terminal 2

    python run_live_gpype.py --sim    # no headset: g.Pype's signal generator
                                      # (checks the wiring; it will not select anything)

The first 40 s are calibration: relax your jaw and look at the red dot.
After that: look at a flickering region to pick it, clench briefly to undo,
clench and hold (about 1 s) to go back to the whole screen.
"""
from __future__ import annotations

import argparse

import gpype as gp

from bci import config
from bci.engine import Engine
from bci.net import Link

PORT_IN = gp.Constants.Defaults.PORT_IN


class DecoderNode(gp.INode):
    """g.Pype sink node: every incoming frame goes through the Engine and the
    resulting commands are sent to the overlay over UDP."""

    def __init__(self, mains=config.MAINS_HZ, **kwargs):
        super().__init__(**kwargs)
        self._mains = mains
        self._engine = None
        self._link = None

    def setup(self, data, port_context_in):
        ctx = port_context_in[PORT_IN]
        fs = float(ctx[gp.Constants.Keys.SAMPLING_RATE])
        n_ch = int(ctx[gp.Constants.Keys.CHANNEL_COUNT])
        # Unicorn order is Fz C3 Cz C4 Pz PO7 Oz PO8: SSVEP uses the back four.
        ssvep_ch = config.UNICORN_SSVEP_CHANNELS if n_ch >= 8 else None
        self._engine = Engine(fs, n_ch, ssvep_channels=ssvep_ch, mains=self._mains)
        if self._link is None:
            self._link = Link(send_port=config.CMD_PORT, listen_port=config.STATE_PORT)
        self._link.send("HELLO")
        return super().setup(data, port_context_in)

    def step(self, data):
        for msg in self._link.poll():
            self._engine.handle(msg)
        for cmd in self._engine.push(data[PORT_IN]):
            self._link.send(cmd)
            if not cmd.startswith("SCORE"):
                print("engine:", cmd, flush=True)
        return {}


def build(sim=False, serial=None):
    p = gp.Pipeline()
    if sim:
        source = gp.Generator(sampling_rate=config.UNICORN_FS, channel_count=8,
                              frame_size=25, signal_frequency=12.0,
                              signal_amplitude=5.0, noise_amplitude=10.0)
    else:
        # OSCAR artifact removal stays OFF: it would clean away the jaw clench.
        source = gp.HybridBlack(serial=serial, enable_oscar=False)
    decoder = DecoderNode()
    p.connect(source, decoder)                      # raw data to the decoder

    display = gp.Bandpass(f_lo=1, f_hi=30)          # filtered copy just for viewing
    scope = gp.TimeSeriesScope(amplitude_limit=50, time_window=10)
    p.connect(source, display)
    p.connect(display, scope)
    return p, scope


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sim", action="store_true", help="use g.Pype's Generator instead of the headset")
    ap.add_argument("--serial", help="Unicorn serial number, e.g. UN-2023.01.01 (default: first found)")
    args = ap.parse_args()

    app = gp.MainApp()
    pipeline, scope = build(sim=args.sim, serial=args.serial)
    app.add_widget(scope)
    pipeline.start()
    app.run()          # blocks until the window is closed
    pipeline.stop()
