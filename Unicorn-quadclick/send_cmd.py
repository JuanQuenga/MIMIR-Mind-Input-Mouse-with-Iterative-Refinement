"""Send a command to the overlay by hand, e.g. to test it with no headset.

    python send_cmd.py KEY 2            # pick the box labelled 2
    python send_cmd.py SEL 3            # pick the box flickering at speed 3 (as the decoder does)
    python send_cmd.py CLENCH_SHORT     # undo
    python send_cmd.py            # interactive: type commands, Enter to send
"""
import sys

from bci import config
from bci.net import Link

link = Link(send_port=config.CMD_PORT)
if len(sys.argv) > 1:
    link.send(" ".join(sys.argv[1:]))
else:
    print("Commands: KEY 1..4 | UNDO | HOME | PAUSE | CHOICES | MODE | QUIT   (Ctrl+C to exit)")
    while True:
        link.send(input("> ").strip().upper())
