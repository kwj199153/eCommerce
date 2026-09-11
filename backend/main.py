"""
FastAPI 应用主入口

跨境电商 AI SaaS 后端 API 服务。
"""

import asyncio
import sys

# Windows 必须在所有导入之前设置事件循环策略
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import config
from core.database import init_db, close_db, get_db_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时：初始化数据库连接
    print(f"🚀 正在启动 {config.app_name} v{config.app_version}...")
    await init_db()
    print("✅ 数据库初始化完成")

    # 启动时：把 PG 里的店铺回灌到内存（stores 读缓存）
    try:
        from modules.stores.router import load_stores_into_memory
        n = await load_stores_into_memory()
        print(f"✅ 已从 PostgreSQL 加载 {n} 个店铺到内存")
    except Exception as e:
        print(f"⚠️ 店铺加载跳过: {e}")

    # 启动时：产品库种子数据（首次启动预置演示数据）
    try:
        from modules.products.seed import seed_products_if_empty
        seeded = await seed_products_if_empty()
        if seeded:
            print(f"✅ 产品库种子数据已预置 {seeded} 条")
    except Exception as e:
        print(f"⚠️ 产品库种子数据跳过: {e}")

    # 启动时：素材库种子数据（首次启动预置演示数据）
    try:
        from modules.assets.seed import seed_assets_if_empty
        seeded = await seed_assets_if_empty()
        if seeded:
            print(f"✅ 素材库种子数据已预置 {seeded} 条")
    except Exception as e:
        print(f"⚠️ 素材库种子数据跳过: {e}")

    # 启动时：候选选品库种子数据（首次启动预置演示数据）
    try:
        from modules.candidates.seed import seed_candidates_if_empty
        seeded = await seed_candidates_if_empty()
        if seeded:
            print(f"✅ 候选选品库种子数据已预置 {seeded} 条")
    except Exception as e:
        print(f"⚠️ 候选选品库种子数据跳过: {e}")

    # 启动时：订阅套餐基础数据（free/pro/enterprise）
    # 缺失会导致注册接口 500：创建默认订阅时 plan_id=1 触发外键约束失败
    try:
        from core.billing.usage_tracker import init_default_plans
        from core.database import get_async_session
        async with get_async_session() as session:
            await init_default_plans(session)
        print("✅ 订阅套餐基础数据已就绪")
    except Exception as e:
        print(f"⚠️ 订阅套餐初始化跳过: {e}")

    yield  # 应用运行中...

    # 关闭时：清理资源
    print("\n🛑 正在关闭服务...")
    await close_db()
    print("✅ 资源已释放")


# ====== 创建 FastAPI 实例 ======
app = FastAPI(
    title=config.app_name,
    version=config.app_version,
    description="一站式 AI 原生跨境电商全链路 SaaS",
    lifespan=lifespan,
    docs_url="/docs" if config.debug else None,  # 生产环境关闭文档
    redoc_url="/redoc" if config.debug else None,
)

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


# ====== 健康检查 ======

@app.get("/health")
async def health_check():
    """健康检查接口"""
    return {
        "status": "ok",
        "service": config.app_name,
        "version": config.app_version,
        "environment": config.environment,
    }


# ====== API 路由注册 ======

# 业务接口统一鉴权依赖
# 条件挂载：只有 config.auth_required=True 时才真正挂到路由上，
#   这样「路由上有依赖」== 「请求真的会被拦」，鉴权覆盖报告不会失真。
#   False（默认，演示模式）-> BUSINESS_AUTH 为空列表，接口行为与改造前完全一致
#   True （生产模式）      -> 全部挂载了该依赖的接口要求 Bearer Token，未登录返回 401
from fastapi import Depends
from core.auth.dependencies import require_auth_if_enabled

BUSINESS_AUTH = [Depends(require_auth_if_enabled)] if config.auth_required else []

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
app.include_router(product_research_router, prefix="/api/v1")

# Listing 生成优化模块 (Phase 3)
from modules.listing_generator.router import router as listing_generator_router
app.include_router(listing_generator_router, dependencies=BUSINESS_AUTH)  # 路由已包含 /api/v1 前缀

# 广告分析模块 (Phase 4)
from modules.ad_analysis.router import router as ad_analysis_router
app.include_router(ad_analysis_router, prefix="/api/v1", dependencies=BUSINESS_AUTH)

# 智能客服模块 (Phase 5)
from modules.customer_service.router import router as customer_service_router
app.include_router(customer_service_router, prefix="/api/v1", dependencies=BUSINESS_AUTH)

# 竞品情报监控模块 (Phase 6)
from modules.competitor_intel.router import router as competitor_intel_router
app.include_router(competitor_intel_router, prefix="/api/v1", dependencies=BUSINESS_AUTH)

# AIGC 媒体生成模块 (Phase 7)
from modules.aigc_media.router import router as aigc_media_router
app.include_router(aigc_media_router, prefix="/api/v1", dependencies=BUSINESS_AUTH)

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
    )
