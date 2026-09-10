"""
店铺群管理 API (Phase 10)

提供店铺 CRUD、费率模板管理、利润计算等接口。

设计原则：
- 从 Header 注入 store_id，构建 context 给利润引擎
- Agent 不感知 Store 模型，只接收 dict context
- 费率模板支持系统默认 + 用户自定义
"""

from fastapi import APIRouter, HTTPException, Header, Query, Depends, Request
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid

from models.store import (
    Store, StoreCreate, StoreUpdate, StoreListResponse,
    StoreDetailResponse, FeeTemplate, FeeTemplateCreate,
    DiscountTemplate, StoreStatus, ConnectionStatus, SyncStatus,
)
from core.auth.dependencies import require_auth_if_enabled
from core.profit_engine import (
    calculate_profit, ProfitCalculationRequest, ProfitCalculationResult,
    get_fee_template, get_platform_type_from_key, get_currency_for_marketplace,
    AMAZON_FEE_TEMPLATES, SHOPEE_FEE_TEMPLATES,
    DEFAULT_DISCOUNT_RULES, AmazonFeeConfig, ShopeeFeeConfig, DiscountRule,
)


# ====== PostgreSQL 持久化（StoreRecord ORM 表）======
#
# 设计：内存 dict `_store_db` 是读缓存（利润引擎等同步代码读取），
#       PG 表 `stores_store` 是权威存储。写操作双写内存+DB，
#       服务启动时（main.lifespan）把 PG 全量回灌到内存。
from sqlalchemy import select
from core.database import async_session_factory
from modules.stores.db_model import StoreRecord


async def load_stores_into_memory() -> int:
    """启动时把 PG 里的店铺回灌到内存 _store_db。返回加载条数。"""
    from sqlalchemy import select as _sel
    async with async_session_factory() as session:
        rows = (await session.execute(_sel(StoreRecord))).scalars().all()
    _store_db.clear()
    for r in rows:
        _store_db[r.id] = _record_to_store(r)
    return len(rows)


def _store_to_record(store: Store) -> StoreRecord:
    """pydantic Store → ORM StoreRecord（供落库）"""
    return StoreRecord(
        id=store.id,
        tenant_id=store.tenant_id,
        owner_id=store.owner_id,
        name=store.name,
        platform=store.platform,
        marketplace_id=store.marketplace_id,
        region_code=store.region_code,
        currency=store.currency,
        fee_template_id=store.fee_template_id,
        discount_template_id=store.discount_template_id,
        status=store.status.value if hasattr(store.status, "value") else str(store.status),
        connection_status=store.connection_status.value if hasattr(store.connection_status, "value") else str(store.connection_status),
        sync_status=store.sync_status.value if hasattr(store.sync_status, "value") else str(store.sync_status),
        last_sync_at=store.last_sync_at,
        has_credentials=store.has_credentials,
        created_at=store.created_at,
        updated_at=store.updated_at,
    )


def _record_to_store(r: StoreRecord) -> Store:
    """ORM StoreRecord → pydantic Store"""
    try:
        status = StoreStatus(r.status)
    except ValueError:
        status = StoreStatus.ACTIVE
    try:
        conn_status = ConnectionStatus(r.connection_status)
    except ValueError:
        conn_status = ConnectionStatus.DISCONNECTED
    try:
        sync_status = SyncStatus(r.sync_status)
    except ValueError:
        sync_status = SyncStatus.IDLE
    return Store(
        id=r.id,
        tenant_id=r.tenant_id,
        owner_id=r.owner_id,
        name=r.name,
        platform=r.platform,
        marketplace_id=r.marketplace_id,
        region_code=r.region_code,
        currency=r.currency,
        fee_template_id=r.fee_template_id,
        discount_template_id=r.discount_template_id,
        status=status,
        connection_status=conn_status,
        sync_status=sync_status,
        last_sync_at=r.last_sync_at,
        has_credentials=r.has_credentials,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


async def _upsert_store_db(store: Store) -> None:
    """把单个店铺 upsert 到 PG（幂等，可重复调用）"""
    record = _store_to_record(store)
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(StoreRecord).where(StoreRecord.id == store.id))
        ).scalar_one_or_none()
        if existing:
            # 更新除主键/时间戳外的字段
            existing.tenant_id = record.tenant_id
            existing.owner_id = record.owner_id
            existing.name = record.name
            existing.platform = record.platform
            existing.marketplace_id = record.marketplace_id
            existing.region_code = record.region_code
            existing.currency = record.currency
            existing.fee_template_id = record.fee_template_id
            existing.discount_template_id = record.discount_template_id
            existing.status = record.status
            existing.connection_status = record.connection_status
            existing.sync_status = record.sync_status
            existing.last_sync_at = record.last_sync_at
            existing.has_credentials = record.has_credentials
            existing.updated_at = datetime.utcnow()
        else:
            session.add(record)
        await session.commit()


