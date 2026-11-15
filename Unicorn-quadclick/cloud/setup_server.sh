#!/usr/bin/env bash
# One-time setup of the QuadClick cloud scanner on a fresh Ubuntu server.
# Run as root:   bash /root/cloud/setup_server.sh
# Safe to run again (it keeps the same access key and certificate).
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo "Run this as root."; exit 1; fi
SRC="$(cd "$(dirname "$0")" && pwd)"
APP=/opt/quadclick
PORT=443
export DEBIAN_FRONTEND=noninteractive

echo "== 1/6 system packages"
apt-get update -y
apt-get install -y python3-venv python3-pip git openssl curl

echo "== 2/6 program files"
id quadclick >/dev/null 2>&1 || useradd --system --create-home --home-dir "$APP" --shell /usr/sbin/nologin quadclick
mkdir -p "$APP"
cp "$SRC/server.py" "$APP/server.py"
[ -d "$APP/OmniParser/.git" ] || git clone --depth 1 https://github.com/microsoft/OmniParser "$APP/OmniParser"
[ -x "$APP/venv/bin/python" ] || python3 -m venv "$APP/venv"

echo "== 3/6 Python packages (PyTorch is a large download: several minutes)"
"$APP/venv/bin/pip" install --upgrade pip
"$APP/venv/bin/pip" install torch torchvision huggingface_hub pillow numpy

echo "== 4/6 access key and certificate"
if [ ! -f "$APP/config.json" ]; then
  KEY="$(openssl rand -hex 24)"
  openssl req -x509 -newkey rsa:2048 -nodes -days 60 -subj "/CN=quadclick" \
    -keyout "$APP/key.pem" -out "$APP/cert.pem" >/dev/null 2>&1
  cat > "$APP/config.json" <<JSON
{"key": "$KEY", "port": $PORT, "cert": "$APP/cert.pem", "keyfile": "$APP/key.pem",
 "omniparser_dir": "$APP/OmniParser"}
JSON
fi
KEY="$(python3 -c "import json;print(json.load(open('$APP/config.json'))['key'])")"
FINGERPRINT="$(openssl x509 -in "$APP/cert.pem" -noout -fingerprint -sha256 | cut -d= -f2 | tr -d ':' | tr 'A-F' 'a-f')"
IP="$(curl -4 -s --max-time 5 https://ifconfig.me || hostname -I | awk '{print $1}')"
cat > "$APP/laptop_settings.json" <<JSON
{"host": "$IP", "port": $PORT, "key": "$KEY", "fingerprint": "$FINGERPRINT"}
JSON
chown -R quadclick:quadclick "$APP"
chmod 600 "$APP/config.json" "$APP/key.pem" "$APP/laptop_settings.json"

echo "== 5/6 download the model and start the service"
if ! runuser -u quadclick -- env HOME="$APP" "$APP/venv/bin/python" - <<'PY'
from huggingface_hub import hf_hub_download
ok = False
for rev in ("refs/pr/37", "main"):
    try:
        print("model file:", hf_hub_download("microsoft/OmniParser-v2.0", "icon_detect_v3/model.pt", revision=rev)); ok = True; break
    except Exception as exc:
        print("  not at", rev, "-", type(exc).__name__)
raise SystemExit(0 if ok else 1)
PY
then
  echo "   newest detector not available, installing the earlier one"
  "$APP/venv/bin/pip" install "ultralytics==8.3.70"
fi
cat > /etc/systemd/system/quadclick.service <<UNIT
[Unit]
Description=QuadClick cloud scanner
After=network-online.target

[Service]
User=quadclick
Environment=HOME=$APP
WorkingDirectory=$APP
ExecStart=$APP/venv/bin/python $APP/server.py
AmbientCapabilities=CAP_NET_BIND_SERVICE
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable quadclick >/dev/null 2>&1
systemctl restart quadclick
command -v ufw >/dev/null 2>&1 && ufw allow "$PORT/tcp" >/dev/null 2>&1 || true

echo "== 6/6 self-test (waiting for the model to load, up to 3 minutes)"
OK=0
for i in $(seq 1 60); do
  if curl -sk --max-time 5 -H "X-Key: $KEY" "https://127.0.0.1:$PORT/health" | grep -q '"ok": true'; then OK=1; break; fi
  sleep 3
done
if [ "$OK" -ne 1 ]; then
  echo; echo "THE SERVICE DID NOT START. Last log lines:"; journalctl -u quadclick -n 30 --no-pager; exit 1
fi
"$APP/venv/bin/python" - <<'PY' > /tmp/quadclick_test.png
import sys
from PIL import Image, ImageDraw
im = Image.new("RGB", (1920, 1080), (240, 240, 240)); d = ImageDraw.Draw(im)
for i in range(8):
    d.rounded_rectangle((100 + 150 * i, 200, 220 + 150 * i, 240), 6, fill=(0, 120, 215)); d.text((120 + 150 * i, 212), f"Button {i}", fill="white")
im.save(sys.stdout.buffer, "PNG")
PY
echo "health: $(curl -sk -H "X-Key: $KEY" "https://127.0.0.1:$PORT/health")"
echo "test scan (first is slow): $(curl -sk -H "X-Key: $KEY" --data-binary @/tmp/quadclick_test.png "https://127.0.0.1:$PORT/detect" | cut -c1-160)..."
echo "second scan: $(curl -sk -H "X-Key: $KEY" --data-binary @/tmp/quadclick_test.png "https://127.0.0.1:$PORT/detect" | grep -o '"ms": [0-9]*')"
if command -v nvidia-smi >/dev/null 2>&1; then echo "graphics card: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"; else echo "graphics card: none found (scans run on the processor and will be slower)"; fi
echo
echo "DONE. Settings for the laptop are in $APP/laptop_settings.json"
