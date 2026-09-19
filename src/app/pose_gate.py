"""Pose estimation gate.

Wraps YOLOv8s-pose (Ultralytics, OpenVINO-accelerated when the sibling
`*_openvino_model` directory is present) and MediaPipe Pose as an
alternative backend. Exposes COCO-17 keypoint constants and a single
`infer(frame)` call that returns the highest-confidence person's
keypoints for the frame, or `None` when nothing is visible.

Design constraints kept from the YOLO26 project:
- Same COCO-17 index layout.
- KP_MIN_CONF = 0.30 gate so bad joints do not fire form rules.
- Lazy load behind a lock so parallel first-frame calls do not race.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

import numpy as np

KP_MIN_CONF = 0.30
POSE_CONF = 0.25

KEYPOINT_NAMES = (
    "nose", "left_eye", "right_eye", "left_ear", "right_ear",
    "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
    "left_wrist", "right_wrist", "left_hip", "right_hip",
    "left_knee", "right_knee", "left_ankle", "right_ankle",
)

NOSE = 0
L_EYE, R_EYE = 1, 2
L_EAR, R_EAR = 3, 4
L_SHOULDER, R_SHOULDER = 5, 6
L_ELBOW, R_ELBOW = 7, 8
L_WRIST, R_WRIST = 9, 10
L_HIP, R_HIP = 11, 12
L_KNEE, R_KNEE = 13, 14
L_ANKLE, R_ANKLE = 15, 16

_C_HEAD = (0, 215, 255)
_C_TORSO = (230, 66, 168)
_C_ARM_R = (80, 220, 80)
_C_ARM_L = (255, 170, 0)
_C_LEG_R = (60, 100, 255)
_C_LEG_L = (255, 255, 0)

_BONE_GROUPS = (
    (((NOSE, L_EYE), (NOSE, R_EYE), (L_EYE, L_EAR), (R_EYE, R_EAR)), _C_HEAD),
    (((NOSE, L_SHOULDER), (NOSE, R_SHOULDER),
      (L_SHOULDER, R_SHOULDER), (L_SHOULDER, L_HIP),
      (R_SHOULDER, R_HIP), (L_HIP, R_HIP)), _C_TORSO),
    (((R_SHOULDER, R_ELBOW), (R_ELBOW, R_WRIST)), _C_ARM_R),
    (((L_SHOULDER, L_ELBOW), (L_ELBOW, L_WRIST)), _C_ARM_L),
    (((R_HIP, R_KNEE), (R_KNEE, R_ANKLE)), _C_LEG_R),
    (((L_HIP, L_KNEE), (L_KNEE, L_ANKLE)), _C_LEG_L),
)

_KP_COLORS: dict = {i: _C_HEAD for i in (NOSE, L_EYE, R_EYE, L_EAR, R_EAR)}
_KP_COLORS.update({i: _C_TORSO for i in (L_SHOULDER, R_SHOULDER, L_HIP, R_HIP)})
_KP_COLORS.update({
    L_ELBOW: _C_ARM_L, L_WRIST: _C_ARM_L,
    R_ELBOW: _C_ARM_R, R_WRIST: _C_ARM_R,
    L_KNEE: _C_LEG_L, L_ANKLE: _C_LEG_L,
    R_KNEE: _C_LEG_R, R_ANKLE: _C_LEG_R,
})

POSE_WEIGHTS_DEFAULT = "yolov8s-pose.pt"

_yolo_model = None
_mp_pose = None
_LOAD_LOCK = threading.Lock()


def _load_yolo(weights: Optional[str] = None):
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model
    with _LOAD_LOCK:
        if _yolo_model is None:
            from ultralytics import YOLO
            w = weights or os.environ.get("POSE_WEIGHTS", POSE_WEIGHTS_DEFAULT)
            if str(w).endswith(".pt"):
                ov_dir = str(w)[:-3] + "_openvino_model"
                if os.path.isdir(ov_dir):
                    w = ov_dir
                    print(f"pose: OpenVINO engine loaded ({ov_dir})")
            _yolo_model = YOLO(w)
    return _yolo_model


def _load_mediapipe():
    global _mp_pose
    if _mp_pose is not None:
        return _mp_pose
    with _LOAD_LOCK:
        if _mp_pose is None:
            import mediapipe as mp
            _mp_pose = mp.solutions.pose.Pose(
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                model_complexity=1,
            )
    return _mp_pose


_MP_TO_COCO17 = {
    0: 0, 2: 1, 5: 2, 7: 3, 8: 4,
    11: 5, 12: 6, 13: 7, 14: 8, 15: 9, 16: 10,
    23: 11, 24: 12, 25: 13, 26: 14, 27: 15, 28: 16,
}


class PoseInferencer:
    """Backend-agnostic single-person pose inferencer.

    `backend="yolo"` uses YOLOv8s-pose (OpenVINO when available) at
    `imgsz=384` for a fair CPU speed/accuracy trade. `backend="mediapipe"`
    uses MediaPipe's Full model and remaps 33 keypoints to COCO-17.
    """

    def __init__(self, backend: str = "yolo", imgsz: int = 384) -> None:
        self.backend = backend
        self.imgsz = imgsz
        if backend == "yolo":
            _load_yolo()
        elif backend == "mediapipe":
            _load_mediapipe()
        else:
            raise ValueError(f"unknown pose backend: {backend!r}")

    def infer(self, frame_bgr) -> Optional[list]:
        """Return `[[x, y, conf], ...]` for 17 COCO joints, or None."""
        if self.backend == "yolo":
            return self._infer_yolo(frame_bgr)
        return self._infer_mediapipe(frame_bgr)

    def _infer_yolo(self, frame_bgr) -> Optional[list]:
        model = _load_yolo()
        results = model.predict(frame_bgr, imgsz=self.imgsz, conf=POSE_CONF,
                                verbose=False)
        if not results:
            return None
        res = results[0]
        if res.keypoints is None or res.boxes is None or len(res.boxes) == 0:
            return None
        confs = [float(c) for c in res.boxes.conf.tolist()]
        best = max(range(len(confs)), key=confs.__getitem__)
        return [[round(x, 1), round(y, 1), round(c, 3)]
                for x, y, c in res.keypoints.data.tolist()[best]]

    def _infer_mediapipe(self, frame_bgr) -> Optional[list]:
        import cv2
        pose = _load_mediapipe()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = pose.process(rgb)
        if not result.pose_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        landmarks = result.pose_landmarks.landmark
        out = [[0.0, 0.0, 0.0] for _ in range(17)]
        for mp_i, coco_i in _MP_TO_COCO17.items():
            lm = landmarks[mp_i]
            out[coco_i] = [lm.x * w, lm.y * h,
                           getattr(lm, "visibility", 1.0)]
        return out


def draw_skeleton(img, kps, min_conf: float = KP_MIN_CONF):
    """Draw the skeleton in-place onto `img`, returning it."""
    if not kps:
        return img
    import cv2
    for edges, _color in _BONE_GROUPS:
        for i, j in edges:
            xi, yi, ci = kps[i]
            xj, yj, cj = kps[j]
            if ci < min_conf or cj < min_conf:
                continue
            cv2.line(img, (int(xi), int(yi)), (int(xj), int(yj)),
                     (20, 20, 20), 5, cv2.LINE_AA)
    for edges, color in _BONE_GROUPS:
        for i, j in edges:
            xi, yi, ci = kps[i]
            xj, yj, cj = kps[j]
            if ci < min_conf or cj < min_conf:
                continue
            cv2.line(img, (int(xi), int(yi)), (int(xj), int(yj)),
                     color, 3, cv2.LINE_AA)
    for idx, (x, y, c) in enumerate(kps):
        if c >= min_conf:
            col = _KP_COLORS.get(idx, (255, 255, 255))
            center = (int(x), int(y))
            cv2.circle(img, center, 5, (255, 255, 255), 1, cv2.LINE_AA)
            cv2.circle(img, center, 4, col, -1, cv2.LINE_AA)
    return img
