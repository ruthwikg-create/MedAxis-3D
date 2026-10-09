from pathlib import Path

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.services.imaging import ImagingData, make_mpr, render_slice_png, series_summary, voxel_statistics
from app.services.mesh import make_surface
from app.services.storage import CaseStore
import app.main as main


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "cases"
    monkeypatch.setattr(main, "DATA_DIR", root)
    monkeypatch.setattr(main, "store", CaseStore(root))
    return TestClient(main.app)


def sample() -> ImagingData:
    volume = np.arange(3 * 4 * 5, dtype=np.float32).reshape(3, 4, 5)
    return ImagingData(volume, (1.0, 2.0, 3.0), "CT", "test", source_type="synthetic")


def test_volume_shape_and_spacing():
    summary = series_summary(sample())
    assert summary["volume_dimensions"] == [5, 4, 3]
    assert summary["pixel_spacing_mm"] == [1.0, 2.0]


def test_statistics_are_data_derived():
    result = voxel_statistics(sample(), "axial", 1)
    assert result["pixel_count"] == 20
    assert result["minimum_intensity"] == 20
    assert result["maximum_intensity"] == 39
    assert result["area_mm2"] == 40.0


def test_other_plane_statistics_use_correct_spacing():
    imaging = sample()
    coronal = voxel_statistics(imaging, "coronal", 1)
    sagittal = voxel_statistics(imaging, "sagittal", 1)
    assert coronal["pixel_count"] == 15
    assert coronal["area_mm2"] == 45.0
    assert sagittal["pixel_count"] == 12
    assert sagittal["area_mm2"] == 72.0


def test_mpr_clamps_and_returns_three_planes():
    result = make_mpr(sample(), z=999, y=-10, x=999)
    assert set(result) == {"axial", "sagittal", "coronal", "position"}
    assert result["position"] == {"z": 2, "y": 0, "x": 4}
    assert all(result[key] for key in ("axial", "sagittal", "coronal"))


def test_slice_renderer_returns_png():
    payload = render_slice_png(sample(), "axial", 1, None, None).getvalue()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(payload) > 80


def test_surface_reconstruction_has_faces_and_derived_metrics():
    volume = np.zeros((24, 24, 24), dtype=np.float32)
    volume[5:19, 6:18, 7:17] = 100
    result = make_surface(volume, (1.0, 1.0, 1.0), mask=volume > 0)
    assert result["status"] == "AVAILABLE"
    assert result["vertex_count"] > 0
    assert result["triangle_count"] > 0
    assert result["surface_area_mm2"] > 0
    assert result["volume_cm3"] == pytest.approx(14 * 12 * 10 / 1000)


def test_threshold_rejects_reversed_bounds(client):
    demo = client.post("/api/cases/demo")
    assert demo.status_code == 200, demo.text
    case_id = demo.json()["case_id"]
    response = client.post("/api/analysis/threshold", json={"case_id": case_id, "lower": 20, "upper": 10})
    assert response.status_code == 422
    assert "Lower threshold" in response.text


def test_demo_volume_preserves_normalized_zyx_shape(client):
    created = client.post("/api/cases/demo")
    assert created.status_code == 200, created.text
    case_id = created.json()["case_id"]

    volume = client.get(f"/api/viewer/{case_id}/volume")
    assert volume.status_code == 200
    assert volume.json()["shape"] == [96, 160, 160]


