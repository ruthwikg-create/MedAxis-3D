from __future__ import annotations

import math
import json
import os
import importlib.util
import shutil
import stat
import zipfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .config import BASE_DIR, CASES_DIR, env_bool
from .services.imaging import build_demo_case, load_case, make_mpr, render_slice_png, series_summary, voxel_statistics
from .services.mesh import make_surface
from .services.storage import CaseStore
from .services import db as database
from .services.auth import auth_required, authenticate_user, create_token, hash_password, require_roles
from .services import auth as auth_service
from .services.object_storage import ObjectStorage
from .services.analytics import intensity_histogram, intensity_profile, mask_metrics, radiomics_features, tissue_bands_ct
from .services.validation import calibration_report, fit_temperature_calibration, segmentation_metrics
from .services.calibration_registry import artifact_hash, fit_platt, load_platt
from .services.cardiac import cardiac_metrics, load_4d_mask
from .services.prostate import analyze_prostate, load_nii
from .services.pirads import validate_assessment
from .services import ai as ai_service
from .services.dicom_export import dicom_source_images, export_seg, export_sr
from .services.radiomics_model import predict_binary_classifier, train_binary_classifier
from .services import synthesis
from .services.cohort_validation import cohort_metrics

DATA_DIR = CASES_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
store = CaseStore(DATA_DIR)
object_storage = ObjectStorage(DATA_DIR / "objects")
ADVANCED_MODEL_ROOT = BASE_DIR / "models"
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(512 * 1024 * 1024)))
MAX_ZIP_FILES = int(os.getenv("MAX_ZIP_FILES", "10000"))
MAX_ZIP_UNCOMPRESSED_BYTES = int(os.getenv("MAX_ZIP_UNCOMPRESSED_BYTES", str(4 * 1024 * 1024 * 1024)))

app = FastAPI(
    title="MedAxis 3D API",
    version="4.1.1",
    description="Research/educational medical imaging workstation API.",
)

allowed_origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class MeasurementRequest(BaseModel):
    case_id: str
    index: int = Field(default=0, ge=0)
    plane: str = "axial"

    @field_validator("plane")
    @classmethod
    def valid_plane(cls, value: str) -> str:
        value = value.lower().strip()
        if value not in {"axial", "sagittal", "coronal"}:
            raise ValueError("plane must be axial, sagittal, or coronal")
        return value


class ThresholdRequest(BaseModel):
    case_id: str
    lower: float
    upper: float
    label: str = Field(default="Research Threshold Mask", min_length=1, max_length=120)

    @field_validator("lower", "upper")
    @classmethod
    def finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("Threshold values must be finite numbers.")
        return value

    def validate_order(self) -> None:
        if self.lower > self.upper:
            raise HTTPException(422, detail={
                "problem": "Invalid intensity range",
                "reason": "Lower threshold is greater than upper threshold.",
                "recommended_action": "Set the lower threshold to a value less than or equal to the upper threshold.",
            })


class ReportRequest(BaseModel):
    case_id: str
    title: str = Field(default="MedAxis 3D Quantitative Imaging Report", min_length=1, max_length=180)
    user_observations: str = Field(default="", max_length=20000)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=512)


class RegisterRequest(LoginRequest):
    role: str = Field(default="viewer", min_length=3, max_length=32)


class AIInferenceRequest(BaseModel):
    case_id: str
    model_id: str
    structure: str | None = None
    device: str | None = None


class PI_RADSRequest(BaseModel):
    case_id: str
    zone: str
    t2_score: int = Field(ge=1, le=5)
    dwi_score: int = Field(ge=1, le=5)
    dce: str = "not_assessed"
    lesion_size_mm: float | None = Field(default=None, gt=0)
    final_category: int | None = Field(default=None, ge=1, le=5)
    reader: str = ""


class CalibrationRequest(BaseModel):
    probabilities: list[float]
    labels: list[int]
    bins: int = Field(default=10, ge=2, le=50)


class ModelCalibrationRequest(BaseModel):
    probabilities: list[float]
    labels: list[int]


class IntensityProfileRequest(BaseModel):
    plane: str = "axial"
    index: int = Field(default=0, ge=0)
    axis: str = "horizontal"
    max_points: int = Field(default=512, ge=32, le=4096)


@app.on_event("startup")
def startup() -> None:
    database.init_db()
    admin_user = os.getenv("BOOTSTRAP_ADMIN_USERNAME", "").strip()
    admin_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD", "").strip()
    if admin_user and admin_password:
        database.ensure_bootstrap_admin(hash_password(admin_password), admin_user)


@app.middleware("http")
async def authentication_middleware(request, call_next):
    if not auth_required() or not request.url.path.startswith("/api/"):
        return await call_next(request)
    public_prefixes = ("/api/health", "/api/auth/login", "/api/auth/register")
    if request.url.path.startswith(public_prefixes):
        return await call_next(request)
    # Role checking is performed by endpoint dependencies for privileged operations.
    # This middleware only verifies that a bearer token exists and is valid.
    from .services.auth import current_user_from_request
    try:
        current_user_from_request(request)
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return await call_next(request)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_case(case_id: str) -> Path:
    try:
        case_dir = store.case_dir(case_id)
    except ValueError as exc:
        raise HTTPException(400, detail={"problem": "Invalid case identifier", "reason": str(exc), "recommended_action": "Use a valid case identifier."}) from exc
    if case_dir.is_dir() and store.read_meta(case_id):
        return case_dir
    persisted = database.get_case(case_id) if database.persistence_enabled() else None
    if persisted:
        case_dir.mkdir(parents=True, exist_ok=True)
        store.write_meta(case_id, persisted)
        return case_dir
    raise HTTPException(404, f"Case '{case_id}' was not found.")


def _restore_raw_from_s3(case_id: str, case_dir: Path) -> None:
    if object_storage.mode != "S3":
        return
    meta = store.read_meta(case_id)
    keys = meta.get("object_storage", {}).get("keys", []) if isinstance(meta.get("object_storage"), dict) else []
    if not keys:
        return
    raw_dir = case_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"cases/{case_id}/raw/"
    root = raw_dir.resolve()
    for key in keys:
        key = str(key)
        if not key.startswith(prefix):
            continue
        relative = Path(key[len(prefix):])
        target = (raw_dir / relative).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise HTTPException(422, detail={"problem": "Stored object path is invalid", "reason": "Object storage metadata attempted to escape the case root.", "recommended_action": "Repair the case manifest before processing."}) from exc
        if target.exists():
            continue
        cached = object_storage.get_path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cached, target)


def case_imaging(case_id: str):
    case_dir = ensure_case(case_id)
    source_dir = case_dir / "raw"
    if not source_dir.exists() and object_storage.mode == "S3":
        _restore_raw_from_s3(case_id, case_dir)
    imaging = load_case(source_dir if source_dir.exists() else case_dir)
    meta = store.read_meta(case_id)
    declared = str(meta.get("study", {}).get("modality", "")).upper()
    if imaging.source_type == "nifti" and declared in {"CT", "MRI", "MR"}:
        imaging.modality = "MRI" if declared in {"MRI", "MR"} else "CT"
    return imaging


def append_provenance(case_id: str, record: dict[str, Any]) -> None:
    store.append_json_item(case_id, "provenance.json", record)


def copy_upload(upload: UploadFile, target: Path) -> int:
    total = 0
    with target.open("wb") as out:
        while True:
            chunk = upload.file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_UPLOAD_BYTES:
                raise HTTPException(413, detail={
                    "problem": "Uploaded file exceeds size limit",
                    "reason": f"The configured per-file limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MiB.",
                    "recommended_action": "Split the study into smaller uploads or increase MAX_UPLOAD_BYTES for controlled local research use.",
                })
            out.write(chunk)
    return total


