from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from .validation import segmentation_metrics


def _load_binary_nifti(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    try:
        import nibabel as nib
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("Cohort validation requires nibabel.") from exc
    if not path.is_file():
        raise FileNotFoundError(str(path))
    nii = nib.as_closest_canonical(nib.load(str(path)))
    data = np.asarray(nii.get_fdata(dtype=np.float32))
    if data.ndim != 3:
        raise ValueError(f"Validation mask must be 3D; received {data.shape} for {path.name}.")
    zooms = tuple(float(v) for v in nii.header.get_zooms()[:3])
    if len(zooms) != 3 or not all(np.isfinite(zooms)) or min(zooms) <= 0:
        raise ValueError(f"Invalid voxel spacing in {path.name}.")
    return np.transpose(data > 0, (2, 1, 0)), zooms


def _bootstrap_ci(values: np.ndarray, confidence: float = 0.95, seed: int = 42, samples: int = 2000) -> list[float] | None:
    values = np.asarray(values, dtype=np.float64)
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None
    if values.size == 1:
        value = float(values[0])
        return [value, value]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, values.size, size=(samples, values.size))
    means = values[idx].mean(axis=1)
    alpha = (1.0 - confidence) / 2.0
    return [float(np.quantile(means, alpha)), float(np.quantile(means, 1.0 - alpha))]


def cohort_metrics(pairs: list[dict[str, str]], base_dir: Path, max_cases: int = 500) -> dict[str, Any]:
    if not pairs:
        raise ValueError("At least one validation pair is required.")
    if len(pairs) > max_cases:
        raise ValueError(f"Validation cohort is limited to {max_cases} cases per request.")
    case_results: list[dict[str, Any]] = []
    for item in pairs:
        case_id = str(item.get("case_id", "")).strip() or f"case-{len(case_results)+1}"
        pred = Path(str(item.get("prediction", "")))
        ref = Path(str(item.get("reference", "")))
        pred = (base_dir / pred).resolve() if not pred.is_absolute() else pred.resolve()
        ref = (base_dir / ref).resolve() if not ref.is_absolute() else ref.resolve()
        for candidate in (pred, ref):
            try:
                candidate.relative_to(base_dir.resolve())
            except ValueError as exc:
                raise ValueError("Validation paths must remain inside the configured validation root.") from exc
        pred_mask, pred_spacing = _load_binary_nifti(pred)
        ref_mask, ref_spacing = _load_binary_nifti(ref)
        if pred_mask.shape != ref_mask.shape:
            raise ValueError(f"Prediction/reference shapes differ for {case_id}: {pred_mask.shape} vs {ref_mask.shape}.")
        if not np.allclose(pred_spacing, ref_spacing, rtol=1e-4, atol=1e-4):
            raise ValueError(f"Prediction/reference voxel spacing differs for {case_id}: {pred_spacing} vs {ref_spacing}.")
        result = segmentation_metrics(pred_mask, ref_mask, pred_spacing)
        result["case_id"] = case_id
        case_results.append(result)

    aggregate_fields = [
        "dice",
        "iou",
        "hausdorff_distance_95_mm",
        "average_symmetric_surface_distance_mm",
        "prediction_volume_cm3",
        "reference_volume_cm3",
        "absolute_volume_difference_cm3",
        "relative_volume_difference",
    ]
    aggregate: dict[str, Any] = {}
    for field in aggregate_fields:
        vals = np.asarray([r[field] for r in case_results if r.get(field) is not None], dtype=np.float64)
        vals = vals[np.isfinite(vals)]
        if not vals.size:
            continue
        aggregate[field] = {
            "mean": float(vals.mean()),
            "median": float(np.median(vals)),
            "std": float(vals.std(ddof=1)) if vals.size > 1 else 0.0,
            "95_percent_bootstrap_ci": _bootstrap_ci(vals),
            "n": int(vals.size),
        }

    return {
        "status": "MEASURED",
        "validation_class": "RESEARCH COHORT VALIDATION",
        "case_count": len(case_results),
        "cases": case_results,
        "aggregate": aggregate,
        "method": "Independent prediction/reference binary masks. Aggregate statistics use nonparametric bootstrap over cases; results are evidence for the supplied cohort only.",
        "clinical_validation_status": "NOT ESTABLISHED",
        "note": "This endpoint computes validation statistics; it does not create regulatory clearance or clinical validation by itself.",
    }