def test_end_to_end_demo_viewer_analysis_report_provenance_audit(client):
    created = client.post("/api/cases/demo")
    assert created.status_code == 200, created.text
    record = created.json()
    case_id = record["case_id"]
    assert record["status"] == "DEMO DATA"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["capabilities"]["mpr"] is True
    assert health.json()["capabilities"]["ai_models"] is False

    cases = client.get("/api/cases")
    assert cases.status_code == 200
    assert any(item["case_id"] == case_id for item in cases.json())

    detail = client.get(f"/api/cases/{case_id}")
    assert detail.status_code == 200

    volume = client.get(f"/api/viewer/{case_id}/volume")
    assert volume.status_code == 200
    shape = volume.json()["shape"]
    assert shape == [96, 160, 160]

    slice_response = client.get(f"/api/viewer/{case_id}/slice", params={"plane": "axial", "index": 48})
    assert slice_response.status_code == 200
    assert slice_response.headers["content-type"].startswith("image/png")
    assert slice_response.content.startswith(b"\x89PNG")

    mpr = client.get(f"/api/viewer/{case_id}/mpr", params={"z": 48, "y": 80, "x": 80})
    assert mpr.status_code == 200
    assert set(mpr.json()) == {"axial", "sagittal", "coronal", "position"}

    measurement = client.post("/api/measurements", json={"case_id": case_id, "plane": "axial", "index": 48})
    assert measurement.status_code == 200, measurement.text
    assert measurement.json()["source"] == "actual imaging data"

    threshold = client.post("/api/analysis/threshold", json={"case_id": case_id, "lower": 100, "upper": 220})
    assert threshold.status_code == 200, threshold.text
    threshold_payload = threshold.json()
    assert threshold_payload["status"] == "COMPLETED"
    assert threshold_payload["mask_voxel_count"] > 0

    lookup = client.get(f"/api/analysis/{threshold_payload['analysis_id']}")
    assert lookup.status_code == 200
    assert lookup.json()["analysis_id"] == threshold_payload["analysis_id"]

    roi = client.post(f"/api/rois/{case_id}", json={"type": "rectangle", "label": "Test ROI"})
    assert roi.status_code == 200
    assert client.get(f"/api/rois/{case_id}").json()[0]["roi_id"] == roi.json()["roi_id"]

    surface = client.get(f"/api/3d/{case_id}/surface")
    assert surface.status_code == 200, surface.text
    assert surface.json()["status"] == "AVAILABLE"
    assert surface.json()["triangle_count"] > 0

    report = client.post("/api/reports", json={"case_id": case_id, "user_observations": "Research review only."})
    assert report.status_code == 200
    assert report.json()["provenance"]

    provenance = client.get(f"/api/provenance/{case_id}")
    audit = client.get(f"/api/audit/{case_id}")
    assert provenance.status_code == 200 and len(provenance.json()) >= 3
    assert audit.status_code == 200 and len(audit.json()) >= 4

    model = client.get("/api/models/spleen-ct/status")
    assert model.status_code == 200
    assert model.json()["status"] in {"MODEL NOT DOWNLOADED", "MODEL INSTALLED — MONAI RUNTIME MISSING", "MODEL READY"}

    seg = client.get(f"/api/segmentation/{case_id}", params={"structure": "Spleen"})
    assert seg.status_code == 200
    assert seg.json()["status"] in {"MODEL NOT DOWNLOADED", "MODEL INSTALLED — MONAI RUNTIME MISSING", "MODEL READY"}

    anonymize = client.post(f"/api/dicom/anonymize/{case_id}")
    assert anonymize.status_code == 200
    assert anonymize.json()["status"] == "REVIEW REQUIRED"

    assert client.delete(f"/api/cases/{case_id}").status_code == 200
    assert client.get(f"/api/cases/{case_id}").status_code == 404


def test_case_path_traversal_is_rejected(client):
    response = client.get("/api/cases/..%2Foutside")
    assert response.status_code in {400, 404, 422}


def test_dicom_seg_and_sr_are_explicitly_unavailable(client):
    demo = client.post("/api/cases/demo")
    case_id = demo.json()["case_id"]
    seg = client.get(f"/api/export/dicom-seg/{case_id}")
    sr = client.get(f"/api/export/dicom-sr/{case_id}")
    assert seg.status_code == 200
    assert sr.status_code == 200
    assert seg.json()["status"] in {"READY", "NOT AVAILABLE"}
    assert sr.json()["status"] in {"READY", "NOT AVAILABLE"}


