"""
FastAPI 应用主入口

跨境电商 AI SaaS 后端 API 服务。
"""

import asyncio
import sys
import time

# Windows 必须在所有导入之前设置事件循环策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from core.config import config
from core.database import init_db, close_db, get_db_session
from core.logger import get_logger

_log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：初始化数据库连接
    _log.info("🚀 正在启动 {} v{}...", config.app_name, config.app_version)

    # ★ 摘掉 SQLAlchemy echo 的 stdout handler（兜底：engine 在 import 期就建好了，
    #   可能晚于 core/logger.py 的 setup，靠 import 顺序不可靠 → 启动时再清一次）
    from core.logger import quiet_sqlalchemy_echo_handlers

    quiet_sqlalchemy_echo_handlers()

    await init_db()
    _log.info("✅ 数据库初始化完成")

    # 决策层 C：初始化 LangGraph Checkpoint（psycopg3 连接池 + 建 checkpoint 表）
    try:
        from core.checkpoint import setup_checkpoint
        await setup_checkpoint()
    except Exception as e:
        _log.warning("⚠️ Checkpoint 初始化跳过: {}", e)

    # 启动时：把 PG 里的店铺回灌到内存（stores 读缓存）
    try:
        from modules.stores.router import load_stores_into_memory
        n = await load_stores_into_memory()
        _log.info("✅ 已从 PostgreSQL 加载 {} 个店铺到内存", n)
    except Exception as e:
        _log.warning("⚠️ 店铺加载跳过: {}", e)

    # 启动时：产品库种子数据（首次启动预置演示数据）
    try:
        from modules.products.seed import seed_products_if_empty
        seeded = await seed_products_if_empty()
        if seeded:
            _log.info("✅ 产品库种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 产品库种子数据跳过: {}", e)

    # 启动时：素材库种子数据（首次启动预置演示数据）
    try:
        from modules.assets.seed import seed_assets_if_empty
        seeded = await seed_assets_if_empty()
        if seeded:
            _log.info("✅ 素材库种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 素材库种子数据跳过: {}", e)

    # 启动时：候选选品库种子数据（首次启动预置演示数据）
    try:
        from modules.candidates.seed import seed_candidates_if_empty
        seeded = await seed_candidates_if_empty()
        if seeded:
            _log.info("✅ 候选选品库种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 候选选品库种子数据跳过: {}", e)

    # 启动时：竞品监控池种子数据（首次启动预置演示数据）
    # 注意：本 seed 不硬编码 shop_id，而是查 stores 表取真实店铺 id 逐个灌。
    # 2026-09-12 起 candidates / products 的 seed 也已统一此写法 —— 真实租户 id 是
    # X-Shop-ID 里的 store_xxxxxxxx，写死 "shop-1" 会导致那批数据任何请求都查不到。
    try:
        from modules.monitors.seed import seed_monitors_if_empty
        seeded = await seed_monitors_if_empty()
        if seeded:
            _log.info("✅ 竞品监控池种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 竞品监控池种子数据跳过: {}", e)

    # 启动时：平台规则库种子数据（首次启动预置演示数据：6 条规则 + 5 篇带正文的文档）
    try:
        from modules.platform_rules.seed import seed_platform_rules_if_empty
        seeded = await seed_platform_rules_if_empty()
        if seeded:
            _log.info("✅ 平台规则库种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 平台规则库种子数据跳过: {}", e)

    # 启动时：业务话术库种子数据（每个店铺各一份默认库 + 6 条通用问答）
    try:
        from modules.knowledge_base.seed import seed_knowledge_if_empty
        seeded = await seed_knowledge_if_empty()
        if seeded:
            _log.info("✅ 业务话术库种子数据已预置 {} 条", seeded)
    except Exception as e:
        _log.warning("⚠️ 业务话术库种子数据跳过: {}", e)

    # 启动时：订阅套餐基础数据（free/pro/enterprise）
    # 缺失会导致注册接口 500：创建默认订阅时 plan_id=1 触发外键约束失败
    try:
        from core.billing.usage_tracker import init_default_plans
        from core.database import get_async_session
        async with get_async_session() as session:
            await init_default_plans(session)
        _log.info("✅ 订阅套餐基础数据已就绪")
    except Exception as e:
        _log.warning("⚠️ 订阅套餐初始化跳过: {}", e)

    yield  # 应用运行中...

    # 关闭时：清理资源
    _log.info("🛑 正在关闭服务...")
    try:
        from core.checkpoint import close_checkpoint
        await close_checkpoint()
    except Exception as exc:  # noqa: BLE001
        # ★ 原来这里是 `except Exception: pass` —— 正是它让
        #   close_checkpoint 里的 NameError 藏了很久（连接池从未真正关闭）。
        #   清理失败不该影响进程退出，但**必须留下痕迹**。
        _log.warning("⚠️ Checkpoint 连接池关闭失败: {}", exc)
    await close_db()
    _log.info("✅ 资源已释放")


