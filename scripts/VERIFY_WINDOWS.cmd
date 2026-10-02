@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"

echo ==========================================
echo MedAxis 3D 4.1.1 - verification
 echo ==========================================

if not exist "%ROOT%\backend\.venv\Scripts\python.exe" (
  echo ERROR: backend .venv is missing. Run scripts\INSTALL_WINDOWS.cmd first.
  exit /b 1
)
if not exist "%ROOT%\frontend\node_modules" (
  echo ERROR: frontend node_modules is missing. Run scripts\INSTALL_WINDOWS.cmd first.
  exit /b 1
)

cd /d "%ROOT%\frontend"
echo [1/3] TypeScript...
npm run typecheck || exit /b 1

echo [2/3] Next.js production build...
npm run build || exit /b 1

cd /d "%ROOT%\backend"
echo [3/3] Python regression tests...
"%ROOT%\backend\.venv\Scripts\python.exe" -m pytest -q || exit /b 1

echo.
echo ALL VERIFICATION CHECKS PASSED.
exit /b 0
