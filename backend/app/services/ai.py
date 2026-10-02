from __future__ import annotations

import json
import os
import subprocess
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .db import create_job, get_job, save_analysis, save_analytics, update_job
from .cardiac import cardiac_metrics
from .imaging import load_case


MODEL_ROOT = Path(__file__).resolve().parents[2] / "models" / "bundles"
MODEL_ROOT.mkdir(parents=True, exist_ok=True)


def monai_available() -> bool:
    """Return whether the MONAI runtime can actually be imported."""
    try:
        import monai  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def torch_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except Exception:
        return False


MODEL_CATALOG: dict[str, dict[str, Any]] = {
    "wholeBody_ct_segmentation": {
        "display_name": "MONAI Whole Body CT Segmentation",
        "version": "0.2.7",
        "modality": "CT",
        "body_region": "Whole body",
        "kind": "segmentation",
        "input_type": "volume",
        "output_type": "labelmap",
        "generic_inference": True,
        "required_sequences": [],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "wholeBody_ct_segmentation",
        "publisher_benchmark": "Mean Dice 0.80 in publisher metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {"spleen": 1, "kidney_right": 2, "kidney_left": 3, "liver": 5, "pancreas": 10, "heart_myocardium": 44, "heart_ventricle_left": 46, "heart_ventricle_right": 48, "brain": 50, "urinary_bladder": 104},
    },
    "spleen_ct_segmentation": {
        "display_name": "MONAI Spleen CT Segmentation",
        "version": "0.6.1",
        "modality": "CT",
        "body_region": "Spleen",
        "kind": "segmentation",
        "input_type": "volume",
        "output_type": "labelmap",
        "generic_inference": True,
        "required_sequences": [],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "spleen_ct_segmentation",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {"spleen": 1},
    },
    "prostate_mri_anatomy": {
        "display_name": "MONAI Prostate MRI Anatomy",
        "version": "0.3.6",
        "modality": "MRI",
        "body_region": "Prostate",
        "kind": "segmentation",
        "input_type": "volume",
        "output_type": "labelmap",
        "generic_inference": True,
        "required_sequences": [],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "prostate_mri_anatomy",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {"central_gland": 1, "peripheral_zone": 2},
    },
    "ventricular_short_axis_3label": {
        "display_name": "MONAI Ventricular Short Axis 3-Label",
        "version": "0.3.5",
        "modality": "MRI",
        "body_region": "Heart",
        "kind": "segmentation",
        "input_type": "4d_cine",
        "output_type": "labelmap_4d",
        "generic_inference": False,
        "required_sequences": ["short-axis cine MRI"],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "ventricular_short_axis_3label",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {"lv_blood_pool": 1, "myocardium": 2, "rv_blood_pool": 3},
    },
    "pathology_tumor_detection": {
        "display_name": "MONAI Pathology Tumor Detection",
        "version": "0.6.4",
        "modality": "PATHOLOGY",
        "body_region": "Whole-slide image",
        "kind": "detection",
        "input_type": "wsi",
        "output_type": "detection_json",
        "generic_inference": False,
        "required_sequences": [],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "pathology_tumor_detection",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {},
    },
    "brats_mri_segmentation": {
        "display_name": "MONAI BraTS MRI Tumor Segmentation",
        "version": "0.5.4",
        "modality": "MRI",
        "body_region": "Brain",
        "kind": "segmentation",
        "input_type": "volume",
        "output_type": "labelmap",
        "generic_inference": False,
        "required_sequences": ["T1", "T1Gd", "T2", "FLAIR"],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "brats_mri_segmentation",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {"tumor_core": 1, "whole_tumor": 2, "enhancing_tumor": 3},
    },
    "lung_nodule_ct_detection": {
        "display_name": "MONAI Lung Nodule CT Detection",
        "version": "0.6.10",
        "modality": "CT",
        "body_region": "Chest",
        "kind": "detection",
        "input_type": "volume",
        "output_type": "detection_json",
        "generic_inference": False,
        "required_sequences": ["LUNA16-resampled-CT"],
        "source": "Project-MONAI Model Zoo",
        "bundle_name": "lung_nodule_ct_detection",
        "publisher_benchmark": "See bundle metadata",
        "validation_status": "Publisher benchmark only; not MedAxis clinical validation",
        "structures": {},
    },
}


