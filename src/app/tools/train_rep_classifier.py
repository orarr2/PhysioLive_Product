"""Train a LightGBM rep-quality classifier and export it to ONNX.

Input format (CSV):

    exercise,rep_index,label,primary_min,primary_max,primary_range,
    knee_min,knee_max,hip_min,hip_max,elbow_min,elbow_max,
    shoulder_min,shoulder_max,torso_vertical_max,knee_over_toe_max,frames

The label column is one of `good`, `nit`, `wrong`. Any missing feature
cell should be left empty; the trainer imputes missing values as zero.

Usage:
    python -m app.tools.train_rep_classifier data/labels/reps.csv \
        --out data/models/rep_clf.onnx
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from app.rep_classifier import CLASSES, FEATURE_ORDER  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("csv", type=str, help="labeled reps CSV")
    ap.add_argument("--out", type=str,
                    default=str(_ROOT / "data" / "models" / "rep_clf.onnx"))
    ap.add_argument("--test-size", type=float, default=0.2)
    args = ap.parse_args()

    import numpy as np
    import pandas as pd
    from sklearn.model_selection import train_test_split
    from sklearn.metrics import classification_report
    import lightgbm as lgb

    df = pd.read_csv(args.csv)
    for col in FEATURE_ORDER:
        if col not in df.columns:
            df[col] = 0.0
    X = df[FEATURE_ORDER].fillna(0.0).astype("float32").values
    y_str = df["label"].astype(str).values
    label_to_idx = {c: i for i, c in enumerate(CLASSES)}
    y = np.array([label_to_idx.get(l, 0) for l in y_str], dtype="int64")

    Xtr, Xte, ytr, yte = train_test_split(
        X, y, test_size=args.test_size, stratify=y, random_state=42)
    model = lgb.LGBMClassifier(
        n_estimators=200, max_depth=6, learning_rate=0.05,
        objective="multiclass", num_class=len(CLASSES),
    )
    model.fit(Xtr, ytr)
    pred = model.predict(Xte)
    print(classification_report(yte, pred,
                                target_names=CLASSES, zero_division=0))

    from onnxmltools import convert_lightgbm
    from onnxconverter_common.data_types import FloatTensorType
    initial_types = [("input", FloatTensorType([None, len(FEATURE_ORDER)]))]
    onnx_model = convert_lightgbm(model, initial_types=initial_types,
                                  zipmap=False, target_opset=13)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(onnx_model.SerializeToString())
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
