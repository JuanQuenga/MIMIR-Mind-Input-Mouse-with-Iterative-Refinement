"""Check the cloud scanner from this laptop: is the server reachable, and how
long does one scan of your screen take?

    python cloud_check.py
"""
import sys
import time

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QColor, QGuiApplication, QPixmap

from bci import cloud


def main():
    settings = cloud.load_settings()
    if not settings:
        sys.exit("cloud_settings.json is missing. Run 7_setup_vultr_server.bat first.")
    print(f"Server: {settings['host']} port {settings['port']}")
    try:
        t0 = time.perf_counter()
        info = cloud.health(settings)
        print(f"Reachable in {time.perf_counter() - t0:.1f} s. Model: {info.get('model')} "
              f"running on: {info.get('device')}")
    except Exception as exc:
        sys.exit(f"CANNOT REACH THE SERVER: {exc}\n"
                 "If this works at home but not at the venue, their network blocks it.")

    app = QGuiApplication(sys.argv[:1])
    shot = app.primaryScreen().grabWindow(0)
    if shot.isNull():
        shot = QPixmap(1920, 1080)
        shot.fill(QColor(220, 220, 220))
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    shot.save(buf, "JPG", 85)
    buf.close()
    print(f"Sending a picture of your screen ({shot.width()}x{shot.height()}, {len(data) // 1024} KB)...")
    for attempt in ("first scan", "second scan"):
        t0 = time.perf_counter()
        try:
            boxes, info = cloud.detect(bytes(data), settings, timeout=60)
        except Exception as exc:
            sys.exit(f"SCAN FAILED: {exc}")
        kept = cloud.tidy(boxes, shot.width(), shot.height())
        print(f"  {attempt}: {len(kept)} buttons/icons found (of {len(boxes)} raw) in "
              f"{time.perf_counter() - t0:.1f} s; the server's part was {info.get('ms')} ms")
    print("The cloud scanner works.")


if __name__ == "__main__":
    main()
