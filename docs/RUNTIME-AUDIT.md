# MedAxis runtime audit — frontend/backend connectivity

## Reviewed source areas

- Next.js frontend startup, main workspace and API helper
- FastAPI health, diagnostics, readiness and synthetic case endpoints
- Existing pytest integration tests and CI setup
- Authentication configuration and public repository hygiene

## Implemented fixes

- `frontend/lib/api.ts`: actionable network failure messages identifying the configured API base; preserves structured FastAPI `detail` errors and HTTP statuses; download endpoints use the same error handling.
- `frontend/components/BackendStatus.tsx`: validates `/api/health`, displays a retryable backend-disconnected warning, and distinguishes an offline Python service from a failed clinical processing operation.
- `frontend/app/page.tsx`: adds backend status to the main workstation without removing viewer functionality.
- `backend/tests/test_workstation.py`: regression checks for health, diagnostics and explicit research/non-clinical readiness.

## How to run on Windows (two terminals)

Backend CMD:

```cmd
cd /d D:\Boredom\MedAxis-3D\backend
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend CMD:

```cmd
cd /d D:\Boredom\MedAxis-3D\frontend
npm ci
npm run typecheck
npm run build
npm run dev -- --port 3000
```

Check `http://127.0.0.1:8000/api/health`, then `http://localhost:3000`. Next, use **Create Demo** to test the synthetic phantom and only then attempt local synthetic DICOM import.

## Known release blockers

1. The example `.env.example` uses `AUTH_REQUIRED=false`. **Only use this for isolated, local synthetic data**. Production-style deployments require verified authorization and a securely provisioned secret. The API's role controls need independent security review.
2. The JWT is stored in browser `localStorage`. Assess XSS implications and consider server-managed HttpOnly session cookies before any clinical deployment.
3. The public repository tracks `data/medaxis-dev.db`. Inspect the database offline for any identifiable medical information or credentials. If sensitive, remove it from the repository and history using an approved remediation plan; deleting a file in a new commit alone does not eliminate the original exposure.
4. The backend/AI runtime is resource-heavy; not all models or Torch/MONAI dependencies are available on every Windows machine.
5. Production DICOM/NIfTI decoding, calibrated quantitative measurements, segmentation, model inference and rendering accuracy are **not** fully covered by these connection tests.
6. An untested merge of RadAssist and WebPACS into MedAxis should not be represented as complete or clinically validated.

## Evidence required to close this PR

- [ ] Local `npm run typecheck` passes
- [ ] Local `npm run build` passes
- [ ] Backend `python -m pytest -q` passes
- [ ] Both processes run concurrently; API health JSON returns `status: ONLINE`
- [ ] Frontend displays a helpful offline notice when the Python server is stopped
- [ ] Retry removes the notice after the Python backend starts
- [ ] Synthetic demo opens, MPR and analysis work, and import error feedback is readable
- [ ] No credentials or patient data in public GitHub history
- [ ] Independently validate spatial/HU/model outputs prior to any serious research conclusions

**No code change in this PR establishes medical device approval, diagnostic safety or regulatory compliance.**
