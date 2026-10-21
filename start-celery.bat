@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS - Celery Worker + Beat
echo ========================================
echo.

cd /d "%~dp0backend"

rem --- 项目固定 Python 环境：backend .venv（单一真源，见 docs/env-single-source.md）---
rem     不用 conda reactAgents 的原因：Dockerfile=3.12、CI=3.12、.venv=3.12，
rem     而 reactAgents=3.11，本地服务与 CI/线上差一个 minor。
rem     %~dp0 = 本文件所在目录，不写死盘符。
set "PY=%~dp0backend\.venv\Scripts\python.exe"

rem --- 命门检查（skill §5）：这三件事缺一个，窗口一闪就没，拿不到任何线索 ---
if not exist "%PY%" (
    echo ERROR: 找不到项目 Python 环境: %PY%
    echo        请先建 backend .venv：uv venv backend/.venv
    echo        再装依赖：backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
    pause
    exit /b 1
)
if not exist "worker.py" (
    echo ERROR: 找不到 worker.py，当前目录 %CD%
    pause
    exit /b 1
)
if not exist "beat.py" (
    echo ERROR: 找不到 beat.py，当前目录 %CD%
    pause
    exit /b 1
)

rem --- 前置：Celery 依赖 Redis（broker）与 PostgreSQL（业务表 / 结果后端）---
rem     这两个容器是 docker run 手工建的，只能 docker start，
rem     compose 会因 container_name 冲突报 already in use。
echo [1/2] Ensuring Docker deps: Redis + PostgreSQL...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ensure-docker-deps.ps1"
if errorlevel 1 (
    echo.
    echo ERROR: Docker deps not ready - Celery cannot reach Redis or PostgreSQL.
    echo        Fix: start Docker Desktop then rerun. Or: docker start my-postgres my-redis
    pause
    exit /b 1
)

echo [2/2] Starting Celery worker + beat in 2 new windows...
echo.
echo   Worker queues:    default, ai_tasks, data_export
echo   Worker metrics:   http://127.0.0.1:9100/metrics   (loopback only)
echo   Beat schedule:    backend\logs\celerybeat-schedule
echo.
echo   Scheduled tasks, all in queue default:
echo     memory.distill_all_owners             nightly
echo     billing.expire_pending_invoices       every 5 min   TTL is 30 min
echo     billing.sweep_expired_subscriptions   03:20 daily
echo     billing.reconcile_alipay_orders       04:30 daily   lookback 7 days
echo.
echo   NOTE: beat owns a single-instance schedule file.
echo         Never run two beats - they double-dispatch every task.
echo.

rem --- LOG_SINK_ROLE：让 worker / beat 各写自己的日志文件（P0-2 日志治理）---
rem     loguru 不是多进程安全的：三个进程共写 backend/logs/{date}.log 时，
rem     午夜会各自触发轮转，产出**内容完全相同的重复 .gz**（实测 2026-09-28 两份
rem     gz 解压后 md5 全等、均 738,001 行）。按角色分文件即可根治；
rem     默认角色为空，uvicorn 那份文件名不变（backend/logs/{date}.log）。
rem     ★ 上面这 5 行原本只被手工加在 start-celery.bat 里，本生成器没有，
rem       任何人重跑一次生成器就会把 P0-2 的修复连注释一起静默抹掉。
rem       r388已回写进真源，从此 bat 与生成器同源。
start "Celery Worker" /d "%~dp0backend" cmd /k "set LOG_SINK_ROLE=worker&& "%PY%" worker.py"
start "Celery Beat"   /d "%~dp0backend" cmd /k "set LOG_SINK_ROLE=beat&& "%PY%" beat.py"

echo.
echo Both launched. Close their windows to stop them.
echo.
pause
