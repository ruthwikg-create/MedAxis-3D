from __future__ import annotations

import math
from typing import Any

import numpy as np
from scipy import ndimage
from skimage.feature import graycomatrix, graycoprops
from scipy.stats import kurtosis, skew

from .mesh import make_surface


def _safe_float(value: Any) -> float | None:
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except Exception:
        return None


def mask_metrics(mask: np.ndarray, spacing: tuple[float, float, float], image: np.ndarray | None = None) -> dict[str, Any]:
    mask = np.asarray(mask, dtype=bool)
    if mask.ndim != 3:
        raise ValueError("Segmentation mask must be a 3D array.")
    voxel_count = int(mask.sum())
    if voxel_count == 0:
        raise ValueError("Segmentation mask is empty.")
    voxel_volume = float(np.prod(spacing))
    volume_mm3 = voxel_count * voxel_volume
    coords = np.argwhere(mask).astype(np.float64)
    # coords are z,y,x; metrics are emitted as x,y,z.
    centroid_zyx = coords.mean(axis=0)
    centroid_xyz = centroid_zyx[[2, 1, 0]] * np.asarray(spacing)
    bbox_zyx = np.ptp(coords, axis=0) * np.asarray(spacing)[::-1]
    principal = principal_dimensions(mask, spacing)
    surface = make_surface(np.zeros_like(mask, dtype=np.float32), spacing, mask=mask)
    result = {
        "voxel_count": voxel_count,
        "volume_mm3": volume_mm3,
        "volume_cm3": volume_mm3 / 1000.0,
        "centroid_mm": [float(v) for v in centroid_xyz],
        "bounding_box_mm": [float(v) for v in bbox_zyx[[2, 1, 0]]],
        "principal_dimensions_mm": principal,
        "surface_area_mm2": surface.get("surface_area_mm2"),
    }
    if image is not None:
        values = np.asarray(image)[mask]
        finite = values[np.isfinite(values)]
        if finite.size:
            result["intensity"] = {
                "mean": float(np.mean(finite)),
                "median": float(np.median(finite)),
                "std": float(np.std(finite)),
                "min": float(np.min(finite)),
                "max": float(np.max(finite)),
                "p10": float(np.percentile(finite, 10)),
                "p90": float(np.percentile(finite, 90)),
            }
    return result


def principal_dimensions(mask: np.ndarray, spacing: tuple[float, float, float]) -> list[float]:
    coords = np.argwhere(mask).astype(np.float64)
    physical = coords[:, [2, 1, 0]] * np.asarray(spacing)[None, :]
    physical -= physical.mean(axis=0, keepdims=True)
    if len(physical) < 3:
        return [0.0, 0.0, 0.0]
    cov = np.cov(physical, rowvar=False)
    eigen = np.linalg.eigvalsh(cov)
    # 4*sqrt(lambda) is a compact, reproducible diameter proxy rather than an unbounded pairwise search.
    dims = 4.0 * np.sqrt(np.maximum(eigen, 0.0))
    return [float(v) for v in np.sort(dims)[::-1]]


def _quantize(values: np.ndarray, levels: int = 32) -> np.ndarray:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return np.zeros_like(values, dtype=np.uint8)
    low, high = np.percentile(finite, [1, 99])
    if high <= low:
        return np.zeros_like(values, dtype=np.uint8)
    scaled = np.clip((values - low) / (high - low), 0, 1)
    return np.floor(scaled * (levels - 1)).astype(np.uint8)


