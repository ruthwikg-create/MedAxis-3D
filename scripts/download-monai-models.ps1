$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
  throw "backend .venv is missing. Run INSTALL_WINDOWS.cmd first."
}

$models = @(
  @{ Name = "wholeBody_ct_segmentation"; Version = "0.2.7" },
  @{ Name = "spleen_ct_segmentation"; Version = "0.6.1" },
  @{ Name = "prostate_mri_anatomy"; Version = "0.3.6" },
  @{ Name = "ventricular_short_axis_3label"; Version = "0.3.5" },
  @{ Name = "brats_mri_segmentation"; Version = "0.5.4" },
  @{ Name = "lung_nodule_ct_detection"; Version = "0.6.10" }
)
$bundleDir = Join-Path $root "backend\models\bundles"
New-Item -ItemType Directory -Force -Path $bundleDir | Out-Null

& $python -c "import monai,torch; print('MONAI', monai.__version__); print('Torch', torch.__version__, 'CUDA', torch.cuda.is_available())"
if ($LASTEXITCODE -ne 0) { throw "MONAI/PyTorch runtime check failed." }

foreach ($m in $models) {
  Write-Host "Downloading $($m.Name) v$($m.Version)..." -ForegroundColor Cyan
  & $python -m monai.bundle download --name $m.Name --version $m.Version --bundle_dir $bundleDir --source github
  if ($LASTEXITCODE -ne 0) { throw "Download failed for $($m.Name) v$($m.Version)." }
}

Write-Host "Verifying MedAxis model readiness..." -ForegroundColor Cyan
& $python -c "from app.services import ai; bad=[m for m in ai.MODEL_CATALOG if not ai.model_status(m)['inference_ready']]; print('Not ready:', bad); raise SystemExit(1 if bad else 0)"
if ($LASTEXITCODE -ne 0) { throw "One or more downloaded bundles failed the MedAxis readiness contract." }

Write-Host "ALL REQUESTED MONAI BUNDLES ARE INSTALLED AND INFERENCE-READY." -ForegroundColor Green