async def _delete_store_db(store_id: str) -> None:
    """从 PG 删除店铺"""
    from sqlalchemy import delete as _del
    async with async_session_factory() as session:
        await session.execute(_del(StoreRecord).where(StoreRecord.id == store_id))
        await session.commit()


router = APIRouter(prefix="/api/v1/stores", tags=["stores"])


# ====== 内存数据存储（MVP 阶段，后续迁移到 PostgreSQL）======

# 店铺数据（key: store_id）
_store_db: Dict[str, Store] = {}

# 费率模板数据
_fee_template_db: Dict[str, FeeTemplate] = {}


def _init_default_templates():
    """初始化默认费率模板"""
    # Amazon 默认模板
    for key, cfg in AMAZON_FEE_TEMPLATES.items():
        _fee_template_db[f"fee_{key}"] = FeeTemplate(
            id=f"fee_{key}",
            name=f"Amazon {key.replace('amazon_', '').upper()} Default",
            platform_type="amazon",
            is_default=True,
            referral_fee_pct=cfg.referral_fee_pct,
            fba_fulfillment_fee=cfg.fba_fulfillment_fee,
            storage_fee_monthly=cfg.storage_fee_monthly,
            closing_fee=cfg.closing_fee,
            vat_rate=cfg.vat_rate,
            size_tier=cfg.size_tier,
        )

    # Shopee 默认模板
    for key, cfg in SHOPEE_FEE_TEMPLATES.items():
        _fee_template_db[f"fee_{key}"] = FeeTemplate(
            id=f"fee_{key}",
            name=f"Shopee {key.replace('shopee_', '').upper()} Default",
            platform_type="shopee",
            is_default=True,
            commission_pct=cfg.commission_pct,
            transaction_fee=cfg.transaction_fee,
            growth_fee_pct=cfg.growth_fee_pct,
            infrastructure_fee=cfg.infrastructure_fee,
            vat_rate=cfg.vat_rate,
            withdrawal_fee_rate=cfg.withdrawal_fee_rate,
            logistics_cost=cfg.logistics_cost,
        )


# 初始化默认模板
_init_default_templates()


# ====== 辅助函数 ======

def _get_store(store_id: str) -> Store:
    """获取店铺，不存在则抛异常"""
    store = _store_db.get(store_id)
    if not store:
        raise HTTPException(status_code=404, detail=f"店铺不存在: {store_id}")
    return store


def _check_store_owner(store: Store, current_user) -> None:
    """
    归属校验（跟随 AUTH_REQUIRED 开关）：
    - 演示模式（current_user 为 None）：放行，不破坏演示体验
    - 生产模式：admin 放行；非 admin 且 owner_id 不匹配 → 403
    """
    if current_user is None:
        return
    if current_user.role.value != "admin" and store.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作该店铺")


def _build_profit_context(store: Store) -> Dict[str, Any]:
    """
    根据店铺信息构建利润计算的上下文

    这是核心解耦点：Agent 不需要知道 Store 的存在，
    只通过这个 dict 获取计算所需的全部参数。
    """
    platform_family = store.platform_family

    # 加载费率配置
    fee_template_id = store.fee_template_id or f"fee_{store.platform}"
    fee_template = _fee_template_db.get(fee_template_id)

    if not fee_template:
        # 回退到默认模板
        fee_config = get_fee_template(store.platform)
    else:
        # 从自定义模板构建配置
        if platform_family == "amazon":
            fee_config = AmazonFeeConfig(
                referral_fee_pct=fee_template.referral_fee_pct or 15.0,
                fba_fulfillment_fee=fee_template.fba_fulfillment_fee or 3.22,
                storage_fee_monthly=fee_template.storage_fee_monthly or 0.87,
                closing_fee=fee_template.closing_fee,
                vat_rate=fee_template.vat_rate or 0.0,
                size_tier=fee_template.size_tier or "standard",
            )
        else:
            fee_config = ShopeeFeeConfig(
                commission_pct=fee_template.commission_pct or 5.5,
                transaction_fee=fee_template.transaction_fee or 4.74,
                growth_fee_pct=fee_template.growth_fee_pct or 6.41,
                infrastructure_fee=fee_template.infrastructure_fee or 1.07,
                vat_rate=fee_template.vat_rate or 0.0,
                withdrawal_fee_rate=fee_template.withdrawal_fee_rate or 1.0,
                logistics_cost=fee_template.logistics_cost or 12.50,
            )

    # 加载折扣规则
    discount_rule = DEFAULT_DISCOUNT_RULES.get(store.discount_template_id, DEFAULT_DISCOUNT_RULES["default"])

    return {
        "platform": platform_family,
        "fee_config": fee_config,
        "currency": store.currency,
        "region_code": store.region_code,
        "discount_rules": discount_rule,
    }


