from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

try:
    import nibabel as nib
except Exception:  # pragma: no cover - optional until dependency installation
    nib = None

try:
    import pydicom
except Exception:  # pragma: no cover - optional until dependency installation
    pydicom = None


@dataclass
class ImagingData:
    """Normalized imaging volume with array axes ordered z, y, x."""

    volume: np.ndarray
    spacing: tuple[float, float, float]  # x, y, z in mm
    modality: str
    orientation: str
    patient_id: str | None = None
    patient_name: str | None = None
    study_uid: str | None = None
    series_uid: str | None = None
    accession_number: str | None = None
    study_date: str | None = None
    study_description: str | None = None
    sequence_name: str | None = None
    body_region: str | None = None
    institution: str | None = None
    referring_physician: str | None = None
    slice_thickness: float | None = None
    pixel_spacing: tuple[float, float] | None = None  # x, y in mm
    source_type: str = "unknown"
    photometric_interpretation: str | None = None
    qc_flags: dict[str, Any] | None = None
    file_count: int = 0
    slice_count: int = 0
    series_count: int = 1
    affine_ras: list[list[float]] | None = None


def _text(ds: Any, name: str) -> str | None:
    value = getattr(ds, name, None)
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def build_demo_case(path: Path) -> Path:
    """Build a clearly-labelled synthetic research phantom.

    NIfTI is preferred. A private NPZ fallback keeps the demo usable when the
    optional nibabel package is not installed in an audit/dev environment.
    """

    z, y, x = 96, 160, 160
    zz, yy, xx = np.mgrid[-1:1:complex(z), -1:1:complex(y), -1:1:complex(x)]
    outer = (xx / 0.92) ** 2 + (yy / 0.75) ** 2 + (zz / 0.92) ** 2
    organ_a = ((xx + 0.25) / 0.31) ** 2 + ((yy + 0.05) / 0.34) ** 2 + ((zz - 0.05) / 0.48) ** 2
    organ_b = ((xx - 0.32) / 0.22) ** 2 + ((yy + 0.08) / 0.25) ** 2 + ((zz + 0.14) / 0.35) ** 2

    volume = np.zeros((z, y, x), dtype=np.float32)
    volume[outer < 1] = 60
    volume[organ_a < 1] = 140
    volume[organ_b < 1] = 210
    rng = np.random.default_rng(42)
    volume += rng.normal(0, 7, volume.shape).astype(np.float32)

    path.parent.mkdir(parents=True, exist_ok=True)
    spacing = np.array([1.25, 1.25, 1.5], dtype=np.float32)
    if nib is not None:
        # ImagingData uses normalized z, y, x array order. NIfTI stores its
        # spatial axes as x, y, z, so transpose before writing; the loader
        # transposes back to the normalized viewer convention.
        nifti_volume = np.transpose(volume, (2, 1, 0))
        affine = np.diag([float(spacing[0]), float(spacing[1]), float(spacing[2]), 1.0])
        img = nib.Nifti1Image(nifti_volume, affine)
        img.header["descrip"] = b"MEDAXIS SYNTHETIC RESEARCH PHANTOM - NOT CLINICAL DATA"
        target = path if path.name.endswith((".nii", ".nii.gz")) else path.with_suffix(".nii.gz")
        nib.save(img, str(target))
        return target

    target = path.with_suffix(".npz") if path.name.endswith((".nii", ".nii.gz")) else path
    np.savez_compressed(target, volume=volume, spacing=spacing, modality="SYNTHETIC")
    return target


def _load_npz_demo(path: Path) -> ImagingData:
    with np.load(path, allow_pickle=False) as data:
        if "volume" not in data or "spacing" not in data:
            raise ValueError("Synthetic NPZ is missing required volume/spacing arrays.")
        volume = np.asarray(data["volume"], dtype=np.float32)
        spacing = tuple(float(x) for x in np.asarray(data["spacing"]).reshape(-1)[:3])
    if volume.ndim != 3 or len(spacing) != 3 or not all(np.isfinite(spacing)) or min(spacing) <= 0:
        raise ValueError("Synthetic demo geometry is invalid.")
    return ImagingData(
        volume=volume,
        spacing=spacing,  # type: ignore[arg-type]
        modality="SYNTHETIC",
        orientation="synthetic Cartesian axes",
        source_type="synthetic",
        photometric_interpretation="MONOCHROME2",
        file_count=1,
        slice_count=int(volume.shape[0]),
    )


