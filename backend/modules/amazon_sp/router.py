"""Amazon SP-API 按店 OAuth 授权链路 —— HTTP 端点（第 351 轮 · P0-6）

==============================================================================
★ 本文件补的是哪个洞
==============================================================================
`modules/amazon_sp/` 有 `db_model.py`（两张表已建、已在 baseline 迁移里）、
有 `data_sources/`（工厂 + mock + 真实实现）、有 `seed.py` / `snapshot_repo.py`
—— **唯独没有 `router.py`**，`main.py` 里也没有它的 `include_router`。
⇒ 全仓 `amazon_credentials` 的写入者在生产代码里**一个都没有**；
   `sp_api_source.fetch_credentials()` 里那句「真实场景凭据由 SP-API 授权
   流程写入 amazon_credentials 表」描述的是一个不存在的流程。
纯逻辑（state 签名 / code 换 token / 按店刷新）在 `oauth.py`，本文件只做
「HTTP 契约 + 归属 + 落库 + 审计」。

==============================================================================
★ 鉴权：**按端点给**，router 级别**不加**全局依赖
==============================================================================
    本模块有一个特殊端点：`GET /oauth/callback` 是 **Amazon 的服务器**把
    卖家的浏览器跳过来的，请求里**没有任何我方凭据**（没有 Authorization 头）。
    若把 `BUSINESS_AUTH` 挂成 router 级依赖，这个端点会被 401 挡死 ——
    授权链路从第一步就永远走不完，而且**症状会伪装成「用户没登录」**。

    ⇒ 照 `modules/billing/payment_router.py` 的既有范式：router 不加全局依赖，
      **每个需要身份端点自带** `Depends(require_acting_user)`；
      回调端点靠 **state 验签 + 归属二次校验**认证。

    ★ fail-closed 的三条落点（本仓 BOLA 判据）：
      1. 除回调外，一律 `require_acting_user`（真匿名 ⇒ 401，**不是** Optional）；
      2. 每个按店的端点都过 `ensure_can_access_store`；
      3. 回调端点先验 state、再查归属，**通过之后才**向 Amazon 发请求 ——
         否则一个伪造回调就能让服务端替他打一次外网（耗时 + 探测面）。

==============================================================================
★ 归属只能服务端注入（回调那一档）
==============================================================================
    回调的 `store_id` **不来自请求参数**，而是从签名 state 里解出来的。
    Amazon 会原样回传 state，但它改不了 state（改了签名就不过）。
    ⇒ 攻击者无法把一次授权绑到别人的店铺上。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.accounts import ensure_can_access_store
from core.auth.dependencies import require_acting_user
from core.database import get_db
from core.logger import get_logger
from core.stores import StoreRecord
from models.amazon_sp import (
    AmazonCredentialDetail,
    AmazonCredentialResponse,
    AuthLogResponse,
    AuthUrlResponse,
    CredentialStatus,
)

from . import oauth
from .db_model import AmazonAuthLog, AmazonCredential

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1/amazon-sp", tags=["amazon-sp"])


# ============================================================
# 内部工具
# ============================================================

def _now() -> datetime:
    """落库统一用 UTC naive（与 `db_model` 既有列口径一致）。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _load_authorized_store(db: AsyncSession, user: Any, store_id: str) -> StoreRecord:
    """按 ID 取店铺，并校验当前用户对它有访问权。

    ★ 「店铺不存在」与「不属于你」返回**逐字相同**的 403 ——
      区分开就等于对外提供一个「这个店铺 ID 存不存在」的枚举接口。
      `ensure_can_access_store` 内部也是同一档，两处口径一致。
    """
    sid = (store_id or "").strip()
    if not sid:
        # 写路径缺值硬拒绝：空 ID 放下去会撞外键，最终伪装成「数据库不可用」。
        raise HTTPException(status_code=400, detail="缺少 store_id")

    store = (
        await db.execute(select(StoreRecord).where(StoreRecord.id == sid))
    ).scalar_one_or_none()
    if store is None:
        raise HTTPException(status_code=403, detail="无权访问该店铺")

    await ensure_can_access_store(db, user, store)
    return store


async def _load_credential(db: AsyncSession, store_id: str) -> Optional[AmazonCredential]:
    return (
        await db.execute(
            select(AmazonCredential).where(AmazonCredential.store_id == store_id)
        )
    ).scalar_one_or_none()


