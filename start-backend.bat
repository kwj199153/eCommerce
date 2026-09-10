@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS Backend Server
echo ========================================
echo.

cd /d "%~dp0backend"

rem --- 项目固定 Python 环境：conda reactAgents ---
set "PY=D:\work\anaconda\anaconda3\envs\reactAgents\python.exe"

if not exist "%PY%" (
    echo ERROR: 找不到项目 Python 环境: %PY%
    echo   请确认 conda 环境 reactAgents 已创建
    pause
    exit /b 1
)

echo [1/2] Using: %PY%
%PY% --version

echo [2/2] Starting server on http://localhost:8000...
echo.
echo   API Docs: http://localhost:8000/docs
echo   Health:   http://localhost:8000/health
echo.
echo   Press Ctrl+C to stop
echo ----------------------------------------

%PY% -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info

pause
