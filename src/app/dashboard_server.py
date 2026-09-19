"""Local dashboard HTTP server.

Serves the static frontend from `src/web/`, exposes the newest annotated
frame as an MJPEG stream at `/stream.mjpg`, and returns the live session
state as JSON at `/api/state`. Runs a `ThreadingHTTPServer` in a daemon
thread so the notebook loop can push frames without blocking on client
I/O.

The pipeline is the producer:
    STATE.push_frame(jpeg_bytes)
    STATE.set_state({...})
The browser is the consumer. Producing at 15fps and consuming at 15fps
keeps the loop lean; when the browser cannot keep up, its MJPEG parser
drops on its side, not ours.
"""
from __future__ import annotations

import http.server
import json
import socket
import socketserver
import threading
import time
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"

_BOUNDARY = "physiolivemjpeg"


class _State:
    """Process-wide, thread-safe live-session state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._frame_jpeg: Optional[bytes] = None
        self._frame_seq: int = 0
        self._state: dict = {}
        self._frame_event = threading.Condition(self._lock)

    def push_frame(self, jpeg_bytes: bytes) -> None:
        with self._frame_event:
            self._frame_jpeg = jpeg_bytes
            self._frame_seq += 1
            self._frame_event.notify_all()

    def wait_for_frame(self, last_seq: int, timeout: float = 1.0):
        with self._frame_event:
            if self._frame_seq == last_seq:
                self._frame_event.wait(timeout=timeout)
            return self._frame_jpeg, self._frame_seq

    def set_state(self, payload: dict) -> None:
        with self._lock:
            self._state = dict(payload)

    def get_state(self) -> dict:
        with self._lock:
            return dict(self._state)


STATE = _State()


class _Handler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, fmt: str, *args) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Cache-Control",
                         "no-store, no-cache, must-revalidate, max-age=0")
        super().end_headers()

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/stream.mjpg":
            self._mjpeg_stream()
            return
        if path == "/api/state":
            self._send_json(200, STATE.get_state())
            return
        if path == "/api/ping":
            self._send_json(200, {"ok": True})
            return
        super().do_GET()

    def _mjpeg_stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type",
                         f"multipart/x-mixed-replace; boundary={_BOUNDARY}")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Pragma", "no-cache")
        super().end_headers()
        last_seq = -1
        try:
            while True:
                jpeg, seq = STATE.wait_for_frame(last_seq, timeout=2.0)
                if jpeg is None:
                    time.sleep(0.05)
                    continue
                if seq == last_seq:
                    continue
                last_seq = seq
                head = (f"--{_BOUNDARY}\r\n"
                        f"Content-Type: image/jpeg\r\n"
                        f"Content-Length: {len(jpeg)}\r\n\r\n").encode("ascii")
                try:
                    self.wfile.write(head)
                    self.wfile.write(jpeg)
                    self.wfile.write(b"\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    return
        except Exception:
            return

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()
        self.wfile.write(body)


def _handler_factory(directory: Path):
    d = str(directory)
    return lambda *a, **k: _Handler(*a, directory=d, **k)


def port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("", port))
            return True
        except OSError:
            return False


class DashboardServer:
    """Threaded HTTP server wrapper. Call `.start()` from the notebook."""

    def __init__(self, port: int = 8000,
                 directory: Optional[Path] = None) -> None:
        self.port = port
        self.directory = directory or WEB_DIR
        self._httpd: Optional[socketserver.ThreadingMixIn] = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> str:
        if not self.directory.is_dir():
            raise RuntimeError(f"web/ folder not found at {self.directory}")
        if not port_is_free(self.port):
            for cand in range(self.port + 1, self.port + 21):
                if port_is_free(cand):
                    self.port = cand
                    break
            else:
                raise RuntimeError(f"no free port near {self.port}")
        http.server.ThreadingHTTPServer.allow_reuse_address = True
        http.server.ThreadingHTTPServer.daemon_threads = True
        self._httpd = http.server.ThreadingHTTPServer(
            ("", self.port), _handler_factory(self.directory))
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True,
                                        name="dashboard-server")
        self._thread.start()
        return f"http://localhost:{self.port}/"

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
