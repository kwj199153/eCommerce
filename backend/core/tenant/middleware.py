"""
多租户中间件（**业务侧**）

★★★ P1-c 收拢后（2026-09-16）本模块只剩两件职责：

  1. **业务侧店铺 ID 解析**（`get_current_shop_id*` / `_resolve_current_shop_id`）
     —— 从 `X-Shop-ID` 头取 `stores_store.id`（`store_xxx`），做归属校验后返回。
  2. **可观测性**（`TenantMiddleware`）—— 把「这条请求声称属于哪个店铺」
     放进 `request.state.shop_id`，供请求日志使用。

★ 本模块删掉的东西（C4，别再写回来）
  收拢前这里还有一整套**账户侧**（`shops` 表 / UUID）的租户上下文设施：

      TenantContext / _tenant_context_var / tenant_context（替换式写入代理） /
      get_tenant_context / _require_owned / get_tenant_from_header /
      get_optional_tenant / get_tenant_from_query / require_shop_owner

  它们唯一的用途是服务 `core/identity/shop_router.py` 那 7 个 `/api/v1/shops`
  端点 —— 那是**账户侧**实体（`shops` 表，UUID 主键），与业务侧 `stores_store`
  （`store_xxx`）是两套互不同步的店铺。实测该模块**生产 0 调用点**，且用它建
  出来的店在业务侧**根本不可用**（UUID 放进 `X-Shop-ID` 打业务端点 →
  `stores_store` 查不到 → 403），即「会安静地生产一批废店」。

  ⇒ 随 `shop_router.py` 一并删除。账户管理改由
    `core/auth/accounts_router.py`（`/api/v1/accounts`）承担；
    归属与权限判定的**唯一真源**是 `core/auth/accounts.py`。

  ★★ 附带的结构性收益：`tenant_context` 这条「未校验的租户身份注入通道」
     **物理消失了**。它曾是 P0 事故（BOLA 跨租户写入）的载体 ——
     `TenantMiddleware` 往里写未校验的原始 `X-Shop-ID`，而
     `modules/product_research/agent_product_research.py::_write_candidates`
     直读它当作写库归属（探针 r84d 实测：伪造头 → 候选落进别人的选品库）。
     收拢前靠「**所有**写入点都必须在归属校验之后」这条不变量约束它；
     现在**一个写入点都没有**，不变量退化成结构事实，不可能再被改错。
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware

from core.auth.dependencies import require_auth_if_enabled
from core.database import get_db
# ★ P0-2（2026-09-16）：account_id（= 本项目的租户语义）的唯一写入点。
from core.observability.context import set_request_context


# ====== 常量 ======

# 请求头中的租户标识
TENANT_HEADER = "X-Shop-ID"

# 查询参数中的租户标识
TENANT_QUERY_PARAM = "shop_id"


# ====== 轻量店铺 ID 依赖（数据层隔离用） ======

# 写方法集合：只有这些方法才强制要求店铺上下文。
# ★ 为什么按 method 而非按端点白名单：84 个端点里 63 个是写、
#   21 个是读，逐个登记必然漂移（新端点会被漏掉）；method 是**未来新写端点
#   自动纳入**的收敛口径。
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

MISSING_SHOP_DETAIL = (
    "缺少店铺上下文：写操作必须携带 X-Shop-ID 请求头。"
    "请先在界面左上角选择一个店铺再重试。"
)


async def get_current_shop_id(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """
    从请求头提取当前选中店铺 ID（stores_store.id，格式 store_xxx）。
    用于业务数据（spus/candidates/assets/monitors/rules）的 shop_id 过滤。

    ★ P1-c 收拢后（2026-09-16）本项目**只有这一个** `X-Shop-ID` 解析者。
      账户侧那套（`get_tenant_from_header` 家族，查 `shops` 表 / UUID）已随
      `core/identity/shop_router.py` 删除；此前「同一个请求头有两个含义不同的
      解析者」是隐患来源，现在结构上不存在了。

    ★★★ 归属校验（P0 安全修复 2026-09-15，OWASP API Security #1 BOLA）
        修复前：直接 `return request.headers.get(TENANT_HEADER)`，零校验
        ⇒ 任何带有效 token 的用户改一下 X-Shop-ID 就能读别人全部业务数据
          （实测 6/6 端点 200：SPU/候选品/素材/监控/规则/音色）。
        修复后：**只要请求带了真 token 就强制做归属校验**，不符一律 403；
          平台超管放行。
          ★ 2026-09-17 补正：原文写的是「config.auth_required=True（生产模式）
            时强制做归属校验」—— 那把「校验」挂在了错误的开关上，结果是
            演示模式下**已正式登录的用户**校验整段不执行（老板实测：登录后
            仍看到别人的 4 个店铺）。现在开关口径改为「有没有解析出真身份」。
        ★★ P1-c（2026-09-16）判定口径更新为
          `stores_store.account_id ∈ 当前用户可见账户集合`
          （含成员表命中；实现见 `core/auth/accounts.py::can_access_store`）。
          修复 2026-09-15 时的口径是 `owner_id == 当前用户 id` —— 那是
          「一店一人」模型，表达不出团队共享，两个入口各抄一份必然漂移。

    ★★★ 空值守卫（P0 修复 2026-09-15，多租户隔离）
        **写方法（POST/PUT/PATCH/DELETE）+ 缺失/空白 X-Shop-ID ⇒ 400。**
        修复前实测（探针 r51-before-write-no-shop）：
          写端点不带头 → 入库 shop_id="" → 被外键
          fk_<表>_shop_id_stores_store 拒绝 → **500，且响应体把 SQLAlchemy
          报错与约束名原样返回给客户端**（信息泄露 + 用户看到"服务器内部错误"）。
        修复后：400 + 可读原因，零数据库往返（守卫在依赖解析阶段就拦下）。
        读方法保持原契约（返回 None → 端点回空列表），前端「未选店铺看空列表」
        的既有体验不受影响。

        ★ 为什么按 method 而不是登记 63 个写端点：登记式必然漂移，
          方法分流是**未来新写端点自动纳入**的收敛口径。
        ★ 需要「写方法但不要求店铺」的对话/导航类入口请显式改用
          `get_current_shop_id_optional`（见其 docstring 的使用边界）。

    ⚠️ 三个设计取舍：
      1. 用 403 不用 404 —— 404 会泄露「该店铺 ID 是否存在」，帮攻击者枚举。
      2. ★ 2026-09-17 更新：归属校验**只在「确实没有身份」时才跳过**。
         修复前这里是「auth_required=False ⇒ require_auth_if_enabled 返回 None
         ⇒ 不做校验」，等于演示模式下**连真实登录用户的归属也不查** ——
         改一下 `X-Shop-ID` 就能读写任意店铺的业务数据（BOLA 回归）。
         现在 `require_auth_if_enabled` 是 optional auth（带真 token 就必须解析
         出身份）：只有 `auth_required=False` 且**完全不带凭据**（或带的是
         `demo_mode` 下那条演示哨兵）时才返回 None ⇒ 本地匿名联调不受影响。
         **注意：空值守卫不受演示模式影响**（它是请求形状校验，与"你是谁"无关）
         —— 演示模式下同样禁止空 shop 写入。
      3. 存量无主店铺（account_id IS NULL **且** owner_id IS NULL）生产模式下
         非超管一律拒绝 ⇒ 上线前须跑回填（迁移 d1e2f3a4b5c6 已为有主的店铺
         建账户并挂 account_id；`scripts/backfill_owner_id.py` 处理无主店铺）。

    用法：
        @router.get("/widgets")
        async def list_widgets(shop_id: Optional[str] = Depends(get_current_shop_id)):
            if shop_id:
                q = q.where(Record.shop_id == shop_id)
            else:
                return {"items": [], "total": 0}  # 未选店铺返回空

        @router.post("/widgets")   # 写端点不用写守卫：缺 X-Shop-ID 自动 400
        async def create_widget(shop_id: Optional[str] = Depends(get_current_shop_id)):
            ...
    """
    return await _resolve_current_shop_id(request, db, require_for_write=True)


async def get_current_shop_id_optional(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Optional[str]:
    """
    与 `get_current_shop_id` 同源，但**不对写方法强制要求店铺上下文**。

    ★ 使用者的**唯一真源**是 `tests/test_shop_id_guard.py::ALLOWED_OPTIONAL`
      （那里用集合相等断言：多一处、少一处都红）。
      本 docstring **刻意不重复列名单** —— 这里曾经手写「当前唯一使用者：
      `POST /api/v1/orchestrator/chat` 店秘书」，第 131 轮 product_research
      的 3 个入口接入后它变成了一句**过时承诺**，而没有任何东西会因此报错。

    ★ 允许豁免的形态只有两种（判据真源同上）：
      ① 该入口**不落业务数据**（纯对话 / 导航）；
      ② 它会落数据，但**写路径在缺店铺上下文时硬拒绝**（零数据库往返）。
      理由：这类入口同时服务只读意图（蓝海 / 利润 / 痛点 / 能力），若用严格版，
      「还没选店铺」的用户会被整个挡在门外（400）—— 属零收益的体验损伤。
      ⇒ 门禁放在「写」那一层，而不是「入口」那一层。
    """
    return await _resolve_current_shop_id(request, db, require_for_write=False)


async def _resolve_current_shop_id(
    request: Request,
    db: AsyncSession,
    *,
    require_for_write: bool,
) -> Optional[str]:
    """上面两个依赖的共用实现（唯一逻辑源，避免两份各自漂移）。"""
    raw = request.headers.get(TENANT_HEADER) or ""
    # ★ `.strip()`：HTTP 头解析不保证调用方不发纯空白值，
    #   "   " 若原样放行会被当成合法店铺 ID 带去查库 → 空匹配 → 静默写空分区。
    shop_id = raw.strip() or None

    # ① 空值守卫（P0 修复 2026-09-15）
    #    修复前实测：写端点不带头 → 入库 shop_id="" → 被
    #    `fk_<表>_shop_id_stores_store` 外键拒绝 → **500，且响应体把
    #    SQLAlchemy 报错与约束名原样吐给客户端**（见探针 r51-before-write-no-shop）。
    #    修复后：同一个请求得到 400 + 可读原因，且不产生任何数据库往返。
    if shop_id is None:
        if require_for_write and request.method.upper() in WRITE_METHODS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=MISSING_SHOP_DETAIL,
            )
        return None

    # ② 认证（你是谁）。
    #   ★★★ 2026-09-17：这里的 `None` 现在**只代表真匿名** —— 完全没带凭据
    #   （且 auth_required=False），或带的是 demo_mode 下那条演示哨兵。
    #
    #   带了真 token 时，`require_auth_if_enabled` 必然**解析出身份**或直接
    #   401/403 抛出去，不会再落到这个分支。
    #
    #   修复前的形态是「auth_required=False ⇒ 连 token 都不解析 ⇒ 恒返回 None」
    #   ⇒ 真实登录的用户在这里也拿到 None ⇒ **下面的归属校验被整段跳过**，
    #   改一下 `X-Shop-ID` 即可读写任意店铺的业务数据（2026-09-15 修的 BOLA
    #   在演示模式下原样回归）。本次与 dependencies 侧一并修掉。
    current_user = await require_auth_if_enabled(request, db)
    if current_user is None:
        return shop_id

    # ③ 授权（这东西归不归你）—— 修复前缺失的就是这一段
    #
    # ★★★ P1-c（2026-09-16）口径升级：判定实现收到 `core/auth/accounts.py`。
    #
    #   改造前这里是 `store.owner_id != current_user.id`，而
    #   `modules/stores/router.py::_check_store_owner` 里**又抄了同一份判断**。
    #   两处各自演进 ⇒ 新增一个入口就要记得补一次，漏一次就是一个越权口子
    #   （这正是 P0 事故的形态）。现在两处都调 `can_access_store()`。
    #
    #   口径本身也换了：从「一店一人」的 owner_id 改为
    #   「store.account_id ∈ 当前用户可见账户集合」—— 后者才表达得出团队共享
    #   （同一家店两个人都要能进）。owner_id 只留作过渡期兜底（account_id 为空的
    #   存量/合成店铺），由 `tests/test_account_store_hierarchy.py` 锁定。
    from modules.stores.db_model import StoreRecord  # 函数内导入，避免循环依赖
    from core.auth.accounts import can_access_store

    result = await db.execute(select(StoreRecord).where(StoreRecord.id == shop_id))
    store = result.scalar_one_or_none()

    # 不存在 / 无主 / 归属他人 —— 统一 403，不区分，避免探测有效 ID
    if store is None or not await can_access_store(db, current_user, store):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该店铺",
        )

    # ★ P0-2（2026-09-16）：归属已确认 —— 把 account_id 写进请求上下文。
    #
    #   为什么必须在这里写，而不是在鉴权依赖 `get_current_user` 里：
    #   一个用户可属于多个账户（个人账户 + 被邀请的团队账户），
    #   "本次请求属于哪个账户"只有**解析出具体店铺之后**才知道。
    #   在鉴权阶段写一个猜测值，等于把错误归属扩散到全部日志与审计。
    #
    #   ★ 只在归属校验通过之后写：走进 403 分支的请求不该在上下文里
    #     留下任何账户痕迹（否则"越权尝试"的日志会带着受害账户的 ID）。
    set_request_context(account_id=store.account_id)

    return shop_id


# ====== FastAPI 中间件 ======

class TenantMiddleware(BaseHTTPMiddleware):
    """
    多租户中间件（**只做可观测性，不做授权**）

    职责边界（P0 安全修复 2026-09-16 后固化，P1-c 收拢后进一步简化）：
      - 做：把请求头/查询参数里的店铺标识放进 `request.state.shop_id`，
            供请求日志与异常处理器展示（"这条请求声称是哪个店铺的"）。
      - **不做**：解析店铺、写任何请求级业务上下文。

    ★★★ 为什么这个中间件永远不许「顺手把 shop_id 存起来给后面用」（根因记录）
        修复前这里是：
            if shop_id:
                get_tenant_context().set_shop_id(shop_id)      # ← 原始头值，零校验
        而 `modules/product_research/agent_product_research.py::_write_candidates`
        **直读**该上下文当作写库归属。两者串起来就是一条跨租户写入链：
        任何带有效 token 的用户，只要把 `X-Shop-ID` 改成别人的店铺 ID，
        候选商品就会落进**别人的选品库**（探针 r84d 实测 200 + 落库对齐受害店铺）。

        危险点不在"谁读了上下文"，而在"上下文里的值从来没人校验过"。
        它看起来只是一个无害的 request-scoped 缓存，实际是一条**未校验的
        租户身份注入通道**，谁读谁中招。

    ★ P1-c 收拢后（2026-09-16）：那条通道所在的整套 `tenant_context` 设施
      已被删除（见模块 docstring）。现在**没有任何地方**可以"存起来给后面用"
      —— 端点侧要拿店铺 ID 请显式 `Depends(get_current_shop_id*)`，
      它会做归属校验并返回原始 ID 字符串。

    注册方式（main.py）：
        app.add_middleware(TenantMiddleware)
    """

    async def dispatch(self, request: Request, call_next):
        # 只提取、不授权：写进 request.state 供日志用，绝不写业务上下文
        shop_id = (
            request.headers.get(TENANT_HEADER)
            or request.query_params.get(TENANT_QUERY_PARAM)
        )
        request.state.shop_id = shop_id

        response = await call_next(request)
        return response
