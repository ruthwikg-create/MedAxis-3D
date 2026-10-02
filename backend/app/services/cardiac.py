from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def load_4d_mask(path: Path) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    try:
        import nibabel as nib
    except Exception as exc:
        raise RuntimeError("Cardiac MRI analysis requires nibabel.") from exc
    nii = nib.as_closest_canonical(nib.load(str(path)))
    data = np.asarray(nii.get_fdata(dtype=np.float32))
    if data.ndim != 4:
        raise ValueError(f"Cardiac mask must be 4D (X,Y,Z,T); received {data.shape}.")
    zooms = tuple(float(v) for v in nii.header.get_zooms()[:4])
    if len(zooms) != 4 or not all(np.isfinite(zooms)) or min(zooms[:3]) <= 0:
        raise ValueError("Cardiac mask has invalid spatial voxel spacing.")
    # Return T,Z,Y,X for internal calculation.
    return np.transpose(data, (3, 2, 1, 0)), zooms


def cardiac_metrics(mask_tzyx: np.ndarray, spacing_xyz: tuple[float, float, float, float], lv_label: int, rv_label: int, myocardium_label: int) -> dict[str, Any]:
    if mask_tzyx.ndim != 4:
        raise ValueError("Cardiac mask must be 4D.")
    frames = mask_tzyx.shape[0]
    voxel_volume_mm3 = float(np.prod(spacing_xyz[:3]))
    lv = np.sum(mask_tzyx == lv_label, axis=(1, 2, 3)).astype(np.float64) * voxel_volume_mm3 / 1000.0
    rv = np.sum(mask_tzyx == rv_label, axis=(1, 2, 3)).astype(np.float64) * voxel_volume_mm3 / 1000.0
    myocardium = np.sum(mask_tzyx == myocardium_label, axis=(1, 2, 3)).astype(np.float64) * voxel_volume_mm3 / 1000.0
    if frames < 2:
        return {
            "status": "INSUFFICIENT PHASES",
            "frames": frames,
            "lv_frame_volumes_cm3": lv.tolist(),
            "rv_frame_volumes_cm3": rv.tolist(),
            "myocardium_frame_volumes_cm3": myocardium.tolist(),
            "note": "EDV/ESV, stroke volume and ejection fraction require at least two cardiac phases from a compatible short-axis cine dataset.",
        }
    lv_edv_idx = int(np.argmax(lv))
    lv_esv_idx = int(np.argmin(lv))
    rv_edv_idx = int(np.argmax(rv))
    rv_esv_idx = int(np.argmin(rv))
    lv_edv, lv_esv = float(lv[lv_edv_idx]), float(lv[lv_esv_idx])
    rv_edv, rv_esv = float(rv[rv_edv_idx]), float(rv[rv_esv_idx])
    return {
        "status": "MEASURED",
        "frames": frames,
        "voxel_spacing_mm": list(spacing_xyz[:3]),
        "lv": {
            "edv_cm3": lv_edv,
            "esv_cm3": lv_esv,
            "stroke_volume_cm3": lv_edv - lv_esv,
            "ejection_fraction_percent": ((lv_edv - lv_esv) / lv_edv * 100.0) if lv_edv > 0 else None,
            "edv_frame": lv_edv_idx,
            "esv_frame": lv_esv_idx,
        },
        "rv": {
            "edv_cm3": rv_edv,
            "esv_cm3": rv_esv,
            "stroke_volume_cm3": rv_edv - rv_esv,
            "ejection_fraction_percent": ((rv_edv - rv_esv) / rv_edv * 100.0) if rv_edv > 0 else None,
            "edv_frame": rv_edv_idx,
            "esv_frame": rv_esv_idx,
        },
        "framewise": {
            "lv_volume_cm3": lv.tolist(),
            "rv_volume_cm3": rv.tolist(),
            "myocardium_volume_cm3": myocardium.tolist(),
        },
        "method": "Voxel-count volumes from the supplied cine segmentation label map; no clinical reference ranges are applied.",
    }
