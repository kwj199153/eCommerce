# ============================================================
#  店管家 AI · 后端镜像
# ------------------------------------------------------------
#  构建（在项目根目录）：
#     docker build -f backend/Dockerfile -t storekeeper-api:latest ./backend
#  运行：
#     docker run --rm -p 8000:8000 --env-file backend/.env storekeeper-api:latest
#
#  设计取舍（每条都对应一个实际会踩的坑）：
#   1. **非 root 运行**：容器逃逸时拿到的是 app 用户，不是 root。
#   2. **slim 而非 alpine**：alpine 用 musl libc，asyncpg / psycopg2 的
#      wheel 不匹配，会退化成源码编译（还要装 postgresql-dev + 一堆 gcc 依赖），
#      体积和构建时间反而更差。
#   3. **gcc/libpq-dev 装在同一个 stage 里**：本镜像不做多阶段瘦身，
#      因为 alembic 迁移和 psycopg2 在运行时都可能需要 libpq。
#      若后续追求镜像体积，再把编译期依赖拆到 builder stage。
#   4. **HEALTHCHECK 打 /health**：该端点会真探活 PostgreSQL/Redis，
#      比只 ping 端口有意义（端口活着但数据库断了，一样不能干活）。
#   5. **单 worker 默认**：/metrics 与进程内限流计数都是**进程级**的，
#      多 worker 会让指标口径不一致。Redis 起来后限流本身没问题，
#      但指标仍需按 instance 聚合 —— 用 UVICORN_WORKERS 显式放大。
# ============================================================

FROM python:3.12-slim

# PYTHONUNBUFFERED：日志实时输出，不然容器里看不到运行日志
# PYTHONDONTWRITEBYTECODE：不生成 .pyc，避免只读文件系统下报错
# PIP_NO_CACHE_DIR：不在镜像里留 pip 缓存
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 系统依赖：
#   build-essential / libpq-dev —— asyncpg(driver 直接编译) 与 psycopg2(alembic 用) 需要
#   curl —— HEALTHCHECK 用；slim 镜像不自带
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 先只拷依赖清单：requirements.txt 不变时这一层走缓存，
# 改业务代码不会触发重新装包（构建时间从几分钟降到几秒）
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 再拷源码（变化最频繁的放最后）
COPY . .

# 运行期需要的可写目录 + 非 root 用户
#   logs/    —— loguru 按天写日志
#   uploads/ —— AIGC 素材落盘（对外经 /static 暴露）
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /app/logs /app/uploads \
    && chown -R app:app /app

USER app

EXPOSE 8000

# start-period 给足 60s：启动时要跑 seed、alembic/建表、加载店铺到内存
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# ⚠️ 不要加 --reload：那是开发用，会起 watchdog 进程且显著吃 CPU。
# ⚠️ uvicorn 自带的 access 日志已由 core/logger.py 关闭（与 RequestLogMiddleware
#    重复且信息更少），此处无需额外配置 —— 该中间件会清掉 uvicorn 的 handler。
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