# ====== 创建 FastAPI 实例 ======
app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="一站式 AI 原生跨境电商全链路 SaaS",
    lifespan=lifespan,
    docs_url="/docs" if config.debug else None,  # 生产环境关闭文档
    redoc_url="/redoc" if config.debug else None,
)

# ====== 错误上报（可选）======
# 未配 SENTRY_DSN → 完全跳过（不 import、不建后台线程）。
# 配了 DSN 但没装 sentry-sdk → 打 WARNING 说清缺哪个包（**不静默降级**）。
from core.observability.sentry import init_sentry

init_sentry()


def _audit_insecure_settings() -> None:
    """
    启动期配置自检：把「能启动但不安全」的组合显式打出来。

    ★ 设计判据：「启动失败」是最强的护栏（已在 config.py 的
      _enforce_production_safety 里用于致命项）；但有些项不该拦住启动
      （例如临时调试），又必须有存在感 —— 那就用 WARNING 刷出来，
      让它出现在日志里而不是被无声接受。
    """
    if config.environment != "production":
        return
    if config.metrics_enabled and not (config.metrics_token or "").strip():
        _log.warning(
            "生产环境 /metrics 未设 METRICS_TOKEN：QPS、错误率、接口清单将对"
            "任何扫到该路径的人可见。建议设 METRICS_TOKEN 或关掉 METRICS_ENABLED"
        )
    if config.public_base_url and not config.public_base_url.startswith("https://"):
        _log.warning(
            "PUBLIC_BASE_URL 非 HTTPS（{}）：浏览器 getUserMedia（语音录音）"
            "在 HTTP 下会被直接拒绝，语音相关功能不可用",
            config.public_base_url,
        )
    if config.voice_clone_enabled and not (config.public_base_url or "").strip():
        _log.warning(
            "VOICE_CLONE_ENABLED=true 但 PUBLIC_BASE_URL 为空：声音复刻样本"
            "需公网可回源，相关接口会显式失败"
        )


_audit_insecure_settings()

# ====== 静态资源（AIGC 生成的素材图）======
# 万相出图返回的是 OSS 临时链接（24h 过期）→ 出图后立即转存到 uploads/，
# 对外只暴露 /static/。缺这一步，归档到素材库的图片次日全部失效。
from modules.aigc_media.storage import upload_root as _upload_root

_static_dir = _upload_root()
_static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

# ====== 中间件配置 ======

# CORS（跨域）
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 租户上下文中间件：从 X-Shop-ID / ?shop_id= 提取当前店铺写入请求级 ContextVar
from core.tenant.middleware import TenantMiddleware
app.add_middleware(TenantMiddleware)

# 限流 + 请求日志（后 add 的更靠外层，因此请求日志在最外层，能统计到限流拒绝的请求）
from core.middleware import RateLimitMiddleware, RequestLogMiddleware
app.add_middleware(RateLimitMiddleware)
app.add_middleware(RequestLogMiddleware)


# ====== 全局异常处理 ======