def test_dicom_geometry_ordering_and_rescale_without_network(monkeypatch, tmp_path: Path):
    from app.services import imaging

    class FakeDataset:
        def __init__(self, value: float, position: float, instance: int, slope: float = 2.0, intercept: float = -1.0):
            self.SOPClassUID = "1.2.3"
            self.Rows = 2
            self.Columns = 3
            self.PixelData = b"pixel"
            self.PixelSpacing = ["2.0", "3.0"]  # row, column -> y, x
            self.ImageOrientationPatient = [0, 1, 0, 0, 0, 1]
            self.ImagePositionPatient = [position, 0, 0]  # normal is +X
            self.InstanceNumber = instance
            self.Modality = "CT"
            self.SeriesInstanceUID = "series-1"
            self.StudyInstanceUID = "study-1"
            self.SliceThickness = "1.0"
            self.RescaleSlope = str(slope)
            self.RescaleIntercept = str(intercept)
            self.PatientID = "P1"
            self.pixel_array = np.full((2, 3), value, dtype=np.int16)

    mapping = {
        "a.dcm": FakeDataset(20, 2.0, 3),
        "b.dcm": FakeDataset(10, 0.0, 1),
        "c.dcm": FakeDataset(15, 1.0, 2),
    }

    class FakePydicom:
        @staticmethod
        def dcmread(filename, **_kwargs):
            return mapping[Path(filename).name]

    monkeypatch.setattr(imaging, "pydicom", FakePydicom)
    for name in mapping:
        (tmp_path / name).write_bytes(b"DICM")

    loaded = imaging.load_case(tmp_path)
    assert loaded.volume.shape == (3, 2, 3)
    assert loaded.spacing == (3.0, 2.0, 1.0)
    assert loaded.volume[:, 0, 0].tolist() == pytest.approx([19.0, 29.0, 39.0])
    assert loaded.source_type == "dicom"
    assert loaded.qc_flags["geometry_incomplete"] is False


def test_nifti_loader_requires_3d_and_preserves_spacing(monkeypatch, tmp_path: Path):
    from app.services import imaging

    class FakeHeader:
        def get_zooms(self):
            return (1.1, 1.2, 1.3)

    class FakeImage:
        shape = (4, 5, 6)
        header = FakeHeader()

        def get_fdata(self, dtype=np.float32):
            return np.ones(self.shape, dtype=dtype)

    class FakeNib:
        @staticmethod
        def load(_path):
            return FakeImage()

        @staticmethod
        def as_closest_canonical(image):
            return image

    monkeypatch.setattr(imaging, "nib", FakeNib)
    target = tmp_path / "volume.nii"
    target.write_bytes(b"not-a-real-nifti-for-mocked-loader")
    loaded = imaging.load_case(target)
    assert loaded.volume.shape == (6, 5, 4)
    assert loaded.spacing == (1.1, 1.2, 1.3)
    assert loaded.source_type == "nifti"

    class Fake4D(FakeImage):
        shape = (4, 5, 6, 2)

    class BadNib(FakeNib):
        @staticmethod
        def load(_path):
            return Fake4D()

    monkeypatch.setattr(imaging, "nib", BadNib)
    with pytest.raises(ValueError, match="exactly 3D"):
        imaging.load_case(target)


def test_zip_safety_rejects_parent_traversal(tmp_path: Path):
    import zipfile
    from app import main

    archive_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../../outside.txt", "unsafe")

    from fastapi import HTTPException
    with pytest.raises(HTTPException, match="Unsafe ZIP path"):
        main.safe_extract_zip(archive_path, tmp_path / "extract")


def test_3d_operations_require_reliable_geometry(client, monkeypatch):
    demo = client.post("/api/cases/demo")
    assert demo.status_code == 200
    case_id = demo.json()["case_id"]
    from app.services import imaging
    broken = imaging.ImagingData(
        volume=np.ones((4, 4, 4), dtype=np.float32),
        spacing=(1.0, 1.0, 2.0),
        modality="CT",
        orientation="test",
        source_type="dicom",
        qc_flags={"geometry_incomplete": True},
    )
    monkeypatch.setattr(main, "case_imaging", lambda _case_id: broken)
    surface = client.get(f"/api/3d/{case_id}/surface")
    assert surface.status_code == 422
    threshold = client.post("/api/analysis/threshold", json={"case_id": case_id, "lower": 0, "upper": 2})
    assert threshold.status_code == 422


