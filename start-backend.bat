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

rem --- 排除监听：logs/ 与 .venv/（P0-2 日志治理，2026-09-30）---
rem     uvicorn --reload 原本监听整个 backend 目录，**包括 backend/logs 自己**，
rem     于是形成「写日志 -> watchfiles 报告文件变更 -> 再写一条日志 -> ...」的自反馈，
rem     实测单日白刷约 2000 条 watchfiles 日志（日志原文里能看到 logs\2026-09-30.log 自己）。
rem     backend/.venv 也在监听范围内，一并排除。
%PY% -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info --reload-exclude "logs/*" --reload-exclude "*.log" --reload-exclude "*.log.gz" --reload-exclude ".venv/*" --reload-exclude "__pycache__/*"

pause
