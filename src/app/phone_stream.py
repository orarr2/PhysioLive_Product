"""Video-source resolver.

Accepts one of:
- integer camera index (0, 1, ...) for a local webcam
- HTTP/HTTPS URL for an IP-Webcam / DroidCam-style MJPEG stream
- RTSP URL
- filesystem path to a video file

Returns an `cv2.VideoCapture` with `BUFFERSIZE=1` where possible so we
always read the newest frame instead of a stale one from the driver
buffer. When the source is a network URL, `probe_latency()` measures the
average round-trip so the caller can warn the user before the session
starts.
"""
from __future__ import annotations

import time
from typing import List, Optional, Union


def open_source(source: Union[int, str], width: int = 1280,
                height: int = 720, fps: int = 30):
    import cv2
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open source: {source!r}")
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass
    if isinstance(source, int):
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap


def list_local_cameras(max_index: int = 4) -> List[dict]:
    """Scan camera indices 0..max_index and report the ones that open.

    Each entry: {'index', 'width', 'height', 'fps'}. Used by the
    notebook's source selection cell.
    """
    import cv2
    out = []
    for i in range(max_index + 1):
        cap = cv2.VideoCapture(i)
        try:
            if not cap.isOpened():
                continue
            ok, _ = cap.read()
            if not ok:
                continue
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
            out.append({"index": i, "width": width, "height": height,
                        "fps": round(fps, 1)})
        finally:
            cap.release()
    return out


def phone_url_from_ip(ip: str, port: int = 8080,
                      path: str = "/video") -> str:
    """Build the http URL for the common IP-Webcam / DroidCam layout."""
    return f"http://{ip}:{port}{path}"


def probe_latency(cap, samples: int = 5) -> float:
    """Rough round-trip in milliseconds. Reads `samples` frames back-to-back
    and returns the average inter-frame gap. Useful for phone streams;
    over 300ms means the user should switch to a faster connection."""
    times = []
    for _ in range(max(1, samples)):
        t0 = time.perf_counter()
        ok, _ = cap.read()
        if not ok:
            break
        times.append((time.perf_counter() - t0) * 1000.0)
    if not times:
        return float("inf")
    return sum(times) / len(times)


def latency_verdict(ms: float) -> str:
    """Human-friendly reading of the number `probe_latency` returned."""
    if ms == float("inf"):
        return "no frames returned"
    if ms < 60:
        return "excellent (below 60 ms)"
    if ms < 120:
        return "good (60-120 ms)"
    if ms < 300:
        return "usable (120-300 ms)"
    return "poor (over 300 ms; switch to Wi-Fi 5 GHz or USB tethering)"
