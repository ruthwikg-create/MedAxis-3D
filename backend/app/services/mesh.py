from __future__ import annotations

from typing import Any

import numpy as np
from skimage.measure import marching_cubes, mesh_surface_area
from skimage.transform import downscale_local_mean


def _downsample_mask(mask: np.ndarray, spacing: tuple[float, float, float], max_voxels: int = 4_000_000) -> tuple[np.ndarray, tuple[float, float, float], int]:
    voxels = int(mask.size)
    if voxels <= max_voxels:
        return mask, spacing, 1
    factor = int(np.ceil((voxels / max_voxels) ** (1 / 3)))
    factor = max(2, factor)
    pad_z = (-mask.shape[0]) % factor
    pad_y = (-mask.shape[1]) % factor
    pad_x = (-mask.shape[2]) % factor
    padded = np.pad(mask.astype(np.float32), ((0, pad_z), (0, pad_y), (0, pad_x)), mode="constant")
    shape = (padded.shape[0] // factor, padded.shape[1] // factor, padded.shape[2] // factor)
    small = downscale_local_mean(padded, (factor, factor, factor)) > 0
    return small.astype(bool), tuple(float(s * factor) for s in spacing), factor


def make_surface(volume: np.ndarray, spacing: tuple[float, float, float], mask: np.ndarray | None = None) -> dict[str, Any]:
    volume = np.asarray(volume)
    if volume.ndim != 3:
        return {"status": "UNAVAILABLE", "message": "Surface extraction requires a 3D volume.", "vertices": [], "faces": []}
    if len(spacing) != 3 or not all(np.isfinite(spacing)) or min(spacing) <= 0:
        return {"status": "UNAVAILABLE", "message": "Valid voxel spacing is required for 3D surface reconstruction.", "vertices": [], "faces": []}

    if mask is None:
        finite = volume[np.isfinite(volume)]
        if finite.size < 20:
            return {"status": "UNAVAILABLE", "message": "No finite source voxels are available for intensity-derived surface extraction.", "vertices": [], "faces": []}
        lo, hi = np.percentile(finite, [65, 99])
        mask = (volume >= lo) & (volume <= hi)
        method = "Percentile intensity-derived research surface from actual source voxels (65th–99th percentile). Not an anatomical segmentation."
        parameters = {"lower_percentile": 65, "upper_percentile": 99}
    else:
        mask = np.asarray(mask, dtype=bool)
        method = "Marching Cubes over an explicitly supplied source-derived binary mask."
        parameters = {}

    if mask.shape != volume.shape:
        return {"status": "UNAVAILABLE", "message": "Surface mask dimensions do not match the source volume.", "vertices": [], "faces": []}
    if int(mask.sum()) < 20:
        return {"status": "UNAVAILABLE", "message": "Insufficient source voxels for surface extraction.", "vertices": [], "faces": []}

    source_voxel_count = int(mask.sum())
    mask, effective_spacing, downsample_factor = _downsample_mask(mask, spacing)
    # Padding guarantees a closed background boundary even when the mask touches a volume edge.
    padded = np.pad(mask.astype(np.uint8), 1, mode="constant", constant_values=0)
    try:
        verts_zyx, faces, _, _ = marching_cubes(
            padded,
            level=0.5,
            spacing=(effective_spacing[2], effective_spacing[1], effective_spacing[0]),
        )
    except (ValueError, RuntimeError) as exc:
        return {"status": "UNAVAILABLE", "message": f"Surface extraction failed: {exc}", "vertices": [], "faces": []}

    # Remove the one-voxel padding offset and reorder into conventional x,y,z coordinates.
    verts_zyx -= np.asarray(effective_spacing[::-1], dtype=np.float64)
    verts_xyz = verts_zyx[:, [2, 1, 0]]
    area_mm2 = float(mesh_surface_area(verts_xyz, faces))
    volume_mm3 = float(source_voxel_count * np.prod(spacing))
    bbox = np.ptp(verts_xyz, axis=0) if len(verts_xyz) else np.zeros(3)

    return {
        "status": "AVAILABLE",
        "vertices": verts_xyz.astype(np.float32).tolist(),
        "faces": faces.astype(np.uint32).tolist(),
        "vertex_count": int(len(verts_xyz)),
        "triangle_count": int(len(faces)),
        "surface_area_mm2": area_mm2,
        "volume_mm3": volume_mm3,
        "volume_cm3": volume_mm3 / 1000.0,
        "bounding_box_mm": [float(v) for v in bbox],
        "method": method,
        "parameters": parameters,
        "downsample_factor": downsample_factor,
        "effective_spacing_mm": list(effective_spacing),
    }
