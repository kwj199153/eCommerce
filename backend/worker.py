"""Celery Worker 入口

用于执行异步任务（AIGC 出图等耗时操作）。

## 为什么 worker 也要有 HTTP 端口

本进程是**独立于 FastAPI 的另一个 Python 进程**：

1. **指标不共享**。``core/observability/metrics.py`` 是进程内内存注册表，
   没有多进程聚合。任务终态计数（``celery_task_results_total`` /
   ``aigc_tasks_total`` / ``aigc_task_duration_ms``）都在 **worker 进程**里自增，
   后端 ``GET /metrics`` 里永远是 0。没有本端口，这些指标就是「定义了但没人看得到」，
   等于没做。
2. **存活无处可查**。本进程原先没有任何健康检查入口 ⇒ compose 里没法给它配
   healthcheck。worker 静默死掉时，容器状态仍是 ``Up``（进程由 celery 主循环持有），
   表现是「任务一直停在 pending」，而 ``docker compose ps`` 看不出异常。

## 端口的定位

- ``GET /health`` —— 存活 + 是否已 ready（Celery 完成初始化）。给 compose healthcheck 用。
- ``GET /metrics`` —— Prometheus 文本格式，与后端 ``/metrics`` 同一套渲染函数。

只绑 ``127.0.0.1``（compose 里也是 ``127.0.0.1:9100:9100``），**不对公网暴露**。

## ★★ 为什么默认池是 ``threads`` 而不是 Celery 默认的 ``prefork``

``core/observability/metrics.py`` 是**进程内**内存注册表，没有多进程聚合：

- ``prefork``（Celery 默认）：任务体跑在 **billiard 子进程**里，``AIGC_TASKS`` /
  ``CELERY_TASK_RESULTS`` / ``AIGC_TASK_DURATION`` 的计数全落在子进程内存中，
  父进程的 ``GET /metrics`` 只会看到 **0**。指标「定义了、暴露了、永远是 0」，
  排查时会误判成「任务从没跑过」。
- ``threads``：任务体跑在**父进程的线程**里。每个线程各自 ``asyncio.run`` 新建
  event loop（见 ``modules/aigc_media/tasks.py`` 顶部说明），因此不存在跨 loop
  复用连接的问题；同时指标注册表与 ``/metrics`` 服务共享同一进程 ⇒ 数字是真的。

业务侧也站 ``threads``：本项目的任务是**网络密集**型（调用 DashScope 出图，
15~25s/张），瓶颈在等 IO 而不是算 CPU，线程池比多进程更合适（内存更省、
无跨进程序列化开销）。可用 ``WORKER_POOL`` 显式改回 ``prefork``。

★ Windows 上另有 ``prefork(billiard)`` 的 spawn 陷阱：子进程会按路径**重新导入
``__main__`` 模块**。若 worker 入口脚本缺少 ``if __name__ == "__main__":`` 守卫，
子进程会在导入期再执行一次 ``worker_main()``，报出极难定位的
``ValueError: not enough values to unpack (expected 3, got 0)``
（``celery/app/trace.py`` 里 ``_localized`` 未初始化）——
现象是「worker 明明 ready、任务明明 received，就是不执行」。
本文件的 ``worker_main`` 已放在 ``__main__`` 守卫内。
"""

from __future__ import annotations

import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from celery.signals import worker_ready, worker_shutdown

from core.config import config
from core.logger import get_logger
from core.observability.metrics import render_prometheus
from core.redis import celery_app

logger = get_logger("worker")

#: 指标/健康端口。设 0 可关闭（不需要观测的场合）。
#: 与后端 /metrics 分开端口是有意的：后端 8000 是业务流量，worker 9100 是运维流量，
#: 两者生命周期与访问控制不同。
METRICS_PORT = int(os.getenv("WORKER_METRICS_PORT", "9100") or "0")
#: 绑回环 —— 这个端口没有任何鉴权，绝不能对公网开放
METRICS_HOST = os.getenv("WORKER_METRICS_HOST", "127.0.0.1")

#: 执行池。默认 threads（理由见文件顶部说明）：任务指标要与 /metrics 同进程才可见。
#: 备选 prefork（CPU 密集）/ solo（单进程顺序执行，Windows 排障用）。
WORKER_POOL = (os.getenv("WORKER_POOL", "threads") or "threads").strip()
#: 并发度。solo 池恒定单并发，传了也会被 Celery 忽略，故不传。
WORKER_CONCURRENCY = os.getenv("WORKER_CONCURRENCY", "4")
#: 节点名。%h 由 Celery 展开为主机名。
WORKER_NODE_NAME = os.getenv("WORKER_NODE_NAME", "worker1@%h")