class JobRunner:
    def start(self, job_id: str, fn: Callable[[], dict[str, Any]]) -> None:
        thread = threading.Thread(target=self._wrapped, args=(job_id, fn), daemon=True)
        thread.start()

    def _wrapped(self, job_id: str, fn: Callable[[], dict[str, Any]]) -> None:
        try:
            update_job(job_id, status="RUNNING", progress=2, message="Preparing model runtime")
            result = fn()
            update_job(job_id, status="COMPLETED", progress=100, message="Inference completed", result=result)
            case_id = str(result.get("case_id") or "")
            save_analysis(job_id, case_id, result.get("analysis_type", "AI INFERENCE"), "COMPLETED", result)
            if case_id:
                save_analytics(case_id, "ai_inference", result)
        except Exception as exc:
            update_job(job_id, status="FAILED", progress=100, message="Inference failed", error=str(exc))


runner = JobRunner()


def model_path(model_id: str) -> Path:
    info = MODEL_CATALOG.get(model_id)
    if info is None:
        raise ValueError(f"Unknown model '{model_id}'.")
    return MODEL_ROOT / str(info["bundle_name"])


def _bundle_files(bundle: Path) -> dict[str, list[str]]:
    configs = [p.name for p in (bundle / "configs").glob("inference.*") if p.is_file()] if (bundle / "configs").exists() else []
    weights = [str(p.relative_to(bundle)) for p in (bundle / "models").rglob("*") if p.is_file() and p.suffix.lower() in {".pt", ".pth", ".ts"}] if (bundle / "models").exists() else []
    return {"configs": configs, "weights": weights}


def model_status(model_id: str) -> dict[str, Any]:
    info = MODEL_CATALOG.get(model_id)
    if info is None:
        raise KeyError(model_id)
    bundle = model_path(model_id)
    files = _bundle_files(bundle)
    config_candidates = [bundle / "configs" / "inference.json", bundle / "configs" / "inference.yaml", bundle / "configs" / "inference.yml"]
    config = next((p for p in config_candidates if p.exists()), None)
    installed = config is not None and bool(files["weights"])
    runtime_ready = monai_available()
    if installed and runtime_ready:
        status = "MODEL READY"
    elif installed and not runtime_ready:
        status = "MODEL INSTALLED — MONAI RUNTIME MISSING"
    else:
        status = "MODEL NOT DOWNLOADED"
    from .calibration_registry import artifact_hash, load_platt
    calibrator = load_platt(model_id, str(info["version"]))
    return {
        **info,
        "model_id": model_id,
        "status": status,
        "bundle_path": str(bundle),
        "device": detected_device(),
        "runtime_contract": "MONAI Bundle config + model weights",
        "runtime_ready": runtime_ready,
        "config_file": str(config) if config else None,
        "weight_files": files["weights"],
        "download_required": not installed,
        "inference_ready": installed and runtime_ready,
        "calibration": {
            "available": calibrator is not None,
            "model_version": str(info["version"]),
            "artifact_hash": artifact_hash(model_id) if calibrator is not None else None,
            "method": calibrator.get("calibrator_type") if calibrator else None,
        },
    }


def detected_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "unknown"


def download_model(model_id: str) -> dict[str, Any]:
    info = MODEL_CATALOG.get(model_id)
    if info is None:
        raise ValueError(f"Unknown model '{model_id}'.")
    try:
        import monai
        from monai.bundle import download as bundle_download
        _ = monai
    except Exception as exc:
        raise RuntimeError("MONAI is not installed. Install backend requirements before downloading a model.") from exc
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    bundle_download(
        name=str(info["bundle_name"]),
        version=str(info["version"]),
        bundle_dir=str(MODEL_ROOT),
        source=os.getenv("MONAI_BUNDLE_SOURCE", "github"),
        progress=True,
    )
    return model_status(model_id)


