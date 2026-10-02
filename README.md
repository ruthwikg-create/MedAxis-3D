# MEDAXIS 3D 4.1.1
## Advanced Multimodal Medical Imaging & Dataset + AI Analytics Workstation

**Created By: Ruthwik Goparaju**

MedAxis 3D 4.1.1 is a research/educational medical-imaging workstation that combines source-derived visualization and quantitative analysis with configurable MONAI inference, validation, storage, authentication/RBAC, DICOM SEG/SR export, specialty cardiac/prostate analysis, radiomics and CT-to-MRI research synthesis.

## Important scientific status

The application is intentionally conservative: software features are executable, but **clinical validation is not created by code**. Published MONAI bundles are exposed with their publisher metadata and are labeled `Publisher benchmark only; not MedAxis clinical validation`. PI-RADS support is a structured v2.1 reader worksheet rather than an automated score generator. Cross-modality synthesis is disabled until a compatible TorchScript checkpoint is explicitly configured.

## Feature set

- DICOM / NIfTI import with geometry checks and secure ZIP extraction
- 2D CT/MR viewer, window/level, slice navigation and cine
- Axial/sagittal/coronal MPR with synchronized crosshair
- 3D surface reconstruction from actual volume-derived masks using Marching Cubes
- Dataset & AI Analytics Suite
- MONAI Model Zoo registry with download/status/inference jobs
- Whole-body CT, spleen CT, prostate MRI, ventricular short-axis MRI, BraTS MRI and lung-nodule CT bundle integrations
- Source-derived radiomics and educational CT tissue bands
- Research binary radiomics classifier training/prediction
- Segmentation validation: Dice, IoU, HD95, ASSD, volume difference
- Calibration evaluation: ECE and Brier score from held-out probabilities/labels
- Cardiac LV/RV functional metrics from 4D cine labelmaps
- Prostate anatomy/ADC/T2 quantitative analysis
- PI-RADS v2.1 structured reader worksheet
- DICOM SEG and DICOM SR export using highdicom 0.28.1 when source geometry is compatible
- Longitudinal study selection/comparison metadata
- PostgreSQL metadata persistence when `DATABASE_URL` points to PostgreSQL
- S3-compatible durable raw-file mirroring when S3 settings are configured
- JWT authentication and role-based access control
- Administrator user management
- CT → MRI-like research synthesis through a user-supplied TorchScript model
- Provenance, audit trail, QC and research validation status

## Roles

`administrator`, `radiologist`, `clinician`, `researcher`, `biomedical_engineer`, `technician`, `viewer`

## Production configuration

Copy `.env.example` to `.env` and configure a strong `JWT_SECRET`, PostgreSQL `DATABASE_URL`, S3 credentials/bucket, `AUTH_REQUIRED=true`, and a compatible `CROSS_MODALITY_MODEL_PATH`. Keep secrets out of source control.

## MONAI bundles

The Model Manager downloads official MONAI Model Zoo bundles on demand. Model weights are intentionally **not bundled** into this ZIP because they can be large and their licenses and dataset terms must be accepted/configured by the deployer. The selected bundles include whole-body CT segmentation, prostate MRI anatomy, ventricular short-axis 3-label cardiac MRI, BraTS MRI and lung-nodule CT detection.

## Run on Windows

### Backend
```powershell
cd backend
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

### Frontend
```powershell
cd frontend
npm install
npm run typecheck
npm run build
npm run dev
```

Open `http://localhost:3000`.

## Local PostgreSQL + S3 option

A production-style deployment should use PostgreSQL for metadata and S3-compatible object storage for raw imaging. The application still keeps a local processing cache because DICOM/NIfTI decoders and ML runtimes operate on files. Configure S3 first; then re-import studies so raw objects are mirrored to the bucket.

## Verification

```powershell
python -m compileall -q backend/app backend/tests
pytest -q
cd frontend
npm run typecheck
npm run build
```

## Clinical / regulatory boundaries

This build makes no FDA, CE, clinical-validation, diagnostic-accuracy, or medical-device certification claim. DICOM SEG/SR export is standards-oriented software functionality; each deployment still needs interoperability testing and validation against its target PACS/viewer.


## v4.1.1 additions

- Production-oriented PostgreSQL connection pooling and persistence fallback from database metadata.
- S3-compatible durable-object archive with case raw-data recovery and prefix cleanup.
- MONAI bundle downloader through the supported `monai.bundle.download` interface; bundle versions are pinned in the model registry.
- MONAI inference uses the bundle's own inference configuration with explicit device overrides; model output is accepted only when a supported artifact is unambiguously produced.
- Cohort segmentation validation with case-level Dice/IoU/HD95/ASSD and bootstrap confidence intervals.
- Temperature-scaling calibration fit for held-out research probabilities, plus Platt-scaled probabilities for the research radiomics classifier.
- Official model metadata is kept as publisher benchmark information; it is not represented as MedAxis clinical validation.
- PI-RADS remains a structured v2.1 reader worksheet; the app does not auto-assign a clinical category.
- CT-to-MRI synthesis runs only when a real TorchScript checkpoint is configured and shape/finite-output checks pass.

## Clinical validation boundary

The application contains real metric, cohort, and calibration computations, but software configuration cannot create clinical validation, regulatory clearance, or diagnostic claims. Any deployed AI model must be independently evaluated on a locked representative cohort under a documented protocol before clinical use.