_STARTED_AT = time.time()
#: Celery 是否已完成初始化（worker_ready 信号置位）。
#: ★ 只看进程活着是不够的：worker 可能在「启动中但还没注册任务」的状态，
#:   此时投递进来的任务会一直排队。健康检查必须区分这两种状态。
_READY = threading.Event()


@worker_ready.connect
def _on_worker_ready(sender=None, **kwargs):  # pragma: no cover - 信号回调
    _READY.set()
    logger.info("[worker] Celery 已完成初始化，开始消费队列")


@worker_shutdown.connect
def _on_worker_shutdown(sender=None, **kwargs):  # pragma: no cover - 信号回调
    _READY.clear()
    logger.info("[worker] 收到关闭信号，停止消费队列")


class _Handler(BaseHTTPRequestHandler):
    """极简 HTTP handler（stdlib，零新依赖）。

    刻意不引 Flask/aiohttp：worker 里再拉一个 Web 框架只为两个只读端点，
    是给部署多加一类依赖风险。
    """

    # 关掉默认的 stderr 访问日志（worker 的日志由 loguru 统一管，别混两套格式）
    def log_message(self, fmt, *args):  # noqa: A003 - 覆写基类方法
        return

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - 基类约定命名
        path = self.path.split("?", 1)[0].rstrip("/") or "/"

        if path == "/health":
            # ready=false 时返回 503：让 compose healthcheck 真的能判「不可用」，
            # 而不是只要进程活着就算健康（那种 healthcheck 等于没配）
            ready = _READY.is_set()
            body = (
                '{"status":"%s","ready":%s,"uptime_s":%d,"app":"%s"}'
                % ("ok" if ready else "starting", "true" if ready else "false",
                   int(time.time() - _STARTED_AT), config.app_name)
            ).encode("utf-8")
            self._respond(200 if ready else 503, body, "application/json; charset=utf-8")
            return

        if path == "/metrics":
            self._respond(
                200,
                render_prometheus().encode("utf-8"),
                "text/plain; version=0.0.4; charset=utf-8",
            )
            return

        self._respond(404, b'{"detail":"not found"}', "application/json; charset=utf-8")


def _serve_metrics() -> None:
    """在守护线程里起一个 HTTP 服务。

    必须是守护线程：主线程跑 ``worker_main``（阻塞），
    非守护线程会让 Ctrl+C / SIGTERM 之后进程无法退出。
    """
    try:
        server = ThreadingHTTPServer((METRICS_HOST, METRICS_PORT), _Handler)
    except OSError as exc:
        # 端口被占用不该让 worker 起不来 —— 观测能力缺失 ≠ 业务能力缺失
        logger.warning(
            "[worker] 指标端口 {}:{} 无法监听（{}），worker 继续启动（本次无 /metrics）",
            METRICS_HOST,
            METRICS_PORT,
            exc,
        )
        return

    thread = threading.Thread(target=server.serve_forever, name="worker-metrics", daemon=True)
    thread.start()
    logger.info("[worker] 指标/健康端点已监听 http://{}:{}/metrics", METRICS_HOST, METRICS_PORT)


if __name__ == "__main__":
    # ★ loguru 用 ``{}`` 占位，**不认** stdlib 的 ``%s``。
    #   写成 %s 时 loguru 不会报错 —— 它会把字面量 "%s" 原样打进日志、把参数丢掉
    #   （实测：日志里出现 "启动 Celery Worker: %s"）。这类错误不抛异常，只能靠看日志发现。
    logger.info("[worker] 启动 Celery Worker: {}", config.app_name)

    if METRICS_PORT:
        _serve_metrics()

    argv = [
        # ★★ 必须有字面量 "worker"：``Celery.worker_main()`` 会在 argv 里找这个
        #    子命令名，找不到就直接
        #      ValueError: The worker sub-command must be specified in argv.
        #    而 compose 里 worker 服务的启动命令正是 `python worker.py`
        #    ⇒ 缺这一项会让 worker 容器**一启动就崩溃重启**（restart: unless-stopped
        #    下表现为反复重启），而 docker compose ps 只会显示 Restarting，
        #    不明显指向「参数写错了」。实测：加之前 EXIT=1 + ValueError。
        "worker",
        "--loglevel=info",
        "--queues=default,ai_tasks,data_export",
        f"--pool={WORKER_POOL}",
    ]
    if WORKER_POOL != "solo":
        # solo 池只跑单并发，传 --concurrency 会被忽略（还会打一条 warning）
        argv.append(f"--concurrency={WORKER_CONCURRENCY}")
    argv += ["-n", WORKER_NODE_NAME]

    logger.info("[worker] pool={} concurrency={} node={}",
                WORKER_POOL, WORKER_CONCURRENCY if WORKER_POOL != "solo" else 1, WORKER_NODE_NAME)

    celery_app.worker_main(argv)
