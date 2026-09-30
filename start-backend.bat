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

rem --- 前置：确保 Docker 依赖就绪（PostgreSQL + Redis）---
rem     必须用 docker start，不能用 docker compose up：这两个容器是 docker run
rem     手工建的（无 compose 标签），compose 会因 container_name 冲突报 already in use。
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
%PY% --version

echo [3/3] Starting server on http://localhost:8000...
echo.
echo   API Docs: http://localhost:8000/docs
echo   Health:   http://localhost:8000/health
echo.
echo   Press Ctrl+C to stop
echo ----------------------------------------

%PY% -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info

pause
