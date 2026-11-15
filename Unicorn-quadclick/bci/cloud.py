"""Laptop side of the cloud scanner: send a screenshot to the rented server
and get back boxes around every button and icon (see cloud/server.py).

The connection is encrypted, and the server's certificate is checked against
the fingerprint in cloud_settings.json, so the screenshot only ever goes to
your own server.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import ssl

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "cloud_settings.json")


def load_settings(path=SETTINGS_FILE):
    """dict(host, port, key, fingerprint), or None if the file is missing/broken."""
    try:
        with open(path, encoding="utf-8") as fh:
            s = json.load(fh)
        if all(s.get(k) for k in ("host", "port", "key", "fingerprint")):
            return s
        print(f"{path} is incomplete (needs host, port, key, fingerprint)", flush=True)
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"Could not read {path}: {exc!r}", flush=True)
    return None


def _request(settings, method, path, body=None, timeout=12.0):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False                 # self-signed: we check the fingerprint instead
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(settings["host"], int(settings["port"]),
                                       timeout=timeout, context=ctx)
    try:
        conn.connect()
        seen = hashlib.sha256(conn.sock.getpeercert(binary_form=True)).hexdigest()
        wanted = settings["fingerprint"].replace(":", "").lower()
        if seen != wanted:
            raise ConnectionError("the server's certificate does not match cloud_settings.json; "
                                  "nothing was sent")
        headers = {"X-Key": settings["key"]}
        if body is not None:
            headers["Content-Type"] = "application/octet-stream"
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = json.loads(resp.read().decode() or "{}")
        if resp.status != 200:
            raise ConnectionError(f"server said {resp.status}: {data.get('error', '?')}")
        return data
    finally:
        conn.close()


def health(settings, timeout=6.0):
    return _request(settings, "GET", "/health", timeout=timeout)


def detect(image_bytes, settings, timeout=12.0, conf=0.05, imgsz=None):
    """Returns (boxes, info). boxes = [(x, y, w, h, confidence)] in image pixels.
    imgsz: the server resizes the picture so its longer side is this many
    pixels before looking (up to 1920). Bigger finds smaller things."""
    path = f"/detect?conf={conf}" + (f"&imgsz={int(imgsz)}" if imgsz else "")
    data = _request(settings, "POST", path, body=image_bytes, timeout=timeout)
    return [tuple(b) for b in data.get("boxes", [])], data


def tidy(boxes, width, height, max_items=200, min_side=8.0, max_share=0.30):
    """Drop boxes that are tiny, cover a big part of the screen, or sit
    (almost) inside a better one; keep the most confident."""
    out = []
    for x, y, w, h, c in sorted(boxes, key=lambda b: -b[4]):
        if w < min_side or h < min_side or w * h > max_share * width * height:
            continue
        cx, cy = x + w / 2.0, y + h / 2.0
        if any(ox <= cx <= ox + ow and oy <= cy <= oy + oh for ox, oy, ow, oh in out):
            continue                            # its middle is inside a box we already kept
        out.append((x, y, w, h))
        if len(out) >= max_items:
            break
    return out


def merge(base, extra):
    """Add the rectangles in `extra` that don't overlap one already in `base`
    (neither one's middle lies inside the other)."""
    out = list(base)
    for e in extra:
        ex, ey = e[0] + e[2] / 2.0, e[1] + e[3] / 2.0
        clash = False
        for b in out:
            bx, by = b[0] + b[2] / 2.0, b[1] + b[3] / 2.0
            if (b[0] <= ex <= b[0] + b[2] and b[1] <= ey <= b[1] + b[3]) or \
               (e[0] <= bx <= e[0] + e[2] and e[1] <= by <= e[1] + e[3]):
                clash = True
                break
        if not clash:
            out.append(e)
    return out
