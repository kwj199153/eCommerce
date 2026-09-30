@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS Frontend (Vue3)
echo ========================================
echo.

cd /d "%~dp0frontend"

echo [1/3] Checking Node.js...
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found!
    pause
    exit /b 1
)

echo [2/3] Checking frontend dependencies...

rem --- node_modules 完整性：.bin 被外部操作清空过（整树曾被误搬走）---
rem     症状是 'vite' 不是内部或外部命令；修复一条命令：npm install
if not exist "node_modules\.bin\vite.cmd" (
    echo ERROR: node_modules is incomplete - node_modules\.bin\vite.cmd missing.
    echo        Fix: run "npm install" inside the frontend folder.
    pause
    exit /b 1
)

echo [3/3] Starting dev server...
echo.
echo   Frontend: http://localhost:5173
echo   Proxy to Backend: http://localhost:8000
echo.
echo   Press Ctrl+C to stop
echo ----------------------------------------

npm run dev

echo.
echo ----------------------------------------
echo Dev server exited. If the window closed instantly, rerun from a terminal.
pause
