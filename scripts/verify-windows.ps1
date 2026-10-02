$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

Write-Host "== MedAxis 3D frontend typecheck =="
Push-Location (Join-Path $root "frontend")
npm run typecheck
Write-Host "== MedAxis 3D frontend build =="
npm run build
Pop-Location

Write-Host "== MedAxis 3D backend tests =="
Push-Location (Join-Path $root "backend")
python -m pytest -q
Pop-Location

Write-Host "ALL LOCAL VERIFICATION STEPS PASSED"