def _ensure_credential_row(db: AsyncSession, store_id: str) -> AmazonCredential:
    """取（或就地新建）凭据行 —— 不 flush，交给依赖收尾统一提交。"""
    row = AmazonCredential(store_id=store_id, credential_status=CredentialStatus.PENDING.value)
    db.add(row)
    return row


async def _log_auth(
    db: AsyncSession,
    store_id: str,
    action: str,
    *,
    request: Optional[Request] = None,
    success: bool = True,
    detail: Optional[str] = None,
    error_message: Optional[str] = None,
) -> None:
    """写一条授权审计日志（`amazon_auth_logs`）。

    ★ `action` 是自由字符串列，但本文件只用下列四个取值（唯一真源 = 本函数的
      调用点）：`authorize_initiated` / `authorized` / `refreshed` / `revoked`。
    """
    ip = None
    ua = None
    if request is not None:
        try:
            ip = request.client.host if request.client else None
        except Exception:  # noqa: BLE001 —— 日志字段取不到不该影响主流程
            ip = None
        try:
            ua = (request.headers.get("user-agent") or "")[:512] or None
        except Exception:  # noqa: BLE001
            ua = None

    db.add(
        AmazonAuthLog(
            store_id=store_id,
            action=action,
            detail=detail,
            ip_address=ip,
            user_agent=ua,
            success=success,
            error_message=error_message,
        )
    )


def _to_response(row: AmazonCredential) -> AmazonCredentialResponse:
    return AmazonCredentialResponse(
        id=row.id or 0,
        store_id=row.store_id,
        seller_id=row.seller_id,
        marketplace_participant_id=row.marketplace_participant_id,
        aws_region=row.aws_region or "us-east-1",
        credential_status=row.credential_status or CredentialStatus.PENDING.value,
        last_refresh_at=row.last_refresh_at,
        token_expires_at=row.token_expires_at,
        created_at=row.created_at or _now(),
    )


def _to_detail(row: AmazonCredential) -> AmazonCredentialDetail:
    remaining: Optional[int] = None
    if row.token_expires_at is not None:
        delta = (row.token_expires_at - _now()).total_seconds()
        remaining = max(0, int(delta))
    base = _to_response(row)
    return AmazonCredentialDetail(
        **base.model_dump(),
        has_refresh_token=bool(row.refresh_token),
        access_token_expires_in=remaining,
        error_count=row.error_count or 0,
        refresh_error=row.refresh_error,
    )


# ============================================================
# ① 发起授权：生成同意页 URL
# ============================================================

@router.post(
    "/stores/{store_id}/oauth/authorize-url",
    response_model=AuthUrlResponse,
    summary="生成 Amazon 授权跳转 URL（含签名 state）",
)
async def create_authorize_url(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(require_acting_user),
) -> AuthUrlResponse:
    store = await _load_authorized_store(db, current_user, store_id)

    with oauth.mapped_errors():
        # ★ 顺序：先签发 state（本地计算，可能因缺密钥 503），再拼 URL
        #   （可能因缺 LWA Client ID 503）—— 两者都在**发出任何外网请求之前**，
        #   所以卖家不会经历「跳到 Amazon 才发现服务端没配好」。
        state = oauth.build_state(store.id, current_user.id)
        auth_url = oauth.build_authorize_url(state)

    # 记一行 pending，让 `/credential` 能回答「已发起、等待回调」，
    # 而不是在回调到达之前一直显示「从未授权」。
    row = await _load_credential(db, store.id)
    if row is None:
        row = _ensure_credential_row(db, store.id)
    elif row.credential_status not in (
        CredentialStatus.ACTIVE.value,
        CredentialStatus.REVOKED.value,
    ):
        row.credential_status = CredentialStatus.PENDING.value

    await _log_auth(
        db, store.id, "authorize_initiated",
        request=request,
        detail=f"生成授权链接（state 有效期 {oauth.STATE_TTL_SECONDS}s）",
    )
    logger.info(
        "amazon-sp 授权发起: store_id=%s user_id=%s", store.id, current_user.id
    )
    return AuthUrlResponse(auth_url=auth_url, state=state)


# ============================================================
# ② 授权回调：换 token + 落库
# ============================================================