@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """全局异常处理器"""
    if config.debug:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": str(exc),
            },
        )
    else:
        # 生产环境不暴露错误详情
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "detail": "服务器内部错误，请联系管理员",
            },
        )


# ====== 健康检查 & 指标 ======

async def _probe_database() -> dict:
    """
    探活 PostgreSQL。

    ★ 为什么必须真发一条 SQL：只检查「engine 对象存在」或「连接池已建」都不
      足以说明数据库可用 —— 进程启动后数据库随时可能挂掉/被网络隔离。
      /health 作为 K8s / SLB 的存活探针，唯一有意义的判据是「真能执行查询」。
    """
    started = time.perf_counter()
    try:
        from sqlalchemy import text as _sa_text

        from core.database import engine

        async with engine.connect() as conn:
            await conn.execute(_sa_text("SELECT 1"))
        return {"up": True, "latency_ms": round((time.perf_counter() - started) * 1000, 1)}
    except Exception as exc:  # noqa: BLE001 —— 探活失败必须转成结构化结果，不能抛
        return {
            "up": False,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "error": f"{type(exc).__name__}: {exc}"[:200],
        }


async def _probe_redis() -> dict:
    """
    探活 Redis。

    ⚠️ 带 1s 超时：Redis 地址不可达时默认会等到 TCP 超时（可能几十秒），
      /health 会被拖死，进而让编排系统误判整个服务不健康 —— 探针本身
      不该比被探测的服务更慢。1s 是「够区分慢与挂」又不拖累编排的折中。
    """
    started = time.perf_counter()
    client = None
    try:
        from core.redis import get_redis_client

        client = await get_redis_client()
        pong = await asyncio.wait_for(client.ping(), timeout=1.0)
        return {
            "up": bool(pong),
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    except asyncio.TimeoutError:
        return {"up": False, "error": "ping 超时（1s）"}
    except Exception as exc:  # noqa: BLE001
        return {"up": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 —— 关连接失败不影响探活结论
                pass


def _probe_llm() -> dict:
    """
    LLM 配置检查（**不发网络请求**）。

    理由：健康检查会被高频调用（秒级），若每次都真调 LLM，既烧配额又拖慢探针。
    「密钥已配置」是这里该回答的问题；「模型是否可用」由业务调用的失败率
    （llm_calls_total{status="error"}）来反映。
    """
    configured = bool((config.dashscope_api_key or "").strip())
    return {
        "up": configured,
        "model": config.llm_default_model,
        "note": "" if configured else "DASHSCOPE_API_KEY 未配置，LLM 相关接口会失败",
    }


@app.get("/health")
async def health_check(detail: bool = False):
    """
    健康检查接口（含依赖探活）。

    ★ P1-8 修复：此前只回一个 `status: "ok"` —— 只要进程活着就报健康，
      哪怕 PostgreSQL / Redis 已经断了。探针的价值全在「能不能真干活」，
      一个恒为 ok 的 /health 等于没有。

    Query:
        detail=true 时返回各依赖的耗时/错误详情（供人工排障）；
        默认只回总状态（供编排系统高频调用，避免泄露内部拓扑）。
    """
    from core.observability.metrics import DEPENDENCY_UP

    db_state = await _probe_database()
    redis_state = await _probe_redis()
    llm_state = _probe_llm()

    DEPENDENCY_UP.set(1 if db_state["up"] else 0, name="postgres")
    DEPENDENCY_UP.set(1 if redis_state["up"] else 0, name="redis")
    DEPENDENCY_UP.set(1 if llm_state["up"] else 0, name="llm_config")
    DEPENDENCY_UP.set(1, name="api")

    # 关键依赖：PostgreSQL 挂了业务全废 → unhealthy；
    # Redis 挂了有降级路径（限流退化为进程内计数）→ 记 degraded 但不判死。
    critical_ok = db_state["up"]
    degraded = not redis_state["up"]

    payload = {
        "status": "ok" if (critical_ok and not degraded) else ("degraded" if critical_ok else "unhealthy"),
        "service": config.app_name,
        "version": config.app_version,
        "environment": config.environment,
    }
    if detail:
        payload["dependencies"] = {
            "postgres": db_state,
            "redis": redis_state,
            "llm": llm_state,
        }
    return payload


if config.metrics_enabled:
    from fastapi import Header
    from fastapi.responses import PlainTextResponse

    from core.observability.metrics import render_prometheus

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint(authorization: str = Header(default="")):
        """
        Prometheus 文本格式指标（自研轻量注册表，零额外依赖）。

        鉴权：config.metrics_token 非空时要求 `Authorization: Bearer <token>`。
        ★ 生产环境务必设 METRICS_TOKEN —— 裸暴露会把 QPS、错误率、接口清单
          告诉任何扫到它的人。未设时启动阶段会打 WARNING 提示。
        """
        token = (config.metrics_token or "").strip()
        if token and authorization.strip() != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="指标端点需要有效令牌")
        return PlainTextResponse(
            render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )


# ====== API 路由注册 ======

# 业务接口统一鉴权依赖
# 条件挂载：只有 config.auth_required=True 时才真正挂到路由上，
#   这样「路由上有依赖」== 「请求真的会被拦」，鉴权覆盖报告不会失真。
#   False（默认，演示模式）-> BUSINESS_AUTH 为空列表，接口行为与改造前完全一致
#   True （生产模式）      -> 全部挂载了该依赖的接口要求 Bearer Token，未登录返回 401
from fastapi import Depends
from core.auth.dependencies import require_auth_if_enabled

BUSINESS_AUTH = [Depends(require_auth_if_enabled)] if config.auth_required else []

# ====== 配额护栏（★ P0 安全修复 2026-09-15）======
#
# 背景：check_quota / check_api_quota / check_agent_chat_quota 三个函数
#       定义齐全（含 429 抛错），但全项目**调用点 0 处** ⇒ 套餐限额纯展示，
#       用户开基础版可以把 LLM / AIGC 无限用下去 —— 直接烧钱。
#
# 挂载原则：**只挂真正烧钱的端点**（会调 LLM / 出图 / 声音复刻这些按次
#   计费的第三方 API）。纯 CRUD（products / assets / candidates / monitors /
#   platform_rules / knowledge_base / stores / conversation）**不挂** ——
#   它们不烧钱，挂了只会误伤：用户翻几页资料库就把 API 额度耗光。
#
# 演示模式：两个 check_* 内部都会先调 require_auth_if_enabled，返回 None
#   （演示模式）时直接 return，不计量不拦截 ⇒ 本地演示零影响。
from core.billing.usage_tracker import check_api_quota, check_agent_chat_quota

# API 调用配额：LLM 生成 / 出图 / 视频 / 声音复刻
API_QUOTA = [Depends(check_api_quota)]
# Agent 对话配额：店秘书等多轮对话入口
CHAT_QUOTA = [Depends(check_agent_chat_quota)]

# 认证模块（登录/注册，必须保持开放，否则拿不到 Token）
from modules.user_subscription.router import router as auth_router
app.include_router(auth_router, prefix="/api/v1")

# 店铺管理模块（自带 get_current_user 鉴权）
from modules.user_subscription.shop_router import router as shop_router
app.include_router(shop_router, prefix="/api/v1")

# 计费模块（自带鉴权）
from modules.user_subscription.billing_router import router as billing_router
app.include_router(billing_router, prefix="/api/v1")

# 选品分析模块 (Phase 2)（自带 get_current_user 鉴权）
from modules.product_research.router import router as product_research_router
app.include_router(product_research_router, prefix="/api/v1", dependencies=API_QUOTA)

# Listing 生成优化模块 (Phase 3)
from modules.listing_generator.router import router as listing_generator_router
app.include_router(listing_generator_router, dependencies=BUSINESS_AUTH + API_QUOTA)  # 路由已包含 /api/v1 前缀

# 广告分析模块 (Phase 4)
from modules.ad_analysis.router import router as ad_analysis_router
app.include_router(ad_analysis_router, prefix="/api/v1", dependencies=BUSINESS_AUTH + API_QUOTA)

# 智能客服模块 (Phase 5)
from modules.customer_service.router import router as customer_service_router
app.include_router(customer_service_router, prefix="/api/v1", dependencies=BUSINESS_AUTH + API_QUOTA)

# 竞品情报监控模块 (Phase 6)
from modules.competitor_intel.router import router as competitor_intel_router
app.include_router(competitor_intel_router, prefix="/api/v1", dependencies=BUSINESS_AUTH + API_QUOTA)

# AIGC 媒体生成模块 (Phase 7)
from modules.aigc_media.router import router as aigc_media_router
app.include_router(aigc_media_router, prefix="/api/v1", dependencies=BUSINESS_AUTH + API_QUOTA)

# 店铺群管理 + 动态利润测算模块 (Phase 10)
from modules.stores.router import router as stores_router
app.include_router(stores_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 产品库模块（资料库 PG 持久化）
from modules.products.router import router as products_router
app.include_router(products_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 素材库模块（资料库 PG 持久化）
from modules.assets.router import router as assets_router
app.include_router(assets_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 候选选品库模块（资料库 PG 持久化，选品→产品流转）
from modules.candidates.router import router as candidates_router
app.include_router(candidates_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 竞品监控池（监控池 + 自建分组，持久化到 PG）
from modules.monitors.router import router as monitors_router
app.include_router(monitors_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 平台规则库（规则 + 来源文档素材，持久化到 PG；含 AI 拆分端点）
from modules.platform_rules.router import router as platform_rules_router
app.include_router(platform_rules_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 业务话术库（知识库容器 + 话术条目 + 文档素材，持久化到 PG）
from modules.knowledge_base.router import router as knowledge_base_router
app.include_router(knowledge_base_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 店秘书（主 Agent / 编排层）
from modules.secretary.router import router as secretary_router
app.include_router(secretary_router, dependencies=BUSINESS_AUTH + CHAT_QUOTA)  # 路由已包含 /api/v1 前缀

# 会话持久化（决策层 B：跨会话记忆）
from modules.conversation.router import router as conversation_router
app.include_router(conversation_router, prefix="/api/v1", dependencies=BUSINESS_AUTH)


# ====== 附加模块（可插拔，默认关闭）======

# 语音克隆（客服音色）：独立 router（前缀 /voice-clone）+ 独立表 shop_voice，
# 不 import 任何业务模块；关闭时该路由**根本不注册**（前端拿到 404 → 入口隐藏）。
# 打开方式：.env 里设 VOICE_CLONE_ENABLED=true，并配好 PUBLIC_BASE_URL（样本需公网可回源）。
if config.voice_clone_enabled:
    from modules.voice_clone.router import router as voice_clone_router
    app.include_router(voice_clone_router, prefix="/api/v1", dependencies=BUSINESS_AUTH + API_QUOTA)
    _log.info("🔌 附加模块已启用：语音克隆（/api/v1/voice-clone）")
else:
    _log.info("🔌 附加模块未启用：语音克隆（VOICE_CLONE_ENABLED=false）")


# ====== 开发模式启动 ======

if __name__ == "__main__":
    import uvicorn

    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    print(f"""
╔══════════════════════════════════════════════════╗
║     {config.app_name} v{config.app_version}
║     环境: {config.environment}
║     地址: http://{config.api_host}:{config.api_port}
║     文档: http://{config.api_host}:{config.api_port}/docs
╚══════════════════════════════════════════════════╝
    """)

    uvicorn.run(
        "main:app",
        host=config.api_host,
        port=config.api_port,
        reload=config.debug,  # 开发模式热重载
        log_level="debug" if config.debug else "info",
        # ★ log_config=None：不让 uvicorn 装自己的 logging handler，
        #   否则标准库 logging 被它接管，InterceptHandler（core/logger.py）失效，
        #   日志又变回「控制台一份、文件里没有」。
        log_config=None,
    )
