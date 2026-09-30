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
    Store, StoreCreate, StoreUpdate, StoreTransfer, StoreListResponse,
    StoreDetailResponse, FeeTemplate, FeeTemplateCreate,
    DiscountTemplate, StoreStatus, ConnectionStatus, SyncStatus,
)
from core.auth.dependencies import require_auth_if_enabled
# ★★★ P1-c（2026-09-16）：归属/权限判定的**唯一真源**。
#   本模块**不再**自己比较 owner_id —— 改造前 `_check_store_owner` 与
#   `core/tenant/middleware.py::_resolve_current_shop_id` 各抄了一份同样的判断，
#   两份各自演进，漏改一处就是一个越权口子。
from core.auth.accounts import (
    ensure_can_access_store,
    ensure_default_account,
    filter_accessible_stores,
    is_platform_admin,
    require_account_permission,
    store_account_id,
)
# ★★★ P1-a 的加密通道（`api_credentials` 的**唯一**写入点）。
#   绕过它给该列赋明文 = 重新引入 P1-a 已修的缺陷（见 core/security/credentials.py）。
from core.security.credentials import (
    CredentialsDecryptError,
    CredentialsKeyMissing,
    CredentialsNotEncryptedError,
    decrypt_credentials,
    encrypt_credentials,
    ensure_key_available,
)
# ★★★ 第 318 轮：平台连接层（把凭据收上来，并**真的去平台验一次**）。
#   导入面刻意很窄：本包顶层只 import 契约与注册表，**平台连接器是取用时才导入**
#   （`registry.get_connector()` 内部走 importlib）—— 于是「前端一进页面就读表单
#   schema」不会把整条 Amazon 依赖链（→ core.config 等）拉起来。
from modules.stores.connect import (
    CredentialsIncomplete,
    PlatformConnector,
    PlatformSchemaList,
    StoreConnectResult,
    StoreConnectSpec,
    UnknownPlatform,
    VerifyReport,
    VerifyResult,
    VerifyStatus,
    get_connector,
    list_schemas,
)
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
from sqlalchemy.ext.asyncio import AsyncSession
# IntegrityError：外键 RESTRICT 拒绝删除时由 SQLAlchemy 抛出（包装 asyncpg 的
# ForeignKeyViolationError）。delete_store 需要捕获它并翻译成 409。
from sqlalchemy.exc import IntegrityError
from core.database import async_session_factory, get_db
from core.stores import StoreRecord, SHOP_ORDER_BY
# ★ P0-5（第 327 轮）通用审计：店铺的接入/断开/转移/删除四类写操作统一留痕。
#   顶层 import 无环顾虑 —— 本文件属 modules 层，core 是单向依赖的下游。
from core.audit import (
    ACTION_STORE_CONNECT,
    ACTION_STORE_DELETE,
    ACTION_STORE_DISCONNECT,
    ACTION_STORE_TRANSFER,
    STATUS_FAILURE,
    STATUS_SUCCESS,
    TARGET_STORE,
    record_audit,
)


async def load_stores_into_memory() -> int:
    """启动时把 PG 里的店铺回灌到内存 _store_db。返回加载条数。

    ⚠️ **必须显式按 `SHOP_ORDER_BY` 排序**：回灌顺序决定 dict 插入顺序，
    而 `/api/v1/stores` 返回 `list(_store_db.values())`。若不排序，
    它就和 `shop_tools._list_shops()` 的序号对不上 → 老板说「切到第 2 个店铺」切错店。
    （本函数不排序时，PG 返回顺序未定义；重启前后还可能变。）
    """
    from sqlalchemy import select as _sel
    async with async_session_factory() as session:
        q = _sel(StoreRecord).order_by(*[getattr(StoreRecord, k) for k in SHOP_ORDER_BY])
        rows = (await session.execute(q)).scalars().all()
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
        account_id=store.account_id,
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
        is_demo=store.is_demo,
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
        account_id=r.account_id,
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
        is_demo=r.is_demo,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )


async def _upsert_store_db(store: Store) -> None:
    """把单个店铺 upsert 到 PG（幂等，可重复调用）。

    ★★ 本函数**刻意不碰 `api_credentials`**（P1-c，2026-09-16）：
      pydantic `Store` 里没有该字段（凭证从不进内存缓存、也从不返回前端）。
      若在这里无脑同步 `existing.api_credentials = record.api_credentials`，
      那么每一次普通更新（改名 / 改状态 / 连接平台）都会把密文**清成 NULL** ——
      现象是「改个店铺名，平台连接就悄悄掉线了」，且没有任何报错。
      凭证的写入单独走 `_save_store_credentials()`。
    """
    record = _store_to_record(store)
    async with async_session_factory() as session:
        existing = (
            await session.execute(select(StoreRecord).where(StoreRecord.id == store.id))
        ).scalar_one_or_none()
        if existing:
            # 更新除主键/时间戳外的字段
            existing.tenant_id = record.tenant_id
            existing.owner_id = record.owner_id
            existing.account_id = record.account_id
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


async def _save_store_credentials(
    store_id: str,
    credentials: Optional[Dict[str, Any]],
) -> None:
    """
    把平台凭证**加密后**写入 `stores_store.api_credentials`（唯一写入点）。

    Args:
        credentials: 凭证 dict；传 `None` 表示清除（断开连接）。

    Raises:
        CredentialsKeyMissing: 未配置 `SHOP_CREDENTIALS_ENCRYPTION_KEY`
            ⇒ **拒绝写入**（绝不退回明文，也不自动生成密钥让密文变砖）。

    ★ 为什么单独一个函数、而不是并进 `_upsert_store_db()`：
      两者的触发条件完全不同 —— 店铺字段是「每次更新都要同步」，
      凭证是「只在连接/断开时才动」。混在一起就会出现
      「改个店铺名顺手把凭证清了」这种静默破坏（见 `_upsert_store_db` docstring）。

    ★ 为什么 UPDATE 而不是走 pydantic Store：pydantic `Store` 里**没有**
      `api_credentials` 字段，这是刻意的 —— 密文不允许出现在任何返回给
      前端的模型里（`response_model=Store` 会把它序列化出去）。
    """
    from sqlalchemy import update as _upd

    encrypted = None
    if credentials is not None:
        encrypted = encrypt_credentials(credentials)  # 缺密钥在此抛 CredentialsKeyMissing

    async with async_session_factory() as session:
        await session.execute(
            _upd(StoreRecord)
            .where(StoreRecord.id == store_id)
            .values(api_credentials=encrypted, updated_at=datetime.utcnow())
        )
        await session.commit()


# ====== 平台连接层的接入点（第 318 轮）======

def _resolve_connector(platform: str) -> PlatformConnector:
    """把店铺平台（`amazon_us` / `shopee_my` ...）解析成对应连接器。

    Raises:
        UnknownPlatform: 平台未登记（脏数据 / 新平台忘了登记）

    ★ 为什么抽成模块级函数，而不是在端点里直接调 `get_connector()`：
      「连到外部平台」是本端点唯一的**外部依赖**。留一个可替换的接缝，
      用例才能注入受控的验证结果（不联网、不打第三方接口）。
      否则想断言「连接成功」就只有真拿一组凭据去请求 Amazon 一条路 ——
      这种用例既慢又不可复现，最后的结局一定是被注释掉。
      （判据：每条「成功路径」都必须能在**离线**条件下被断言。）
    """
    return get_connector(platform)


async def _load_store_credentials(store_id: str) -> Optional[Dict[str, Any]]:
    """读回该店铺**解密后**的凭证（仅供服务端内部使用）。

    ★ 返回值**绝不能**出现在任何响应体里 —— 掩码回显走
      `connector.masked_echo()`，它只挑非敏感字段。

    Raises:
        CredentialsKeyMissing: 未配置密钥（本部署还不能读写凭证）
        CredentialsNotEncryptedError / CredentialsDecryptError:
            存量值不是本模块写下的密文，或密钥换过导致解不开。
            **显式上抛，不静默当成「没配过」** —— 后者会让用户以为没配过而重填，
            用一个新值覆盖掉可能还能救回来的密文。
    """
    async with async_session_factory() as session:
        stored = (
            await session.execute(
                select(StoreRecord.api_credentials).where(StoreRecord.id == store_id)
            )
        ).scalar()
    if not stored:
        return None
    return decrypt_credentials(stored)


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