def test_remaining_read_only_routes_and_export_states(client):
    created = client.post("/api/cases/demo")
    assert created.status_code == 200
    case_id = created.json()["case_id"]

    assert client.get("/api/studies").status_code == 200
    assert client.get(f"/api/series/{case_id}").status_code == 200
    assert client.get(f"/api/dicom/metadata/{case_id}").status_code == 200
    assert client.get("/api/models").status_code == 200
    assert client.get("/api/system/diagnostics").status_code == 200

    bad_viewer = client.get(f"/api/viewer/{case_id}/slice", params={"plane": "oblique", "index": 0})
    assert bad_viewer.status_code == 422

    assert client.post(f"/api/dicom/anonymize/{case_id}").json()["status"] == "REVIEW REQUIRED"
    assert client.get(f"/api/export/dicom-seg/{case_id}").status_code == 200
    assert client.get(f"/api/export/dicom-sr/{case_id}").status_code == 200


def test_zip_safe_extraction_and_duplicate_rejection(tmp_path: Path):
    import zipfile
    from app import main

    good = tmp_path / "good.zip"
    with zipfile.ZipFile(good, "w") as archive:
        archive.writestr("study/one.dcm", b"one")
        archive.writestr("study/two.dcm", b"two")
    out = tmp_path / "out"
    main.safe_extract_zip(good, out)
    assert (out / "study" / "one.dcm").read_bytes() == b"one"
    assert (out / "study" / "two.dcm").read_bytes() == b"two"

    duplicate = tmp_path / "duplicate.zip"
    with pytest.warns(UserWarning, match="Duplicate name: 'same.dcm'"):
        with zipfile.ZipFile(duplicate, "w") as archive:
            archive.writestr("same.dcm", b"first")
            archive.writestr("same.dcm", b"second")
    with pytest.raises(HTTPException, match="duplicate filenames"):
        main.safe_extract_zip(duplicate, tmp_path / "duplicate-out")


def test_dicom_rejects_mixed_series_and_missing_calibration(monkeypatch, tmp_path: Path):
    from app.services import imaging

    class FakeDataset:
        def __init__(self, series_uid: str | None = "series-1", pixel_spacing=(1.0, 1.0), position=0.0, orientation=None):
            self.SOPClassUID = "1.2.3"
            self.Rows = 2
            self.Columns = 2
            self.PixelData = b"pixel"
            if pixel_spacing is not None:
                self.PixelSpacing = [str(pixel_spacing[0]), str(pixel_spacing[1])]
            self.ImageOrientationPatient = orientation if orientation is not None else [1, 0, 0, 0, 1, 0]
            self.ImagePositionPatient = [0, 0, position]
            self.InstanceNumber = int(position) + 1
            self.Modality = "CT"
            if series_uid is not None:
                self.SeriesInstanceUID = series_uid
            self.StudyInstanceUID = "study-1"
            self.SliceThickness = "1.0"
            self.pixel_array = np.ones((2, 2), dtype=np.int16)

    files = [tmp_path / "a.dcm", tmp_path / "b.dcm"]
    for file_path in files:
        file_path.write_bytes(b"DICM")

    class MixedPydicom:
        @staticmethod
        def dcmread(filename, **_kwargs):
            return FakeDataset("series-1" if Path(filename).name == "a.dcm" else "series-2", position=0.0 if Path(filename).name == "a.dcm" else 1.0)

    monkeypatch.setattr(imaging, "pydicom", MixedPydicom)
    with pytest.raises(ValueError, match="Mixed or incomplete SeriesInstanceUID"):
        imaging.load_case(tmp_path)

    class MissingSpacingPydicom:
        @staticmethod
        def dcmread(filename, **_kwargs):
            return FakeDataset(pixel_spacing=None)

    monkeypatch.setattr(imaging, "pydicom", MissingSpacingPydicom)
    with pytest.raises(ValueError, match="PixelSpacing metadata is missing"):
        imaging.load_case(tmp_path)


