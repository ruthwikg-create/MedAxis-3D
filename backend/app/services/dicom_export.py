from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def _validate_written_dicom(
    output_path: Path,
    *,
    expected_sop_class_uid: str,
    source_study_uid: str,
) -> dict[str, Any]:
    try:
        import pydicom
    except Exception as exc:
        raise RuntimeError("DICOM artifact validation requires pydicom 3.x.") from exc
    if not output_path.is_file() or output_path.stat().st_size < 256:
        raise RuntimeError("DICOM writer did not produce a non-empty artifact.")
    try:
        ds = pydicom.dcmread(str(output_path), stop_before_pixels=True, force=True)
    except Exception as exc:
        raise RuntimeError(f"The generated DICOM artifact could not be parsed: {exc}") from exc
    sop = str(getattr(ds, "SOPClassUID", ""))
    study = str(getattr(ds, "StudyInstanceUID", ""))
    instance = str(getattr(ds, "SOPInstanceUID", ""))
    series = str(getattr(ds, "SeriesInstanceUID", ""))
    if sop != expected_sop_class_uid:
        raise RuntimeError(f"Generated DICOM SOP Class UID {sop!r} does not match expected {expected_sop_class_uid!r}.")
    if source_study_uid and study != source_study_uid:
        raise RuntimeError("Generated DICOM StudyInstanceUID does not match the source evidence study.")
    if not instance or not series:
        raise RuntimeError("Generated DICOM object is missing SOPInstanceUID or SeriesInstanceUID.")
    return {
        "sop_class_uid": sop,
        "study_instance_uid": study,
        "series_instance_uid": series,
        "sop_instance_uid": instance,
        "file_size_bytes": output_path.stat().st_size,
        "validated": True,
    }


def _conventional_sources(case_dir: Path) -> list[Any]:
    try:
        import pydicom
    except Exception as exc:
        raise RuntimeError("DICOM export requires pydicom 3.x.") from exc
    datasets: list[Any] = []
    for path in case_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() == ".zip":
            continue
        try:
            ds = pydicom.dcmread(str(path), force=True)
        except Exception:
            continue
        if not hasattr(ds, "PixelData") or not hasattr(ds, "SOPInstanceUID"):
            continue
        if int(getattr(ds, "NumberOfFrames", 1) or 1) != 1:
            continue
        if not hasattr(ds, "Rows") or not hasattr(ds, "Columns"):
            continue
        if not hasattr(ds, "SeriesInstanceUID") or not hasattr(ds, "StudyInstanceUID"):
            continue
        datasets.append(ds)
    if not datasets:
        raise RuntimeError("No conventional single-frame DICOM source images are available for export.")

    series_uids = {str(ds.SeriesInstanceUID) for ds in datasets}
    study_uids = {str(ds.StudyInstanceUID) for ds in datasets}
    if len(series_uids) != 1 or len(study_uids) != 1:
        raise RuntimeError("DICOM export requires exactly one consistent source study and SeriesInstanceUID.")

    first = datasets[0]
    rows_cols = {(int(ds.Rows), int(ds.Columns)) for ds in datasets}
    if len(rows_cols) != 1:
        raise RuntimeError("Source DICOM series contains inconsistent Rows/Columns geometry.")

    pixel_spacings = []
    orientations = []
    for ds in datasets:
        try:
            ps = tuple(float(v) for v in ds.PixelSpacing)
            iop = tuple(float(v) for v in ds.ImageOrientationPatient)
            if len(ps) != 2 or min(ps) <= 0 or len(iop) != 6:
                raise ValueError
            pixel_spacings.append(ps)
            orientations.append(iop)
        except Exception as exc:
            raise RuntimeError("Every exported source image must provide valid PixelSpacing and ImageOrientationPatient.") from exc
    if not all(np.allclose(pixel_spacings[0], ps, rtol=1e-5, atol=1e-5) for ps in pixel_spacings[1:]):
        raise RuntimeError("Source DICOM series contains inconsistent PixelSpacing.")
    if not all(np.allclose(orientations[0], iop, rtol=1e-5, atol=1e-5) for iop in orientations[1:]):
        raise RuntimeError("Source DICOM series contains inconsistent ImageOrientationPatient values.")

    iop = np.asarray(orientations[0], dtype=np.float64)
    normal = np.cross(iop[:3], iop[3:])

    def key(ds: Any) -> tuple[float, int, str]:
        try:
            ipp = np.asarray([float(v) for v in ds.ImagePositionPatient], dtype=np.float64)
            if ipp.size != 3:
                raise ValueError
            distance = float(np.dot(ipp, normal))
        except Exception:
            distance = 0.0
        try:
            instance = int(getattr(ds, "InstanceNumber", 0) or 0)
        except Exception:
            instance = 0
        return distance, instance, str(ds.SOPInstanceUID)

    datasets.sort(key=key)
    distances = []
    for ds in datasets:
        try:
            ipp = np.asarray([float(v) for v in ds.ImagePositionPatient], dtype=np.float64)
            distances.append(float(np.dot(ipp, normal)))
        except Exception:
            pass
    if len(distances) > 1:
        gaps = np.diff(np.asarray(distances))
        positive = np.abs(gaps)
        median = float(np.median(positive))
        if median > 0 and np.any(positive > median * 1.5):
            raise RuntimeError("Source DICOM series contains a slice-spacing gap; export was stopped to avoid an ambiguous frame map.")

    return datasets