async def _ensure_store_access(
    db: AsyncSession,
    store: Store,
    current_user,
    *,
    permission: Optional[str] = None,
) -> None:
    """
    店铺端点的**唯一**守卫：① 归属判定 + ② 账户能力门。

    ① 归属 —— 转发唯一真源 `core.auth.accounts.ensure_can_access_store()`。
       ★★★ P1-c（2026-09-16）改造前，本函数自己写了一份判定：
           `if current_user.role.value != "admin" and store.owner_id != current_user.id`
         而 `core/tenant/middleware.py::_resolve_current_shop_id` 里**又抄了同一份**。
         两份各自演进 ⇒ 新增一个入口就要记得补一次，漏一次就是一个越权口子。
         现在这里只剩「转发」，判定口径只有一处。

         口径（唯一）：`store.account_id ∈ 当前用户可见账户集合`
                       （自己拥有的账户 ∪ 自己是 ACTIVE 成员的账户）。
                       平台超管（`User.role == admin`）短路放行**全部**账户。
         失败一律 403（不区分「无主 / 归属他人」）。

         ⚠️ 但**「店铺 id 根本不存在」在本模块是 404**，来自 `_get_store()` ——
            它查的是全量内存缓存（不看用户），于是「存在性」先于「归属」被判定。
            两者可被区分的后果 = 攻击者能判定某个 store_id 是否存在；枚举空间是
            32-bit 随机 hex（`store_` + 8 位）。统一成 403 需要同时处理
            「演示模式下 store 为 None」的分支，**本轮未做**，
            已记入批 C 遗留清单（C6 报告）。

         ★★ 纵深防御实测（反向注入 INJ-5，2026-09-16）：
            把本函数的归属判定（①）短路成 `pass` 后，**只有读端点
            （`permission=None`）越权成功** —— `stranger 详情` 由 403 变 200；
            而 stranger 的改名 / 删店 / 连接 / 断开**仍然 403**，因为它们还要过
            ② 的能力门，而 stranger 不在该账户的成员表里。
            ⇒ 读路径（`permission=None`）的**唯一**防线就是这里的归属判定。
            ★ 这也是「反向注入毫无反应 ≠ 没走这条修复」的一个实例：可能是
              **另一层独立防御**把结果兜住了 —— 该判据必须带这个前提，
              否则会得出完全相反的结论。

    ② 能力 —— 按 `ACCOUNT_PERMISSIONS` 矩阵判当前用户在该账户内的角色。
       ★ 这一层是「角色矩阵」能否落地的**唯一判据**：
         `AccountRole.VIEWER` 的定义是「只读（可看，任何写操作 403）」，
         若业务端点只做①不查矩阵，viewer 照样能改名/删店，矩阵就只是装饰。
       ★ `permission=None`（读操作）时不需要额外判定：能通过①就说明他是该账户的
         owner 或 ACTIVE 成员，而 `account.read` 对四种角色**全开**。

    ★ 演示模式（`current_user is None`）：①② 都放行，
      与 `require_auth_if_enabled` 的放行口径一致，本地演示体验不变。
    """
    # ① 归属
    await ensure_can_access_store(db, current_user, store, detail="无权操作该店铺")

    # ② 能力
    if permission is None or current_user is None or is_platform_admin(current_user):
        # 平台超管短路：他不是这个团队的人，只是有超管身份（与本模块的
        # 「两条链路不可互推」一致）—— 矩阵对他不适用。
        return

    account_id = store_account_id(store)
    if account_id is None:
        # ⚠️ 过渡期分支：`account_id` 为空的存量/合成店铺没有账户可查矩阵 ⇒
        #    跳过能力门（保持旧行为）。随回填完成一起消失，
        #    由 `tests/test_account_store_hierarchy.py` 锁定。
        return

    await require_account_permission(db, current_user, account_id, permission)


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

# ====== 店铺 CRUD 接口 ======

