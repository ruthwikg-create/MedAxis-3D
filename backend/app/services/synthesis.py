from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

from .imaging import load_case


def model_path() -> Path:
    value = os.getenv("CROSS_MODALITY_MODEL_PATH", "").strip()
    return Path(value).expanduser().resolve() if value else Path(__file__).resolve().parents[2] / "models" / "cross_modality" / "ct_to_mri.ts"


def status() -> dict[str, Any]:
    path = model_path()
    return {
        "model_id": "ct_to_mri",
        "display_name": "CT → MRI research image-to-image synthesis",
        "status": "MODEL READY" if path.is_file() else "MODEL NOT CONFIGURED",
        "model_path": str(path),
        "framework": "TorchScript",
        "input": "3D CT volume",
        "output": "3D synthetic MRI-like volume",
        "note": "Research-only synthesis. Output is generated data and must never be treated as acquired MRI or used as a substitute for clinical imaging.",
    }


def _load_torchscript(path: Path):
    try:
        import torch
    except Exception as exc:
        raise RuntimeError("CT→MRI synthesis requires PyTorch.") from exc
    try:
        model = torch.jit.load(str(path), map_location="cpu")
        model.eval()
        return torch, model
    except Exception as exc:
        raise RuntimeError(f"Unable to load TorchScript synthesis model: {exc}") from exc


def run(case_id: str, output_path: Path) -> dict[str, Any]:
    model_status = status()
    if model_status["status"] != "MODEL READY":
        raise RuntimeError("CT→MRI synthesis model is not configured. Set CROSS_MODALITY_MODEL_PATH to a validated research TorchScript checkpoint before enabling synthesis.")

    root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
    source = root / "raw" if (root / "raw").exists() else root
    imaging = load_case(source)
    if imaging.modality != "CT":
        raise ValueError(f"Cross-modality synthesis expects CT input, received {imaging.modality}.")
    if imaging.volume.ndim != 3 or not np.isfinite(imaging.volume).any():
        raise ValueError("CT input volume is not a valid finite 3D volume.")

    torch, model = _load_torchscript(Path(model_status["model_path"]))
    finite = np.isfinite(imaging.volume)
    values = imaging.volume[finite].astype(np.float32)
    lo, hi = float(values.min()), float(values.max())
    scale = max(hi - lo, 1e-6)
    normalized = np.zeros_like(imaging.volume, dtype=np.float32)
    normalized[finite] = (imaging.volume[finite] - lo) / scale
    tensor = torch.from_numpy(normalized[None, None]).float()
    with torch.inference_mode():
        output = model(tensor)
    if isinstance(output, (list, tuple)):
        output = output[0]
    if not hasattr(output, "detach"):
        raise RuntimeError("Synthesis model returned an unsupported output type.")
    data = output.detach().cpu().numpy()
    while data.ndim > 3 and data.shape[0] == 1:
        data = data[0]
    while data.ndim > 3 and data.shape[-1] == 1:
        data = data[..., 0]
    if data.ndim != 3 or not np.isfinite(data).any():
        raise RuntimeError(f"Synthesis model returned unsupported output shape {data.shape}.")
    output_array = data.astype(np.float32)
    if output_array.shape != imaging.volume.shape:
        raise RuntimeError(f"Synthesis output shape {output_array.shape} does not match input shape {imaging.volume.shape}.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import nibabel as nib
        # Store as x,y,z while MedAxis internal arrays are z,y,x.
        nifti = nib.Nifti1Image(np.transpose(output_array, (2, 1, 0)), np.diag([imaging.spacing[0], imaging.spacing[1], imaging.spacing[2], 1.0]))
        nifti.header["descrip"] = b"MEDAXIS CT TO MRI SYNTHESIS - RESEARCH GENERATED - NOT ACQUIRED MRI"
        nib.save(nifti, str(output_path))
    except Exception as exc:
        raise RuntimeError("Synthetic output requires nibabel to write NIfTI.") from exc

    return {
        "status": "COMPLETED",
        "case_id": case_id,
        "output_file": str(output_path),
        "model_id": model_status["model_id"],
        "framework": "TorchScript",
        "input_modality": "CT",
        "output_type": "SYNTHETIC MRI-LIKE VOLUME",
        "voxel_spacing_mm": list(imaging.spacing),
        "shape_zyx": list(output_array.shape),
        "source_range": [lo, hi],
        "note": model_status["note"],
    }