def _glcm_features(image: np.ndarray, mask: np.ndarray, levels: int = 32, max_slices: int = 24) -> dict[str, float | None]:
    coords = np.argwhere(mask)
    if coords.size == 0:
        return {}
    z_values = sorted(set(int(z) for z in coords[:, 0]))
    if len(z_values) > max_slices:
        pick = np.linspace(0, len(z_values) - 1, max_slices, dtype=int)
        z_values = [z_values[i] for i in np.unique(pick)]
    feature_acc: dict[str, list[float]] = {name: [] for name in ("contrast", "dissimilarity", "homogeneity", "energy", "correlation", "ASM")}
    for z in z_values:
        plane = image[z]
        plane_mask = mask[z]
        if int(plane_mask.sum()) < 16:
            continue
        quant = _quantize(plane, levels=levels)
        ys, xs = np.where(plane_mask)
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        crop = quant[y0:y1 + 1, x0:x1 + 1]
        cmask = plane_mask[y0:y1 + 1, x0:x1 + 1]
        if crop.size == 0:
            continue
        # Replace pixels outside the ROI with the ROI median before computing the
        # GLCM so the descriptor is driven by the selected ROI rather than the
        # surrounding crop background. This remains a research subset, not an IBSI
        # complete radiomics implementation.
        roi_quantized = quant[plane_mask]
        if roi_quantized.size == 0:
            continue
        fill = int(np.median(roi_quantized))
        crop = crop.copy()
        crop[~cmask] = fill
        try:
            glcm = graycomatrix(crop, [1], [0, np.pi / 4, np.pi / 2, 3 * np.pi / 4], levels=levels, symmetric=True, normed=True)
            for name in feature_acc:
                feature_acc[name].append(float(np.nanmean(graycoprops(glcm, name))))
        except ValueError:
            continue
    return {name: (float(np.mean(values)) if values else None) for name, values in feature_acc.items()}


def radiomics_features(image: np.ndarray, mask: np.ndarray, spacing: tuple[float, float, float], modality: str) -> dict[str, Any]:
    image = np.asarray(image, dtype=np.float32)
    mask = np.asarray(mask, dtype=bool)
    if image.shape != mask.shape:
        raise ValueError("Image and ROI mask dimensions do not match.")
    values = image[mask]
    values = values[np.isfinite(values)]
    if values.size < 8:
        raise ValueError("At least 8 finite ROI voxels are required for radiomics extraction.")
    geom = mask_metrics(mask, spacing, image=None)
    first_order = {
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "std": float(values.std()),
        "min": float(values.min()),
        "max": float(values.max()),
        "p10": float(np.percentile(values, 10)),
        "p25": float(np.percentile(values, 25)),
        "p75": float(np.percentile(values, 75)),
        "p90": float(np.percentile(values, 90)),
        "skewness": _safe_float(skew(values, bias=False)) if values.size > 2 else None,
        "kurtosis": _safe_float(kurtosis(values, fisher=True, bias=False)) if values.size > 3 else None,
        "entropy_32bin": entropy(values, bins=32),
    }
    texture = _glcm_features(image, mask)
    features = {
        "modality": modality,
        "feature_source": "actual source image voxels restricted by a source-derived ROI/segmentation mask",
        "first_order": first_order,
        "shape": geom,
        "texture_glcm": texture,
        # Common flat keys keep the UI/API contract stable while the full nested
        # feature groups remain available for research pipelines.
        "volume_mm3": float(geom["volume_mm3"]),
        "volume_cm3": float(geom["volume_cm3"]),
        "surface_area_mm2": float(geom["surface_area_mm2"]) if geom.get("surface_area_mm2") is not None else None,
        "entropy": float(first_order["entropy_32bin"]),
        "energy": float(texture["energy"]) if texture.get("energy") is not None else None,
        "method": "research radiomics subset; not an IBSI-complete implementation unless explicitly extended and validated.",
    }
    return features


def entropy(values: np.ndarray, bins: int = 32) -> float:
    hist, _ = np.histogram(values, bins=bins)
    hist = hist.astype(np.float64)
    total = hist.sum()
    if total <= 0:
        return 0.0
    p = hist[hist > 0] / total
    return float(-(p * np.log2(p)).sum())


def tissue_bands_ct() -> list[dict[str, float | str]]:
    # Educational reference bands only. These are not diagnostic thresholds.
    return [
        {"name": "Air", "lower_hu": -1200, "upper_hu": -700, "note": "Educational reference band; do not use as a diagnostic threshold."},
        {"name": "Fat", "lower_hu": -190, "upper_hu": -30, "note": "Educational reference band; scanner and reconstruction dependent."},
        {"name": "Fluid-like", "lower_hu": -10, "upper_hu": 40, "note": "Approximate educational reference only."},
        {"name": "Soft tissue", "lower_hu": 20, "upper_hu": 100, "note": "Broad educational band; tissue overlap is expected."},
        {"name": "Bone", "lower_hu": 300, "upper_hu": 2500, "note": "Educational high-attenuation band; not a clinical threshold."},
    ]


