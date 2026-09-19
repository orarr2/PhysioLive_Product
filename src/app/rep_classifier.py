"""Rep-quality classifier.

Wraps a LightGBM model exported to ONNX and served through
`onnxruntime` on CPU. The model consumes the per-rep feature vector
built from a `RepSample` (min / max of the tracked angles, ROM, tempo)
and returns a probability distribution over `good | nit | wrong`.

If no model file is present at `data/models/rep_clf.onnx` the classifier
returns `None` and the pipeline falls back to the deterministic rule
verdict. Train a new model with `python -m app.tools.train_rep_classifier`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .rep_counter import RepSample


DEFAULT_MODEL_PATH = (Path(__file__).resolve().parents[2]
                      / "data" / "models" / "rep_clf.onnx")

FEATURE_ORDER: List[str] = [
    "primary_min", "primary_max", "primary_range",
    "knee_min", "knee_max",
    "hip_min", "hip_max",
    "elbow_min", "elbow_max",
    "shoulder_min", "shoulder_max",
    "torso_vertical_max", "knee_over_toe_max",
    "frames",
]

CLASSES: List[str] = ["good", "nit", "wrong"]


@dataclass
class ClassifierResult:
    label: str
    confidence: float
    probabilities: Dict[str, float]


class RepClassifier:
    def __init__(self, model_path: Optional[Path] = None) -> None:
        self.model_path = Path(model_path or DEFAULT_MODEL_PATH)
        self._sess = None
        self._input_name: Optional[str] = None

    def is_available(self) -> bool:
        return self.model_path.is_file()

    def _ensure(self) -> bool:
        if self._sess is not None:
            return True
        if not self.is_available():
            return False
        try:
            import onnxruntime as ort
            self._sess = ort.InferenceSession(str(self.model_path),
                                              providers=["CPUExecutionProvider"])
            self._input_name = self._sess.get_inputs()[0].name
        except Exception as e:
            print(f"rep_classifier: load failed ({e})")
            self._sess = None
            return False
        return True

    def classify(self, sample: RepSample) -> Optional[ClassifierResult]:
        if not self._ensure():
            return None
        import numpy as np
        vec = np.array([[_feature(sample, name) for name in FEATURE_ORDER]],
                       dtype="float32")
        try:
            outputs = self._sess.run(None, {self._input_name: vec})
        except Exception as e:
            print(f"rep_classifier: inference failed ({e})")
            return None
        probs = _resolve_probs(outputs)
        if probs is None:
            return None
        best = max(range(len(probs)), key=probs.__getitem__)
        return ClassifierResult(
            label=CLASSES[best] if best < len(CLASSES) else str(best),
            confidence=float(probs[best]),
            probabilities={CLASSES[i]: float(p) for i, p in enumerate(probs)
                           if i < len(CLASSES)},
        )


def _feature(sample: RepSample, name: str) -> float:
    if name == "primary_min":
        v = sample.get_min("primary")
    elif name == "primary_max":
        v = sample.get_max("primary")
    elif name == "primary_range":
        lo = sample.get_min("primary")
        hi = sample.get_max("primary")
        v = None if lo is None or hi is None else hi - lo
    elif name == "knee_min":
        v = sample.get_min("knee")
    elif name == "knee_max":
        v = sample.get_max("knee")
    elif name == "hip_min":
        v = sample.get_min("hip")
    elif name == "hip_max":
        v = sample.get_max("hip")
    elif name == "elbow_min":
        v = sample.get_min("elbow")
    elif name == "elbow_max":
        v = sample.get_max("elbow")
    elif name == "shoulder_min":
        v = sample.get_min("shoulder")
    elif name == "shoulder_max":
        v = sample.get_max("shoulder")
    elif name == "torso_vertical_max":
        v = sample.get_max("torso_vertical")
    elif name == "knee_over_toe_max":
        v = sample.get_max("knee_over_toe_norm")
    elif name == "frames":
        v = float(sample.frames)
    else:
        v = None
    return 0.0 if v is None else float(v)


def _resolve_probs(outputs) -> Optional[List[float]]:
    """LightGBM ONNX exports usually put probabilities at index 1 as a
    list-of-dicts. Fall back to a plain softmax head at index 0."""
    if not outputs:
        return None
    if len(outputs) >= 2:
        probs_out = outputs[1]
        if isinstance(probs_out, list) and probs_out and isinstance(
                probs_out[0], dict):
            row = probs_out[0]
            return [float(row.get(i, 0.0)) for i in range(len(CLASSES))]
    first = outputs[0]
    try:
        vec = list(first[0])
        if len(vec) >= len(CLASSES):
            total = sum(float(v) for v in vec[:len(CLASSES)]) or 1.0
            return [float(v) / total for v in vec[:len(CLASSES)]]
    except Exception:
        return None
    return None