# ====== 店铺 CRUD 接口 ======

@router.get("", response_model=StoreListResponse)
async def list_stores(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    request: Request = None,
    current_user=Depends(require_auth_if_enabled),
):
    """获取店铺列表（生产模式按当前用户过滤）"""
    stores = list(_store_db.values())

    # 归属过滤：生产模式下只返回当前用户名下的店铺（admin 看全部）
    if current_user is not None and current_user.role.value != "admin":
        stores = [s for s in stores if s.owner_id == current_user.id]

    if status:
        stores = [s for s in stores if s.status.value == status]
    if platform:
        stores = [s for s in stores if s.platform == platform]

    return StoreListResponse(stores=stores, total=len(stores))


@router.get("/{store_id}", response_model=StoreDetailResponse)
async def get_store(
    store_id: str,
    current_user=Depends(require_auth_if_enabled),
):
    """获取店铺详情（含费率模板摘要）"""
    store = _get_store(store_id)
    _check_store_owner(store, current_user)

    # 构建费率模板摘要
    fee_summary = None
    if store.fee_template_id and store.fee_template_id in _fee_template_db:
        ft = _fee_template_db[store.fee_template_id]
        fee_summary = {
            "id": ft.id,
            "name": ft.name,
            "platform_type": ft.platform_type,
        }

    # 折扣规则摘要
    disc_rule = DEFAULT_DISCOUNT_RULES.get(store.discount_template_id)
    disc_summary = {
        "id": store.discount_template_id,
        "coupon_discount_pct": disc_rule.coupon_discount_pct if disc_rule else 10,
        "flash_sale_discount_pct": disc_rule.flash_sale_discount_pct if disc_rule else 45,
    } if disc_rule else None

    return StoreDetailResponse(**store.model_dump(), fee_template_summary=fee_summary, discount_template_summary=disc_summary)


@router.post("", response_model=Store, status_code=201)
async def create_store(
    data: StoreCreate,
    current_user=Depends(require_auth_if_enabled),
):
    """创建新店铺"""
    store_id = f"store_{uuid.uuid4().hex[:8]}"

    # 自动推断 currency 和 region_code
    currency = data.currency or get_currency_for_marketplace(data.platform)
    region_code = data.region_code or data.platform.split("_")[-1].upper()

    # 归属：生产模式注入当前用户 ID；演示模式（无登录）置 None
    owner_id = current_user.id if current_user is not None else None

    store = Store(
        id=store_id,
        tenant_id="default_tenant",  # 隔离由 owner_id 承担，tenant_id 保留兼容
        owner_id=owner_id,
        name=data.name,
        platform=data.platform,
        marketplace_id=data.marketplace_id,
        region_code=region_code,
        currency=currency,
        fee_template_id=data.fee_template_id,
        discount_template_id=data.discount_template_id,
    )

    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG
    return store


@router.put("/{store_id}", response_model=Store)
async def update_store(
    store_id: str,
    data: StoreUpdate,
    current_user=Depends(require_auth_if_enabled),
):
    """更新店铺信息"""
    store = _get_store(store_id)
    _check_store_owner(store, current_user)

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(store, field, value)

    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG
    return store


@router.delete("/{store_id}")
async def delete_store(
    store_id: str,
    current_user=Depends(require_auth_if_enabled),
):
    """删除店铺"""
    store = _get_store(store_id)  # 验证存在性
    _check_store_owner(store, current_user)
    del _store_db[store_id]
    await _delete_store_db(store_id)  # 从 PG 删除
    return {"message": "店铺已删除", "store_id": store_id}


# ====== 平台连接接口 ======

@router.post("/{store_id}/connect")
async def connect_store_platform(
    store_id: str,
    credentials: Dict[str, Any] = None,
    current_user=Depends(require_auth_if_enabled),
):
    """连接平台 API（配置凭证）"""
    store = _get_store(store_id)
    _check_store_owner(store, current_user)

    # TODO: 实际验证凭证有效性
    # MVP 阶段仅标记为已连接
    store.connection_status = ConnectionStatus.CONNECTED
    store.has_credentials = True
    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG

    return {
        "message": f"已连接到 {store.platform}",
        "store_id": store_id,
        "connection_status": "connected",
    }


@router.post("/{store_id}/disconnect")
async def disconnect_store_platform(
    store_id: str,
    current_user=Depends(require_auth_if_enabled),
):
    """断开平台 API 连接"""
    store = _get_store(store_id)
    _check_store_owner(store, current_user)
    store.connection_status = ConnectionStatus.DISCONNECTED
    store.has_credentials = False
    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG

    return {"message": "已断开连接", "store_id": store_id}


# ====== 利润计算接口（核心！）======

