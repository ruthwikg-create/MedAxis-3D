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

"%PY%" -c "import monai,torch,fire,requests,huggingface_hub; print('MONAI:', monai.__version__); print('Torch:', torch.__version__, 'CUDA:', torch.cuda.is_available()); print('Downloader dependencies: OK')" || exit /b 1

for %%A in (
"wholeBody_ct_segmentation"
"spleen_ct_segmentation"
"prostate_mri_anatomy"
"ventricular_short_axis_3label"
"brats_mri_segmentation"
"lung_nodule_ct_detection"
) do (
  echo.
  echo Downloading %%A ...
  "%PY%" -m monai.bundle download --name "%%A" --bundle_dir "%ROOT%\backend\models\bundles" --source monaihosting --remove_prefix monai_ --progress || exit /b 1
)

echo.
echo Verifying requested downloaded bundle contracts...
"%PY%" -c "from app.services import ai; requested=['wholeBody_ct_segmentation','spleen_ct_segmentation','prostate_mri_anatomy','ventricular_short_axis_3label','brats_mri_segmentation','lung_nodule_ct_detection']; bad=[m for m in requested if not ai.model_status(m)['inference_ready']]; [print(m, '=>', ai.model_status(m)['status']) for m in requested]; print('Not ready:', bad); raise SystemExit(1 if bad else 0)" || exit /b 1

echo.
echo ALL REQUESTED MONAI BUNDLES ARE INSTALLED AND INFERENCE-READY.
echo Note: pathology_tumor_detection is intentionally not part of this CT/MRI workstation download set.
exit /b 0