def _load_nifti(path: Path) -> ImagingData:
    if nib is None:
        raise RuntimeError("NIfTI support requires nibabel. Install backend requirements first.")

    nii = nib.load(str(path))
    if len(nii.shape) != 3:
        raise ValueError(f"NIfTI image must be exactly 3D; received shape {tuple(nii.shape)}.")
    canon = nib.as_closest_canonical(nii)
    data = np.asarray(canon.get_fdata(dtype=np.float32))
    if data.ndim != 3:
        raise ValueError("NIfTI volume is not 3D after canonical reorientation.")
    zooms = tuple(float(v) for v in canon.header.get_zooms()[:3])
    if len(zooms) != 3 or not all(np.isfinite(zooms)) or min(zooms) <= 0:
        raise ValueError("NIfTI voxel spacing is missing or invalid.")
    if not np.isfinite(data).any():
        raise ValueError("NIfTI volume contains no finite voxel values.")

    return ImagingData(
        volume=np.transpose(data, (2, 1, 0)),
        spacing=(zooms[0], zooms[1], zooms[2]),
        modality="NIFTI",
        orientation="canonical RAS (reoriented for viewer)",
        source_type="nifti",
        photometric_interpretation="MONOCHROME2",
        file_count=1,
        slice_count=int(data.shape[2]),
        pixel_spacing=(zooms[0], zooms[1]),
        slice_thickness=zooms[2],
        affine_ras=np.asarray(getattr(canon, "affine", np.eye(4)), dtype=np.float64).tolist(),
    )


def _is_dicom_file(path: Path) -> bool:
    if pydicom is None or not path.is_file():
        return False
    try:
        ds = pydicom.dcmread(str(path), stop_before_pixels=True, force=True)
        return hasattr(ds, "SOPClassUID") and (hasattr(ds, "PixelData") or (hasattr(ds, "Rows") and hasattr(ds, "Columns")))
    except Exception:
        return False


def _direction_from_iop(value: Any) -> tuple[np.ndarray, np.ndarray, np.ndarray] | None:
    try:
        vals = np.asarray([float(v) for v in value], dtype=np.float64)
        if vals.size != 6:
            return None
        row = vals[:3]
        col = vals[3:]
        row /= np.linalg.norm(row)
        col /= np.linalg.norm(col)
        normal = np.cross(row, col)
        normal /= np.linalg.norm(normal)
        if not (np.all(np.isfinite(row)) and np.all(np.isfinite(col)) and np.all(np.isfinite(normal))):
            return None
        if abs(float(np.dot(row, col))) > 1e-3:
            return None
        return row, col, normal
    except Exception:
        return None