def dicom_source_images(case_dir: Path) -> list[Any]:
    return _conventional_sources(case_dir)


def export_seg(
    source_images: list[Any],
    mask: np.ndarray,
    output_path: Path,
    label: str,
    algorithm_type: str = "AUTOMATIC",
) -> dict[str, Any]:
    try:
        import highdicom as hd
        from pydicom.sr.codedict import codes
        from pydicom.uid import SegmentationStorage
    except Exception as exc:
        raise RuntimeError("DICOM SEG export requires highdicom 0.28.1 and pydicom 3.x. Install backend requirements.") from exc
    if not source_images:
        raise ValueError("At least one DICOM source image is required.")
    if mask.ndim != 3:
        raise ValueError("SEG mask must be 3D in z,y,x order.")
    expected = (len(source_images), int(source_images[0].Rows), int(source_images[0].Columns))
    if tuple(mask.shape) != expected:
        raise ValueError(f"SEG mask shape {tuple(mask.shape)} does not match source images {expected}.")
    if not np.isfinite(mask).all():
        raise ValueError("SEG mask contains non-finite values.")
    binary_mask = mask.astype(bool)
    if not binary_mask.any():
        raise ValueError("SEG mask is empty; refusing to write an empty research segmentation object.")

    category = codes.SCT.Tissue
    property_types = {
        "spleen": codes.SCT.Spleen,
        "liver": codes.SCT.Liver,
        "prostate": codes.SCT.Prostate,
        "heart": codes.SCT.Heart,
        "brain": codes.SCT.Brain,
        "lung": codes.SCT.Lung,
        "kidney": codes.SCT.Kidney,
    }
    property_type = property_types.get(label.lower(), codes.SCT.AnatomicalStructure)
    algo_enum = getattr(hd.seg.SegmentAlgorithmTypeValues, algorithm_type, hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC)
    from highdicom.content import AlgorithmIdentificationSequence
    algorithm_id = AlgorithmIdentificationSequence(
        name="MedAxis 3D segmentation pipeline",
        family=codes.DCM.ArtificialIntelligence,
        version="4.1.1",
        source="MedAxis 3D",
        parameters={"mask_source": algorithm_type},
    )
    description = hd.seg.SegmentDescription(
        segment_number=1,
        segment_label=label[:64],
        segmented_property_category=category,
        segmented_property_type=property_type,
        algorithm_type=algo_enum,
        algorithm_identification=algorithm_id,
        tracking_uid=hd.UID(),
        tracking_id=f"MEDAXIS-{label[:24]}",
    )
    seg = hd.seg.Segmentation(
        source_images=source_images,
        pixel_array=binary_mask.astype(np.uint8),
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=[description],
        series_instance_uid=hd.UID(),
        series_number=901,
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer="MedAxis 3D",
        manufacturer_model_name="MedAxis 3D Research Imaging Workstation",
        software_versions="4.1.1",
        device_serial_number="MEDAXIS-LOCAL",
        series_description=f"MedAxis SEG - {label}"[:64],
        content_description=f"Research segmentation export for {label}"[:64],
        content_label="MEDAXIS",
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seg.save_as(str(output_path))
    validation = _validate_written_dicom(
        output_path,
        expected_sop_class_uid=str(SegmentationStorage),
        source_study_uid=str(source_images[0].StudyInstanceUID),
    )
    return {
        "status": "EXPORTED_AND_VALIDATED",
        "path": str(output_path),
        "sop_class": validation["sop_class_uid"],
        "segment_label": label,
        "source_series_uid": str(source_images[0].SeriesInstanceUID),
        "source_sop_count": len(source_images),
        "format": "DICOM Segmentation Storage",
        "validation": validation,
    }


def export_sr(
    source_images: list[Any],
    measurements: dict[str, float],
    output_path: Path,
    title: str = "MedAxis Quantitative Imaging Report",
) -> dict[str, Any]:
    try:
        import highdicom as hd
        from pydicom.sr.codedict import codes
        from pydicom.sr.coding import Code
        from pydicom.uid import Comprehensive3DSRStorage
        from highdicom.sr.templates import Measurement, TrackingIdentifier
    except Exception as exc:
        raise RuntimeError("DICOM SR export requires highdicom 0.28.1 and pydicom 3.x. Install backend requirements.") from exc
    if not source_images:
        raise ValueError("At least one DICOM source image is required for SR evidence.")
    volume_mm3 = float(measurements.get("volume_mm3", float("nan")))
    if not np.isfinite(volume_mm3) or volume_mm3 <= 0:
        raise ValueError("A finite positive volume measurement is required for DICOM SR export.")

    observer_context = hd.sr.ObservationContext(
        observer_person_context=hd.sr.ObserverContext(
            observer_type=codes.DCM.Person,
            observer_identifying_attributes=hd.sr.PersonObserverIdentifyingAttributes(name="MedAxis^Operator"),
        )
    )
    algorithm_id = hd.sr.AlgorithmIdentification(
        name="MedAxis quantitative imaging pipeline",
        family=codes.DCM.ArtificialIntelligence,
        version="4.1.1",
        source="MedAxis 3D",
    )
    measurements_items = [
        Measurement(
            name=codes.SCT.Volume,
            value=volume_mm3,
            unit=codes.UCUM.CubicMillimeter,
            algorithm_id=algorithm_id,
        )
    ]
    surface_area = measurements.get("surface_area_mm2")
    if surface_area is not None and np.isfinite(float(surface_area)) and float(surface_area) > 0:
        measurements_items.append(
            Measurement(
                name=codes.SCT.SurfaceArea,
                value=float(surface_area),
                unit=codes.UCUM.SquareMillimeter,
                algorithm_id=algorithm_id,
            )
        )
    group = hd.sr.MeasurementsAndQualitativeEvaluations(
        source_images=[hd.sr.SourceImageForMeasurementGroup.from_source_image(im) for im in source_images],
        measurements=measurements_items,
        tracking_identifier=TrackingIdentifier(uid=hd.UID(), identifier="MEDAXIS-QUANT-1"),
        algorithm_id=algorithm_id,
    )
    modality = str(getattr(source_images[0], "Modality", "")).upper()
    procedure = Code(
        "P5-08000" if modality == "CT" else "R-40B00",
        "SRT",
        "Computed tomography" if modality == "CT" else "Magnetic resonance imaging",
    )
    measurement_report = hd.sr.MeasurementReport(
        observation_context=observer_context,
        procedure_reported=procedure,
        imaging_measurements=[group],
        title=codes.DCM.ImagingMeasurementReport,
    )
    sr = hd.sr.Comprehensive3DSR(
        evidence=source_images,
        content=measurement_report,
        series_number=902,
        series_instance_uid=hd.UID(),
        sop_instance_uid=hd.UID(),
        instance_number=1,
        manufacturer="MedAxis 3D",
        manufacturer_model_name="MedAxis 3D Research Imaging Workstation",
        software_versions="4.1.1",
        device_serial_number="MEDAXIS-LOCAL",
        series_description=title[:64],
        is_complete=True,
        is_final=False,
        is_verified=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sr.save_as(str(output_path))
    validation = _validate_written_dicom(
        output_path,
        expected_sop_class_uid=str(Comprehensive3DSRStorage),
        source_study_uid=str(source_images[0].StudyInstanceUID),
    )
    return {
        "status": "EXPORTED_AND_VALIDATED",
        "path": str(output_path),
        "sop_class": validation["sop_class_uid"],
        "format": "Comprehensive 3D SR",
        "measurement_names": ["Volume"] + (["Surface Area"] if surface_area is not None and np.isfinite(float(surface_area)) and float(surface_area) > 0 else []),
        "validation": validation,
    }
