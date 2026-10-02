@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"
if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo ERROR: Run INSTALL_WINDOWS.cmd first.
  exit /b 1
)

echo This downloads official MONAI Model Zoo research bundles into backend\models\bundles.
echo Model weights are not redistributed by MedAxis; review each bundle license before use.
echo.
"%ROOT%\backend\.venv\Scripts\python.exe" -c "import monai; print('MONAI runtime:', monai.__version__)" || exit /b 1

for %%M in (wholeBody_ct_segmentation spleen_ct_segmentation prostate_mri_anatomy ventricular_short_axis_3label brats_mri_segmentation lung_nodule_ct_detection) do (
  echo Downloading %%M ...
  "%ROOT%\backend\.venv\Scripts\python.exe" -m monai.bundle download --name %%M --bundle_dir "%ROOT%\backend\models\bundles" --source monaihosting || exit /b 1
)

echo.
echo MONAI bundle download completed. Use MedAxis Model Manager to verify each bundle status.
exit /b 0