def _load_dicom_dir(path: Path) -> ImagingData:
    if pydicom is None:
        raise RuntimeError("DICOM support requires pydicom. Install backend requirements first.")

    candidates = [p for p in path.rglob("*") if p.is_file() and _is_dicom_file(p)]
    if not candidates:
        raise ValueError("No readable DICOM image files were found.")

    datasets: list[tuple[Path, Any]] = []
    decode_errors: list[str] = []
    for file_path in candidates:
        try:
            ds = pydicom.dcmread(str(file_path), force=True)
            if not hasattr(ds, "PixelData"):
                continue
            if str(getattr(ds, "PhotometricInterpretation", "MONOCHROME2")).upper() not in {"MONOCHROME1", "MONOCHROME2"}:
                decode_errors.append(f"Unsupported photometric interpretation in {file_path.name}.")
                continue
            datasets.append((file_path, ds))
        except Exception as exc:
            decode_errors.append(f"{file_path.name}: {exc}")

    if not datasets:
        detail = f" {decode_errors[0]}" if decode_errors else ""
        raise ValueError(f"DICOM files were detected but no supported pixel data could be decoded.{detail}")

    series_uid_values = [_text(ds, "SeriesInstanceUID") for _, ds in datasets]
    known_series_uids = {value for value in series_uid_values if value is not None}
    if len(known_series_uids) > 1 or (known_series_uids and any(value is None for value in series_uid_values)):
        raise ValueError("Mixed or incomplete SeriesInstanceUID metadata detected; select one geometrically consistent series.")

    first_ds = datasets[0][1]
    modality = (_text(first_ds, "Modality") or "DICOM").upper()
    if modality not in {"CT", "MR"}:
        # The viewer can decode other grayscale objects, but clearly labels them as unsupported for modality-specific analysis.
        modality = modality or "DICOM"

    # Validate that all slices are single-frame 2D grayscale images.
    shapes: list[tuple[int, int]] = []
    for _, ds in datasets:
        arr_shape = tuple(int(v) for v in ds.pixel_array.shape)
        if len(arr_shape) != 2:
            raise ValueError("Enhanced/multiframe DICOM objects are not supported by this reference volume loader. Use a conventional single-frame series.")
        shapes.append(arr_shape)
    if len(set(shapes)) != 1:
        raise ValueError("Inconsistent DICOM image dimensions detected across slices.")

    # Pixel spacing must be explicit; 1.0 mm defaults would fabricate calibration.
    spacing_values: list[tuple[float, float]] = []
    for _, ds in datasets:
        ps = getattr(ds, "PixelSpacing", None)
        if ps is None or len(ps) < 2:
            raise ValueError("PixelSpacing metadata is missing; calibrated measurement is unavailable for this series.")
        try:
            spacing_values.append((float(ps[1]), float(ps[0])))  # x, y from DICOM row/column spacing
        except Exception as exc:
            raise ValueError("PixelSpacing metadata is invalid.") from exc
    if not np.allclose(np.asarray(spacing_values), np.asarray(spacing_values[0]), rtol=1e-4, atol=1e-4):
        raise ValueError("PixelSpacing changes within the series; select a geometrically consistent series.")
    pixel_spacing = spacing_values[0]

    directions = [_direction_from_iop(getattr(ds, "ImageOrientationPatient", None)) for _, ds in datasets]
    directions_present = [d for d in directions if d is not None]
    geometry_incomplete = len(directions_present) != len(datasets)
    if directions_present:
        row0, col0, normal0 = directions_present[0]
        for direction in directions_present[1:]:
            row, col, normal = direction
            if not (
                np.allclose(row, row0, rtol=1e-4, atol=1e-4)
                and np.allclose(col, col0, rtol=1e-4, atol=1e-4)
                and np.allclose(normal, normal0, rtol=1e-4, atol=1e-4)
            ):
                raise ValueError("Inconsistent ImageOrientationPatient values detected within the series.")
    else:
        normal0 = np.array([0.0, 0.0, 1.0], dtype=np.float64)

    positions: list[float] = []
    have_positions = True
    for _, ds in datasets:
        ipp = getattr(ds, "ImagePositionPatient", None)
        if ipp is None or len(ipp) < 3:
            have_positions = False
            break
        try:
            positions.append(float(np.dot(np.asarray([float(v) for v in ipp[:3]]), normal0)))
        except Exception:
            have_positions = False
            break

    if have_positions:
        order = np.argsort(np.asarray(positions), kind="stable")
        datasets = [datasets[int(i)] for i in order]
        positions = [positions[int(i)] for i in order]
        diffs = np.abs(np.diff(positions))
        nonzero = diffs[diffs > 1e-5]
        spacing_z = float(np.median(nonzero)) if nonzero.size else float("nan")
        duplicate_positions = len(positions) != len({round(v, 4) for v in positions})
        if not np.isfinite(spacing_z) or spacing_z <= 0:
            thickness = getattr(first_ds, "SliceThickness", None)
            spacing_z = float(thickness) if thickness is not None else float("nan")
        if not np.isfinite(spacing_z) or spacing_z <= 0:
            raise ValueError("Slice spacing cannot be derived from ImagePositionPatient or SliceThickness.")
        gaps = diffs[diffs > 1e-5]
        missing_gap_count = int(np.sum(gaps > spacing_z * 1.5)) if gaps.size else 0
        inconsistent_spacing = bool(gaps.size > 1 and not np.allclose(gaps, spacing_z, rtol=0.03, atol=0.05))
    else:
        instance_numbers = []
        for _, ds in datasets:
            value = getattr(ds, "InstanceNumber", None)
            try:
                instance_numbers.append(int(value))
            except Exception:
                instance_numbers.append(0)
        datasets = [item for _, item in sorted(zip(instance_numbers, datasets), key=lambda pair: pair[0])]
        thickness = getattr(first_ds, "SliceThickness", None)
        if thickness is None:
            raise ValueError("ImagePositionPatient and SliceThickness are missing; z-axis calibration is unavailable.")
        spacing_z = float(thickness)
        if spacing_z <= 0 or not np.isfinite(spacing_z):
            raise ValueError("SliceThickness metadata is invalid.")
        duplicate_positions = False
        missing_gap_count = 0
        inconsistent_spacing = False

    frames: list[np.ndarray] = []
    for file_path, ds in datasets:
        try:
            arr = ds.pixel_array.astype(np.float32)
        except Exception as exc:
            raise ValueError(f"Failed to decode pixel data in {file_path.name}.") from exc
        slope = float(getattr(ds, "RescaleSlope", 1.0))
        intercept = float(getattr(ds, "RescaleIntercept", 0.0))
        if not np.isfinite(slope) or not np.isfinite(intercept):
            raise ValueError(f"Invalid rescale metadata in {file_path.name}.")
        frames.append(arr * slope + intercept)

    volume = np.stack(frames, axis=0)
    qc_flags = {
        "duplicate_slices": duplicate_positions,
        "inconsistent_spacing": inconsistent_spacing,
        "missing_slice_gaps": missing_gap_count,
        "geometry_incomplete": geometry_incomplete or not have_positions,
        "decode_errors": len(decode_errors),
    }

    first = datasets[0][1]
    return ImagingData(
        volume=volume,
        spacing=(pixel_spacing[0], pixel_spacing[1], spacing_z),
        modality=modality,
        orientation=str(getattr(first, "ImageOrientationPatient", "unknown")),
        patient_id=_text(first, "PatientID"),
        patient_name=_text(first, "PatientName"),
        study_uid=_text(first, "StudyInstanceUID"),
        series_uid=_text(first, "SeriesInstanceUID"),
        accession_number=_text(first, "AccessionNumber"),
        study_date=_text(first, "StudyDate"),
        study_description=_text(first, "StudyDescription"),
        body_region=_text(first, "BodyPartExamined"),
        institution=_text(first, "InstitutionName"),
        referring_physician=_text(first, "ReferringPhysicianName"),
        slice_thickness=float(getattr(first, "SliceThickness", spacing_z)),
        pixel_spacing=pixel_spacing,
        source_type="dicom",
        photometric_interpretation=str(getattr(first, "PhotometricInterpretation", "MONOCHROME2")).upper(),
        qc_flags=qc_flags,
        file_count=len(datasets),
        slice_count=len(datasets),
        series_count=1,
        affine_ras=None,
    )


