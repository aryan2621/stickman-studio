"""Send to phone: a QR code that opens the finished video on a phone on the same Wi-Fi.

The Mac serves the one video over the local network, nothing goes through the internet: a small
page with the video and a Download button, and the file itself (with range requests, which
phones need to play video). The link carries a random key and works for that video only; it stops
when the user closes the dialog, after 15 minutes, or when the app quits.
"""

import html
import io
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

import segno

LIFETIME = 15 * 60


def _interfaces(active_only: bool = True) -> list[tuple[str, str]]:
    """(interface, IPv4 address) for every interface with an address (VPN tunnels report no
    "status" line, so `active_only=False` includes them)."""
    import re
    import subprocess

    out = subprocess.run(["ifconfig"], capture_output=True, text=True).stdout
    found, name, active, addresses = [], None, False, []
    for line in out.splitlines() + ["end:"]:
        header = re.match(r"^(\S+):", line)
        if header:
            if name and (active or not active_only):
                found += [(name, a) for a in addresses]
            name, active, addresses = header.group(1), False, []
            continue
        if "status: active" in line:
            active = True
        inet = re.search(r"\binet (\d+\.\d+\.\d+\.\d+)", line)
        if inet:
            addresses.append(inet.group(1))
    return found


def lan_ip() -> tuple[str, str]:
    """This Mac's address on the local Wi-Fi or Ethernet, the one a phone on the same network can
    reach, and the interface it's on. VPN tunnels (utun, ipsec, ppp) are skipped: a VPN is often
    the default route, but its address is useless to a phone in the same room."""
    usable = [
        (iface, ip) for iface, ip in _interfaces()
        if iface.startswith("en") and not ip.startswith(("127.", "169.254."))
    ]
    if not usable:
        raise RuntimeError("This Mac isn’t on Wi-Fi or Ethernet. Connect it to the same Wi-Fi as your phone.")
    # Prefer the usual home ranges, then the lowest interface number (en0 is Wi-Fi on a MacBook).
    usable.sort(key=lambda x: (not x[1].startswith(("192.168.", "172.", "10.")), int(x[0][2:] or 0) if x[0][2:].isdigit() else 99))
    iface, ip = usable[0]
    return ip, iface


def vpn_active() -> bool:
    return any(iface.startswith(("utun", "ipsec", "ppp")) and not ip.startswith("169.254.") for iface, ip in _interfaces(active_only=False))


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{margin:0;font:16px -apple-system,system-ui,sans-serif;background:#1f1e1d;color:#f5f4ef;text-align:center}}
main{{max-width:520px;margin:0 auto;padding:20px 16px 40px}}
h1{{font-size:20px;font-weight:600;margin:6px 0 14px}}
video{{width:100%;max-height:70vh;border-radius:14px;background:#000}}
a.button{{display:block;margin:18px 0 10px;padding:15px;border-radius:12px;background:#d97757;color:#fff;
text-decoration:none;font-weight:600;font-size:17px}}
p{{color:#c2c0b6;font-size:14px;line-height:1.45;margin:6px 0}}
</style></head><body><main>
<h1>{title}</h1>
<video src="{video}" controls playsinline preload="metadata"></video>
<a class="button" href="{video}?download=1" download="{filename}">Download video</a>
<p>iPhone: tap <b>Download video</b>, then open it from the ⬇︎ downloads in Safari and choose
<b>Share → Save Video</b> to put it in Photos.</p>
<p>Android: tap <b>Download video</b>; it goes to your Downloads.</p>
</main></body></html>"""


class Share:
    def __init__(self, emit):
        self.emit = emit
        self.lock = threading.Lock()
        self.server: ThreadingHTTPServer | None = None
        self.timer: threading.Timer | None = None

    def start(self, video: Path, title: str) -> dict:
        self.stop()
        if not video.exists():
            raise ValueError("Make the video first")
        token = secrets.token_urlsafe(12)
        filename = (title.strip() or "video") + ".mp4"
        size = video.stat().st_size
        share = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep the engine's output clean
                pass

            def do_GET(self):
                path = self.path.split("?", 1)[0]
                if path in (f"/{token}", f"/{token}/"):
                    return self._page()
                if path == f"/{token}/video.mp4":
                    return self._video()
                self.send_error(404)

            def _page(self):
                body = PAGE.format(title=html.escape(title), video=f"/{token}/video.mp4", filename=html.escape(filename)).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                share.emit("share", {"state": "opened"})

            def _video(self):
                start, end = 0, size - 1
                ranged = self.headers.get("Range", "")
                if ranged.startswith("bytes="):
                    first, _, last = ranged[6:].split(",")[0].partition("-")
                    if first:
                        start = int(first)
                        end = int(last) if last else end
                    elif last:  # the last N bytes
                        start = max(0, size - int(last))
                    end = min(end, size - 1)
                    if start > end:
                        self.send_error(416)
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                else:
                    self.send_response(200)
                self.send_header("Content-Type", "video/mp4")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(end - start + 1))
                if "download=1" in self.path:
                    self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
                self.end_headers()
                if self.command == "HEAD":
                    return
                with open(video, "rb") as f:
                    f.seek(start)
                    remaining = end - start + 1
                    try:
                        while remaining > 0:
                            chunk = f.read(min(1 << 20, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        return  # the phone stopped reading (seeking, or closed)
                if "download=1" in self.path and remaining == 0:
                    share.emit("share", {"state": "downloaded"})

            do_HEAD = do_GET

        ip, iface = lan_ip()
        server = ThreadingHTTPServer(("0.0.0.0", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        url = f"http://{ip}:{server.server_address[1]}/{token}/"
        with self.lock:
            self.server = server
            self.timer = threading.Timer(LIFETIME, self.stop)
            self.timer.daemon = True
            self.timer.start()
        try:
            out = io.BytesIO()
            segno.make(url, error="m").save(out, kind="svg", scale=6, border=2, dark="#1f1e1d", light="#ffffff", xmldecl=False)
        except Exception:
            self.stop()
            raise
        return {"url": url, "qr": out.getvalue().decode(), "expiresAt": time.time() + LIFETIME,
                "network": iface, "vpn": vpn_active()}

    def stop(self):
        with self.lock:
            server, self.server = self.server, None
            if self.timer:
                self.timer.cancel()
                self.timer = None
        if server:
            server.shutdown()
            server.server_close()
