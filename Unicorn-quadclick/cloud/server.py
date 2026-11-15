"""QuadClick cloud scanner: send a screenshot, get back boxes around every
button and icon. Runs on the rented server (see setup_server.sh).

It uses the box-finding half of Microsoft's OmniParser (the "icon_detect"
model) and skips the slow half that writes a description of each box.

    POST /detect      body = one JPEG or PNG image, header X-Key: <access key>
                      -> {"boxes": [[x, y, w, h, confidence], ...], "ms": ..., "device": ...}
    GET  /health      header X-Key -> {"ok": true, "device": ..., "model": ...}

Only HTTPS, and every request needs the access key from config.json.
"""
from __future__ import annotations

import hmac
import importlib.util
import io
import json
import os
import ssl
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = json.load(open(os.environ.get("QUADCLICK_CONFIG", os.path.join(HERE, "config.json"))))
MAX_BYTES = 15 * 1024 * 1024
REPO = "microsoft/OmniParser-v2.0"
LOCK = threading.Lock()                    # one scan at a time


class FakeDetector:
    """Stand-in used only for testing the plumbing (QUADCLICK_FAKE=1)."""
    name, device = "fake", "none"

    def detect(self, image, imgsz, conf):
        w, h = image.size
        return [[w * (0.1 + 0.2 * i), h * (0.2 + 0.25 * j), 48.0, 32.0, 0.9]
                for j in range(3) for i in range(4)]


class Detector:
    def __init__(self):
        import torch
        from huggingface_hub import hf_hub_download
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.model, self.name = None, ""
        errors = []
        # 1) the current detector (YOLOv9-E, MIT licence). Its small loader
        #    lives in the OmniParser repository that setup_server.sh cloned.
        loader = os.path.join(CONFIG.get("omniparser_dir", ""), "util", "yolov9.py")
        for revision in ("refs/pr/37", "main"):
            try:
                path = hf_hub_download(REPO, "icon_detect_v3/model.pt", revision=revision)
                spec = importlib.util.spec_from_file_location("omni_yolov9", loader)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                self.model = mod.YOLOv9Detector(model_path=path, device=self.device)
                self.name = f"icon_detect_v3 ({revision})"
                break
            except Exception as exc:
                errors.append(f"v3 {revision}: {exc!r}")
        # 2) fall back to the earlier detector (needs the ultralytics package)
        if self.model is None:
            try:
                from ultralytics import YOLO
                self.model = YOLO(hf_hub_download(REPO, "icon_detect/model.pt"))
                self.name = "icon_detect (ultralytics)"
            except Exception as exc:
                errors.append(f"v2: {exc!r}")
                raise RuntimeError("Could not load any detector:\n  " + "\n  ".join(errors))

    def detect(self, image, imgsz, conf):
        # OmniParser's own settings: keep weak boxes (0.05), merge overlaps hard (0.1)
        kw = dict(conf=conf, iou=0.1, imgsz=imgsz)
        if "ultralytics" in self.name:
            kw["verbose"] = False
        res = self.model.predict(image, **kw)[0]
        xyxy = res.boxes.xyxy.float().cpu().tolist()
        confs = res.boxes.conf.float().cpu().tolist()
        return [[x0, y0, x1 - x0, y1 - y0, c] for (x0, y0, x1, y1), c in zip(xyxy, confs)]


DETECTOR = None


class Handler(BaseHTTPRequestHandler):
    server_version = "QuadClickScan/1"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def reply(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        key = self.headers.get("X-Key", "")
        if hmac.compare_digest(key.encode(), CONFIG["key"].encode()):
            return True
        self.reply(401, {"error": "wrong or missing access key"})
        return False

    def do_GET(self):
        if not self.allowed():
            return
        if urlparse(self.path).path == "/health":
            self.reply(200, {"ok": True, "device": DETECTOR.device, "model": DETECTOR.name})
        else:
            self.reply(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():
            return
        url = urlparse(self.path)
        if url.path != "/detect":
            return self.reply(404, {"error": "not found"})
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if not 0 < n <= MAX_BYTES:
            return self.reply(413, {"error": "image missing or larger than 15 MB"})
        data = self.rfile.read(n)
        q = parse_qs(url.query)
        try:
            from PIL import Image
            image = Image.open(io.BytesIO(data)).convert("RGB")
            if max(image.size) > 4096:
                return self.reply(413, {"error": "image larger than 4096 pixels"})
            conf = min(0.9, max(0.01, float(q.get("conf", ["0.05"])[0])))
            longest = min(1920, max(320, int(q.get("imgsz", [str(max(image.size))])[0])))
            scale = longest / float(max(image.size))
            imgsz = (int(image.size[1] * scale), int(image.size[0] * scale))    # (height, width)
            t0 = time.time()
            with LOCK:
                boxes = DETECTOR.detect(image, imgsz, conf)
            ms = int((time.time() - t0) * 1000)
        except Exception as exc:
            return self.reply(500, {"error": repr(exc)})
        self.reply(200, {"boxes": [[round(v, 1) for v in b[:4]] + [round(b[4], 3)] for b in boxes],
                         "ms": ms, "device": DETECTOR.device, "model": DETECTOR.name,
                         "size": list(image.size)})


def main():
    global DETECTOR
    DETECTOR = FakeDetector() if os.environ.get("QUADCLICK_FAKE") else Detector()
    print(f"detector: {DETECTOR.name} on {DETECTOR.device}", flush=True)
    httpd = ThreadingHTTPServer((CONFIG.get("host", "0.0.0.0"), int(CONFIG["port"])), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(CONFIG["cert"], CONFIG["keyfile"])
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print(f"listening on port {CONFIG['port']} (HTTPS)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
