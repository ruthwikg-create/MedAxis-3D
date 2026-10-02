from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def load_nii(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    try:
        import nibabel as nib
    except Exception as exc:
        raise RuntimeError("Prostate MRI analysis requires nibabel.") from exc
    nii = nib.as_closest_canonical(nib.load(str(path)))
    data = np.asarray(nii.get_fdata(dtype=np.float32))
    if data.ndim != 3:
        raise ValueError(f"Expected a 3D NIfTI volume; received {data.shape}.")
    zooms = tuple(float(v) for v in nii.header.get_zooms()[:3])
    if len(zooms) != 3 or not all(np.isfinite(zooms)) or min(zooms) <= 0:
        raise ValueError("NIfTI voxel spacing is invalid.")
    return np.transpose(data, (2, 1, 0)), zooms


def analyze_prostate(image: np.ndarray, mask: np.ndarray, spacing: tuple[float, float, float], adc: np.ndarray | None = None, t2: np.ndarray | None = None) -> dict[str, Any]:
    if image.shape != mask.shape:
        raise ValueError("Prostate image and mask shapes do not match.")
    prostate = np.asarray(mask) > 0
    voxels = int(prostate.sum())
    if voxels == 0:
        raise ValueError("Prostate segmentation is empty.")
    volume_cm3 = voxels * float(np.prod(spacing)) / 1000.0
    values = image[prostate]
    result: dict[str, Any] = {
        "status": "MEASURED",
        "voxel_spacing_mm": list(spacing),
        "volume_cm3": volume_cm3,
        "voxel_count": voxels,
        "signal": {
            "mean": float(np.mean(values)),
            "median": float(np.median(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
        },
        "method": "Voxel-count volume and first-order signal statistics from supplied MRI and prostate segmentation.",
        "pi_rads": "Structured PI-RADS v2.1 worksheet only; automated scoring is not performed by this implementation.",
    }
    if adc is not None:
        if adc.shape != mask.shape:
            raise ValueError("ADC volume and prostate mask shapes do not match.")
        av = adc[prostate]
        result["adc"] = {"mean": float(np.mean(av)), "median": float(np.median(av)), "std": float(np.std(av))}
    if t2 is not None:
        if t2.shape != mask.shape:
            raise ValueError("T2 volume and prostate mask shapes do not match.")
        tv = t2[prostate]
        result["t2"] = {"mean": float(np.mean(tv)), "median": float(np.median(tv)), "std": float(np.std(tv))}
    return result