def safe_extract_zip(zip_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise HTTPException(413, "ZIP archive contains too many members for the configured import limit.")
        total_uncompressed = sum(int(max(0, m.file_size)) for m in members)
        if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
            raise HTTPException(413, "ZIP archive exceeds the configured uncompressed-size limit.")
        safe_members: list[tuple[zipfile.ZipInfo, Path, str]] = []
        seen_names: set[str] = set()
        for member in members:
            member_name = member.filename.replace("\\", "/")
            if member_name in seen_names:
                raise HTTPException(400, "ZIP archive contains duplicate filenames; ambiguous extraction is not allowed.")
            seen_names.add(member_name)
            if "\x00" in member_name or member_name.startswith("/") or (len(member_name) >= 3 and member_name[1] == ":" and member_name[2] == "/"):
                raise HTTPException(400, "Unsafe ZIP filename detected during import.")
            member_mode = (member.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(member_mode):
                raise HTTPException(400, "ZIP symbolic links are not allowed during import.")
            destination_path = (destination / member_name).resolve()
            try:
                destination_path.relative_to(destination_resolved)
            except ValueError as exc:
                raise HTTPException(400, "Unsafe ZIP path detected during import.") from exc
            safe_members.append((member, destination_path, member_name))
        for member, destination_path, member_name in safe_members:
            if member.is_dir() or member_name.endswith("/"):
                destination_path.mkdir(parents=True, exist_ok=True)
                continue
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member, "r") as source, destination_path.open("wb") as target:
                shutil.copyfileobj(source, target, length=1024 * 1024)


@app.get("/api/health")
def health() -> dict[str, Any]:
    """Lightweight liveness endpoint: never import PyTorch or probe model weights.

    The frontend polls this route at startup. Full AI availability is assessed
    separately through model-specific readiness endpoints, since MONAI/Torch
    initialization may take many seconds on Windows even when the API is healthy.
    """
    from .services import imaging as imaging_service
    available = lambda package: importlib.util.find_spec(package) is not None
    return {
        "status": "ONLINE",
        "application": "MedAxis 3D",
        "version": app.version,
        "timestamp": now_iso(),
        "capabilities": {
            "dicom": imaging_service.pydicom is not None,
            "nifti": imaging_service.nib is not None,
            "mpr": True,
            "surface": True,
            # Conservative status: model readiness must be checked explicitly.
            "ai_models": False,
            "advanced_ai_runtime": False,
            "model_runtime": False,
            "ai_readiness_deferred": True,
            "advanced_dicom_seg_export": available("highdicom") and available("pydicom"),
            "advanced_dicom_sr_export": available("highdicom") and available("pydicom"),
            "cross_modality_runtime": available("torch") and available("nibabel"),
            "postgis": False,
            "highdicom": available("highdicom"),
            "postgresql": database.db_kind() == "postgresql",
            "persistence": database.persistence_enabled(),
            "s3": object_storage.mode == "S3",
            "auth": auth_required(),
        },
    }


@app.get("/api/cases")
def list_cases() -> list[dict[str, Any]]:
    return database.list_cases() if database.persistence_enabled() else store.list_cases()


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict[str, Any]:
    case_dir = ensure_case(case_id)
    return store.read_meta(case_id) if store.read_meta(case_id) else (database.get_case(case_id) or {})


@app.delete("/api/cases/{case_id}")
def delete_case(case_id: str) -> dict[str, str]:
    case_dir = ensure_case(case_id)
    store.delete_case(case_id) if case_dir.exists() else None
    if object_storage.mode == "S3":
        object_storage.delete_prefix(f"cases/{case_id}/")
    if database.persistence_enabled():
        database.delete_case(case_id)
    return {"status": "DELETED", "case_id": case_id}


@app.post("/api/cases/demo")
def create_demo() -> dict[str, Any]:
    case_id = f"demo-{uuid.uuid4().hex[:8]}"
    case_dir = store.create_case(case_id)
    try:
        requested = case_dir / "synthetic_research_phantom.nii.gz"
        imaging_path = build_demo_case(requested)
        summary = series_summary(load_case(imaging_path))
        meta = {
            "case_id": case_id,
            "status": "DEMO DATA",
            "classification": "SYNTHETIC / RESEARCH PHANTOM",
            "created_at": now_iso(),
            "study": {
                "patient_id": "DEMO-SYNTHETIC",
                "patient_name": "Synthetic Research Phantom",
                "accession_number": "DEMO",
                "study_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "study_description": "Synthetic volumetric imaging phantom — not clinical data",
                "modality": "SYNTHETIC",
                "body_region": "Research Phantom",
                "study_uid": None,
                "series_uid": None,
            },
            "files": [imaging_path.name],
            "summary": summary,
        }
        store.write_meta(case_id, meta)
        if database.persistence_enabled():
            database.upsert_case(meta)
        store.audit(case_id, "Case created", {"source": "synthetic_demo"})
        if database.persistence_enabled():
            database.audit(case_id, "Case created", {"source": "synthetic_demo"})
        append_provenance(case_id, {"timestamp": now_iso(), "case_id": case_id, "operation": "demo_create", "source": imaging_path.name, "pipeline_version": "4.1.1"})
        return meta
    except Exception:
        shutil.rmtree(case_dir, ignore_errors=True)
        raise


@app.post("/api/dicom/import")
async def import_files(files: list[UploadFile] = File(...), modality: str = Form("AUTO")) -> dict[str, Any]:
    valid = [upload for upload in files if upload.filename]
    if not valid:
        raise HTTPException(400, "No imaging files were supplied.")

    case_id = f"case-{uuid.uuid4().hex[:10]}"
    case_dir = store.create_case(case_id)
    raw_dir = case_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    saved: list[str] = []
    try:
        for upload in valid:
            source_name = Path(str(upload.filename or "upload").replace("\\", "/")).name
            safe_name = source_name or f"upload-{uuid.uuid4().hex[:8]}"
            target = raw_dir / safe_name
            if target.exists():
                target = raw_dir / f"{target.stem}-{uuid.uuid4().hex[:6]}{''.join(target.suffixes)}"
            copy_upload(upload, target)
            saved.append(target.name)
            if target.suffix.lower() == ".zip":
                extract_dir = raw_dir / f"{target.stem}_extracted"
                extract_dir.mkdir(exist_ok=True)
                safe_extract_zip(target, extract_dir)

        object_keys: list[str] = []
        if object_storage.mode == "S3":
            for raw_file in raw_dir.rglob("*"):
                if raw_file.is_file():
                    key = f"cases/{case_id}/raw/{raw_file.relative_to(raw_dir).as_posix()}"
                    object_storage.put_path(raw_file, key)
                    object_keys.append(key)
        imaging = load_case(raw_dir)
        declared_modality = modality.strip().upper()
        if imaging.source_type == "nifti":
            if declared_modality not in {"CT", "MRI", "MR", "AUTO"}:
                raise ValueError("For NIfTI input, modality must be CT, MRI, MR, or AUTO.")
            if declared_modality in {"MRI", "MR"}:
                imaging.modality = "MRI"
            elif declared_modality == "CT":
                imaging.modality = "CT"
            else:
                raise ValueError("NIfTI modality is ambiguous. Select CT or MRI before importing a NIfTI dataset used for AI/quantitative analysis.")
        elif declared_modality not in {"AUTO", imaging.modality}:
            raise ValueError(f"Declared modality {declared_modality} does not match the imported DICOM modality {imaging.modality}.")
        summary = series_summary(imaging)
    except HTTPException:
        store.audit(case_id, "Import failed", {"reason": "HTTP validation error"})
        shutil.rmtree(case_dir, ignore_errors=True)
        raise
    except Exception as exc:
        store.audit(case_id, "Import failed", {"reason": str(exc)})
        shutil.rmtree(case_dir, ignore_errors=True)
        raise HTTPException(
            422,
            detail={
                "problem": "Imaging import failed",
                "reason": str(exc),
                "recommended_action": "Select a valid DICOM series or one 3D NIfTI volume with consistent geometry.",
            },
        ) from exc

    meta = {
        "case_id": case_id,
        "status": "IMPORTED",
        "classification": "USER DATA",
        "created_at": now_iso(),
        "study": summary["study"],
        "files": saved,
        "object_storage": {"mode": object_storage.mode, "keys": object_keys},
        "summary": summary,
    }
    store.write_meta(case_id, meta)
    if database.persistence_enabled():
        database.upsert_case(meta)
    store.audit(case_id, "Case imported", {"file_count": len(saved), "source_type": imaging.source_type})
    if database.persistence_enabled():
        database.audit(case_id, "Case imported", {"file_count": len(saved), "source_type": imaging.source_type})
    append_provenance(case_id, {"timestamp": now_iso(), "case_id": case_id, "operation": "import", "input_files": saved, "source_type": imaging.source_type, "voxel_spacing": list(imaging.spacing), "input_dimensions": list(imaging.volume.shape), "pipeline_version": "4.1.1"})
    return meta


@app.get("/api/studies")
def studies() -> list[dict[str, Any]]:
    return [{"case_id": item["case_id"], **item.get("study", {})} for item in store.list_cases()]


@app.get("/api/series/{case_id}")
def series(case_id: str) -> dict[str, Any]:
    return series_summary(case_imaging(case_id))


@app.get("/api/dicom/metadata/{case_id}")
def dicom_metadata(case_id: str) -> dict[str, Any]:
    ensure_case(case_id)
    return store.read_meta(case_id).get("summary", {})


@app.get("/api/viewer/{case_id}/slice")
def viewer_slice(case_id: str, plane: str = "axial", index: Optional[int] = None, wl: Optional[float] = None, ww: Optional[float] = None):
    imaging = case_imaging(case_id)
    try:
        payload = render_slice_png(imaging, plane, index, wl, ww)
    except ValueError as exc:
        raise HTTPException(422, detail={"problem": "Slice rendering failed", "reason": str(exc), "recommended_action": "Select a valid plane/index and verify source image values."}) from exc
    return StreamingResponse(payload, media_type="image/png", headers={"X-MedAxis-Source": "actual-imported-imaging-data"})


@app.get("/api/viewer/{case_id}/mpr")
def viewer_mpr(case_id: str, z: int = 0, y: int = 0, x: int = 0, wl: Optional[float] = None, ww: Optional[float] = None):
    imaging = case_imaging(case_id)
    planes = make_mpr(imaging, z=z, y=y, x=x, wl=wl, ww=ww)
    return JSONResponse(planes)


@app.get("/api/viewer/{case_id}/volume")
def volume_data(case_id: str) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    return {
        "shape": list(imaging.volume.shape),
        "spacing": list(imaging.spacing),
        "orientation": imaging.orientation,
        "modality": imaging.modality,
        "source_type": imaging.source_type,
        "finite_voxels": int(np.isfinite(imaging.volume).sum()),
        "total_voxels": int(imaging.volume.size),
    }


@app.post("/api/measurements")
def measurements(req: MeasurementRequest) -> dict[str, Any]:
    imaging = case_imaging(req.case_id)
    try:
        stats = voxel_statistics(imaging, req.plane, req.index)
    except ValueError as exc:
        raise HTTPException(422, detail={"problem": "Measurement unavailable", "reason": str(exc), "recommended_action": "Verify source image values and geometry."}) from exc
    method = stats.pop("method")
    result = {
        "case_id": req.case_id,
        "type": "RAW / DERIVED IMAGING MEASUREMENT",
        "source": "actual imaging data",
        "method": method,
        "computed_at": now_iso(),
        "plane": req.plane,
        "index": req.index,
        "voxel_spacing_mm": list(imaging.spacing),
        **stats,
    }
    store.audit(req.case_id, "Measurement created", {"plane": req.plane, "index": req.index})
    append_provenance(req.case_id, {"timestamp": result["computed_at"], "case_id": req.case_id, "operation": "measurement", "plane": req.plane, "index": req.index, "method": method, "voxel_spacing": list(imaging.spacing)})
    return result


def require_reliable_3d_geometry(imaging) -> None:
    flags = imaging.qc_flags or {}
    problems = []
    if flags.get("geometry_incomplete"):
        problems.append("incomplete spatial metadata")
    if flags.get("duplicate_slices"):
        problems.append("duplicate slice positions")
    if flags.get("inconsistent_spacing"):
        problems.append("inconsistent slice spacing")
    if flags.get("missing_slice_gaps"):
        problems.append("missing slice gaps")
    if problems:
        raise HTTPException(422, detail={
            "problem": "3D measurement unavailable",
            "reason": "; ".join(problems) + ".",
            "recommended_action": "Select a series that passes geometry QC before calculating volume or reconstructing a 3D surface.",
        })


@app.post("/api/analysis/threshold")
def threshold_analysis(req: ThresholdRequest) -> dict[str, Any]:
    req.validate_order()
    imaging = case_imaging(req.case_id)
    require_reliable_3d_geometry(imaging)
    finite = np.isfinite(imaging.volume)
    mask = finite & (imaging.volume >= req.lower) & (imaging.volume <= req.upper)
    voxel_count = int(mask.sum())
    voxel_volume_mm3 = float(np.prod(imaging.spacing))
    volume_mm3 = voxel_count * voxel_volume_mm3
    analysis_id = f"threshold-{uuid.uuid4().hex[:10]}"
    mask_path = DATA_DIR / req.case_id / "analysis" / f"{analysis_id}-mask.nii.gz"
    mask_file = None
    try:
        import nibabel as nib
        affine = np.asarray(imaging.affine_ras, dtype=np.float64) if imaging.affine_ras is not None else np.diag([imaging.spacing[0], imaging.spacing[1], imaging.spacing[2], 1.0])
        nib.save(nib.Nifti1Image(np.transpose(mask.astype(np.uint8), (2, 1, 0)), affine), str(mask_path))
        mask_file = str(mask_path)
    except Exception:
        # Analysis remains valid, but export workflows that require a persisted binary mask will explain why the artifact is unavailable.
        mask_file = None
    result = {
        "analysis_id": analysis_id,
        "case_id": req.case_id,
        "analysis_type": "RESEARCH THRESHOLD SEGMENTATION",
        "label": req.label,
        "model": None,
        "status": "COMPLETED",
        "note": "This is an explicit research threshold algorithm, not an organ-specific clinical AI model.",
        "mask_voxel_count": voxel_count,
        "mask_file": mask_file,
        "volume_mm3": volume_mm3,
        "volume_cm3": volume_mm3 / 1000.0,
        "voxel_spacing_mm": list(imaging.spacing),
        "parameters": {"lower": req.lower, "upper": req.upper},
        "provenance": {
            "input": store.read_meta(req.case_id).get("files", []),
            "processing_pipeline_version": "research-threshold-v1",
            "timestamp": now_iso(),
        },
    }
    store.write_json(req.case_id, f"analysis-{analysis_id}.json", result)
    database.save_analysis(analysis_id, req.case_id, result["analysis_type"], "COMPLETED", result)
    database.save_analytics(req.case_id, "threshold_segmentation", result)
    append_provenance(req.case_id, {"timestamp": result["provenance"]["timestamp"], "case_id": req.case_id, "operation": "threshold_segmentation", "analysis_id": analysis_id, "parameters": result["parameters"], "voxel_spacing": list(imaging.spacing), "pipeline_version": "research-threshold-v1"})
    store.audit(req.case_id, "Analysis completed", {"analysis_id": analysis_id, "type": result["analysis_type"]})
    database.audit(req.case_id, "Analysis completed", {"analysis_id": analysis_id, "type": result["analysis_type"]})
    return result


@app.get("/api/segmentation/{case_id}")
def segmentation_status(case_id: str, structure: str = "") -> dict[str, Any]:
    ensure_case(case_id)
    candidates = [
        item for item in (ai_service.model_status(model_id) for model_id in ai_service.MODEL_CATALOG)
        if structure and structure.lower() in {str(name).lower() for name in (item.get("structures") or {})}
    ]
    return {
        "status": "AVAILABLE" if any(item.get("status") == "MODEL READY" for item in candidates) else "MODEL NOT DOWNLOADED",
        "structure": structure or "unspecified",
        "compatible_models": [{"model_id": item["model_id"], "display_name": item["display_name"], "status": item["status"], "version": item["version"]} for item in candidates],
        "message": "A compatible official MONAI bundle is ready for inference." if any(item.get("status") == "MODEL READY" for item in candidates) else "No downloaded model currently advertises this structure; use Model Manager to download a compatible official MONAI bundle.",
        "clinical_status": "NOT CLINICALLY VALIDATED BY MEDAXIS",
    }


@app.get("/api/models")
def models() -> list[dict[str, Any]]:
    """Fast catalogue listing; expensive model runtime validation is opt-in.

    The UI fetches this route when it loads, often before any model is installed.
    Importing torch/monai for each catalogue entry slows or blocks the API health
    response. Users can request /api/models/{model_id}/status for full readiness.
    """
    items: list[dict[str, Any]] = []
    for model_id, info in ai_service.MODEL_CATALOG.items():
        bundle = ai_service.model_path(model_id)
        config_dir, weights_dir = bundle / "configs", bundle / "models"
        has_config = any((config_dir / filename).is_file() for filename in (
            "inference.json", "inference.yaml", "inference.yml",
        ))
        has_weights = weights_dir.is_dir() and any(
            file.is_file() and file.suffix.lower() in {".pt", ".pth", ".ts"}
            for file in weights_dir.rglob("*")
        )
        items.append({
            "model_id": model_id,
            "model_name": info["display_name"],
            "version": info["version"],
            "modality": info["modality"],
            "body_region": info["body_region"],
            "status": "RUNTIME NOT VERIFIED" if has_config and has_weights else "MODEL NOT DOWNLOADED",
            "validation_status": info["validation_status"],
        })
    return items


@app.get("/api/models/{model_id}/status")
def model_status(model_id: str) -> dict[str, Any]:
    aliases = {"spleen-ct": "spleen_ct_segmentation"}
    resolved = aliases.get(model_id, model_id)
    try:
        result = ai_service.model_status(resolved)
        if resolved != model_id:
            result["requested_model_id"] = model_id
        return result
    except KeyError as exc:
        raise HTTPException(404, f"Unknown model '{model_id}'.") from exc


@app.get("/api/analysis/{analysis_id}")
def analysis_status(analysis_id: str) -> dict[str, Any]:
    persisted = database.get_analysis(analysis_id)
    if persisted:
        return persisted
    for meta in store.list_cases():
        case_id = meta["case_id"]
        candidate = store.read_json(case_id, f"analysis-{analysis_id}.json", default=None)
        if candidate:
            return candidate
    raise HTTPException(404, "Analysis record was not found.")


@app.get("/api/rois/{case_id}")
def list_rois(case_id: str) -> list[dict[str, Any]]:
    ensure_case(case_id)
    return store.read_json(case_id, "rois.json", default=[])


@app.post("/api/rois/{case_id}")
def save_roi(case_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_case(case_id)
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(422, "ROI payload must be a non-empty JSON object.")
    item = {"roi_id": uuid.uuid4().hex[:10], "created_at": now_iso(), **payload}
    store.append_json_item(case_id, "rois.json", item)
    store.audit(case_id, "ROI created", {"roi_id": item["roi_id"]})
    return item


@app.get("/api/provenance/{case_id}")
def provenance(case_id: str) -> list[dict[str, Any]]:
    ensure_case(case_id)
    return store.read_json(case_id, "provenance.json", default=[])


@app.get("/api/audit/{case_id}")
def audit(case_id: str) -> list[dict[str, Any]]:
    ensure_case(case_id)
    file_rows = store.read_json(case_id, "audit.json", default=[])
    db_rows = database.read_audit(case_id) if database.persistence_enabled() else []
    rows = [*(file_rows if isinstance(file_rows, list) else []), *(db_rows if isinstance(db_rows, list) else [])]
    # Keep both local and database audit evidence visible in local/research mode.
    # Deduplicate exact records when a persistence backend mirrors the same event.
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in rows:
        key = json.dumps(row, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            merged.append(row)
    merged.sort(key=lambda row: str(row.get("timestamp", "")))
    return merged


@app.get("/api/system/diagnostics")
def diagnostics() -> dict[str, Any]:
    import platform
    from .services import imaging as imaging_service
    return {
        "frontend": "ONLINE",
        "backend": "ONLINE",
        "database": "POSTGRESQL" if database.db_kind() == "postgresql" else ("SQLITE PERSISTENCE" if database.persistence_enabled() else "LOCAL FILE STORE (stateless development mode)"),
        "object_storage": object_storage.health(),
        "authentication": "REQUIRED" if auth_required() else "DISABLED (development mode)",
        # Deep AI/model readiness is assessed in /api/models/{model_id}/status.
        "ai_engine": "MODEL RUNTIME NOT PROBED (see AI Analysis for readiness)",
        "dicom_engine": "ONLINE" if imaging_service.pydicom is not None else "OFFLINE — pydicom not installed",
        "nifti_engine": "ONLINE" if imaging_service.nib is not None else "OFFLINE — nibabel not installed",
        "3d_engine": "ONLINE",
        "gpu": "NOT PROBED (AI runtime may initialize slowly)",
        "cpu": platform.processor() or platform.machine(),
        "memory": "runtime dependent",
        "storage": str(DATA_DIR.resolve()),
    }


@app.post("/api/reports")
def create_report(req: ReportRequest) -> dict[str, Any]:
    ensure_case(req.case_id)
    meta = store.read_meta(req.case_id)
    qc_result = qc(req.case_id)
    report = {
        "report_id": uuid.uuid4().hex[:12],
        "application": "MEDAXIS 3D",
        "version": app.version,
        "created_by": "Ruthwik Goparaju",
        "created_at": now_iso(),
        "classification": "Research / Educational Use",
        "title": req.title,
        "patient_case": meta.get("study", {}),
        "technique": "Derived from imported imaging data and recorded processing metadata.",
        "findings": "No unsupported clinical diagnosis is generated by this research build.",
        "user_observations": req.user_observations,
        "quality_control": qc_result,
        "provenance": store.read_json(req.case_id, "provenance.json", default=[]),
        "limitations": [
            "AI model outputs are research-use integrations; MedAxis has not clinically validated patient-specific performance.",
            "DICOM SEG/SR export requires compatible conventional DICOM source geometry and validated deployment testing.",
            "Clinical interpretation remains the responsibility of a qualified professional.",
        ],
    }
    store.write_json(req.case_id, f"report-{report['report_id']}.json", report)
    store.audit(req.case_id, "Report created", {"report_id": report["report_id"]})
    return report


@app.get("/api/export/dicom-seg/{case_id}")
def dicom_seg_help(case_id: str):
    ensure_case(case_id)
    available = bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom"))
    return {"status": "READY" if available else "NOT AVAILABLE", "method": "POST /api/export/seg/{case_id}", "note": "DICOM SEG export uses highdicom 0.28.1 and pydicom when compatible source evidence and a geometry-matched binary mask are present."}


@app.get("/api/export/dicom-sr/{case_id}")
def dicom_sr_help(case_id: str):
    ensure_case(case_id)
    available = bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom"))
    return {"status": "READY" if available else "NOT AVAILABLE", "method": "POST /api/export/sr/{case_id}", "note": "DICOM SR export uses highdicom 0.28.1 and pydicom when compatible source evidence is present."}


@app.post("/api/dicom/anonymize/{case_id}")
def anonymize_review(case_id: str) -> dict[str, Any]:
    ensure_case(case_id)
    return {
        "status": "REVIEW REQUIRED",
        "message": "A research de-identification workflow requires validated tag handling and human review before export.",
        "warning": "Pixel data may contain burned-in identifiers and requires additional review.",
        "source_case": case_id,
    }


@app.get("/api/qc/{case_id}")
def qc(case_id: str) -> dict[str, Any]:
    checks = series_summary(case_imaging(case_id)).get("qc", [])
    statuses = {c["status"] for c in checks}
    overall = "FAIL" if "ERROR" in statuses else "WARNING" if "WARNING" in statuses else "PASS"
    return {"overall": overall, "tests": checks}


@app.get("/api/3d/{case_id}/surface")
def surface(case_id: str, lower: Optional[float] = None, upper: Optional[float] = None) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    require_reliable_3d_geometry(imaging)
    if (lower is None) != (upper is None):
        raise HTTPException(422, "Both lower and upper intensity bounds must be provided together.")
    if lower is not None and upper is not None and (not math.isfinite(lower) or not math.isfinite(upper) or lower > upper):
        raise HTTPException(422, "Invalid surface intensity bounds.")
    mask = None if lower is None else (np.isfinite(imaging.volume) & (imaging.volume >= lower) & (imaging.volume <= upper))
    result = make_surface(imaging.volume, imaging.spacing, mask=mask)
    if result.get("status") == "AVAILABLE":
        append_provenance(case_id, {"timestamp": now_iso(), "case_id": case_id, "operation": "surface_reconstruction", "method": result.get("method"), "parameters": result.get("parameters", {}), "voxel_spacing": list(imaging.spacing)})
    return result




@app.post("/api/auth/login")
def auth_login(req: LoginRequest) -> dict[str, Any]:
    user = authenticate_user(req.username.strip(), req.password)
    if user is None:
        raise HTTPException(401, detail={"problem": "Authentication failed", "reason": "Username or password is incorrect.", "recommended_action": "Check credentials and try again."})
    token = create_token(user.username, user.role)
    return {"access_token": token, "token_type": "bearer", "expires_in_minutes": int(os.getenv("JWT_EXPIRE_MINUTES", "480")), "user": {"username": user.username, "role": user.role}}


@app.post("/api/auth/register")
def auth_register(req: RegisterRequest) -> dict[str, Any]:
    if not os.getenv("ALLOW_SELF_REGISTER", "false").lower() in {"1", "true", "yes", "on"}:
        raise HTTPException(403, detail={"problem": "Registration disabled", "reason": "Self-registration is disabled for this installation.", "recommended_action": "Create users through your administrator or set ALLOW_SELF_REGISTER=true for controlled research environments."})
    from sqlalchemy import select
    from .services.db import User, SessionLocal, init_db
    init_db()
    role = req.role.strip().lower()
    if role not in {"viewer", "technician", "biomedical_engineer", "researcher", "clinician", "radiologist"}:
        raise HTTPException(422, "Unsupported self-registration role.")
    with SessionLocal.begin() as session:
        if session.scalars(select(User).where(User.username == req.username.strip())).first() is not None:
            raise HTTPException(409, "Username already exists.")
        session.add(User(username=req.username.strip(), password_hash=hash_password(req.password), role=role, active=True))
    return {"status": "CREATED", "username": req.username.strip(), "role": role}


@app.get("/api/auth/me")
def auth_me(user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer", "technician", "viewer"))) -> dict[str, Any]:
    return user


@app.get("/api/advanced/models")
def advanced_models() -> list[dict[str, Any]]:
    return [ai_service.model_status(model_id) for model_id in ai_service.MODEL_CATALOG]


@app.get("/api/advanced/models/{model_id}/status")
def advanced_model_status(model_id: str) -> dict[str, Any]:
    try:
        return ai_service.model_status(model_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown model '{model_id}'.") from exc


@app.get("/api/advanced/models/{model_id}/metadata")
def advanced_model_metadata(model_id: str) -> dict[str, Any]:
    info = ai_service.model_status(model_id)
    config = info.get("config_file")
    if not config:
        raise HTTPException(404, detail={"problem": "Model metadata unavailable", "reason": "The bundle is not downloaded on this server.", "recommended_action": "Download the bundle from Model Manager first."})
    path = Path(str(config))
    try:
        if path.suffix.lower() == ".json":
            return {"model_id": model_id, "metadata_type": "inference config", "config": json.loads(path.read_text(encoding="utf-8"))}
        return {"model_id": model_id, "metadata_type": "inference config", "config_path": str(path), "message": "YAML config is present; inspect the downloaded bundle for full configuration."}
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Model metadata could not be read", "reason": str(exc), "recommended_action": "Verify the downloaded MONAI bundle is intact."}) from exc


@app.post("/api/advanced/models/{model_id}/download")
def advanced_model_download(model_id: str, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    try:
        result = ai_service.download_model(model_id)
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Model download failed", "reason": str(exc), "recommended_action": "Verify internet access, MONAI installation, and available disk space."}) from exc
    return result


@app.post("/api/ai/inference")
def advanced_inference(req: AIInferenceRequest, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    ensure_case(req.case_id)
    try:
        job_id = ai_service.start_inference(req.case_id, req.model_id, req.structure, req.device)
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "AI inference unavailable", "reason": str(exc), "recommended_action": "Download a compatible MONAI model and verify modality/sequence requirements."}) from exc
    return {"status": "QUEUED", "job_id": job_id, "requested_by": user["username"]}


@app.get("/api/jobs/{job_id}")
def advanced_job(job_id: str) -> dict[str, Any]:
    result = ai_service.get_job_status(job_id)
    if result is None:
        raise HTTPException(404, "Job was not found.")
    return result


@app.post("/api/ai/lung-nodule/{case_id}")
def lung_nodule_inference(case_id: str, device: str | None = None, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    ensure_case(case_id)
    try:
        job_id = ai_service.start_lung_nodule_inference(case_id, device)
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Lung nodule inference unavailable", "reason": str(exc), "recommended_action": "Download the official MONAI lung_nodule_ct_detection bundle and provide a LUNA16-resampled CT case."}) from exc
    return {"status": "QUEUED", "job_id": job_id, "model_id": "lung_nodule_ct_detection", "requested_by": user["username"], "note": "Research detection workflow; model score is not a clinical diagnosis."}


@app.post("/api/ai/brats")
async def brats_inference(
    t1: UploadFile = File(...),
    t1gd: UploadFile = File(...),
    t2: UploadFile = File(...),
    flair: UploadFile = File(...),
    device: str | None = Form(None),
    user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer")),
) -> dict[str, Any]:
    try:
        root = DATA_DIR.parent / "standalone-ai" / f"brats-{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        paths = []
        for name, upload in (("t1", t1), ("t1gd", t1gd), ("t2", t2), ("flair", flair)):
            safe = root / f"{name}.nii.gz"
            safe.write_bytes(await upload.read())
            paths.append(safe)
        job_id = ai_service.start_brats_inference(t1=paths[0], t1gd=paths[1], t2=paths[2], flair=paths[3], output_root=root, device=device)
        return {"status": "QUEUED", "job_id": job_id, "model_id": "brats_mri_segmentation", "requested_by": user["username"], "note": "Four-sequence BraTS research segmentation; outputs are not clinical diagnoses."}
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "BraTS inference unavailable", "reason": str(exc), "recommended_action": "Download the official BraTS bundle and supply geometry-compatible T1, T1Gd, T2 and FLAIR NIfTI files."}) from exc


@app.post("/api/analytics/radiomics")
def analytics_radiomics(case_id: str, lower: float | None = None, upper: float | None = None, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    if (lower is None) != (upper is None):
        raise HTTPException(422, "Provide both lower and upper values or neither.")
    if lower is None:
        finite = np.isfinite(imaging.volume)
        mask = finite
    else:
        if lower > upper:
            raise HTTPException(422, "Lower threshold must be <= upper threshold.")
        mask = np.isfinite(imaging.volume) & (imaging.volume >= lower) & (imaging.volume <= upper)
    result = radiomics_features(imaging.volume, mask, imaging.spacing, imaging.modality)
    result.update({"case_id": case_id, "created_at": now_iso(), "analysis_class": "RESEARCH RADIOMICS"})
    database.save_analytics(case_id, "radiomics", result)
    return result


@app.get("/api/analytics/tissue-bands/{case_id}")
def analytics_tissue_bands(case_id: str) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    if imaging.modality != "CT":
        return {"status": "NOT_APPLICABLE", "modality": imaging.modality, "message": "Universal calibrated tissue bands are not defined for MRI signal intensity; use sequence- and scanner-specific references."}
    return {"status": "EDUCATIONAL_REFERENCE", "modality": "CT", "bands": tissue_bands_ct(), "warning": "Reference bands are educational display aids and are not diagnostic thresholds."}


@app.get("/api/analytics/intensity-histogram/{case_id}")
def analytics_intensity_histogram(case_id: str, bins: int = 64) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    try:
        result = intensity_histogram(imaging.volume, bins=bins)
    except ValueError as exc:
        raise HTTPException(422, detail={"problem": "Intensity histogram unavailable", "reason": str(exc), "recommended_action": "Import a valid imaging volume containing finite voxel values."}) from exc
    result.update({"case_id": case_id, "modality": imaging.modality, "sequence_name": imaging.sequence_name, "voxel_spacing_mm": list(imaging.spacing)})
    return result


@app.post("/api/analytics/intensity-profile/{case_id}")
def analytics_intensity_profile(case_id: str, req: IntensityProfileRequest) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    try:
        result = intensity_profile(
            imaging.volume,
            plane=req.plane,
            index=req.index,
            axis=req.axis,
            max_points=req.max_points,
        )
    except ValueError as exc:
        raise HTTPException(422, detail={
            "problem": "Intensity profile unavailable",
            "reason": str(exc),
            "recommended_action": "Select a valid plane, slice index, and source volume containing finite voxels.",
        }) from exc
    result.update({"case_id": case_id, "modality": imaging.modality, "sequence_name": imaging.sequence_name, "voxel_spacing_mm": list(imaging.spacing)})
    return result


@app.get("/api/validation/calibrator/{model_id}")
def validation_calibrator_status(model_id: str) -> dict[str, Any]:
    info = ai_service.MODEL_CATALOG.get(model_id)
    if info is None:
        raise HTTPException(404, f"Unknown model '{model_id}'.")
    calibrator = load_platt(model_id, str(info["version"]))
    return {
        "model_id": model_id,
        "model_version": str(info["version"]),
        "available": calibrator is not None,
        "artifact_hash": artifact_hash(model_id) if calibrator else None,
        "method": calibrator.get("calibrator_type") if calibrator else None,
        "status": "CALIBRATOR AVAILABLE" if calibrator else "NO MODEL-MATCHED CALIBRATOR",
        "clinical_validation_status": "NOT ESTABLISHED",
    }


@app.post("/api/validation/calibrator/{model_id}")
def validation_calibrator_fit(model_id: str, req: ModelCalibrationRequest, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    info = ai_service.MODEL_CATALOG.get(model_id)
    if info is None:
        raise HTTPException(404, f"Unknown model '{model_id}'.")
    try:
        result = fit_platt(model_id, req.probabilities, req.labels, str(info["version"]))
    except ValueError as exc:
        raise HTTPException(422, detail={
            "problem": "Model calibrator fitting failed",
            "reason": str(exc),
            "recommended_action": "Supply at least 20 held-out model scores with both binary outcome classes for this exact model version.",
        }) from exc
    result["fitted_by"] = user["username"]
    return result


@app.get("/api/analytics/findings/{case_id}")
def analytics_findings(case_id: str, limit: int = 50) -> dict[str, Any]:
    ensure_case(case_id)
    analyses = database.list_analyses(case_id, limit=limit)
    findings: list[dict[str, Any]] = []
    for row in analyses:
        result = row.get("result") if isinstance(row.get("result"), dict) else row
        detections = result.get("detections") if isinstance(result, dict) else None
        if isinstance(detections, dict):
            for det in detections.get("detections", []):
                if isinstance(det, dict):
                    findings.append({
                        "type": row.get("analysis_type", "MODEL OUTPUT"),
                        "label": det.get("label"),
                        "score": det.get("score"),
                        "box": det.get("box"),
                        "model_id": result.get("model_id"),
                        "model_version": result.get("model_version"),
                        "created_at": row.get("created_at"),
                        "status": "MODEL OUTPUT — NOT A DIAGNOSIS",
                    })
    return {
        "case_id": case_id,
        "count": len(findings),
        "findings": findings,
        "method": "Only persisted model detection outputs are listed; absent model outputs produce an empty result.",
    }


@app.post("/api/validation/segmentation")
async def validation_segmentation(prediction: UploadFile = File(...), reference: UploadFile = File(...), spacing_x: float = 1.0, spacing_y: float = 1.0, spacing_z: float = 1.0, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    try:
        import nibabel as nib
        pred_path = DATA_DIR.parent / f"_validation_{uuid.uuid4().hex}_pred.nii.gz"
        ref_path = DATA_DIR.parent / f"_validation_{uuid.uuid4().hex}_ref.nii.gz"
        pred_path.write_bytes(await prediction.read())
        ref_path.write_bytes(await reference.read())
        pred = np.asarray(nib.load(str(pred_path)).get_fdata()) > 0
        ref = np.asarray(nib.load(str(ref_path)).get_fdata()) > 0
        if pred.shape != ref.shape:
            raise ValueError(f"Prediction/reference shapes differ: {pred.shape} vs {ref.shape}.")
        metrics = segmentation_metrics(np.transpose(pred, (2, 1, 0)), np.transpose(ref, (2, 1, 0)), (spacing_x, spacing_y, spacing_z))
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Validation calculation failed", "reason": str(exc), "recommended_action": "Provide two independently generated, geometry-compatible binary NIfTI masks."}) from exc
    finally:
        for candidate in locals().get("pred_path", None), locals().get("ref_path", None):
            try:
                if candidate is not None:
                    Path(candidate).unlink(missing_ok=True)
            except Exception:
                pass
    metrics.update({"status": "MEASURED", "validation_claim": "RESEARCH METRICS ONLY", "calculation_time": now_iso()})
    return metrics


@app.post("/api/validation/calibration")
def validation_calibration(req: CalibrationRequest, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    try:
        return calibration_report(req.probabilities, req.labels, req.bins)
    except ValueError as exc:
        raise HTTPException(422, detail={"problem": "Calibration analysis failed", "reason": str(exc), "recommended_action": "Supply held-out model probabilities paired with binary reference outcomes."}) from exc


@app.post("/api/validation/calibration/fit")
def validation_calibration_fit(req: CalibrationRequest, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    try:
        return fit_temperature_calibration(req.probabilities, req.labels)
    except ValueError as exc:
        raise HTTPException(422, detail={"problem": "Calibration fitting failed", "reason": str(exc), "recommended_action": "Supply paired model probabilities and binary reference outcomes from a research calibration cohort."}) from exc


@app.post("/api/validation/segmentation-cohort")
async def validation_segmentation_cohort(bundle_file: UploadFile = File(...), user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    temp_root = DATA_DIR.parent / f"_validation_cohort_{uuid.uuid4().hex}"
    archive = temp_root.with_suffix(".zip")
    try:
        temp_root.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(await bundle_file.read())
        extract_dir = temp_root / "cohort"
        safe_extract_zip(archive, extract_dir)
        manifest = next(iter(sorted(extract_dir.rglob("manifest.csv"))), None)
        if manifest is None:
            raise ValueError("Validation ZIP must contain manifest.csv with case_id,prediction,reference columns.")
        import csv
        pairs = list(csv.DictReader(manifest.read_text(encoding="utf-8-sig").splitlines()))
        required = {"case_id", "prediction", "reference"}
        if not pairs or not required.issubset(pairs[0].keys()):
            raise ValueError("manifest.csv requires columns: case_id,prediction,reference.")
        result = cohort_metrics(pairs, extract_dir)
        result["archive_name"] = bundle_file.filename
        return result
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Cohort validation failed", "reason": str(exc), "recommended_action": "Upload a ZIP containing manifest.csv plus geometry-compatible prediction/reference NIfTI masks."}) from exc
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(temp_root, ignore_errors=True)


@app.post("/api/cardiac/analyze")
async def cardiac_analyze(mask_file: UploadFile = File(...), case_id: str | None = None, lv_label: int = 1, myocardium_label: int = 2, rv_label: int = 3, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher"))) -> dict[str, Any]:
    path = DATA_DIR.parent / f"_cardiac_{uuid.uuid4().hex}.nii.gz"
    try:
        path.write_bytes(await mask_file.read())
        mask, spacing = load_4d_mask(path)
        result = cardiac_metrics(mask, spacing, lv_label, rv_label, myocardium_label)
        result["analysis_class"] = "CARDIAC MRI RESEARCH"
        result["created_at"] = now_iso()
        if case_id:
            case = ensure_case(case_id)
            case_modality = str((case.get("study") or {}).get("modality") or "").upper()
            if case_modality not in {"MRI", "MR"}:
                raise ValueError(f"Cardiac MRI analysis requires an MRI case; selected case is {case_modality or 'UNKNOWN'}.")
            result["case_id"] = case_id
            database.save_analytics(case_id, "cardiac_lv_rv", result)
            database.audit(case_id, "Cardiac MRI analysis completed", {"user": user["username"]})
        return result
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Cardiac MRI analysis failed", "reason": str(exc), "recommended_action": "Supply a 4D short-axis cine segmentation NIfTI with LV/myocardium/RV labels."}) from exc
    finally:
        path.unlink(missing_ok=True)


@app.post("/api/prostate/analyze")
async def prostate_analyze(image_file: UploadFile = File(...), mask_file: UploadFile = File(...), adc_file: UploadFile | None = File(None), t2_file: UploadFile | None = File(None), case_id: str | None = None, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher"))) -> dict[str, Any]:
    paths: list[Path] = []
    try:
        def save_upload(prefix: str, upload: UploadFile) -> Path:
            path = DATA_DIR.parent / f"_{prefix}_{uuid.uuid4().hex}.nii.gz"
            path.write_bytes(upload.file.read())
            paths.append(path)
            return path
        image_path = save_upload("prostate_image", image_file)
        mask_path = save_upload("prostate_mask", mask_file)
        image, spacing = load_nii(image_path)
        mask, mask_spacing = load_nii(mask_path)
        if not np.allclose(spacing, mask_spacing, rtol=1e-4, atol=1e-4):
            raise ValueError("Prostate image and mask voxel spacing differ.")
        adc = load_nii(save_upload("prostate_adc", adc_file))[0] if adc_file else None
        t2 = load_nii(save_upload("prostate_t2", t2_file))[0] if t2_file else None
        result = analyze_prostate(image, mask, spacing, adc=adc, t2=t2)
        if case_id:
            case = ensure_case(case_id)
            case_modality = str((case.get("study") or {}).get("modality") or "").upper()
            if case_modality not in {"MRI", "MR"}:
                raise ValueError(f"Prostate MRI analysis requires an MRI case; selected case is {case_modality or 'UNKNOWN'}.")
            result["case_id"] = case_id
            database.save_analytics(case_id, "prostate_analysis", result)
            database.audit(case_id, "Prostate MRI analysis completed", {"user": user["username"]})
        return result
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Prostate MRI analysis failed", "reason": str(exc), "recommended_action": "Provide geometry-compatible prostate MRI and segmentation volumes; ADC/T2 are optional."}) from exc
    finally:
        for path in paths:
            path.unlink(missing_ok=True)


@app.post("/api/pi-rads/{case_id}")
def pirads(case_id: str, req: PI_RADSRequest, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician"))) -> dict[str, Any]:
    if case_id != req.case_id:
        raise HTTPException(400, "Case identifier mismatch.")
    try:
        result = validate_assessment(req.model_dump())
    except (ValueError, KeyError) as exc:
        raise HTTPException(422, detail={"problem": "PI-RADS assessment invalid", "reason": str(exc), "recommended_action": "Complete the structured PI-RADS v2.1 fields."}) from exc
    result.update({"case_id": case_id, "created_at": now_iso(), "entered_by": user["username"]})
    database.save_analytics(case_id, "pi_rads", result)
    return result


@app.get("/api/comparison")
def comparison(case_ids: str) -> dict[str, Any]:
    requested = [item.strip() for item in case_ids.split(",") if item.strip()]
    if len(requested) < 2:
        raise HTTPException(422, "Provide at least two case IDs separated by commas.")
    records = []
    for cid in requested:
        ensure_case(cid)
        meta = store.read_meta(cid) or database.get_case(cid) or {}
        analytics_rows = database.list_analytics(cid)
        latest: dict[str, Any] = {}
        for row in analytics_rows:
            for metric in ("volume_cm3", "volume_mm3", "surface_area_mm2", "mean_intensity", "median_intensity", "stroke_volume_cm3", "ejection_fraction_percent"):
                if metric in row and isinstance(row[metric], (int, float)) and metric not in latest:
                    latest[metric] = float(row[metric])
        records.append({"case_id": cid, "study": meta.get("study", {}), "summary": meta.get("summary", {}), "latest_compatible_metrics": latest})
    changes: list[dict[str, Any]] = []
    baseline = records[0].get("latest_compatible_metrics", {})
    for current in records[1:]:
        current_metrics = current.get("latest_compatible_metrics", {})
        delta: dict[str, Any] = {}
        for metric, base_value in baseline.items():
            current_value = current_metrics.get(metric)
            if isinstance(current_value, (int, float)):
                change = float(current_value) - float(base_value)
                delta[metric] = {"baseline": float(base_value), "current": float(current_value), "absolute_change": change, "relative_change_percent": (change / float(base_value) * 100.0) if base_value != 0 else None}
        changes.append({"baseline_case_id": records[0]["case_id"], "current_case_id": current["case_id"], "changes": delta})
    return {"status": "READY", "cases": records, "changes": changes, "method": "Pairwise comparison of compatible numeric analytics records saved by MedAxis. Changes are not reported for missing or incompatible metrics."}



def _analysis_mask_for_export(case_id: str, analysis_id: str | None, imaging) -> tuple[np.ndarray, str]:
    if analysis_id:
        result = database.get_analysis(analysis_id)
        if result is None:
            # Legacy file record fallback
            result = store.read_json(case_id, f"analysis-{analysis_id}.json", default=None)
        if result is None:
            raise HTTPException(404, f"Analysis '{analysis_id}' was not found.")
        mask_file = result.get("mask_file") if isinstance(result, dict) else None
        if not mask_file:
            raise HTTPException(422, detail={"problem": "Export mask unavailable", "reason": "The selected analysis does not contain a binary mask artifact.", "recommended_action": "Run a segmentation analysis that produces a geometry-matched binary mask before exporting."})
        try:
            import nibabel as nib
            mask_path = Path(str(mask_file)).expanduser().resolve()
            case_root = (DATA_DIR / case_id).resolve()
            try:
                mask_path.relative_to(case_root)
            except ValueError as exc:
                raise ValueError("Analysis mask artifact is outside the selected case directory.") from exc
            nii = nib.load(str(mask_path))
            arr = np.asarray(nii.get_fdata())
            if arr.ndim != 3:
                raise ValueError(f"Mask artifact has unsupported shape {arr.shape}.")
            mask = np.transpose(arr > 0, (2, 1, 0))
            if tuple(mask.shape) != tuple(imaging.volume.shape):
                raise ValueError(f"Mask shape {mask.shape} does not match source volume {imaging.volume.shape}.")
            return mask.astype(bool), str(result.get("model_id") or result.get("analysis_type") or "analysis")
        except Exception as exc:
            raise HTTPException(422, detail={"problem": "Analysis mask could not be loaded", "reason": str(exc), "recommended_action": "Use a NIfTI mask produced on the same voxel grid as the DICOM source series."}) from exc
    finite = np.isfinite(imaging.volume)
    if not finite.any():
        raise HTTPException(422, detail={"problem": "Research-derived export mask unavailable", "reason": "The source volume contains no finite voxels.", "recommended_action": "Select a valid imaging series."})
    mask = finite & (imaging.volume >= np.percentile(imaging.volume[finite], 75))
    return mask, "research-threshold-v1"

@app.post("/api/export/seg/{case_id}")
def advanced_export_seg(case_id: str, structure: str = "spleen", analysis_id: str | None = None, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher"))):
    case_dir = ensure_case(case_id)
    imaging = case_imaging(case_id)
    if imaging.source_type != "dicom":
        raise HTTPException(422, detail={"problem": "DICOM SEG export unavailable", "reason": "SEG requires a conventional DICOM source series and a geometry-matched mask.", "recommended_action": "Import a conventional DICOM series and run an analysis that generates a geometry-matched mask."})
    try:
        sources = dicom_source_images(case_dir / "raw" if (case_dir / "raw").exists() else case_dir)
        mask, mask_source = _analysis_mask_for_export(case_id, analysis_id, imaging)
        if tuple(mask.shape) != (len(sources), int(sources[0].Rows), int(sources[0].Columns)):
            raise ValueError("Derived or AI mask does not match the DICOM source geometry.")
        path = case_dir / "exports" / f"medaxis-{structure}-seg.dcm"
        result = export_seg(sources, mask, path, structure, algorithm_type="AUTOMATIC")
        database.audit(case_id, "DICOM SEG exported", {"structure": structure, "path": str(path), "mask_source": mask_source, "analysis_id": analysis_id, "user": user["username"]})
        return FileResponse(path, media_type="application/dicom", filename=path.name, headers={"X-MedAxis-Export-Status": "EXPORTED", "X-MedAxis-Structure": structure, "X-MedAxis-Mask-Source": mask_source})
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "DICOM SEG export failed", "reason": str(exc), "recommended_action": "Verify conventional single-frame DICOM geometry and a matching binary mask."}) from exc


@app.post("/api/export/sr/{case_id}")
def advanced_export_sr(case_id: str, analysis_id: str | None = None, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher"))):
    case_dir = ensure_case(case_id)
    imaging = case_imaging(case_id)
    if imaging.source_type != "dicom":
        raise HTTPException(422, detail={"problem": "DICOM SR export unavailable", "reason": "This exporter requires conventional DICOM source evidence.", "recommended_action": "Import a conventional DICOM series before exporting SR."})
    try:
        sources = dicom_source_images(case_dir / "raw" if (case_dir / "raw").exists() else case_dir)
        mask, mask_source = _analysis_mask_for_export(case_id, analysis_id, imaging)
        derived = mask_metrics(mask, imaging.spacing, imaging.volume)
        path = case_dir / "exports" / "medaxis-quantitative-sr.dcm"
        export_sr(sources, {"volume_mm3": float(derived["volume_mm3"]), "surface_area_mm2": float(derived["surface_area_mm2"]) if derived.get("surface_area_mm2") is not None else None}, path)
        database.audit(case_id, "DICOM SR exported", {"path": str(path), "mask_source": mask_source, "analysis_id": analysis_id, "user": user["username"]})
        return FileResponse(path, media_type="application/dicom", filename=path.name, headers={"X-MedAxis-Export-Status": "EXPORTED"})
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "DICOM SR export failed", "reason": str(exc), "recommended_action": "Verify conventional DICOM evidence and highdicom installation."}) from exc


@app.post("/api/radiomics/classifier/train")
async def radiomics_classifier_train(training_csv: UploadFile = File(...), model_id: str = "radiomics-research", user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    path = DATA_DIR.parent / f"_training_{uuid.uuid4().hex}.csv"
    try:
        path.write_bytes(await training_csv.read())
        return train_binary_classifier(path, model_id)
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Radiomics classifier training failed", "reason": str(exc), "recommended_action": "Provide a labeled research CSV with a binary label and numeric radiomics features."}) from exc
    finally:
        path.unlink(missing_ok=True)


class RadiomicsPredictionRequest(BaseModel):
    features: dict[str, float]


@app.post("/api/radiomics/classifier/predict")
def radiomics_classifier_predict(model_id: str, req: RadiomicsPredictionRequest, user: dict[str, Any] = Depends(require_roles("administrator", "radiologist", "clinician", "researcher", "biomedical_engineer"))) -> dict[str, Any]:
    try:
        return predict_binary_classifier(model_id, req.features)
    except Exception as exc:
        raise HTTPException(422, detail={"problem": "Radiomics classifier prediction unavailable", "reason": str(exc), "recommended_action": "Train or install a compatible research classifier with the required feature schema."}) from exc


@app.get("/api/analytics/history/{case_id}")
def analytics_history(case_id: str) -> list[dict[str, Any]]:
    ensure_case(case_id)
    return database.list_analytics(case_id)


@app.get("/api/research/validation/status")
def validation_status() -> dict[str, Any]:
    return {"status": "READY FOR RESEARCH EVALUATION", "clinical_validation": "NOT ESTABLISHED", "required_evidence": ["independent reference standard", "predefined protocol", "locked model/version", "representative test cohort", "prospective/retrospective study design as appropriate", "statistical analysis", "documented acceptance criteria"], "note": "Software can calculate validation metrics; it cannot create clinical validation merely by enabling this endpoint."}


@app.get("/api/auth/users")
def list_users(user: dict[str, Any] = Depends(require_roles("administrator"))) -> list[dict[str, Any]]:
    from sqlalchemy import select
    from .services.db import SessionLocal, User
    database.init_db()
    with SessionLocal() as session:
        rows = session.scalars(select(User).order_by(User.username.asc())).all()
        return [{"id": row.id, "username": row.username, "role": row.role, "active": row.active, "created_at": row.created_at.isoformat()} for row in rows]


@app.post("/api/auth/users")
def create_user_admin(req: RegisterRequest, user: dict[str, Any] = Depends(require_roles("administrator"))) -> dict[str, Any]:
    from sqlalchemy import select
    from .services.db import SessionLocal, User
    role = req.role.strip().lower()
    if role not in {"administrator", "viewer", "technician", "biomedical_engineer", "researcher", "clinician", "radiologist"}:
        raise HTTPException(422, "Unsupported role.")
    username = req.username.strip()
    if not username:
        raise HTTPException(422, "Username is required.")
    database.init_db()
    with SessionLocal.begin() as session:
        if session.scalars(select(User).where(User.username == username)).first() is not None:
            raise HTTPException(409, "Username already exists.")
        session.add(User(username=username, password_hash=hash_password(req.password), role=role, active=True))
    return {"status": "CREATED", "username": username, "role": role, "created_by": user["username"]}


@app.patch("/api/auth/users/{username}")
def update_user_admin(username: str, active: bool | None = None, role: str | None = None, user: dict[str, Any] = Depends(require_roles("administrator"))) -> dict[str, Any]:
    from sqlalchemy import select
    from .services.db import SessionLocal, User
    if role is not None and role not in {"administrator", "viewer", "technician", "biomedical_engineer", "researcher", "clinician", "radiologist"}:
        raise HTTPException(422, "Unsupported role.")
    database.init_db()
    with SessionLocal.begin() as session:
        row = session.scalars(select(User).where(User.username == username)).first()
        if row is None:
            raise HTTPException(404, "User not found.")
        if username == user["username"] and active is False:
            raise HTTPException(400, "An administrator cannot deactivate their own account.")
        if active is not None:
            row.active = active
        if role is not None:
            row.role = role
        return {"status": "UPDATED", "username": row.username, "role": row.role, "active": row.active}


@app.get("/api/advanced/synthesis/status")
def synthesis_status() -> dict[str, Any]:
    return synthesis.status()


@app.post("/api/advanced/synthesis/ct-to-mri/{case_id}")
def ct_to_mri(case_id: str, user: dict[str, Any] = Depends(require_roles("administrator", "researcher", "biomedical_engineer"))):
    ensure_case(case_id)
    path = DATA_DIR / case_id / "synthesis" / f"ct-to-mri-{uuid.uuid4().hex[:10]}.nii.gz"
    try:
        result = synthesis.run(case_id, path)
        database.save_analytics(case_id, "cross_modality_synthesis", result)
        database.audit(case_id, "CT to MRI synthesis completed", {"user": user["username"], "output": str(path)})
        return FileResponse(path, media_type="application/gzip", filename=path.name, headers={"X-MedAxis-Synthesis": "RESEARCH-GENERATED-NOT-ACQUIRED-MRI"})
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(422, detail={"problem": "CT→MRI synthesis unavailable", "reason": str(exc), "recommended_action": "Configure and validate a compatible TorchScript model through CROSS_MODALITY_MODEL_PATH before using image-to-image synthesis."}) from exc


@app.get("/api/system/readiness")
def system_readiness() -> dict[str, Any]:
    """Detailed, non-ambiguous runtime readiness for production/research deployment."""
    package_status = {name: bool(importlib.util.find_spec(name)) for name in (
        "pydicom", "nibabel", "SimpleITK", "monai", "torch", "highdicom", "sqlalchemy", "boto3", "pwdlib"
    )}
    postgres_ready = database.db_kind() == "postgresql"
    s3_ready = object_storage.mode == "S3"
    configured_model_count = sum(1 for mid in ai_service.MODEL_CATALOG if ai_service.model_status(mid).get("inference_ready"))
    return {
        "status": "READY" if all(package_status.get(k, False) for k in ("pydicom", "nibabel", "SimpleITK", "sqlalchemy")) else "DEGRADED",
        "classification": "RESEARCH / EDUCATIONAL USE",
        "clinical_validation": "NOT ESTABLISHED",
        "packages": package_status,
        "database": {"backend": database.db_kind(), "production_ready": postgres_ready},
        "object_storage": {"mode": object_storage.mode, "production_ready": s3_ready},
        "monai": {"runtime_ready": ai_service.monai_available(), "models_ready": configured_model_count},
        "dicom_export": {"seg": bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom")), "sr": bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom"))},
        "synthesis": synthesis.status(),
        "note": "Production-capable integrations are configuration- and validation-dependent. This endpoint does not certify clinical safety, efficacy, or regulatory compliance.",
    }


@app.get("/api/analytics/capabilities")
def analytics_capabilities() -> dict[str, Any]:
    ready_models = [ai_service.model_status(model_id) for model_id in ai_service.MODEL_CATALOG]
    return {
        "structural_mapping": True,
        "tissue_characterization": True,
        "disease_detection": any(m.get("kind") == "detection" and m.get("input_type") == "volume" and m.get("status") == "MODEL READY" for m in ready_models),
        "radiomics": True,
        "segmentation": any(m.get("kind") == "segmentation" and m.get("status") == "MODEL READY" for m in ready_models),
        "cardiac_lv_rv": True,
        "prostate_analysis": True,
        "pi_rads_v2_1_worksheet": True,
        "dicom_seg": bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom")),
        "dicom_sr": bool(importlib.util.find_spec("highdicom")) and bool(importlib.util.find_spec("pydicom")),
        "monai_runtime": ai_service.monai_available(),
        "cohort_validation": True,
        "probability_calibration": True,
        "postgresql": database.db_kind() == "postgresql",
        "s3": object_storage.mode == "S3",
        "cross_modality_synthesis": synthesis.status(),
        "clinical_validation": "NOT ESTABLISHED",
        "ready_models": [{"model_id": m["model_id"], "status": m["status"], "input_type": m.get("input_type"), "generic_inference": m.get("generic_inference", False)} for m in ready_models],
        "research_radiomics_classifier": True,
        "pi_rads_guideline_calculator": True,
        "pi_rads_automated_ai": False,
    }


@app.get("/api/analytics/dataset-profile/{case_id}")
def dataset_profile(case_id: str) -> dict[str, Any]:
    imaging = case_imaging(case_id)
    finite = imaging.volume[np.isfinite(imaging.volume)]
    if finite.size == 0:
        raise HTTPException(422, detail={"problem": "Dataset profile unavailable", "reason": "The source volume contains no finite voxels.", "recommended_action": "Import a valid imaging volume."})
    percentiles = {str(q): float(np.percentile(finite, q)) for q in (1, 5, 25, 50, 75, 95, 99)}
    return {
        "case_id": case_id,
        "status": "MEASURED",
        "modality": imaging.modality,
        "sequence_name": imaging.sequence_name,
        "shape_zyx": list(imaging.volume.shape),
        "spacing_xyz_mm": list(imaging.spacing),
        "finite_voxels": int(finite.size),
        "intensity_range": [float(finite.min()), float(finite.max())],
        "mean": float(finite.mean()),
        "std": float(finite.std()),
        "percentiles": percentiles,
        "source": "actual imported imaging data",
        "note": "MRI signal intensity remains sequence/scanner dependent; CT values are source-derived and require valid calibration metadata for HU interpretation.",
    }


@app.get("/api/analytics/longitudinal/{case_id}")
def longitudinal(case_id: str) -> dict[str, Any]:
    ensure_case(case_id)
    rows = database.list_analytics(case_id)
    return {"case_id": case_id, "history": rows, "record_count": len(rows), "note": "Use /api/comparison with two or more compatible case IDs for cross-study comparison. Metrics are only compared when methodologies are compatible."}


@app.get("/api/role-matrix")
def role_matrix() -> dict[str, Any]:
    return {"roles": sorted(auth_service.ROLES), "permissions": {
        "administrator": ["all configured operations", "user management"],
        "radiologist": ["viewer", "measurements", "AI inference", "prostate/cardiac review", "DICOM SEG/SR export"],
        "clinician": ["viewer", "measurements", "AI inference", "specialty review", "DICOM SEG/SR export"],
        "researcher": ["viewer", "analysis", "model management", "validation", "radiomics", "synthesis"],
        "biomedical_engineer": ["viewer", "analysis", "model management", "validation", "system configuration"],
        "technician": ["viewer", "case/import operations"],
        "viewer": ["read-only review"],
    }, "status": "CONFIGURABLE RBAC — deployment policy remains administrator-controlled"}


@app.get("/api/analytics/clinical-status")
def analytics_clinical_status() -> dict[str, Any]:
    return {
        "application_status": "RESEARCH / EDUCATIONAL",
        "clinical_validation": "NOT ESTABLISHED",
        "regulatory_status": "NOT CLAIMED",
        "ai_patient_specific_validation": "NOT ESTABLISHED",
        "note": "Validation evidence must be generated on representative independent data under a predefined protocol; code does not create clinical validation.",
    }

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    content = exc.detail if isinstance(exc.detail, (dict, list, str, int, float, bool)) else str(exc.detail)
    return JSONResponse(status_code=exc.status_code, content=content)
