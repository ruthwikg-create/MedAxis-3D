from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

MODEL_DIR = Path(__file__).resolve().parents[2] / "models" / "classifiers"
MODEL_DIR.mkdir(parents=True, exist_ok=True)


def _fit_platt_calibrator(probs, y):
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    probs = np.asarray(probs, dtype=np.float64).reshape(-1, 1)
    eps = 1e-6
    x = np.log(np.clip(probs, eps, 1 - eps) / np.clip(1 - probs, eps, 1 - eps))
    calibrator = LogisticRegression(C=1e6, solver="lbfgs")
    calibrator.fit(x, np.asarray(y, dtype=np.int64))
    return calibrator


def _apply_platt(calibrator, probs):
    import numpy as np

    p = np.asarray(probs, dtype=np.float64).reshape(-1, 1)
    eps = 1e-6
    x = np.log(np.clip(p, eps, 1 - eps) / np.clip(1 - p, eps, 1 - eps))
    return calibrator.predict_proba(x)[:, 1]


def train_binary_classifier(csv_path: Path, model_id: str) -> dict[str, Any]:
    import joblib
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score
    from sklearn.model_selection import StratifiedKFold, cross_val_predict
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    rows = list(csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines()))
    if not rows or "label" not in rows[0]:
        raise ValueError("Training CSV must contain a binary 'label' column and numeric feature columns.")
    feature_names = [name for name in rows[0].keys() if name != "label"]
    if not feature_names:
        raise ValueError("Training CSV must contain at least one numeric feature column.")
    try:
        X = np.asarray([[float(row[name]) for name in feature_names] for row in rows], dtype=np.float64)
        y = np.asarray([int(row["label"]) for row in rows], dtype=np.int64)
    except (TypeError, ValueError) as exc:
        raise ValueError("Training CSV contains non-numeric features or non-integer labels.") from exc
    if np.any(~np.isfinite(X)):
        raise ValueError("Training features must be finite.")
    if np.any((y != 0) & (y != 1)):
        raise ValueError("Training labels must be binary 0/1.")
    if len(np.unique(y)) != 2:
        raise ValueError("Training requires both binary classes to be present.")
    if len(rows) < 20:
        raise ValueError("At least 20 labeled samples are required for this research classifier workflow.")

    base_model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=2000, class_weight="balanced"))
    splits = min(5, int(np.bincount(y).min()))
    if splits < 2:
        raise ValueError("At least two samples are required in each class for cross-validation.")
    cv = StratifiedKFold(n_splits=splits, shuffle=True, random_state=42)
    oof_proba = cross_val_predict(base_model, X, y, cv=cv, method="predict_proba")[:, 1]
    oof_calibrator = _fit_platt_calibrator(oof_proba, y)
    calibrated_oof = _apply_platt(oof_calibrator, oof_proba)
    auc = float(roc_auc_score(y, oof_proba))
    auc_cal = float(roc_auc_score(y, calibrated_oof))
    accuracy = float(accuracy_score(y, oof_proba >= 0.5))
    brier_pre = float(brier_score_loss(y, oof_proba))
    brier_post = float(brier_score_loss(y, calibrated_oof))
    base_model.fit(X, y)
    artifact = MODEL_DIR / f"{model_id}.joblib"
    joblib.dump(
        {
            "model": base_model,
            "calibrator": oof_calibrator,
            "feature_names": feature_names,
            "label_meaning": "1=research positive class, 0=research negative class",
            "training_rows": len(rows),
            "calibration_method": "Platt scaling fitted on out-of-fold probabilities",
        },
        artifact,
    )
    return {
        "status": "TRAINED",
        "model_id": model_id,
        "artifact": str(artifact),
        "features": feature_names,
        "samples": len(rows),
        "cross_validated_auc": auc,
        "cross_validated_calibrated_auc": auc_cal,
        "cross_validated_accuracy": accuracy,
        "oof_brier_before_calibration": brier_pre,
        "oof_brier_after_calibration": brier_post,
        "calibration_method": "Platt scaling fitted on out-of-fold probabilities",
        "note": "Research classifier metrics on supplied data. Calibrated probability is model-derived for the supplied research cohort and is not a clinical malignancy probability.",
    }


def predict_binary_classifier(model_id: str, features: dict[str, float]) -> dict[str, Any]:
    import joblib
    import numpy as np

    path = MODEL_DIR / f"{model_id}.joblib"
    if not path.exists():
        raise FileNotFoundError(f"Research radiomics model '{model_id}' is not installed.")
    artifact = joblib.load(path)
    names = list(artifact["feature_names"])
    missing = [name for name in names if name not in features]
    if missing:
        raise ValueError(f"Required radiomics features are missing: {', '.join(missing)}")
    try:
        X = [[float(features[name]) for name in names]]
    except (TypeError, ValueError) as exc:
        raise ValueError("Radiomics feature values must be finite numeric values.") from exc
    if not np.isfinite(np.asarray(X, dtype=np.float64)).all():
        raise ValueError("Radiomics feature values must be finite.")
    model = artifact["model"]
    probability = float(model.predict_proba(X)[0, 1])
    calibrated_probability = None
    calibrator = artifact.get("calibrator")
    if calibrator is not None:
        calibrated_probability = float(_apply_platt(calibrator, [probability])[0])
    return {
        "status": "MEASURED",
        "model_id": model_id,
        "positive_class_probability": probability,
        "calibrated_probability": calibrated_probability,
        "confidence_status": "CALIBRATED RESEARCH PROBABILITY" if calibrated_probability is not None else "UNCALIBRATED MODEL PROBABILITY",
        "class_label": "research positive" if (calibrated_probability if calibrated_probability is not None else probability) >= 0.5 else "research negative",
        "note": "Model-derived research probability from a user-trained classifier; it is not a clinical malignancy probability or patient prognosis estimate.",
    }
