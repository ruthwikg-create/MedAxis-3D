$ErrorActionPreference = "Stop"

Write-Host "=== MedAxis 3D ===" -ForegroundColor Cyan
Write-Host "Starting backend and frontend..."

$root = Split-Path -Parent $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\backend'; if (!(Test-Path '.venv')) { py -m venv .venv }; .\.venv\Scripts\Activate.ps1; pip install -r requirements.txt; uvicorn app.main:app --reload --port 8000"
Start-Sleep -Seconds 2
Start-Process powershell -ArgumentList "-NoExit","-Command","cd '$root\frontend'; npm install; npm run dev"

Write-Host "Backend:  http://localhost:8000"
Write-Host "Frontend: http://localhost:3000"