@router.get(
    "/oauth/callback",
    response_model=AmazonCredentialResponse,
    summary="Amazon 授权回调（由 Amazon 跳转，无 Authorization 头）",
)
async def oauth_callback(
    request: Request,
    db: AsyncSession = Depends(get_db),
    state: Optional[str] = Query(None, description="我方签发的 state，Amazon 原样回传"),
    code: Optional[str] = Query(None, description="授权码（旧版参数名）"),
    spapi_oauth_code: Optional[str] = Query(None, description="SP-API OAuth code（新版参数名）"),
    selling_partner_id: Optional[str] = Query(None, description="卖家 Seller ID"),
    error: Optional[str] = Query(None, description="卖家在同意页选择「拒绝」时 Amazon 回传"),
    error_description: Optional[str] = Query(None),
) -> AmazonCredentialResponse:
    # ---- 1. 验 state（这是本端点**唯一**的认证手段）----
    if not state:
        raise HTTPException(status_code=400, detail="回调缺少 state，无法确认授权归属")
    try:
        store_id, user_id = oauth.parse_state(state)
    except oauth.SpApiStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # ---- 2. 归属二次校验（在**发出任何外网请求之前**）----
    from core.identity.models import User  # 局部导入：只有本端点需要 User 实体

    store = (
        await db.execute(select(StoreRecord).where(StoreRecord.id == store_id))
    ).scalar_one_or_none()
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if store is None or user is None:
        raise HTTPException(status_code=403, detail="无权访问该店铺")
    await ensure_can_access_store(db, user, store)

    # ---- 3. 卖家拒绝授权：如实记录，不制造「已授权」的假象 ----
    if error:
        reason = (error_description or error).strip()
        await _log_auth(
            db, store.id, "authorize_initiated",
            request=request, success=False,
            detail="卖家在同意页拒绝授权",
            error_message=reason[:500],
        )
        # ★★★ 必须在 raise **之前**提交。
        #   `get_db` 依赖的形态是 `yield session` → 正常返回时 commit，
        #   一旦有异常传播上来就 rollback。若这里直接抛，
        #   上面那条「卖家拒绝」的审计记录会被**静默回滚掉** ——
        #   于是事后完全无法回答「他到底点没点过授权」，
        #   而失败路径**没有痕迹**正是本仓点名要避免的形态。
        await db.commit()
        raise HTTPException(status_code=400, detail=f"卖家未完成授权：{reason}")

    # ---- 4. 换长期 refresh_token ----
    auth_code = (spapi_oauth_code or code or "").strip()
    if not auth_code:
        raise HTTPException(status_code=400, detail="回调缺少授权码（code / spapi_oauth_code）")

    with oauth.mapped_errors():
        token_data = await oauth.exchange_authorization_code(auth_code)

    # ---- 5. 落库（token 一律加密，列里绝不出现明文）----
    row = await _load_credential(db, store.id)
    if row is None:
        row = AmazonCredential(store_id=store.id)
        db.add(row)

    with oauth.mapped_errors():
        row.refresh_token = oauth.seal_value(token_data.get("refresh_token"))
        row.access_token = oauth.seal_value(token_data.get("access_token"))

    row.token_expires_at = oauth.token_expiry(token_data.get("expires_in"))
    row.seller_id = (selling_partner_id or row.seller_id or None) or None
    row.credential_status = CredentialStatus.ACTIVE.value
    row.last_refresh_at = _now()
    row.refresh_error = None
    row.error_count = 0

    await _log_auth(
        db, store.id, "authorized",
        request=request,
        detail=f"授权成功（seller_id={row.seller_id or '-'}）",
    )
    logger.info(
        "amazon-sp 授权成功: store_id=%s seller_id=%s", store.id, row.seller_id
    )
    # flush 而不是 commit：让 `id` / `created_at` 这两个 DB 侧默认值在**响应里**
    # 就有真值（否则刚新建的行返回 id=0，前端拿不到可追踪的凭据编号）。
    # 事务收尾仍由 `get_db` 依赖统一负责 —— 端点内不自行 commit。
    await db.flush()
    return _to_response(row)


# ============================================================
# ③ 查询授权状态
# ============================================================

@router.get(
    "/stores/{store_id}/credential",
    response_model=AmazonCredentialDetail,
    summary="查询店铺的 Amazon 授权状态（不含 token 明文）",
)
async def get_credential(
    store_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(require_acting_user),
) -> AmazonCredentialDetail:
    store = await _load_authorized_store(db, current_user, store_id)
    row = await _load_credential(db, store.id)
    if row is None:
        # ★ 用 404 而不是返回一个「空的 200」：前者让前端能明确区分
        #   「从未授权」（该显示「去授权」按钮）与「授权已过期」（该显示「重新授权」）。
        raise HTTPException(status_code=404, detail="该店铺尚未发起过 Amazon 授权")
    return _to_detail(row)


