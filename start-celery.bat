@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS - Celery Worker + Beat
echo ========================================
echo.

cd /d "%~dp0backend"

rem --- 项目固定 Python 环境：conda reactAgents ---
set "PY=D:\work\anaconda\anaconda3\envs\reactAgents\python.exe"

rem --- 命门检查（skill §5）：这三件事缺一个，窗口一闪就没，拿不到任何线索 ---
if not exist "%PY%" (
    echo ERROR: 找不到项目 Python 环境: %PY%
    echo        请确认 conda 环境 reactAgents 已创建
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
start "Celery Worker" /d "%~dp0backend" cmd /k "set LOG_SINK_ROLE=worker&& "%PY%" worker.py"
start "Celery Beat"   /d "%~dp0backend" cmd /k "set LOG_SINK_ROLE=beat&& "%PY%" beat.py"

echo.
echo Both launched. Close their windows to stop them.
echo.
pause
