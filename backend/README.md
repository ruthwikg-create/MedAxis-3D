# MedAxis 3D — Backend

FastAPI research/educational imaging service.

## Run

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The service stores development cases under `../data/cases`.

### Important
- DICOM/NIfTI measurements are computed from decoded source data.
- The bundled demo is a clearly labelled synthetic research phantom.
- Organ-specific AI model binaries are not bundled; Model Manager reports them as unavailable.
- DICOM SEG/SR export endpoints intentionally return a structured unavailable response rather than producing an invalid object.
- This build is **Research / Educational Use** and is not represented as clinically validated or regulator-approved.