@router.post("/profit/calculate", response_model=ProfitCalculationResult)
async def calculate_store_profit(
    req: ProfitCalculationRequest,
    x_store_id: str = Header(..., alias="X-Store-ID", description="当前选中的店铺 ID"),
):
    """
    动态利润计算

    前端调用时在 Header 中传入当前选中的 store_id，
    后端自动：
    1. 根据 store_id 查找店铺信息和平台类型
    2. 加载对应的费率模板（Amazon 或 Shopee）
    3. 调用通用利润计算引擎
    4. 返回完整计算结果

    解耦设计：Agent 不需要知道 Store 模型的存在，
    所有上下文通过此中间件注入。
    """
    # 获取店铺
    store = _get_store(x_store_id)

    # 构建上下文（核心！Agent 完全不感知这个过程）
    context = _build_profit_context(store)

    # 调用通用计算引擎
    result = calculate_profit(req, context)

    return result


@router.get("/profit/fee-template/{platform_key}")
async def get_fee_template_info(platform_key: str):
    """获取指定平台的费率模板详情"""
    try:
        config = get_fee_template(platform_key)
        platform_type = get_platform_type_from_key(platform_key)
        currency = get_currency_for_marketplace(platform_key)

        return {
            "platform_key": platform_key,
            "platform_type": platform_type,
            "currency": currency,
            "config": config.model_dump(),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/profit/supported-markets")
async def list_supported_markets_api():
    """列出所有支持的站点和对应币种"""
    from core.profit_engine import list_supported_markets
    markets = list_supported_markets()

    result = {}
    for platform, keys in markets.items():
        result[platform] = [
            {
                "key": k,
                "currency": get_currency_for_marketplace(k),
                "template_id": f"fee_{k}",
            }
            for k in keys
        ]

    return result


# ====== 费率模板管理接口 ======

@router.get("/fee-templates", response_model=List[FeeTemplate])
async def list_fee_templates(
    platform_type: Optional[str] = None,
):
    """获取费率模板列表"""
    templates = list(_fee_template_db.values())
    if platform_type:
        templates = [t for t in templates if t.platform_type == platform_type]
    return templates


@router.post("/fee-templates", response_model=FeeTemplate, status_code=201)
async def create_fee_template(data: FeeTemplateCreate):
    """创建自定义费率模板"""
    template_id = f"fee_custom_{uuid.uuid4().hex[:8]}"

    template = FeeTemplate(
        id=template_id,
        name=data.name,
        platform_type=data.platform_type,
        is_default=False,
        **data.model_dump(exclude={"name", "platform_type", "is_default"}, exclude_none=True),
    )

    _fee_template_db[template_id] = template
    return template


# ====== 折扣规则接口 ======

@router.get("/discount-templates")
async def list_discount_templates():
    """获取可用的折扣规则模板"""
    return [
        {
            "id": key,
            "name": key.replace("_", " ").title(),
            "config": rule.model_dump(),
        }
        for key, rule in DEFAULT_DISCOUNT_RULES.items()
    ]


# ====== 示例数据初始化（已禁用 - 生产环境应从数据库加载）======
#
# 首次进入显示空状态，用户手动添加店铺后才显示列表。
# 如需测试数据，可取消下方注释。
#
# def _init_demo_stores():
#     """创建示例店铺数据（仅开发测试用）"""
#     demo_stores = [
#         Store(
#             id="store_amazon_us_001",
#             tenant_id="default_tenant",
#             name="Amazon US Store",
#             platform="amazon_us",
#             marketplace_id="ATVPDKIKX0DER",
#             region_code="US",
#             currency="USD",
#             fee_template_id="fee_amazon_us",
#             discount_template_id="default",
#             status=StoreStatus.ACTIVE,
#             connection_status=ConnectionStatus.CONNECTED,
#             has_credentials=True,
#         ),
#         Store(
#             id="store_shopee_my_001",
#             tenant_id="default_tenant",
#             name="Shopee Malaysia",
#             platform="shopee_my",
#             region_code="MY",
#             currency="MYR",
#             fee_template_id="fee_shopee_my",
#             discount_template_id="aggressive",
#             status=StoreStatus.ACTIVE,
#             connection_status=ConnectionStatus.CONNECTED,
#             has_credentials=True,
#         ),
#         Store(
#             id="store_shopee_tw_001",
#             tenant_id="default_tenant",
#             name="Shopee Taiwan",
#             platform="shopee_tw",
#             region_code="TW",
#             currency="TWD",
#             fee_template_id="fee_shopee_tw",
#             discount_template_id="conservative",
#             status=StoreStatus.ACTIVE,
#             connection_status=ConnectionStatus.DISCONNECTED,
#             has_credentials=False,
#         ),
#     ]
#
#     for store in demo_stores:
#         _store_db[store.id] = store
#
#
# # 启动时初始化示例数据（已禁用）
# # _init_demo_stores()