def load_case(path: Path) -> ImagingData:
    path = path.resolve()
    if path.is_file():
        suffixes = "".join(path.suffixes).lower()
        if suffixes.endswith(".nii") or suffixes.endswith(".nii.gz"):
            return _load_nifti(path)
        if suffixes.endswith(".npz"):
            return _load_npz_demo(path)
        if _is_dicom_file(path):
            return _load_dicom_dir(path.parent)

    if path.is_dir():
        nifti_files = [p for p in path.rglob("*") if p.is_file() and "".join(p.suffixes).lower().endswith((".nii", ".nii.gz"))]
        npz_files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".npz"]
        dicom_files = [p for p in path.rglob("*") if p.is_file() and _is_dicom_file(p)]
        dicom_extension_files = [p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".dcm"]
        has_dicom_source = bool(dicom_files or dicom_extension_files)
        source_types = int(bool(nifti_files)) + int(bool(npz_files)) + int(has_dicom_source)
        if source_types > 1:
            raise ValueError("Multiple incompatible imaging source types were found in the case directory.")
        if len(nifti_files) > 1:
            raise ValueError("Multiple NIfTI volumes were found; select exactly one volume.")
        if nifti_files:
            return _load_nifti(nifti_files[0])
        if npz_files:
            if len(npz_files) > 1:
                raise ValueError("Multiple synthetic NPZ volumes were found; select exactly one.")
            return _load_npz_demo(npz_files[0])
        return _load_dicom_dir(path)

    raise FileNotFoundError(f"No supported imaging source found at {path}")


def _finite_values(arr: np.ndarray) -> np.ndarray:
    values = np.asarray(arr, dtype=np.float32)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("Selected imaging region contains no finite numeric values.")
    return values