@router.get("", response_model=StoreListResponse)
async def list_stores(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """获取店铺列表（生产模式按当前用户过滤）

    ★ 顺序必须与 `shop_tools._list_shops()`（LLM 侧）一致：老板在对话里说
    「切到第 2 个店铺」时，LLM 按工具返回的顺序数，而用户看的是本端点的顺序。
    不一致 = 静默切错店。所以这里**不依赖 dict 插入顺序**，显式按 `SHOP_ORDER_BY`
    排序 —— 与回灌时同一组键，构成双重保险（任一处漏改都不会错位）。
    """
    key = lambda s: tuple(getattr(s, k) for k in SHOP_ORDER_BY)  # noqa: E731
    stores = sorted(_store_db.values(), key=key)

    # 归属过滤 —— 走唯一真源（★ P1-c 2026-09-16）。
    #   改造前这里是 `s.owner_id == current_user.id`，与另外两处**各写一份**；
    #   且口径是「一店一人」，团队共享的店铺在列表里**看不见**（即使详情能进），
    #   表现为「店在、但列表里没有」。现在与单店判定共用 accounts.py 一套口径。
    #   （真源内部对超管短路、对演示模式放行，本端点无需再判 admin。）
    #
    # ★ 本端点**不需要**能力门，这不是遗漏：`account.read` 对四种角色
    #   （owner/admin/member/viewer）**全开** —— 能被筛进「可见账户集合」的人
    #   必然有 `account.read`，判定恒真。列表只展示店铺字段，不泄露凭证
    #   （pydantic `Store` 里没有 `api_credentials`）。
    # ★ 第 175 轮：`current_user is None`（演示档）**不再**等于空列表 ——
    #   它返回 `is_demo` 的那一家。判定在真源内部，本端点不复制口径
    #   （本项目吃过亏：同一判定两份实现 ⇒ 至少一份永远测不到）。
    #   改造前这里恒返回空 ⇒ 前端拿不到任何店铺 ⇒ 全站面板皆空，
    #   而根因藏在 core/auth/accounts.py 里（见迁移 d4a7b2e8c1f6）。
    stores = await filter_accessible_stores(db, current_user, stores)

    if status:
        stores = [s for s in stores if s.status.value == status]
    if platform:
        stores = [s for s in stores if s.platform == platform]

    return StoreListResponse(stores=stores, total=len(stores))


# ====== 平台连接：表单规格下发（第 318 轮）======
#
# ★★ 路由顺序（不是风格问题，是正确性问题）：
#   `/connect/schema` 必须注册在 `/{store_id}` **之前**。它现在多一段路径
#   （`/stores/connect/schema` 两段 vs `/stores/{store_id}` 一段）所以不冲突，
#   但 FastAPI 是**按注册顺序**匹配的 —— 将来若有人加一个 `/stores/{store_id}/xxx`
#   或合并路径，先注册的具体路径永远赢。这条顺序零成本，所以照做。

@router.get("/connect/schema", response_model=PlatformSchemaList)
async def list_connect_schemas(
    current_user=Depends(require_auth_if_enabled),
):
    """下发**全部平台**的连接表单规格。

    ★ 这是「不要每个平台写一套」的落点：前端不认识 `amazon` / `shopee` 这些
      名字，只认识 `PlatformSchema` 这个结构 —— 加平台 = 后端加几条声明，
      前端零改动（同一个弹窗组件吃下全部平台）。

    ★ 为什么不做权限过滤：它只是**字段规格**（要填哪些框、哪些是密码、
      去哪拿），既不含任何店铺数据，也不含任何凭据。
    """
    return PlatformSchemaList(schemas=list_schemas())


@router.get("/{store_id}/connect/schema", response_model=StoreConnectSpec)
async def get_store_connect_schema(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """单店的连接规格 + **掩码**回显（用户重开弹窗时用）。

    ★ 权限走**读**门（`permission=None`），不是 `store.write`。
      理由：本响应里没有任何明文 —— 敏感字段一律 `••••••`，其余
      （client_id / shop_id / region 之类）都是平台侧的**公开标识符**，
      而且正是用户自己在表单上填过的。用写门会让 `viewer` 一打开弹窗就 403，
      连「这家店配没配过」都看不到；真要改配置时，`POST .../connect`
      仍有 `store.write` 把关。
    """
    store = _get_store(store_id)
    await _ensure_store_access(db, store, current_user)

    try:
        connector = _resolve_connector(store.platform)
    except UnknownPlatform as exc:
        # 平台未登记 ⇒ 表单渲染不出来，也不能假装「对方还没配」。
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        stored = await _load_store_credentials(store_id)
    except CredentialsKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (CredentialsNotEncryptedError, CredentialsDecryptError) as exc:
        # ★ 500 而不是「200 + 空回显」：这是**服务端数据状态**问题
        #   （存量明文 / 密钥换过），不是用户输入问题。若静默回成「什么都没配」，
        #   用户会重填一遍并覆盖掉那串其实还能救回来的密文。
        raise HTTPException(
            status_code=500,
            detail=f"该店铺的凭据存储异常，无法回显配置：{exc}",
        ) from exc

    echo = connector.masked_echo(stored)
    return StoreConnectSpec(
        spec=connector.schema(),
        configured=echo["configured"],
        values=echo["values"],
        any_configured=echo["any_configured"],
        connection_status=(
            store.connection_status.value
            if hasattr(store.connection_status, "value")
            else str(store.connection_status)
        ),
        is_connected=store.is_connected,
        has_credentials=store.has_credentials,
    )


@router.get("/{store_id}", response_model=StoreDetailResponse)
async def get_store(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """获取店铺详情（含费率模板摘要）"""
    store = _get_store(store_id)
    await _ensure_store_access(db, store, current_user)  # 读：account.read 对四角色全开

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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """创建新店铺"""
    store_id = f"store_{uuid.uuid4().hex[:8]}"

    # 自动推断 currency 和 region_code
    currency = data.currency or get_currency_for_marketplace(data.platform)
    region_code = data.region_code or data.platform.split("_")[-1].upper()

    # 归属（★ P1-c 2026-09-16；★ A 档 2026-09-17 支持指定账户）：
    #   owner_id   —— 「谁创建的」这一**事实**记录（审计/展示），不参与授权
    #   account_id —— 归属判定的**唯一依据**
    #
    # ★ 两条路径：
    #   ① 未指定 `data.account_id`（默认）→ 建到自己的**个人账户**
    #   ② 指定了 `data.account_id`        → 建到该账户，但**必须过能力门**
    #
    #   ★★★ 关于②的能力门（就地更正此前的判断）：
    #     改造前这里写「本端点不需要账户能力门 …… 能力门恒真，加了是死代码」，
    #     那个结论的**前提**是"除个人账户外没有任何入口"（`StoreCreate` 里
    #     没有 `account_id`）。A 档加了这个字段之后前提不成立 ⇒ 门从"死代码"
    #     变成**必需**：没有它，任何登录用户都能把店挂进**别人**的团队账户
    #     （一种写入型越权 —— 污染他人的数据视图，且不会报任何错）。
    owner_id = current_user.id if current_user is not None else None
    account_id = None
    if current_user is not None:
        if data.account_id:
            # 目标账户不存在/已停用 → 404；存在但当前用户无权 → 403
            # （两种错误的区分在能力门内部完成，端点不再自己分辨）
            await require_account_permission(
                db, current_user, data.account_id, "store.write"
            )
            account_id = data.account_id
        else:
            # `ensure_default_account()` 是**幂等**的：老用户此前没有容器记录时补建，
            # 已有则复用。非幂等会造出第二个账户，而重复账户**不报错** ——
            # 用户会看到两个一模一样的团队、店铺散落其中，日志里毫无提示。
            account = await ensure_default_account(db, current_user)
            account_id = account.id
        # ★★ 必须显式提交，不能只 flush：
        #   `_upsert_store_db()` 用的是**另一个** session（async_session_factory），
        #   未提交的 accounts 行对它不可见（PostgreSQL 默认 READ COMMITTED）
        #   ⇒ `stores_store.account_id` 的外键会因「目标账户不存在」而违例。
        #   （`expire_on_commit=False` 已配置，commit 后 current_user 仍可读。）
        await db.commit()

    store = Store(
        id=store_id,
        tenant_id="default_tenant",  # 历史兼容列，不参与任何判定
        owner_id=owner_id,
        account_id=account_id,
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
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """更新店铺信息"""
    store = _get_store(store_id)
    await _ensure_store_access(db, store, current_user, permission="store.write")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(store, field, value)

    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG
    return store


@router.post("/{store_id}/transfer", response_model=Store)
async def transfer_store(
    store_id: str,
    data: StoreTransfer,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """把店铺转移到另一个账户（团队）（★ A 档 2026-09-17 新增）。

    ★ 为什么需要这个端点：「新建账户」在改造前是个**没有闭环的空壳** ——
      账户建出来了，却没有任何办法把已有的店放进去（`StoreCreate` 不接受
      `account_id`，也没有转移入口）。用户建团队后用不上，只能看到
      一堆彼此无关的空账户。

    ★★ 两道门，缺一不可（各自保护**不同**的东西）：
      ① **源侧** `store.write`（经 `_ensure_store_access`）——
         转移是一种写入：它改变了"谁能看见这家店"。少了这道门，
         任何人都能把**别人的店**搬进自己的账户（等于接管）。
      ② **目标侧** `store.write`（经 `require_account_permission`）——
         少了这道门，可以把店塞进一个自己并不属于的团队账户，
         污染他人的数据视图（对方甚至看不出是谁干的）。
      只查一道是典型的"半扇门"：**少查的那一道不会报任何错**，
      只会安静地放行一种越权。

    ★ `owner_id` **不动**：它是「谁创建了这家店」这一事实的记录，
      转移归属不该改写历史（审计价值正在于此）。

    ★ 幂等：目标账户 == 当前账户时直接返回 200。
      重复点击"转移"是常见操作，把它做成错误只会教用户不再相信这个按钮。

    ⚠️ 演示模式（`current_user is None`）：两道门都放行，与其余店铺端点一致。
    """
    store = _get_store(store_id)

    # ① 源侧：对这家店要有写权限（否则就是"把别人的店搬走"）
    await _ensure_store_access(db, store, current_user, permission="store.write")
    # ② 目标侧：对目标账户也要有写权限（否则就是"往别人团队里塞店"）
    await require_account_permission(db, current_user, data.account_id, "store.write")

    if store_account_id(store) == data.account_id:
        return store  # 幂等：已经在目标账户下

    # ★ P0-5：转移前先记下**源账户** —— 只记目标账户等于丢掉"从哪儿搬来的"
    #   这一半信息，而"谁把我的店搬走了"恰恰是最需要回答的那一问。
    prev_account_id = store_account_id(store)
    store.account_id = data.account_id
    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG
    await record_audit(
        action=ACTION_STORE_TRANSFER,
        actor=current_user,
        target_type=TARGET_STORE,
        target_id=store_id,
        summary=f"转移店铺归属：{store_id} → 账户 {data.account_id}",
        detail={"from_account_id": prev_account_id, "to_account_id": data.account_id},
        request=request,
    )
    return store


@router.delete("/{store_id}")
async def delete_store(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """删除店铺。

    ★ 顺序：先删 PG（权威存储），成功后再清内存缓存。

    反过来（先 `del _store_db[...]` 再删 PG）有个静默缺陷：PG 删除失败时
    内存里的店铺已经消失、库里却还在 —— 两边不一致，且要等下次服务重启
    回灌才会"自己好"。期间用户看到的是"已删除"，但数据仍在（刷新后又回来）。
    这类"假成功"比直接报错难排查得多。

    ★ 外键约束（迁移 d5e6f7a8b9c0）：该店铺下若还有业务数据
    （spus / assets / candidates / monitors / knowledge_* / platform_rules ...），
    数据库会以 RESTRICT 拒绝删除。这里把它翻译成 409 + 可操作文案，
    而不是让它冒成未处理的 500。

    为什么用 RESTRICT 而不是 CASCADE：删店是低频高风险操作，
    "误点一下连带删掉一家店的全部数据" 的代价，远高于 "删店时被提示先清理数据"。
    """
    store = _get_store(store_id)  # 验证存在性（不存在直接 404）
    # 删店不可逆 ⇒ 收紧到 owner/admin（viewer 与 member 均 403）
    await _ensure_store_access(db, store, current_user, permission="store.delete")

    try:
        await _delete_store_db(store_id)  # 先删权威存储
    except IntegrityError as exc:
        # ★ P0-5：**被拒的删除也要留痕**。审计问的是"谁试过"，而"尝试删店被
        #   拦下"是最该被看见的一类痕迹 —— 成功的删除有界面反馈，失败尝试
        #   往往只显示给操作者本人，别处查不到。（record_audit 不自抛，
        #   不会掩盖这里的原始异常。）
        await record_audit(
            action=ACTION_STORE_DELETE,
            actor=current_user,
            status=STATUS_FAILURE,
            target_type=TARGET_STORE,
            target_id=store_id,
            summary=f"删除店铺被拒（仍有关联业务数据）：{store_id}",
            request=request,
        )
        raise HTTPException(
            status_code=409,
            detail=(
                f"店铺 {store_id} 下仍有业务数据（商品/素材/选品/监控/知识库/平台规则等），"
                "已拒绝删除以避免产生孤儿数据。请先清理该店铺的数据，或将店铺置为停用。"
            ),
        ) from exc

    _store_db.pop(store_id, None)  # 成功后才清内存缓存
    await record_audit(
        action=ACTION_STORE_DELETE,
        actor=current_user,
        target_type=TARGET_STORE,
        target_id=store_id,
        summary=f"删除店铺：{store_id}",
        request=request,
    )
    return {"message": "店铺已删除", "store_id": store_id}


# ====== 平台连接接口 ======

@router.post("/{store_id}/connect", response_model=StoreConnectResult)
async def connect_store_platform(
    store_id: str,
    request: Request,
    credentials: Dict[str, Any] = None,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """连接平台：**先真验证、通过后才落库并标记「已连接」**。

    ★ 请求体形态：**扁平的凭据 dict**（不是 `{"credentials": {...}}`）——
      与前端既有契约一致：`post('/stores/${id}/connect', credentials)`。

    ★★★ 执行顺序（每一步都在堵一个已知的坑，顺序本身就是契约）

      ① 存在性 404 / 归属 + 能力门 403 —— 与其它店铺端点同一套守卫
      ② `normalize`  白名单 + 去空白 + 去成对引号
      ③ `require`    复核必填（**在联网之前**）⇒ 缺项 400 + 中文标签
      ④ **密钥可用性**（`ensure_key_available`，**仍在联网之前**）⇒ 未配密钥 503
         ★ 若把它挪到「落库那一刻」才检查，就会出现一个**顺序错误**：
           服务端压根没配密钥（凭据永远写不进去），却仍然先拿用户凭据去打平台，
           而一旦那次调用恰好回「凭据无效」，用户会去反复修改一个没写错的东西，
           **真因（服务端漏配密钥）被完全掩盖**。
      ⑤ 真验证（`connector.verify`）
      ⑥ 按验证结果分流：
         - `INVALID`     ⇒ **400，且不落库、不改状态**。凭据被平台明确拒绝时
                            存下来只会制造「看起来配好了、实际取不到数」的假象。
         - `UNREACHABLE` ⇒ 200，落库，**但不标记已验证**。凭据好坏未知 ——
                            不能因为网络抖一下就判用户的凭据是错的。
         - `UNSUPPORTED` ⇒ 200，落库，**但不标记已验证**（本平台还没接校验）。
         - `OK`          ⇒ 200，落库，标记 `CONNECTED`。
      ⑦ 落库凭证（入参值 + 连接器产出的刷新值）→ **才**写 `has_credentials`
         与连接状态（顺序铁律：先加密落库、成功后才置位）。

    ★★★ 连接状态**只由本次验证结果决定**：`OK` ⇒ `CONNECTED`，其余任何结果 ⇒
      不保留 `CONNECTED`。因为「已连接」这个标记的含义是
      「**库里这一组**凭据已通过平台校验」，而此刻库里刚被写入一组
      **未通过校验**的新凭据 —— 继续挂着 `CONNECTED`，就是把旧的验证结论
      安到新凭据头上（同「三态压两态＝静默洗白」）。
      `EXPIRED` / `ERROR` 两个历史值不由本端点产生：它们描述的是**运行期取数**
      失败，属于同步链路的职责。

    ★ 为什么非要真验证（而不是只落库）：改造前这里是「收下 `credentials` 后直接
      **丢弃**，只把 `has_credentials` 置 True」——「已连接」是一个**空承诺**。
      用户看到绿灯、以为接上了，直到真去拉数据才以「连接正常但调不通」爆出来，
      且日志里没有任何提示。**验证凭据对不对，是连接这件事本身的一部分。**
    """
    store = _get_store(store_id)  # 不存在 → 404
    # 连接平台 = 写店铺配置（并落库凭证）⇒ 需 store.write，viewer 403
    await _ensure_store_access(db, store, current_user, permission="store.write")

    # ①② 解析连接器（平台未登记 ⇒ 400，不是 500）
    try:
        connector = _resolve_connector(store.platform)
    except UnknownPlatform as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ②③ 收敛输入 + 复核必填 —— 都在联网之前
    try:
        values = connector.normalize(credentials)
        connector.require(values)
    except CredentialsIncomplete as exc:
        # 缺项绝不放行去联网：否则「少填了一个」会被平台回成「签名错误」，
        # 用户去改一个本来填对了的字段。
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ④ 密钥可用性 —— 必须在联网之前（理由见 docstring）
    try:
        ensure_key_available()
    except CredentialsKeyMissing as exc:
        # 缺密钥 = 服务端配置问题，原因可读、修法明确；用 503 而非 500。
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # ⑤ 真验证。连接器约定**不抛异常**；真抛了按 UNREACHABLE 兜底 ——
    #    「校验过程自己出错」绝不能退化成「凭据无效」。
    try:
        result = await connector.verify(values)
    except Exception as exc:  # 校验层的任何意外都不应让端点 500
        result = VerifyResult(
            status=VerifyStatus.UNREACHABLE,
            message=(
                f"校验过程异常（{type(exc).__name__}: {exc}）。"
                "凭据好坏未知，请检查网络 / 代理后重试。"
            ),
        )

    # ⑥ 分流一：被平台明确拒绝 ⇒ **不落库、不改状态**
    if result.status is VerifyStatus.INVALID:
        # ★ P0-5：**未通过的凭据尝试**要留痕 —— 它是"有人在试这家店的凭据"
        #   的唯一信号。⚠️ detail 只放平台与校验结论，**绝不放凭据本身**
        #   （审计表的读面最广，不能成为泄露点）。
        await record_audit(
            action=ACTION_STORE_CONNECT,
            actor=current_user,
            status=STATUS_FAILURE,
            target_type=TARGET_STORE,
            target_id=store_id,
            summary=f"连接店铺被平台拒绝：{store_id}（{store.platform}）",
            detail={"platform": store.platform, "verify_status": result.status.value},
            request=request,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "message": result.message,
                "status": result.status.value,
                "checks": [c.model_dump() for c in result.checks],
            },
        )

    # ⑦ 落库：入参值 + **连接器产出的刷新值**（如 Shopee 换到的新 token）。
    #    刷新值只认连接器写的，不合并请求体 —— 否则客户端能凭请求体改写落库凭据。
    payload = dict(values)
    payload.update(result.refreshed or {})
    try:
        await _save_store_credentials(store_id, payload)
    except CredentialsKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 更新内存缓存（★ 只改内存对象，凭证不进内存 —— pydantic Store 无该字段）
    store.has_credentials = True
    store.connection_status = (
        ConnectionStatus.CONNECTED if result.ok else ConnectionStatus.DISCONNECTED
    )
    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    # 持久化非凭证字段（本函数刻意不碰 api_credentials，避免把密文清掉）
    await _upsert_store_db(store)

    # ★ P0-5：只记"谁在什么时候给哪个店换了凭据"+ 校验结论，
    #   **绝不记凭据内容**（理由同上）。
    await record_audit(
        action=ACTION_STORE_CONNECT,
        actor=current_user,
        status=STATUS_SUCCESS if result.ok else STATUS_FAILURE,
        target_type=TARGET_STORE,
        target_id=store_id,
        summary=f"连接店铺：{store_id}（{store.platform}）",
        detail={"platform": store.platform, "verify_status": result.status.value},
        request=request,
    )

    return StoreConnectResult(
        store_id=store_id,
        platform=store.platform,
        family=connector.platform,
        message=result.message,
        # ★ 用 VerifyReport 而不是 result 本身：后者带 refreshed（新令牌明文）。
        verify=VerifyReport.from_result(result),
        connection_status=(
            store.connection_status.value
            if hasattr(store.connection_status, "value")
            else str(store.connection_status)
        ),
        is_connected=store.is_connected,
        has_credentials=store.has_credentials,
    )


@router.post("/{store_id}/disconnect")
async def disconnect_store_platform(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_auth_if_enabled),
):
    """断开平台 API 连接（**同时清除已存的加密凭证**）

    ★ 断开必须真的把凭证从库里删掉：只翻 `has_credentials` 标志而留着密文，
      等于「用户以为撤销了授权、密文还在库里」。授权撤销要落在数据上，
      不能只落在界面上。
    """
    store = _get_store(store_id)
    await _ensure_store_access(db, store, current_user, permission="store.write")

    # 先清凭证（唯一写入点，传 None 表示清除），再改标志
    await _save_store_credentials(store_id, None)

    store.connection_status = ConnectionStatus.DISCONNECTED
    store.has_credentials = False
    store.updated_at = datetime.utcnow()
    _store_db[store_id] = store
    await _upsert_store_db(store)  # 持久化到 PG

    # ★ P0-5：断开 = 撤销授权。必须留痕 —— "谁把这家店的接入断掉了"
    #   是排障的第一步（数据突然拉不到时，先看是不是有人撤了授权）。
    await record_audit(
        action=ACTION_STORE_DISCONNECT,
        actor=current_user,
        target_type=TARGET_STORE,
        target_id=store_id,
        summary=f"断开店铺连接（已清除凭据）：{store_id}",
        request=request,
    )

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
