# -*- coding: utf-8 -*-
"""生成 start-celery.bat（Celery worker + beat 双进程启动器）。

为什么用脚本生成而不是直接 Write
================================
`windows-launcher-docker-prelude` skill 的坑 2：`.bat` 必须**纯 CRLF**，
混入孤立 LF 会让 cmd 认不出标签 / `goto` 失效（症状诡异且不报错），
而 Write/Edit 工具插入的行是 LF。⇒ 走 bytes 写盘 + 立即回读断言。

skill 的坑 3：控制台输出避开 GBK 外字形 —— `⇒`(U+21D2) 会被吞成 `?`，
汉字反而没事。本脚本全文用 `->`，不出现 `⇒` / `✅`。

skill §5：`echo` 行里的裸 `>` 会被 cmd 当重定向（会真的落一个文件）。
本脚本的提示行里 URL 一律不加 `->` 之外的重定向符号。
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "start-celery.bat"

TEXT = """@echo off
chcp 65001 >nul
echo ========================================
echo   CrossBorder AI SaaS - Celery Worker + Beat
echo ========================================
echo.

cd /d "%~dp0backend"

rem --- 项目固定 Python 环境：conda reactAgents ---
set "PY=D:\\work\\anaconda\\anaconda3\\envs\\reactAgents\\python.exe"

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
echo   Beat schedule:    backend\\logs\\celerybeat-schedule
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

start "Celery Worker" /d "%~dp0backend" cmd /k ""%PY%" worker.py"
start "Celery Beat"   /d "%~dp0backend" cmd /k ""%PY%" beat.py"

echo.
echo Both launched. Close their windows to stop them.
echo.
pause
"""

body = TEXT.replace("\n", "\r\n")
TARGET.write_bytes(body.encode("utf-8"))

# ---- 回读断言（不靠自述）----
raw = TARGET.read_bytes()
crlf = raw.count(b"\r\n")
lf = raw.count(b"\n")
print("落盘:", TARGET)
print("  bytes =", len(raw))
print("  CRLF  =", crlf, "| LF-only =", lf - crlf)
assert lf == crlf, "混入了孤立 LF，cmd 会认不出标签"
assert b"\xc3\xaf\xc2\xbb\xc2\xbf" not in raw[:8], "文件头混入了双重编码的假 BOM"
assert "⇒".encode("utf-8") not in raw, "含 GBK 外字形，控制台会吞成问号"
print("  断言: 纯 CRLF / 无假 BOM / 无 ⇒")
print("  行数 =", crlf)