def series_summary(imaging: ImagingData) -> dict[str, Any]:
    z, y, x = imaging.volume.shape
    qc_flags = imaging.qc_flags or {}
    qc = [
        {"test": "Image dimensions", "result": f"{x} × {y} × {z}", "threshold": "Reference threshold not configured.", "observed": [x, y, z], "status": "PASS", "method": "Decoded volume shape"},
        {"test": "Voxel spacing", "result": f"{imaging.spacing[0]:g} × {imaging.spacing[1]:g} × {imaging.spacing[2]:g} mm", "threshold": "Reference threshold not configured.", "observed": list(imaging.spacing), "status": "PASS", "method": "DICOM/NIfTI metadata"},
        {"test": "Orientation", "result": imaging.orientation, "threshold": "Reference threshold not configured.", "observed": imaging.orientation, "status": "WARNING" if "unknown" in imaging.orientation.lower() or qc_flags.get("geometry_incomplete") else "PASS", "method": "Source metadata / canonical NIfTI reorientation"},
        {"test": "Pixel decoding", "result": "Decoded", "threshold": "All requested slices must decode.", "observed": imaging.file_count, "status": "PASS" if not qc_flags.get("decode_errors") else "WARNING", "method": "Source decoder"},
    ]
    if qc_flags.get("duplicate_slices"):
        qc.append({"test": "Duplicate slice positions", "result": "Detected", "threshold": "No duplicate positions expected.", "observed": True, "status": "WARNING", "method": "Duplicate ImagePositionPatient projection check"})
    if qc_flags.get("missing_slice_gaps", 0):
        qc.append({"test": "Missing slice gaps", "result": f"{qc_flags['missing_slice_gaps']} large geometry gaps", "threshold": "Geometry-derived spacing continuity check; reference clinical threshold not configured.", "observed": qc_flags["missing_slice_gaps"], "status": "WARNING", "method": "Adjacent projected slice-position gap analysis"})
    if qc_flags.get("inconsistent_spacing"):
        qc.append({"test": "Slice spacing consistency", "result": "Inconsistent spacing detected", "threshold": "Geometry consistency rule (3% relative / 0.05 mm absolute).", "observed": True, "status": "WARNING", "method": "Adjacent projected slice-position spacing comparison"})
    if qc_flags.get("geometry_incomplete"):
        qc.append({"test": "Geometry completeness", "result": "Incomplete spatial metadata", "threshold": "ImagePositionPatient and ImageOrientationPatient preferred for calibrated 3D geometry.", "observed": True, "status": "WARNING", "method": "DICOM spatial metadata presence check"})
    return {
        "study": {
            "patient_id": imaging.patient_id,
            "patient_name": imaging.patient_name,
            "accession_number": imaging.accession_number,
            "study_date": imaging.study_date,
            "study_description": imaging.study_description,
            "sequence_name": imaging.sequence_name,
            "modality": imaging.modality,
            "body_region": imaging.body_region,
            "study_uid": imaging.study_uid,
            "series_uid": imaging.series_uid,
            "institution": imaging.institution,
            "referring_physician": imaging.referring_physician,
        },
        "modality": imaging.modality,
        "orientation": imaging.orientation,
        "slice_thickness_mm": imaging.slice_thickness,
        "pixel_spacing_mm": list(imaging.pixel_spacing or imaging.spacing[:2]),
        "matrix": [x, y],
        "volume_dimensions": [x, y, z],
        "source_type": imaging.source_type,
        "files_detected": imaging.file_count,
        "slices_detected": imaging.slice_count,
        "series_detected": imaging.series_count,
        "qc_flags": qc_flags,
        "qc": qc,
    }


def _window(arr: np.ndarray, wl: float | None, ww: float | None) -> np.ndarray:
    x = np.asarray(arr, dtype=np.float32)
    finite = x[np.isfinite(x)]
    if finite.size == 0:
        raise ValueError("Selected slice contains no finite image values.")
    if wl is None or ww is None or ww <= 0:
        lo, hi = np.percentile(finite, [1, 99])
    else:
        if not np.isfinite(wl) or not np.isfinite(ww) or ww <= 0:
            raise ValueError("Window/level values must be finite and window width must be greater than zero.")
        lo, hi = wl - ww / 2.0, wl + ww / 2.0
    if hi <= lo:
        hi = lo + 1.0
    clean = np.nan_to_num(x, nan=lo, posinf=hi, neginf=lo)
    out = np.clip((clean - lo) / (hi - lo), 0, 1)
    return (out * 255).astype(np.uint8)


