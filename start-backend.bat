@echo off
chcp 65001 >nul
rem ============================================================
rem  This file must stay PURE ASCII. Two measured reasons:
rem   1) chcp 65001 + non-ASCII bytes in a .bat make cmd.exe lose
rem      sync while reading the file, so rem comment lines get
rem      executed as commands. Probe-verified: ASCII-only fixes it.
rem   2) click >= 8.0 expands globs in sys.argv on Windows by default
rem      (windows_expand_args=True), so --reload-exclude "logs/*"
rem      blows up into many real paths and uvicorn refuses to start.
rem      All uvicorn args now live in backend\run_dev.py instead.
rem  Chinese console output comes from run_dev.py and
rem  ensure-docker-deps.ps1, never from this file.
rem ============================================================
echo ========================================
echo   CrossBorder AI SaaS Backend Server
echo ========================================
echo.

cd /d "%~dp0backend"

rem --- Project python: conda env reactAgents ---
set "PY=D:\work\anaconda\anaconda3\envs\reactAgents\python.exe"

if not exist "%PY%" (
    echo ERROR: project python not found: %PY%
    echo        Fix: create the conda env "reactAgents" first.
    pause
    exit /b 1
)

rem --- Prereq: PostgreSQL + Redis ---
rem     Must use docker start, NOT docker compose up: both containers
rem     were created by hand with docker run (no compose labels), so
rem     compose would fail with a container_name conflict.
echo [1/3] Ensuring Docker deps: PostgreSQL + Redis...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure-docker-deps.ps1"
if errorlevel 1 (
    echo.
    echo ERROR: Docker deps not ready - backend cannot reach DB or Redis.
    echo        Fix: start Docker Desktop then rerun. Or: docker start my-postgres my-redis
    pause
    exit /b 1
)

echo [2/3] Using: %PY%
"%PY%" --version

echo [3/3] Starting server on http://localhost:8000...
echo.

"%PY%" "%~dp0backend\run_dev.py"

pause
