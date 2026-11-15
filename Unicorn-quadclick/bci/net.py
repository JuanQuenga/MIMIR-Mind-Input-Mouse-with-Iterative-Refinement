"""Tiny UDP helpers. Messages are short text lines such as "SEL 2 4.10"."""
from __future__ import annotations

import socket

from . import config


class Link:
    """Send to one port, listen (without blocking) on another."""

    def __init__(self, send_port, listen_port=None, host=config.HOST):
        self.target = (host, send_port)
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.inp = None
        if listen_port:
            self.inp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):       # Windows
                self.inp.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                self.inp.bind((host, listen_port))
            except OSError:
                raise SystemExit(
                    f"\nPort {listen_port} is already in use: another copy of this "
                    "program is still running.\nClose the old QuadClick windows "
                    "(or run 0_stop_all.bat) and start again.\n")
            self.inp.setblocking(False)

    def send(self, msg: str):
        self.out.sendto(msg.encode(), self.target)

    def poll(self) -> list[str]:
        msgs = []
        while self.inp:
            try:
                msgs.append(self.inp.recv(4096).decode(errors="replace").strip())
            except (BlockingIOError, ConnectionResetError):
                break
        return msgs

    def close(self):
        self.out.close()
        if self.inp:
            self.inp.close()
