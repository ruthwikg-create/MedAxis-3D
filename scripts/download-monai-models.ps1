$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "backend .venv is missing. Run INSTALL_WINDOWS.cmd first."
}

$models = @(
  "wholeBody_ct_segmentation",
  "spleen_ct_segmentation",
  "prostate_mri_anatomy",
  "ventricular_short_axis_3label",
  "brats_mri_segmentation",
  "lung_nodule_ct_detection",
  "pathology_tumor_detection"
)
$bundleDir = Join-Path $root "backend\models\bundles"
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null

& $python -c "import monai,torch,fire,requests,huggingface_hub; print('MONAI', monai.__version__); print('Torch', torch.__version__, 'CUDA', torch.cuda.is_available()); print('Downloader dependencies: OK')"
if ($LASTEXITCODE -ne 0) { throw "MONAI/PyTorch/downloader dependency check failed." }

foreach ($name in $models) {
  Write-Host "Downloading $name..." -ForegroundColor Cyan
  & $python -m monai.bundle download --name $name --bundle_dir $bundleDir --source monaihosting --remove_prefix monai_ --progress
  if ($LASTEXITCODE -ne 0) { throw "Download failed for $name." }
}

Write-Host "Verifying requested MedAxis model readiness..." -ForegroundColor Cyan
& $python -c "from app.services import ai; requested=['wholeBody_ct_segmentation','spleen_ct_segmentation','prostate_mri_anatomy','ventricular_short_axis_3label','brats_mri_segmentation','lung_nodule_ct_detection','pathology_tumor_detection']; bad=[m for m in requested if not ai.model_status(m)['inference_ready']]; [print(m, '=>', ai.model_status(m)['status']) for m in requested]; print('Not ready:', bad); raise SystemExit(1 if bad else 0)"
if ($LASTEXITCODE -ne 0) { throw "One or more requested bundles failed the MedAxis readiness contract." }

Write-Host "ALL REQUESTED MONAI BUNDLES ARE INSTALLED AND INFERENCE-READY." -ForegroundColor Green
Write-Host "Pathology is included as an optional MONAI whole-slide research model."