def intensity_histogram(
    image: np.ndarray,
    bins: int = 64,
    sample_limit: int = 1_000_000,
) -> dict[str, Any]:
    """Return a source-derived intensity histogram for interactive analytics.

    Large volumes are deterministically subsampled by stride to keep response
    sizes bounded. The histogram is descriptive only; it does not infer tissue
    class or pathology.
    """
    if bins < 8 or bins > 256:
        raise ValueError("Histogram bins must be between 8 and 256.")
    values = np.asarray(image, dtype=np.float32).ravel()
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("The source volume contains no finite intensity values.")
    sampled = values
    if sampled.size > sample_limit:
        stride = int(np.ceil(sampled.size / sample_limit))
        sampled = sampled[::stride]
    lo = float(np.min(sampled))
    hi = float(np.max(sampled))
    if hi <= lo:
        hi = lo + 1.0
    counts, edges = np.histogram(sampled, bins=int(bins), range=(lo, hi))
    centers = ((edges[:-1] + edges[1:]) / 2.0).astype(np.float64)
    return {
        "status": "MEASURED",
        "bins": int(bins),
        "counts": [int(v) for v in counts.tolist()],
        "bin_edges": [float(v) for v in edges.tolist()],
        "centers": [float(v) for v in centers.tolist()],
        "sample_count": int(sampled.size),
        "source_voxel_count": int(values.size),
        "range": [lo, float(np.max(values))],
        "sampling": "full volume" if sampled.size == values.size else f"deterministic stride sampling (1/{int(np.ceil(values.size / sampled.size))})",
        "method": "Histogram of finite source voxel intensities; no tissue classification is inferred.",
    }


def intensity_profile(
    image: np.ndarray,
    plane: str = "axial",
    index: int = 0,
    axis: str = "horizontal",
    max_points: int = 512,
) -> dict[str, Any]:
    """Return a line profile from the actual source image plane.

    The profile is descriptive only. It never classifies tissue or pathology.
    Internal volumes use Z,Y,X order; emitted coordinate spacing follows X,Y,Z.
    """
    volume = np.asarray(image, dtype=np.float32)
    if volume.ndim != 3:
        raise ValueError("Intensity profile requires a 3D source volume.")
    plane = plane.lower().strip()
    axis = axis.lower().strip()
    if plane not in {"axial", "sagittal", "coronal"}:
        raise ValueError("Plane must be axial, sagittal, or coronal.")
    if axis not in {"horizontal", "vertical"}:
        raise ValueError("Axis must be horizontal or vertical.")

    if plane == "axial":
        idx = int(np.clip(index, 0, volume.shape[0] - 1))
        data = volume[idx]
    elif plane == "coronal":
        idx = int(np.clip(index, 0, volume.shape[1] - 1))
        data = volume[:, idx, :]
    else:
        idx = int(np.clip(index, 0, volume.shape[2] - 1))
        data = volume[:, :, idx]

    row = data.shape[0] // 2
    col = data.shape[1] // 2
    values = data[row, :] if axis == "horizontal" else data[:, col]
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Selected profile contains no finite source voxels.")
    step = max(1, int(np.ceil(values.size / max_points)))
    sampled = values[::step]
    return {
        "status": "MEASURED",
        "plane": plane,
        "index": idx,
        "axis": axis,
        "sample_count": int(sampled.size),
        "source_count": int(values.size),
        "values": [float(v) for v in sampled],
        "coordinate": [int(i) for i in range(0, int(values.size), step)][: int(sampled.size)],
        "source": "actual imported imaging voxels",
        "note": "MRI signal intensity is sequence/scanner dependent; CT HU interpretation requires valid source calibration metadata.",
    }
