@echo off
setlocal
title MedAxis-3D Python Backend (Research Only)

set "ROOT=%~dp0"
cd /d "%ROOT%backend"
if errorlevel 1 (
  echo [ERROR] Could not open the MedAxis backend directory.
  pause
  exit /b 1
)

set "PYTHON=%CD%\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  echo [ERROR] The backend virtual environment does not exist.
  echo Run these commands in CMD:
  echo cd /d "%CD%"
  echo py -3.11 -m venv .venv
  echo .venv\Scripts\python.exe -m pip install -r requirements.txt
  pause
  exit /b 1
)

echo.
echo MedAxis-3D Research Backend
echo Using: "%PYTHON%"
"%PYTHON%" --version
echo.
echo Starting FastAPI on http://127.0.0.1:8000
echo Once running, check http://127.0.0.1:8000/api/health
echo Leave this window open while using the workstation.
echo.
"%PYTHON%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level info

echo.
echo [INFO] FastAPI has exited. Review the error messages above.
pause
endlocal
