from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[2] / "models" / "calibrators"
ROOT.mkdir(parents=True, exist_ok=True)


def _safe_model_filename(model_id: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in model_id.strip())
    if not cleaned:
        raise ValueError("Model ID is required.")
    return cleaned[:160] + ".json"


def _logit(probabilities: np.ndarray) -> np.ndarray:
    eps = 1e-6
    p = np.clip(np.asarray(probabilities, dtype=np.float64), eps, 1.0 - eps)
    return np.log(p / (1.0 - p))


def fit_platt(model_id: str, probabilities: list[float], labels: list[int], model_version: str) -> dict[str, Any]:
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import log_loss

    p = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.int64).ravel()
    if p.size < 20 or p.size != y.size:
        raise ValueError("At least 20 paired held-out probabilities and labels are required.")
    if np.any(~np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        raise ValueError("Probabilities must be finite values in [0,1].")
    if np.any((y != 0) & (y != 1)):
        raise ValueError("Labels must contain only 0/1 values.")
    if np.unique(y).size < 2:
        raise ValueError("Calibration data must contain both outcome classes.")

    x = _logit(p).reshape(-1, 1)
    clf = LogisticRegression(C=1e6, solver="lbfgs")
    clf.fit(x, y)
    a = float(clf.coef_[0, 0])
    b = float(clf.intercept_[0])
    calibrated = 1.0 / (1.0 + np.exp(-np.clip(a * x[:, 0] + b, -60.0, 60.0)))
    payload = {
        "model_id": model_id,
        "model_version": model_version,
        "calibrator_type": "PLATT_SCALING_ON_MODEL_SCORE_LOGIT",
        "coefficient": a,
        "intercept": b,
        "training_sample_count": int(p.size),
        "positive_count": int(y.sum()),
        "negative_count": int((1 - y).sum()),
        "raw_log_loss": float(log_loss(y, p, labels=[0, 1])),
        "calibrated_log_loss": float(log_loss(y, calibrated, labels=[0, 1])),
        "source": "held-out research calibration cohort supplied by operator",
        "created_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "status": "RESEARCH CALIBRATOR FIT",
        "clinical_validation_status": "NOT ESTABLISHED",
    }
    target = ROOT / _safe_model_filename(model_id)
    target.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    payload["artifact"] = str(target)
    return payload


def load_platt(model_id: str, model_version: str) -> dict[str, Any] | None:
    target = ROOT / _safe_model_filename(model_id)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if str(data.get("model_version")) != str(model_version):
            return None
        if data.get("calibrator_type") != "PLATT_SCALING_ON_MODEL_SCORE_LOGIT":
            return None
        return data
    except Exception:
        return None


def apply_platt(calibrator: dict[str, Any], probability: float) -> float:
    a = float(calibrator["coefficient"])
    b = float(calibrator["intercept"])
    logit = float(_logit(np.asarray([probability]))[0])
    return float(1.0 / (1.0 + np.exp(-np.clip(a * logit + b, -60.0, 60.0))))


def artifact_hash(model_id: str) -> str | None:
    target = ROOT / _safe_model_filename(model_id)
    if not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()