def _case_to_nifti(case_id: str, output_path: Path) -> Path:
    case_root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
    source = case_root / "raw" if (case_root / "raw").exists() else case_root
    imaging = load_case(source)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if imaging.source_type == "dicom":
        try:
            import SimpleITK as sitk
            reader = sitk.ImageSeriesReader()
            names = reader.GetGDCMSeriesFileNames(str(source))
            if not names:
                raise RuntimeError("SimpleITK could not enumerate the DICOM series.")
            reader.SetFileNames(names)
            image = reader.Execute()
            sitk.WriteImage(image, str(output_path), useCompression=True)
            return output_path
        except Exception as exc:
            raise RuntimeError("DICOM→NIfTI conversion for model inference requires SimpleITK and a valid DICOM series geometry.") from exc
    try:
        import nibabel as nib
        array_xyz = np.transpose(imaging.volume, (2, 1, 0)).astype(np.float32)
        affine = np.asarray(imaging.affine_ras, dtype=np.float64) if imaging.affine_ras is not None else np.diag([imaging.spacing[0], imaging.spacing[1], imaging.spacing[2], 1.0])
        img = nib.Nifti1Image(array_xyz, affine)
        nib.save(img, str(output_path))
        return output_path
    except Exception as exc:
        raise RuntimeError("NIfTI export for AI inference requires nibabel.") from exc

def _find_prediction(output_dir: Path, started_at: float) -> Path:
    allowed = {".nii.gz", ".nii", ".json", ".csv", ".npz"}
    candidates = [
        p for p in output_dir.rglob("*")
        if p.is_file() and (p.suffix.lower() in {".nii", ".json", ".csv", ".npz"} or p.name.lower().endswith(".nii.gz"))
        and p.stat().st_mtime >= started_at - 2
        and p.name.lower() not in {"monai-run.log"}
    ]
    if not candidates:
        raise RuntimeError("MONAI completed without producing a supported prediction artifact (NIfTI/JSON/CSV/NPZ).")
    semantic = [p for p in candidates if any(token in p.name.lower() for token in ("pred", "seg", "label", "output", "prob", "result"))]
    if len(semantic) == 1:
        return semantic[0]
    if len(candidates) == 1:
        return candidates[0]
    raise RuntimeError(f"MONAI produced multiple output artifacts ({len(candidates)}); MedAxis will not guess which one is the prediction. Configure the bundle output contract explicitly.")


def _labelmap_from_prediction(path: Path) -> tuple[np.ndarray, tuple[float, float, float]]:
    import nibabel as nib
    nii = nib.load(str(path))
    data = np.asarray(nii.get_fdata(dtype=np.float32))
    if data.ndim == 4 and data.shape[-1] > 1:
        data = np.argmax(data, axis=-1).astype(np.uint16)
    if data.ndim != 3:
        raise RuntimeError(f"Unsupported model output dimensions: {data.shape}")
    # NIfTI is x,y,z; internal volume is z,y,x.
    spacing_xyz = tuple(float(v) for v in nii.header.get_zooms()[:3])
    return np.transpose(data, (2, 1, 0)), (spacing_xyz[0], spacing_xyz[1], spacing_xyz[2])


def _read_detection_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("Detection output JSON must be an array of per-image prediction objects.")
    detections: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        boxes = item.get("box", [])
        labels = item.get("label", [])
        scores = item.get("label_scores", [])
        image = item.get("image")
        for idx, score in enumerate(scores if isinstance(scores, list) else []):
            label = labels[idx] if isinstance(labels, list) and idx < len(labels) else None
            box = boxes[idx] if isinstance(boxes, list) and idx < len(boxes) else None
            try:
                numeric_score = float(score)
            except (TypeError, ValueError):
                continue
            detections.append({"image": image, "label": label, "score": numeric_score, "box": box})
    return {"detections": detections, "count": len(detections), "source_file": str(path)}