def test_monochrome1_display_is_inverted():
    from app.services import imaging

    data = ImagingData(
        volume=np.array([[[0, 10]]], dtype=np.float32),
        spacing=(1.0, 1.0, 1.0),
        modality="CT",
        orientation="test",
        photometric_interpretation="MONOCHROME1",
    )
    normal = imaging._display_uint8(data.volume[0], 5, 10, False)
    inverted = imaging._display_uint8(data.volume[0], 5, 10, True)
    assert np.array_equal(inverted, 255 - normal)


def test_dataset_ai_analytics_suite_endpoints(client):
    created = client.post("/api/cases/demo")
    assert created.status_code == 200
    case_id = created.json()["case_id"]

    profile = client.get(f"/api/analytics/dataset-profile/{case_id}")
    assert profile.status_code == 200
    assert profile.json()["status"] == "MEASURED"
    assert profile.json()["source"] == "actual imported imaging data"

    histogram = client.get(f"/api/analytics/intensity-histogram/{case_id}?bins=32")
    assert histogram.status_code == 200
    assert len(histogram.json()["counts"]) == 32

    findings = client.get(f"/api/analytics/findings/{case_id}")
    assert findings.status_code == 200
    assert isinstance(findings.json()["findings"], list)

    capabilities = client.get("/api/analytics/capabilities")
    assert capabilities.status_code == 200
    payload = capabilities.json()
    assert payload["radiomics"] is True
    assert payload["research_radiomics_classifier"] is True
    assert payload["pi_rads_automated_ai"] is False

    synthesis = client.get("/api/advanced/synthesis/status")
    assert synthesis.status_code == 200
    assert synthesis.json()["status"] in {"MODEL READY", "MODEL NOT CONFIGURED"}


def test_health_endpoint_reports_actual_application(client):
    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["application"] == "MedAxis 3D"
    assert payload["status"] == "ONLINE"
    assert isinstance(payload["capabilities"], dict)
    assert "dicom" in payload["capabilities"]


def test_diagnostics_endpoint_has_explicit_auth_mode(client):
    response = client.get("/api/system/diagnostics")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["backend"] == "ONLINE"
    assert payload["authentication"] in {"REQUIRED", "DISABLED (development mode)"}


def test_readiness_endpoint_discloses_unvalidated_clinical_status(client):
    response = client.get("/api/system/readiness")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["clinical_validation"] == "NOT ESTABLISHED"
    assert payload["classification"] == "RESEARCH / EDUCATIONAL USE"


def test_synthetic_demo_slice_mpr_and_measurements(client):
    """Check rendering, not merely whether the demo metadata was created."""
    response = client.post("/api/cases/demo")
    assert response.status_code == 200, response.text
    case_id = response.json()["case_id"]
    volume = client.get(f"/api/viewer/{case_id}/volume")
    assert volume.status_code == 200, volume.text
    shape = volume.json()["shape"]
    assert len(shape) == 3 and all(axis > 0 for axis in shape)

    slice_response = client.get(f"/api/viewer/{case_id}/slice?plane=axial&index={shape[0] // 2}")
    assert slice_response.status_code == 200, slice_response.text
    assert slice_response.headers["content-type"].startswith("image/png")
    assert slice_response.content.startswith(b"\\x89PNG\\r\\n\\x1a\\n")

    mpr = client.get(f"/api/viewer/{case_id}/mpr?z={shape[0] // 2}&y={shape[1] // 2}&x={shape[2] // 2}")
    assert mpr.status_code == 200, mpr.text
    assert all(mpr.json().get(plane) for plane in ("axial", "coronal", "sagittal"))

    measures = client.post("/api/measurements", json={
        "case_id": case_id, "plane": "axial", "index": shape[0] // 2,
    })
    assert measures.status_code == 200, measures.text
    assert "mean_intensity" in measures.json()