def _png_bytes(arr: np.ndarray) -> bytes:
    image = Image.fromarray(arr)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _slice_array(volume: np.ndarray, plane: str, index: int | None) -> np.ndarray:
    plane = plane.lower()
    if plane == "axial":
        i = volume.shape[0] // 2 if index is None else max(0, min(int(index), volume.shape[0] - 1))
        return volume[i]
    if plane == "sagittal":
        i = volume.shape[2] // 2 if index is None else max(0, min(int(index), volume.shape[2] - 1))
        return volume[:, :, i]
    if plane == "coronal":
        i = volume.shape[1] // 2 if index is None else max(0, min(int(index), volume.shape[1] - 1))
        return volume[:, i, :]
    raise ValueError("plane must be axial, sagittal, or coronal")


def _display_uint8(arr: np.ndarray, wl: float | None, ww: float | None, invert: bool = False) -> np.ndarray:
    output = _window(arr, wl, ww)
    if invert:
        output = 255 - output
    return np.flipud(output)


def render_slice_png(imaging: ImagingData, plane: str, index: int | None, wl: float | None, ww: float | None) -> io.BytesIO:
    arr = _slice_array(imaging.volume, plane, index)
    invert = imaging.photometric_interpretation == "MONOCHROME1"
    return io.BytesIO(_png_bytes(_display_uint8(arr, wl, ww, invert)))


def _b64_png(arr: np.ndarray, wl: float | None = None, ww: float | None = None, invert: bool = False) -> str:
    return base64.b64encode(_png_bytes(_display_uint8(arr, wl, ww, invert))).decode("ascii")


def make_mpr(imaging: ImagingData, z: int | None = None, y: int | None = None, x: int | None = None, wl: float | None = None, ww: float | None = None) -> dict[str, Any]:
    volume = imaging.volume
    zi = volume.shape[0] // 2 if z is None else max(0, min(int(z), volume.shape[0] - 1))
    yi = volume.shape[1] // 2 if y is None else max(0, min(int(y), volume.shape[1] - 1))
    xi = volume.shape[2] // 2 if x is None else max(0, min(int(x), volume.shape[2] - 1))
    return {
        "axial": _b64_png(volume[zi], wl, ww, imaging.photometric_interpretation == "MONOCHROME1"),
        "sagittal": _b64_png(volume[:, :, xi], wl, ww, imaging.photometric_interpretation == "MONOCHROME1"),
        "coronal": _b64_png(volume[:, yi, :], wl, ww, imaging.photometric_interpretation == "MONOCHROME1"),
        "position": {"z": zi, "y": yi, "x": xi},
    }


def voxel_statistics(imaging: ImagingData, plane: str, index: int) -> dict[str, Any]:
    arr = _slice_array(imaging.volume, plane, index)
    flat = _finite_values(arr).astype(np.float64)
    plane = plane.lower()
    if plane == "axial":
        source_spacing = imaging.spacing[:2]
    elif plane == "coronal":
        source_spacing = (imaging.spacing[0], imaging.spacing[2])
    elif plane == "sagittal":
        source_spacing = (imaging.spacing[1], imaging.spacing[2])
    else:
        raise ValueError("Unsupported plane")

    stats: dict[str, Any] = {
        "pixel_count": int(flat.size),
        "mean_intensity": float(np.mean(flat)),
        "median_intensity": float(np.median(flat)),
        "minimum_intensity": float(np.min(flat)),
        "maximum_intensity": float(np.max(flat)),
        "standard_deviation": float(np.std(flat)),
        "p05": float(np.percentile(flat, 5)),
        "p25": float(np.percentile(flat, 25)),
        "p75": float(np.percentile(flat, 75)),
        "p95": float(np.percentile(flat, 95)),
        "area_mm2": float(flat.size * source_spacing[0] * source_spacing[1]),
        "units": "HU" if imaging.modality.upper() == "CT" else "source intensity units",
        "method": "Statistics computed directly from decoded source pixels/voxels for the selected plane; physical area uses source pixel/voxel spacing metadata.",
    }
    if imaging.modality.upper() == "CT":
        stats.update({"mean_hu": stats["mean_intensity"], "median_hu": stats["median_intensity"], "minimum_hu": stats["minimum_intensity"], "maximum_hu": stats["maximum_intensity"]})
    return stats