# ============================================================
# ④ 刷新 access_token
# ============================================================

@router.post(
    "/stores/{store_id}/credential/refresh",
    response_model=AmazonCredentialResponse,
    summary="用已存的 refresh_token 刷新 access_token",
)
async def refresh_credential(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(require_acting_user),
) -> AmazonCredentialResponse:
    store = await _load_authorized_store(db, current_user, store_id)
    row = await _load_credential(db, store.id)
    if row is None or not row.refresh_token:
        raise HTTPException(
            status_code=409, detail="该店铺尚未完成授权，无法刷新令牌（请先完成授权）"
        )

    with oauth.mapped_errors():
        refresh_token = oauth.open_value(row.refresh_token)
    if not refresh_token:
        raise HTTPException(status_code=409, detail="库里的 refresh_token 为空，请重新授权")

    try:
        with oauth.mapped_errors():
            token_data = await oauth.refresh_access_token(refresh_token)
            row.access_token = oauth.seal_value(token_data.get("access_token"))
    except HTTPException as exc:
        # 刷新失败要**留下痕迹**：`error_count` 递增、`refresh_error` 记原因、
        # 连续失败则把状态置为 error —— 这是运维判断「卖家是不是撤销了授权」的依据。
        row.error_count = (row.error_count or 0) + 1
        row.refresh_error = str(exc.detail)[:500]
        if row.error_count >= 3:
            row.credential_status = CredentialStatus.ERROR.value
        await _log_auth(
            db, store.id, "refreshed",
            request=request, success=False,
            detail=f"刷新失败（第 {row.error_count} 次）",
            error_message=row.refresh_error,
        )
        # ★★★ 同 callback 的卖家拒绝分支：`get_db` 在异常上传时会 rollback，
        #   不在这里提交的话 `error_count` 永远停在 0、`refresh_error` 永远为空
        #   ⇒ 「连续失败 3 次置 error」这条判据**形同虚设**，
        #   运维也永远看不到「卖家是不是撤销了授权」。
        await db.commit()
        raise

    row.token_expires_at = oauth.token_expiry(token_data.get("expires_in"))
    row.last_refresh_at = _now()
    row.refresh_error = None
    row.error_count = 0
    row.credential_status = CredentialStatus.ACTIVE.value

    await _log_auth(db, store.id, "refreshed", request=request, detail="access_token 刷新成功")
    await db.flush()
    return _to_response(row)


# ============================================================
# ⑤ 撤销授权
# ============================================================

@router.post(
    "/stores/{store_id}/credential/revoke",
    status_code=204,
    summary="撤销本店铺的 Amazon 授权（清空 token）",
)
async def revoke_credential(
    store_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(require_acting_user),
) -> Response:
    store = await _load_authorized_store(db, current_user, store_id)
    row = await _load_credential(db, store.id)
    if row is None:
        raise HTTPException(status_code=404, detail="该店铺尚未发起过 Amazon 授权")

    # ★ 清空的是**我们这边的副本** —— Amazon 侧的授权仍然存在，
    #   卖家若想彻底撤销要去卖家中心的「管理你的应用」里移除。
    #   这一句必须留在代码里（也留在对外文案里），否则是虚假陈述。
    row.refresh_token = None
    row.access_token = None
    row.token_expires_at = None
    row.credential_status = CredentialStatus.REVOKED.value
    row.refresh_error = None
    row.error_count = 0

    await _log_auth(db, store.id, "revoked", request=request, detail="本地凭据已清空")
    return Response(status_code=204)


# ============================================================
# ⑥ 授权审计日志
# ============================================================

@router.get(
    "/stores/{store_id}/auth-logs",
    response_model=List[AuthLogResponse],
    summary="查询该店铺的授权操作审计日志",
)
async def list_auth_logs(
    store_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(require_acting_user),
) -> List[AuthLogResponse]:
    store = await _load_authorized_store(db, current_user, store_id)
    rows = (
        await db.execute(
            select(AmazonAuthLog)
            .where(AmazonAuthLog.store_id == store.id)
            .order_by(AmazonAuthLog.created_at.desc(), AmazonAuthLog.id.desc())
            .limit(limit)
        )
    ).scalars().all()
    return [AuthLogResponse.model_validate(r) for r in rows]


__all__ = ["router"]
