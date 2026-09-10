@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS Frontend (Vue3)
echo ========================================
echo.

cd /d "%~dp0frontend"

echo [1/2] Checking Node.js...
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found!
    pause
    exit /b 1
)

echo [2/2] Starting dev server...
echo.
echo   Frontend: http://localhost:5173
echo   Proxy -> Backend: http://localhost:8000
echo.
echo   Press Ctrl+C to stop
echo ----------------------------------------

npm run dev

pause
