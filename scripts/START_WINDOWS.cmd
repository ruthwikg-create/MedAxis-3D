@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo Backend environment is missing.
  echo Running installer first...
  call "%ROOT%\scripts\INSTALL_WINDOWS.cmd" || exit /b 1
)
if not exist "%ROOT%\frontend\node_modules" (
  echo Frontend dependencies are missing.
  echo Running installer first...
  call "%ROOT%\scripts\INSTALL_WINDOWS.cmd" || exit /b 1
)

echo Starting backend...
start "MedAxis 3D Backend" cmd /k "cd /d ""%ROOT%\backend"" ^&^& ""%ROOT%\backend\.venv\Scripts\python.exe"" -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"

ping 127.0.0.1 -n 3 >nul

echo Starting frontend...
start "MedAxis 3D Frontend" cmd /k "cd /d ""%ROOT%\frontend"" ^&^& npm run dev"

ping 127.0.0.1 -n 3 >nul
start "" http://localhost:3000

echo.
echo MedAxis 3D is starting.
echo Frontend: http://localhost:3000
echo Backend:  http://127.0.0.1:8000/docs
echo Keep both spawned terminal windows open while using the application.
exit /b 0