def test_synthetic_volume_slice_navigation_across_all_planes(client):
    """All three slice axes must be accessible and produce distinct research images."""
    created = client.post("/api/cases/demo")
    assert created.status_code == 200, created.text
    case_id = created.json()["case_id"]
    volume = client.get(f"/api/viewer/{case_id}/volume")
    assert volume.status_code == 200, volume.text
    z, y, x = volume.json()["shape"]
    assert z >= 3 and y >= 3 and x >= 3

    for plane, dimension in (("axial", z), ("coronal", y), ("sagittal", x)):
        indices = (0, dimension // 2, dimension - 1)
        images = []
        for index in indices:
            response = client.get(
                f"/api/viewer/{case_id}/slice",
                params={"plane": plane, "index": index},
            )
            assert response.status_code == 200, (plane, index, response.text)
            assert response.headers["content-type"].startswith("image/png")
            assert response.content.startswith(b"\\x89PNG\\r\\n\\x1a\\n")
            images.append(response.content)
        # Synthetic volume has z/x/y variation; this detects a stuck slice index.
        assert len(set(images)) >= 2, f"{plane} slices did not change"

    center = {"z": z // 2, "y": y // 2, "x": x // 2}
    mpr = client.get(f"/api/viewer/{case_id}/mpr", params=center)
    assert mpr.status_code == 200, mpr.text
    assert mpr.json()["position"] == center

    measures = client.post("/api/measurements", json={
        "case_id": case_id, "plane": "coronal", "index": y // 2,
    })
    assert measures.status_code == 200, measures.text
    assert measures.json()["plane"] == "coronal"
    assert measures.json()["index"] == y // 2


def test_startup_health_does_not_probe_monai_torch_or_models(client, monkeypatch):
    """Health and initial UI metadata must remain responsive without ML imports."""
    from app import main

    def expensive_probe(*_args, **_kwargs):
        raise AssertionError("Fast startup routes must not probe heavyweight model runtimes")

    monkeypatch.setattr(main.ai_service, "monai_available", expensive_probe)
    monkeypatch.setattr(main.ai_service, "model_status", expensive_probe)
    monkeypatch.setattr(main.ai_service, "detected_device", expensive_probe)

    response = client.get("/api/health")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "ONLINE"
    assert payload["capabilities"]["ai_readiness_deferred"] is True
    assert payload["capabilities"]["ai_models"] is False

    diagnostics = client.get("/api/system/diagnostics")
    assert diagnostics.status_code == 200, diagnostics.text
    assert diagnostics.json()["backend"] == "ONLINE"
    assert "NOT PROBED" in diagnostics.json()["ai_engine"]

    models = client.get("/api/models")
    assert models.status_code == 200, models.text
    assert all(model["status"] in {"MODEL NOT DOWNLOADED", "RUNTIME NOT VERIFIED"} for model in models.json())


def test_model_catalogue_reports_unverified_installed_bundle_without_importing_monai(client, monkeypatch, tmp_path):
    """Installed files are distinguished from validated, runnable AI model weights."""
    from app import main

    model_id = "spleen_ct_segmentation"
    test_bundle = tmp_path / "spleen"
    (test_bundle / "configs").mkdir(parents=True)
    (test_bundle / "models").mkdir()
    (test_bundle / "configs" / "inference.json").write_text("{}", encoding="utf-8")
    (test_bundle / "models" / "weights.pt").write_bytes(b"not-real-weights")

    original_model_path = main.ai_service.model_path
    monkeypatch.setattr(
        main.ai_service,
        "model_path",
        lambda requested_id: test_bundle if requested_id == model_id else original_model_path(requested_id),
    )
    response = client.get("/api/models")
    assert response.status_code == 200, response.text
    chosen = next(model for model in response.json() if model["model_id"] == model_id)
    assert chosen["status"] == "RUNTIME NOT VERIFIED"
