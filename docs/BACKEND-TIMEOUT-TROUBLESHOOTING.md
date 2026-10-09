# Windows FastAPI health-check startup and timeout regression

## Reported issue

Chrome `localhost:3000` displayed "Python backend disconnected" with `signal timed out`.
This is a **12-second frontend timeout** in this branch; older versions timed out after 6 seconds.
It is not proof that FastAPI is stopped.

## Code findings

Prior to this patch, opening the frontend generated **concurrent requests** to:
- `/api/health`: repeatedly checked every MONAI model via `ai_service.model_status` and imported `torch`/`monai`.
- `/api/system/diagnostics`: eagerly checked MONAI runtime and probed CUDA.
- `/api/models`: performed costly model-runtime checks for every catalog entry.

On Windows, importing PyTorch/MONAI and probing GPU during startup can cause long delays. Deep status checking is now deferred to the explicit `/api/models/{model_id}/status` and `/api/system/readiness` endpoints, **not** the health poll. The regular `/api/models` endpoint only checks whether model files are present and reports `RUNTIME NOT VERIFIED` when present. It cannot claim a model is ready for inference until explicitly verified.

The health endpoint conservatively reports `ai_readiness_deferred: true` and `ai_models: false`. **The false value is a liveness-safety default, not a negative comprehensive model readiness determination.** The UI uses backend polling to automatically recover the connection indicator.

## Windows use

Open CMD at project root:

```cmd
cd /d D:\Boredom\MedAxis-3D
START_BACKEND_WINDOWS.cmd
```

Leave the backend terminal open. This script uses `backend\.venv\Scripts\python.exe` and does not reinstall dependencies. If the backend crashes, it remains visible at the `pause` step to show why.

Start frontend in a separate CMD:

```cmd
cd /d D:\Boredom\MedAxis-3D\frontend
npm run dev -- --port 3000
```

Check that the API responds directly, without Next.js:

```cmd
curl.exe --max-time 20 -v http://127.0.0.1:8000/api/health
```

Also open `http://127.0.0.1:8000/api/health` in Chrome. If the URL times out, the issue is in FastAPI startup, process health, or resource contention, not React.

Use `netstat -ano | findstr :8000` to check whether any process is listening on port 8000. For errors, inspect the backend terminal and check RAM/CPU in Task Manager.

## Acceptance criteria

- [ ] Windows backend `/api/health` responds quickly after FastAPI startup, with JSON `status: ONLINE`.
- [ ] Backend startup and `/api/health` do not require any model downloads or GPU initialization.
- [ ] `/api/system/diagnostics` and `/api/models` do not import Torch/MONAI.
- [ ] On initial frontend startup, the connectivity warning disappears when health succeeds.
- [ ] When FastAPI exits, the frontend shows a warning after the next 20-second poll; after FastAPI restarts, the warning clears on its next poll or after pressing Retry connection.
- [ ] Open Demo Case, navigate multiple slices, view MPR, and verify research measurements still work.
- [ ] `cd frontend && npm run typecheck && npm run build` and `cd backend && python -m pytest -q` pass.
- [ ] Check actual model readiness explicitly before enabling any AI inference.

Important: This change improves connectivity and transparency, not the correctness or clinical readiness of diagnostic outputs. MedAxis is still research-only.
