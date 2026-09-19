"""Pose estimation gate.

Runs one of three backends and returns a rich landmark dict:

- `mediapipe_holistic` (default): 33 body landmarks, 21 landmarks per
  hand (full finger articulation), plus a virtual neck point drawn
  between the shoulders. Best coverage.
- `mediapipe_pose`: 33 body landmarks only (no hands).
- `yolo`: 17 COCO landmarks via YOLOv8-pose (OpenVINO-preferred).
  Fastest CPU option; body only.

Every backend also fills a `coco17` list so downstream angle math works
identically regardless of which backend produced the frame.

The KP_MIN_CONF gate keeps a joint out of the drawing and rules pipeline
when its detection confidence is below 0.30, so a badly-occluded wrist
does not fire a form rule.
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from typing import List, Optional

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

# BGR colors, one per anatomical region. Warm palette for the right side,
# cool palette for the left side, so a crossed-limb frame stays readable.
_C_HEAD = (0, 215, 255)     # golden
_C_TORSO = (230, 66, 168)   # violet
_C_ARM_R = (80, 220, 80)    # green
_C_ARM_L = (255, 170, 0)    # azure
_C_LEG_R = (60, 100, 255)   # orange-red
_C_LEG_L = (255, 255, 0)    # cyan
_C_NECK = (255, 220, 180)   # pale blue
_C_HAND_THUMB = (60, 120, 255)
_C_HAND_INDEX = (0, 200, 255)
_C_HAND_MIDDLE = (0, 255, 200)
_C_HAND_RING = (255, 180, 0)
_C_HAND_PINKY = (255, 80, 180)
_C_HAND_PALM = (220, 220, 220)

POSE_WEIGHTS_DEFAULT = "yolov8s-pose.pt"

# ---- MediaPipe pose constants (33 landmarks) --------------------------
MP_POSE_L_SHOULDER, MP_POSE_R_SHOULDER = 11, 12
MP_POSE_L_ELBOW, MP_POSE_R_ELBOW = 13, 14
MP_POSE_L_WRIST, MP_POSE_R_WRIST = 15, 16
MP_POSE_L_HIP, MP_POSE_R_HIP = 23, 24
MP_POSE_L_KNEE, MP_POSE_R_KNEE = 25, 26
MP_POSE_L_ANKLE, MP_POSE_R_ANKLE = 27, 28
MP_POSE_NOSE = 0

# MediaPipe pose body connections grouped by region.
_MP_BODY_GROUPS = (
    # Face outline
    (((0, 1), (1, 2), (2, 3), (3, 7), (0, 4), (4, 5), (5, 6), (6, 8),
      (9, 10)), _C_HEAD),
    # Torso trunk
    (((11, 12), (11, 23), (12, 24), (23, 24)), _C_TORSO),
    # Left arm and hand-in-pose (shoulder to thumb/index/pinky tips)
    (((11, 13), (13, 15), (15, 17), (15, 19), (15, 21), (17, 19)),
     _C_ARM_L),
    # Right arm and hand-in-pose
    (((12, 14), (14, 16), (16, 18), (16, 20), (16, 22), (18, 20)),
     _C_ARM_R),
    # Left leg and foot
    (((23, 25), (25, 27), (27, 29), (29, 31), (27, 31)), _C_LEG_L),
    # Right leg and foot
    (((24, 26), (26, 28), (28, 30), (30, 32), (28, 32)), _C_LEG_R),
)

# 21-landmark hand skeleton (MediaPipe convention).
#   0        wrist
#   1..4     thumb (CMC, MCP, IP, tip)
#   5..8     index (MCP, PIP, DIP, tip)
#   9..12    middle
#   13..16   ring
#   17..20   pinky
_HAND_GROUPS = (
    (((0, 1), (1, 2), (2, 3), (3, 4)), _C_HAND_THUMB),
    (((0, 5), (5, 6), (6, 7), (7, 8)), _C_HAND_INDEX),
    (((9, 10), (10, 11), (11, 12)), _C_HAND_MIDDLE),
    (((13, 14), (14, 15), (15, 16)), _C_HAND_RING),
    (((17, 18), (18, 19), (19, 20)), _C_HAND_PINKY),
    # Palm cross-links so the hand reads as a solid shape.
    (((5, 9), (9, 13), (13, 17), (0, 17)), _C_HAND_PALM),
)

# Mapping from MediaPipe pose 33 landmarks to legacy COCO-17 indices,
# so downstream angle math sees a single canonical layout.
_MP_TO_COCO17 = {
    0: 0, 2: 1, 5: 2, 7: 3, 8: 4,
    11: 5, 12: 6, 13: 7, 14: 8, 15: 9, 16: 10,
    23: 11, 24: 12, 25: 13, 26: 14, 27: 15, 28: 16,
}


@dataclass
class PoseFrame:
    """Rich pose result for a single frame."""

    coco17: List[List[float]] = field(default_factory=list)
    body33: Optional[List[List[float]]] = None
    hand_left: Optional[List[List[float]]] = None
    hand_right: Optional[List[List[float]]] = None


# ---- Lazy backend holders ---------------------------------------------
_yolo_model = None
_mp_pose = None
_mp_holistic = None
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


def _load_mp_pose():
    global _mp_pose
    if _mp_pose is not None:
        return _mp_pose
    with _LOAD_LOCK:
        if _mp_pose is None:
            import mediapipe as mp
            if not hasattr(mp, "solutions"):
                raise RuntimeError(
                    "The installed mediapipe build does not include the "
                    "legacy solutions API. Install a compatible version "
                    "(`pip install mediapipe==0.10.14` on Python 3.9) or "
                    "set pose_backend to 'yolo' in the exercise config.")
            _mp_pose = mp.solutions.pose.Pose(
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                model_complexity=1,
            )
    return _mp_pose


def _load_mp_holistic():
    global _mp_holistic
    if _mp_holistic is not None:
        return _mp_holistic
    with _LOAD_LOCK:
        if _mp_holistic is None:
            import mediapipe as mp
            if not hasattr(mp, "solutions"):
                raise RuntimeError(
                    "The installed mediapipe build does not include the "
                    "legacy solutions API. Install a compatible version "
                    "(`pip install mediapipe==0.10.14` on Python 3.9) or "
                    "set pose_backend to 'yolo' in the exercise config.")
            _mp_holistic = mp.solutions.holistic.Holistic(
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
                model_complexity=1,
                smooth_landmarks=True,
                enable_segmentation=False,
                refine_face_landmarks=False,
            )
    return _mp_holistic


def _body33_to_coco17(body33: List[List[float]]) -> List[List[float]]:
    out = [[0.0, 0.0, 0.0] for _ in range(17)]
    for mp_i, coco_i in _MP_TO_COCO17.items():
        out[coco_i] = list(body33[mp_i])
    return out


class PoseInferencer:
    """Backend-agnostic single-person pose inferencer."""

    def __init__(self, backend: str = "mediapipe_holistic",
                 imgsz: int = 384) -> None:
        self.backend = backend
        self.imgsz = imgsz
        if backend == "yolo":
            _load_yolo()
        elif backend == "mediapipe_pose":
            _load_mp_pose()
        elif backend == "mediapipe_holistic":
            _load_mp_holistic()
        else:
            raise ValueError(f"unknown pose backend: {backend!r}")

    def infer(self, frame_bgr) -> Optional[PoseFrame]:
        if self.backend == "yolo":
            return self._infer_yolo(frame_bgr)
        if self.backend == "mediapipe_pose":
            return self._infer_mp_pose(frame_bgr)
        return self._infer_mp_holistic(frame_bgr)

    def _infer_yolo(self, frame_bgr) -> Optional[PoseFrame]:
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
        coco = [[round(x, 1), round(y, 1), round(c, 3)]
                for x, y, c in res.keypoints.data.tolist()[best]]
        return PoseFrame(coco17=coco)

    def _infer_mp_pose(self, frame_bgr) -> Optional[PoseFrame]:
        import cv2
        pose = _load_mp_pose()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = pose.process(rgb)
        if not result.pose_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        body33 = _landmarks_to_list(result.pose_landmarks.landmark, w, h)
        return PoseFrame(coco17=_body33_to_coco17(body33), body33=body33)

    def _infer_mp_holistic(self, frame_bgr) -> Optional[PoseFrame]:
        import cv2
        holistic = _load_mp_holistic()
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = holistic.process(rgb)
        if not result.pose_landmarks:
            return None
        h, w = frame_bgr.shape[:2]
        body33 = _landmarks_to_list(result.pose_landmarks.landmark, w, h)
        hand_l = (_landmarks_to_list(result.left_hand_landmarks.landmark, w, h)
                  if result.left_hand_landmarks else None)
        hand_r = (_landmarks_to_list(result.right_hand_landmarks.landmark, w, h)
                  if result.right_hand_landmarks else None)
        return PoseFrame(coco17=_body33_to_coco17(body33), body33=body33,
                         hand_left=hand_l, hand_right=hand_r)


def _landmarks_to_list(landmarks, width: int, height: int
                       ) -> List[List[float]]:
    out: List[List[float]] = []
    for lm in landmarks:
        vis = float(getattr(lm, "visibility", 1.0) or 0.0)
        # Presence is sometimes 0 for hand landmarks; fall back to 1.0 so
        # the point stays visible.
        if vis == 0.0 and getattr(lm, "presence", None) is not None:
            vis = float(lm.presence)
        if vis == 0.0:
            vis = 1.0
        out.append([float(lm.x) * width, float(lm.y) * height, vis])
    return out


def _draw_bones(img, kps, groups, min_conf: float) -> None:
    import cv2
    # Dark halo pass so bones stay readable on any background, then the
    # colored pass on top.
    for edges, _color in groups:
        for i, j in edges:
            xi, yi, ci = kps[i]
            xj, yj, cj = kps[j]
            if ci < min_conf or cj < min_conf:
                continue
            cv2.line(img, (int(xi), int(yi)), (int(xj), int(yj)),
                     (20, 20, 20), 5, cv2.LINE_AA)
    for edges, color in groups:
        for i, j in edges:
            xi, yi, ci = kps[i]
            xj, yj, cj = kps[j]
            if ci < min_conf or cj < min_conf:
                continue
            cv2.line(img, (int(xi), int(yi)), (int(xj), int(yj)),
                     color, 3, cv2.LINE_AA)


def _draw_joints(img, kps, min_conf: float, radius: int = 4) -> None:
    import cv2
    for x, y, c in kps:
        if c < min_conf:
            continue
        center = (int(x), int(y))
        cv2.circle(img, center, radius + 1, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.circle(img, center, radius, (240, 240, 240), -1, cv2.LINE_AA)


def _draw_neck(img, body33, min_conf: float) -> None:
    """Virtual neck: a short colored bone from the mid-shoulder to the nose.
    MediaPipe does not emit a neck landmark, so this is a display aid only.
    """
    import cv2
    ls = body33[MP_POSE_L_SHOULDER]
    rs = body33[MP_POSE_R_SHOULDER]
    nose = body33[MP_POSE_NOSE]
    if ls[2] < min_conf or rs[2] < min_conf or nose[2] < min_conf:
        return
    mid = ((ls[0] + rs[0]) / 2.0, (ls[1] + rs[1]) / 2.0)
    p1 = (int(mid[0]), int(mid[1]))
    p2 = (int(nose[0]), int(nose[1]))
    cv2.line(img, p1, p2, (20, 20, 20), 5, cv2.LINE_AA)
    cv2.line(img, p1, p2, _C_NECK, 3, cv2.LINE_AA)
    cv2.circle(img, p1, 5, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.circle(img, p1, 4, _C_NECK, -1, cv2.LINE_AA)


def draw_pose(img, result: PoseFrame,
              min_conf: float = KP_MIN_CONF):
    """Draw everything the backend gave us onto `img` in place."""
    if result is None:
        return img
    if result.body33 is not None:
        _draw_bones(img, result.body33, _MP_BODY_GROUPS, min_conf)
        _draw_neck(img, result.body33, min_conf)
        _draw_joints(img, result.body33, min_conf, radius=4)
    else:
        # YOLO backend: draw the 17 COCO points with a compact skeleton.
        coco_groups = (
            (((0, 5), (0, 6), (5, 6), (5, 11), (6, 12), (11, 12)), _C_TORSO),
            (((5, 7), (7, 9)), _C_ARM_L),
            (((6, 8), (8, 10)), _C_ARM_R),
            (((11, 13), (13, 15)), _C_LEG_L),
            (((12, 14), (14, 16)), _C_LEG_R),
            (((1, 3), (2, 4), (0, 1), (0, 2)), _C_HEAD),
        )
        _draw_bones(img, result.coco17, coco_groups, min_conf)
        _draw_joints(img, result.coco17, min_conf, radius=4)
    if result.hand_left is not None:
        _draw_bones(img, result.hand_left, _HAND_GROUPS, min_conf)
        _draw_joints(img, result.hand_left, min_conf, radius=3)
    if result.hand_right is not None:
        _draw_bones(img, result.hand_right, _HAND_GROUPS, min_conf)
        _draw_joints(img, result.hand_right, min_conf, radius=3)
    return img
