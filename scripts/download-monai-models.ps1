$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
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
python -c "import monai; print('MONAI', monai.__version__)"
foreach ($m in $models) {
  Write-Host "Downloading $($m.Name) v$($m.Version)..." -ForegroundColor Cyan
  python -m monai.bundle download --name $($m.Name) --version $($m.Version) --bundle_dir $bundleDir --source github
}
Write-Host "Official MONAI bundles downloaded. Review each bundle's model/data license, then use Model Manager to verify status and run research validation." -ForegroundColor Green