def _run_bundle(
    bundle: Path,
    input_payload: Any,
    output_dir: Path,
    device: str,
    *,
    config_overrides: dict[str, Any] | None = None,
    run_id: str = "run",
) -> Path:
    """Run an official MONAI Bundle with explicit, inspectable overrides.

    ``input_payload`` is normally a list of image paths for single-volume bundles.
    Model-specific bundles may use dictionaries (e.g. BraTS 4-channel MRI) and pass
    additional ConfigParser variables through ``config_overrides``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    config = bundle / "configs" / "inference.json"
    if not config.exists():
        for name in ("inference.yaml", "inference.yml"):
            candidate = bundle / "configs" / name
            if candidate.exists():
                config = candidate
                break
    if not config.exists():
        raise RuntimeError(f"Bundle is missing an inference config: {bundle}")

    overrides = config_overrides or {}
    cmd = [
        sys.executable,
        "-m",
        "monai.bundle",
        "run",
        run_id,
        "--config_file",
        str(config),
        "--datalist",
        json.dumps(input_payload),
        "--output_dir",
        str(output_dir),
        "--device",
        f'$torch.device("{device}")',
        "--inferer#device",
        f'$torch.device("{device}")',
    ]
    for key, value in overrides.items():
        cmd.extend([f"--{key}", json.dumps(value) if not isinstance(value, str) or value.startswith("{") else value])

    completed = subprocess.run(
        cmd,
        cwd=str(bundle),
        capture_output=True,
        text=True,
        timeout=int(os.getenv("MODEL_INFERENCE_TIMEOUT", "3600")),
    )
    log_path = output_dir / "monai-run.log"
    log_path.write_text((completed.stdout or "") + "\n" + (completed.stderr or ""), encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "MONAI inference failed.")[-12000:])
    return _find_prediction(output_dir, started_at)


def _prepare_case_input(case_id: str, work_dir: Path) -> tuple[Path, Any]:
    work_dir.mkdir(parents=True, exist_ok=True)
    input_path = _case_to_nifti(case_id, work_dir / "input.nii.gz")
    return input_path, [str(input_path).replace("\\", "/")]




def _resample_nifti_spacing(input_path: Path, output_path: Path, target_spacing_xyz: tuple[float, float, float]) -> Path:
    """Resample a NIfTI volume to an explicit spacing using SimpleITK."""
    try:
        import SimpleITK as sitk
    except Exception as exc:
        raise RuntimeError("Lung-nodule preprocessing requires SimpleITK for explicit LUNA16 spacing resampling.") from exc
    image = sitk.ReadImage(str(input_path))
    old_spacing = image.GetSpacing()
    old_size = image.GetSize()
    new_size = [max(1, int(round(old_size[i] * old_spacing[i] / target_spacing_xyz[i]))) for i in range(3)]
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(tuple(float(v) for v in target_spacing_xyz))
    resampler.SetSize([int(v) for v in new_size])
    resampler.SetOutputOrigin(image.GetOrigin())
    resampler.SetOutputDirection(image.GetDirection())
    resampler.SetTransform(sitk.Transform())
    resampler.SetInterpolator(sitk.sitkLinear)
    resampler.SetDefaultPixelValue(float(sitk.GetArrayViewFromImage(image).min()))
    resampled = resampler.Execute(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sitk.WriteImage(resampled, str(output_path), useCompression=True)
    return output_path

def start_lung_nodule_inference(case_id: str, device: str | None = None) -> str:
    """Run the official MONAI LUNA16 lung nodule detection bundle.

    The bundle expects a LUNA16-resampled CT-compatible volume. The result is a
    JSON detection artifact; MedAxis does not convert scores into a diagnostic label.
    """
    model_id = "lung_nodule_ct_detection"
    status = model_status(model_id)
    if not status.get("inference_ready"):
        raise RuntimeError(f"{status['display_name']} is not ready for inference: {status['status']}.")
    root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
    source = root / "raw" if (root / "raw").exists() else root
    imaging = load_case(source)
    if imaging.modality != "CT":
        raise RuntimeError(f"Lung nodule model expects CT; selected case is {imaging.modality}.")
    required_spacing = (0.703125, 0.703125, 1.25)
    use_device = (device or detected_device()).lower()
    if use_device.startswith("cuda") and detected_device() != "cuda":
        raise RuntimeError("CUDA was requested but is not available on this server.")
    if use_device not in {"cpu", "cuda", "cuda:0"}:
        raise RuntimeError("Unsupported inference device. Use CPU or CUDA.")
    job_id = f"ai-{int(time.time())}-{os.urandom(4).hex()}"
    create_job(job_id, case_id, f"AI_INFERENCE:{model_id}")

    def work() -> dict[str, Any]:
        case_root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
        work_dir = case_root / "ai" / job_id
        input_path, _ = _prepare_case_input(case_id, work_dir)
        datalist_dir = work_dir / "bundle-data"
        datalist_dir.mkdir(parents=True, exist_ok=True)
        datalist = datalist_dir / "dataset_fold0.json"
        dataset_dir = datalist_dir
        local_input = dataset_dir / "input.nii.gz"
        _resample_nifti_spacing(input_path, local_input, required_spacing)
        datalist.write_text(json.dumps({"validation": [{"image": "input.nii.gz"}]}), encoding="utf-8")
        update_job(job_id, progress=10, message="Resampled CT to the detector's LUNA16 spacing contract")
        prediction = _run_bundle(
            model_path(model_id),
            [],
            work_dir / "output",
            use_device,
            config_overrides={
                "data_list_file_path": str(datalist),
                "dataset_dir": str(dataset_dir),
                "whether_raw_luna16": False,
                "whether_resampled_luna16": True,
            },
        )
        parsed = _read_detection_json(prediction)
        return {
            "analysis_id": job_id,
            "case_id": case_id,
            "analysis_type": "MONAI LUNG NODULE DETECTION",
            "model_id": model_id,
            "model_name": status["display_name"],
            "model_version": status["version"],
            "model_source": status["source"],
            "device": use_device,
            "prediction_file": str(prediction),
            "detections": parsed,
            "confidence": "MODEL SCORE — calibration not available from the bundle output",
            "validation_status": status["validation_status"],
            "note": "Research detection output. LUNA16 compatibility is required; this result is not a diagnosis and has not been clinically validated by MedAxis.",
        }
    runner.start(job_id, work)
    return job_id


def start_brats_inference(
    *,
    t1: Path,
    t1gd: Path,
    t2: Path,
    flair: Path,
    output_root: Path,
    device: str | None = None,
) -> str:
    """Run the official MONAI BraTS four-channel research segmentation bundle."""
    model_id = "brats_mri_segmentation"
    status = model_status(model_id)
    if not status.get("inference_ready"):
        raise RuntimeError(f"{status['display_name']} is not ready for inference: {status['status']}.")
    use_device = (device or detected_device()).lower()
    if use_device.startswith("cuda") and detected_device() != "cuda":
        raise RuntimeError("CUDA was requested but is not available on this server.")
    if use_device not in {"cpu", "cuda", "cuda:0"}:
        raise RuntimeError("Unsupported inference device. Use CPU or CUDA.")
    job_id = f"ai-brats-{int(time.time())}-{os.urandom(4).hex()}"
    create_job(job_id, "unattached", f"AI_INFERENCE:{model_id}")

    def work() -> dict[str, Any]:
        work_dir = output_root / job_id
        dataset_dir = work_dir / "dataset"
        dataset_dir.mkdir(parents=True, exist_ok=True)
        names = {"t1": t1, "t1gd": t1gd, "t2": t2, "flair": flair}
        for key, source in names.items():
            if not source.is_file():
                raise FileNotFoundError(f"Missing BraTS input: {source}")
            shutil.copy2(source, dataset_dir / f"{key}.nii.gz")
        datalist = work_dir / "datalist.json"
        datalist.write_text(json.dumps({"testing": [{"image": ["t1.nii.gz", "t1gd.nii.gz", "t2.nii.gz", "flair.nii.gz"]}]}), encoding="utf-8")
        update_job(job_id, progress=12, message="Prepared four-channel BraTS research input")
        prediction = _run_bundle(
            model_path(model_id),
            [],
            work_dir / "output",
            use_device,
            config_overrides={"data_list_file_path": str(datalist), "dataset_dir": str(dataset_dir)},
        )
        return {
            "analysis_id": job_id,
            "case_id": None,
            "analysis_type": "MONAI BRATS MRI TUMOR SEGMENTATION",
            "model_id": model_id,
            "model_name": status["display_name"],
            "model_version": status["version"],
            "prediction_file": str(prediction),
            "device": use_device,
            "validation_status": status["validation_status"],
            "note": "Four-sequence BraTS research segmentation. Output labels follow the downloaded bundle contract and are not a clinical tumor diagnosis.",
        }
    runner.start(job_id, work)
    return job_id


def start_cardiac_inference(
    *,
    cine_file: Path,
    output_root: Path,
    case_id: str | None = None,
    device: str | None = None,
) -> str:
    """Run the MONAI ventricular short-axis model frame-by-frame on a 4D cine NIfTI.

    The official bundle operates on 2D short-axis MR images, so MedAxis performs
    explicit frame-wise inference and reassembles the outputs into a 4D label map.
    """
    model_id = "ventricular_short_axis_3label"
    status = model_status(model_id)
    if not status.get("inference_ready"):
        raise RuntimeError(f"{status['display_name']} is not ready for inference: {status['status']}.")
    use_device = (device or detected_device()).lower()
    if use_device.startswith("cuda") and detected_device() != "cuda":
        raise RuntimeError("CUDA was requested but is not available on this server.")
    if use_device not in {"cpu", "cuda", "cuda:0"}:
        raise RuntimeError("Unsupported inference device. Use CPU or CUDA.")

    try:
        import nibabel as nib
    except Exception as exc:
        raise RuntimeError("Cardiac inference requires nibabel.") from exc
    nii = nib.as_closest_canonical(nib.load(str(cine_file)))
    data = np.asarray(nii.get_fdata(dtype=np.float32))
    if data.ndim != 4:
        raise ValueError(f"Cardiac cine input must be 4D X,Y,Z,T; received {data.shape}.")
    if not np.isfinite(data).any():
        raise ValueError("Cardiac cine input contains no finite voxels.")
    spatial = tuple(int(v) for v in data.shape[:3])
    frames = int(data.shape[3])
    if frames < 2:
        raise ValueError("At least two cardiac phases are required for frame-wise LV/RV analysis.")
    zooms = tuple(float(v) for v in nii.header.get_zooms()[:4])
    if len(zooms) < 4 or not all(np.isfinite(v) and v > 0 for v in zooms[:3]):
        raise ValueError("Cardiac cine NIfTI has invalid spatial voxel spacing.")

    job_id = f"ai-cardiac-{int(time.time())}-{os.urandom(4).hex()}"
    create_job(job_id, case_id or "unattached", f"AI_INFERENCE:{model_id}")

    def work() -> dict[str, Any]:
        work_dir = output_root / job_id
        frame_root = work_dir / "frames"
        output_dir = work_dir / "outputs"
        frame_root.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        frame_masks: list[np.ndarray] = []
        for frame_idx in range(frames):
            frame_dir = frame_root / f"frame-{frame_idx:04d}"
            frame_dir.mkdir(parents=True, exist_ok=True)
            frame_nii = nib.Nifti1Image(data[:, :, :, frame_idx], np.asarray(nii.affine, dtype=np.float64))
            frame_path = frame_dir / "input.nii.gz"
            nib.save(frame_nii, str(frame_path))
            update_job(job_id, progress=10 + (70 * frame_idx / frames), message=f"Running ventricular segmentation for cine frame {frame_idx + 1}/{frames}")
            prediction = _run_bundle(
                model_path(model_id),
                [],
                output_dir / f"frame-{frame_idx:04d}",
                use_device,
                config_overrides={"dataset_dir": str(frame_dir), "output_dir": str(output_dir / f"frame-{frame_idx:04d}")},
                run_id="evaluating",
            )
            labelmap_zyx, pred_spacing = _labelmap_from_prediction(prediction)
            if tuple(labelmap_zyx.shape) != spatial[::-1]:
                raise RuntimeError(f"Cardiac model output shape {labelmap_zyx.shape} does not match source frame Z,Y,X {spatial[::-1]}.")
            if not np.allclose(pred_spacing, zooms[:3], rtol=1e-3, atol=1e-3):
                raise RuntimeError("Cardiac model output spacing does not match the source cine spacing; implicit spatial resampling is disabled.")
            frame_masks.append(labelmap_zyx.astype(np.uint8))

        mask_tzyx = np.stack(frame_masks, axis=0)
        mask_xyz_t = np.transpose(mask_tzyx, (3, 2, 1, 0))
        mask_path = work_dir / "cardiac-labelmap.nii.gz"
        nib.save(nib.Nifti1Image(mask_xyz_t.astype(np.uint8), np.asarray(nii.affine, dtype=np.float64)), str(mask_path))
        metrics = cardiac_metrics(mask_tzyx, zooms[:4], 1, 3, 2)
        update_job(job_id, progress=96, message="Calculated frame-wise LV/RV functional metrics")
        result = {
            "analysis_id": job_id,
            "case_id": case_id,
            "analysis_type": "MONAI CARDIAC LV/RV SEGMENTATION",
            "model_id": model_id,
            "model_name": status["display_name"],
            "model_version": status["version"],
            "model_source": status["source"],
            "device": use_device,
            "frames": frames,
            "mask_file": str(mask_path),
            "voxel_spacing_mm": list(zooms[:3]),
            "metrics": metrics,
            "validation_status": status["validation_status"],
            "note": "Frame-wise research inference using the official MONAI ventricular bundle. MedAxis has not clinically validated patient-specific performance.",
        }
        return result

    runner.start(job_id, work)
    return job_id

def start_inference(case_id: str, model_id: str, structure: str | None = None, device: str | None = None) -> str:
    status = model_status(model_id)
    if not status.get("inference_ready"):
        if status.get("status") == "MODEL INSTALLED — MONAI RUNTIME MISSING":
            raise RuntimeError(f"{status['display_name']} is installed but MONAI is not importable in this Python environment. Install backend requirements and restart the API.")
        raise RuntimeError(f"{status['display_name']} is not downloaded. Use Model Manager → Download Model first.")
    root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
    source = root / "raw" if (root / "raw").exists() else root
    imaging = load_case(source)
    expected = str(status.get("modality", "")).upper()
    if status.get("input_type") != "volume" or not status.get("generic_inference", False):
        required = ", ".join(str(v) for v in status.get("required_sequences", [])) or "model-specific inputs"
        raise RuntimeError(
            f"Model '{model_id}' uses a model-specific adapter ({status.get('input_type')}); generic DICOM/NIfTI inference is disabled. "
            f"Required input contract: {required}."
        )
    if expected == "CT" and imaging.modality != "CT":
        raise RuntimeError(f"Model expects CT input but the selected case is {imaging.modality}.")
    if expected == "MRI" and imaging.modality not in {"MRI", "MR"}:
        raise RuntimeError(f"Model expects MRI input but the selected case is {imaging.modality}.")
    flags = imaging.qc_flags or {}
    if any(flags.get(k) for k in ("geometry_incomplete", "duplicate_slices", "inconsistent_spacing", "missing_slice_gaps")):
        raise RuntimeError("AI inference requires a geometrically consistent imaging series; current QC flags indicate incomplete or inconsistent geometry.")
    if structure and structure.lower() not in {str(k).lower() for k in status.get("structures", {})}:
        raise RuntimeError(f"Structure '{structure}' is not defined by model {model_id}.")
    job_id = f"ai-{int(time.time())}-{os.urandom(4).hex()}"
    create_job(job_id, case_id, f"AI_INFERENCE:{model_id}")
    use_device = (device or detected_device()).lower()
    if use_device.startswith("cuda") and detected_device() != "cuda":
        raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false on this server. Select CPU or install a compatible CUDA-enabled PyTorch build.")
    if use_device not in {"cpu", "cuda", "cuda:0"}:
        raise RuntimeError("Unsupported inference device. Use CPU or CUDA.")

    def work() -> dict[str, Any]:
        case_root = Path(__file__).resolve().parents[2] / "data" / "cases" / case_id
        work_dir = case_root / "ai" / job_id
        input_path = _case_to_nifti(case_id, work_dir / "input.nii.gz")
        update_job(job_id, progress=10, message="Prepared NIfTI model input")
        prediction = _run_bundle(model_path(model_id), input_path, work_dir / "output", use_device)
        update_job(job_id, progress=85, message="Reading model result")
        info = MODEL_CATALOG[model_id]
        selected_id = info.get("structures", {}).get((structure or "").lower()) if structure else None
        labelmap = None
        spacing = imaging.spacing
        binary = None
        detections = None
        if prediction.name.lower().endswith((".nii", ".nii.gz")):
            labelmap, spacing = _labelmap_from_prediction(prediction)
            binary = None if selected_id is None else labelmap == int(selected_id)
        elif prediction.suffix.lower() == ".json" and info.get("output_type") == "detection_json":
            detections = _read_detection_json(prediction)
            from .calibration_registry import apply_platt, load_platt
            calibrator = load_platt(model_id, str(info["version"]))
            if detections.get("detections"):
                for det in detections["detections"]:
                    raw_score = float(det.get("score", 0.0))
                    if calibrator is not None:
                        det["raw_score"] = raw_score
                        det["score"] = apply_platt(calibrator, raw_score)
                        det["confidence_status"] = "CALIBRATED RESEARCH PROBABILITY"
                    else:
                        det["confidence_status"] = "MODEL SCORE — NOT CALIBRATED"
        mask_path = work_dir / "mask.nii.gz"
        derived_metrics = None
        if binary is not None:
            if tuple(labelmap.shape) != tuple(imaging.volume.shape):
                raise RuntimeError(
                    f"Model mask shape {tuple(labelmap.shape)} does not match source volume {tuple(imaging.volume.shape)}. "
                    "MedAxis will not resample an AI mask implicitly because that could change spatial meaning."
                )
            if not np.allclose(tuple(spacing), tuple(imaging.spacing), rtol=1e-3, atol=1e-3):
                raise RuntimeError(
                    f"Model mask spacing {tuple(spacing)} does not match source spacing {tuple(imaging.spacing)}. "
                    "MedAxis requires an explicit validated resampling contract before physical metrics are reported."
                )
            try:
                import nibabel as nib
                mask_affine = np.asarray(imaging.affine_ras, dtype=np.float64) if imaging.affine_ras is not None else np.diag([spacing[0], spacing[1], spacing[2], 1.0])
                img = nib.Nifti1Image(np.transpose(binary.astype(np.uint8), (2, 1, 0)), mask_affine)
                nib.save(img, str(mask_path))
                from .analytics import mask_metrics
                derived_metrics = mask_metrics(binary, spacing, imaging.volume)
            except Exception as exc:
                raise RuntimeError("Prediction was generated, but the selected binary mask or derived metrics could not be written.") from exc
        return {
            "analysis_id": job_id,
            "case_id": case_id,
            "analysis_type": "MONAI BUNDLE INFERENCE",
            "model_id": model_id,
            "model_name": info["display_name"],
            "model_version": info["version"],
            "model_source": info["source"],
            "publisher_benchmark": info["publisher_benchmark"],
            "validation_status": info["validation_status"],
            "structure": structure,
            "selected_label_id": selected_id,
            "device": use_device,
            "prediction_file": str(prediction),
            "output_artifact_type": "NIFTI" if prediction.name.lower().endswith((".nii", ".nii.gz")) else prediction.suffix.upper().lstrip("."),
            "mask_file": str(mask_path) if binary is not None and mask_path.exists() else None,
            "voxel_spacing_mm": list(spacing),
            "confidence": (
                "CALIBRATED RESEARCH PROBABILITY" if detections and all(d.get("confidence_status") == "CALIBRATED RESEARCH PROBABILITY" for d in detections.get("detections", []))
                else "MODEL SCORE — NOT CALIBRATED" if detections
                else "NOT AVAILABLE — bundle output was not a calibrated probability map"
            ),
            "derived_metrics": derived_metrics,
            "detections": detections,
            "note": "Research-use model inference. MedAxis has not clinically validated this model or its patient-specific output.",
        }

    runner.start(job_id, work)
    return job_id


def get_job_status(job_id: str) -> dict[str, Any] | None:
    return get_job(job_id)
