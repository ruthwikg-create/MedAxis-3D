@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"
set "PY=%ROOT%\backend\.venv\Scripts\python.exe"

if not exist "%PY%" (
  echo ERROR: backend .venv is missing. Run INSTALL_WINDOWS.cmd first.
  exit /b 1
)

echo This downloads official MONAI research bundles into backend\models\bundles.
echo Model weights are intentionally excluded from Git.
echo Review each bundle's license and publisher validation before research use.
echo.

"%PY%" -c "import monai; import torch; print('MONAI:', monai.__version__); print('Torch:', torch.__version__, 'CUDA:', torch.cuda.is_available())" || exit /b 1

for %%A in (
"wholeBody_ct_segmentation|0.2.7"
"spleen_ct_segmentation|0.6.1"
"prostate_mri_anatomy|0.3.6"
"ventricular_short_axis_3label|0.3.5"
"brats_mri_segmentation|0.5.4"
"lung_nodule_ct_detection|0.6.10"
) do (
  for /f "tokens=1,2 delims=|" %%B in ("%%A") do (
    echo.
    echo Downloading %%B v%%C ...
    "%PY%" -m monai.bundle download --name "%%B" --version "%%C" --bundle_dir "%ROOT%\backend\models\bundles" --source github || exit /b 1
  )
)

echo.
echo Verifying downloaded bundle contracts...
"%PY%" -c "from app.services import ai; bad=[]; [(bad.append(m) if not ai.model_status(m)['inference_ready'] else None) for m in ai.MODEL_CATALOG]; print('Models not inference-ready:', bad); raise SystemExit(1 if bad else 0)" || exit /b 1

echo.
echo ALL REQUESTED MONAI BUNDLES ARE INSTALLED AND INFERENCE-READY.
exit /b 0
