"""Shared settings. Everything the team is likely to tune lives here."""

# Flicker frequency (Hz) for each region, in order:
#   0 = upper left, 1 = upper right, 2 = lower left, 3 = lower right
# These match the g.tec SSVEP dataset so offline numbers carry over.
FREQS = (9.0, 10.0, 12.0, 15.0)

# Two-choice mode uses two of the four speeds. On the dataset every pair did
# about equally well; 9 and 15 Hz are the furthest apart.
BINARY_PAIR = (0, 3)

MAINS_HZ = 60.0            # 60 in the US, 50 in Europe (the g.tec dataset)

# Unicorn Hybrid Black channel order: Fz C3 Cz C4 Pz PO7 Oz PO8
UNICORN_FS = 250.0
UNICORN_SSVEP_CHANNELS = (4, 5, 6, 7)      # Pz, PO7, Oz, PO8 (back of head)

# g.tec SSVEP dataset channel order: PO7 PO3 POz PO4 PO8 O1 Oz O2
DATASET_FS = 256.0
DATASET_UNICORN_LIKE = (0, 6, 4)           # PO7, Oz, PO8 (what a Unicorn has)

# UDP: decoder -> overlay (commands) and overlay -> anyone (layout/clicks)
HOST = "127.0.0.1"
CMD_PORT = 5005
STATE_PORT = 5006

# SSVEP decision rule (evaluate_dataset.py shows how these behave on real data)
SSVEP = dict(
    windows=(2.0, 3.0, 4.0),  # s of data the decoder looks at (grows over time)
    step=0.25,          # s between evaluations
    thr_score=4.5,      # best target must be this far above idle (z units)
    thr_margin=2.0,     # ...and beat the runner-up by this much
    n_agree=2,          # ...on this many evaluations in a row
    settle=1.0,         # s ignored after the layout changes (eyes are moving)
)
CALIB_SECONDS = 40.0    # idle data collected at start-up (20 s gave more wrong picks)

# Jaw clench (muscle burst) detector
CLENCH = dict(
    band=(30.0, 100.0), # Hz; muscle activity lives here, EEG mostly does not
    win=0.15,           # s RMS window
    k=6.0,              # threshold = baseline median + k * MAD
    hold=0.30,          # s above threshold before it counts
    long=0.90,          # s; held this long = CLENCH_LONG, else CLENCH_SHORT
    refractory=1.0,     # s ignored after a clench
    baseline=5.0,       # s of quiet data used to learn the baseline
)
