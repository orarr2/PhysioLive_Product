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
from typing import Union


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
