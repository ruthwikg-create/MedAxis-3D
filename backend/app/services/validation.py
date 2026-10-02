from __future__ import annotations

from typing import Any

import numpy as np
from scipy import ndimage


def _surface(mask: np.ndarray) -> np.ndarray:
    eroded = ndimage.binary_erosion(mask, structure=ndimage.generate_binary_structure(3, 1), border_value=0)
    return mask ^ eroded


def _surface_distances(a: np.ndarray, b: np.ndarray, spacing: tuple[float, float, float]) -> np.ndarray:
    if not a.any() or not b.any():
        return np.array([], dtype=np.float64)
    # distance_transform_edt accepts sampling along array z,y,x; spacing is x,y,z.
    spacing_zyx = (spacing[2], spacing[1], spacing[0])
    dist_to_b = ndimage.distance_transform_edt(~b, sampling=spacing_zyx)
    return dist_to_b[_surface(a)]


def segmentation_metrics(pred: np.ndarray, ref: np.ndarray, spacing: tuple[float, float, float]) -> dict[str, Any]:
    pred = np.asarray(pred, dtype=bool)
    ref = np.asarray(ref, dtype=bool)
    if pred.shape != ref.shape:
        raise ValueError(f"Prediction/reference shapes differ: {pred.shape} vs {ref.shape}.")
    if len(spacing) != 3 or min(spacing) <= 0:
        raise ValueError("Valid voxel spacing is required for physical-distance metrics.")

    intersection = int(np.logical_and(pred, ref).sum())
    union = int(np.logical_or(pred, ref).sum())
    pred_count = int(pred.sum())
    ref_count = int(ref.sum())
    dice = (2 * intersection / (pred_count + ref_count)) if pred_count + ref_count else 1.0
    iou = (intersection / union) if union else 1.0
    voxel_volume = float(np.prod(spacing))
    volume_pred = pred_count * voxel_volume
    volume_ref = ref_count * voxel_volume
    abs_volume_diff = abs(volume_pred - volume_ref)
    relative_volume_diff = abs_volume_diff / volume_ref if volume_ref else None

    d1 = _surface_distances(pred, ref, spacing)
    d2 = _surface_distances(ref, pred, spacing)
    all_dist = np.concatenate([d1, d2]) if d1.size and d2.size else np.array([], dtype=np.float64)
    hd95 = float(np.percentile(all_dist, 95)) if all_dist.size else None
    assd = float(all_dist.mean()) if all_dist.size else None

    return {
        "dice": float(dice),
        "iou": float(iou),
        "hausdorff_distance_95_mm": hd95,
        "average_symmetric_surface_distance_mm": assd,
        "prediction_voxels": pred_count,
        "reference_voxels": ref_count,
        "prediction_volume_cm3": volume_pred / 1000.0,
        "reference_volume_cm3": volume_ref / 1000.0,
        "absolute_volume_difference_cm3": abs_volume_diff / 1000.0,
        "relative_volume_difference": relative_volume_diff,
        "method": "Binary segmentation overlap and surface-distance metrics against an independent reference mask.",
    }


def expected_calibration_error(probabilities: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    probs = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.float64).ravel()
    if probs.size != y.size or probs.size == 0:
        raise ValueError("Probability and label arrays must have equal non-zero length.")
    if np.any(~np.isfinite(probs)) or np.any(~np.isfinite(y)):
        raise ValueError("Probability and label arrays must be finite.")
    if np.any((probs < 0) | (probs > 1)) or np.any((y != 0) & (y != 1)):
        raise ValueError("Probabilities must be within [0,1] and labels must be 0/1.")
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        mask = (probs >= lo) & (probs < hi if hi < 1 else probs <= hi)
        if not mask.any():
            continue
        ece += float(mask.mean()) * abs(float(probs[mask].mean()) - float(y[mask].mean()))
    return float(ece)


def calibration_report(probabilities: list[float], labels: list[int], bins: int = 10) -> dict[str, Any]:
    probs = np.asarray(probabilities, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int64)
    ece = expected_calibration_error(probs, y, bins=bins)
    brier = float(np.mean((probs - y) ** 2))
    return {
        "sample_count": int(probs.size),
        "ece": ece,
        "brier_score": brier,
        "bins": bins,
        "method": "Expected Calibration Error and Brier score on supplied held-out probabilities/labels.",
        "status": "MEASURED",
    }


def fit_temperature_calibration(probabilities: list[float], labels: list[int]) -> dict[str, Any]:
    import numpy as np
    from scipy.optimize import minimize_scalar

    probs = np.asarray(probabilities, dtype=np.float64).ravel()
    y = np.asarray(labels, dtype=np.int64).ravel()
    if probs.size < 10 or probs.size != y.size:
        raise ValueError("At least 10 paired probabilities/labels with equal lengths are required for temperature calibration.")
    if np.any(~np.isfinite(probs)) or np.any((probs < 0) | (probs > 1)) or np.any((y != 0) & (y != 1)):
        raise ValueError("Probabilities must be finite values in [0,1] and labels must be binary 0/1.")
    eps = 1e-6
    logits = np.log(np.clip(probs, eps, 1 - eps) / np.clip(1 - probs, eps, 1 - eps))

    def sigmoid(x):
        x = np.clip(x, -60.0, 60.0)
        return 1.0 / (1.0 + np.exp(-x))

    def nll(temp: float) -> float:
        q = sigmoid(logits / max(float(temp), 1e-6))
        return float(-np.mean(y * np.log(np.clip(q, eps, 1 - eps)) + (1 - y) * np.log(np.clip(1 - q, eps, 1 - eps))))

    fit = minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded", options={"xatol": 1e-4})
    temperature = float(fit.x)
    calibrated = sigmoid(logits / temperature)
    before = calibration_report(probs.tolist(), y.tolist())
    after = calibration_report(calibrated.tolist(), y.tolist())
    return {
        "status": "CALIBRATED ON SUPPLIED RESEARCH DATA",
        "method": "Temperature scaling fitted by minimizing binary negative log-likelihood.",
        "temperature": temperature,
        "before": before,
        "after": after,
        "calibrated_probabilities": calibrated.tolist(),
        "note": "Use a locked independent validation cohort before treating calibration as evidence for deployment performance.",
    }
