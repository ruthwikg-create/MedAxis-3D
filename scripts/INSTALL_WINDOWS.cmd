@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0.."
set "ROOT=%CD%"

echo ==========================================
echo MedAxis 3D 4.1.1 - Windows installer
 echo ==========================================

where py >nul 2>&1 || (echo ERROR: Python launcher ^(py^) was not found. Install Python 3.11+ and try again.& exit /b 1)
where npm >nul 2>&1 || (echo ERROR: npm was not found. Install Node.js 20+ and try again.& exit /b 1)

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo [1/5] Creating backend virtual environment...
  py -3 -m venv "%ROOT%\backend\.venv" || exit /b 1
) else echo [1/5] Backend virtual environment already exists.

echo [2/5] Installing Python dependencies...
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
"%ROOT%\backend\.venv\Scripts\python.exe" -m pip install -r "%ROOT%\backend\requirements.txt" || exit /b 1

echo [3/5] Installing frontend dependencies...
cd /d "%ROOT%\frontend"
npm install || exit /b 1

echo [4/5] Frontend typecheck + production build...
npm run typecheck || exit /b 1
npm run build || exit /b 1

echo [5/5] Backend regression suite...
cd /d "%ROOT%\backend"
"%ROOT%\backend\.venv\Scripts\python.exe" -m pytest -q || exit /b 1

echo.
echo INSTALLATION AND VERIFICATION COMPLETED.
echo Run START_WINDOWS.cmd to launch MedAxis 3D.
exit /b 0
