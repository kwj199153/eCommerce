"""
账户与成员管理 API（★ P1-c 2026-09-16）

==============================================================================
★ 本模块是什么
==============================================================================
`core/auth/accounts.py` 是「归属与权限判定」的真源（纯逻辑），本模块是它的
**HTTP 面** —— 账户 CRUD + 成员与角色矩阵。

它取代的是 `core/identity/shop_router.py`（7 个 `/api/v1/shops` 端点，
**已于同批 C4 整体删除**）：
那套端点挂在**账户侧** `shops` 表（UUID 主键）上，与业务侧 `stores_store`
（`store_xxx`）是两套互不同步的实体 —— 实测生产 **0 调用点**，且用它建出来的
店在业务侧**根本不可用**（UUID 放进 X-Shop-ID 查 `stores_store` 查不到 → 403），
即「会安静地生产一批废店」。

==============================================================================
★ 为什么这些端点不挂 BUSINESS_AUTH
==============================================================================
`BUSINESS_AUTH`（`require_auth_if_enabled`）的语义是「业务数据按店铺分区时的鉴权」，
它服务的是 `X-Shop-ID` 那一层。而本模块管的是**账户本身** —— 层级更高，
且**没有店铺上下文可依赖**（用户可能一家店都还没有）。

⇒ 这里用 `_current_user()`：拿不到身份一律 **401**（fail-closed）。
  ★ 与演示模式（`AUTH_REQUIRED=false`）的关系：演示模式下凭据端点会整体不可用，
    这是**刻意**的 —— 账户管理是身份与授权数据，说不清"你是谁"就不该能改。
    它不会影响既有体验：演示模式下的店铺/业务数据路径仍按原样放行。

==============================================================================
★ 权限判定一律走 `accounts.py`，本文件不写任何 if role == ...
==============================================================================
「谁能做什么」只有一处定义（`ACCOUNT_PERMISSIONS` 表）。本文件的每个端点
只声明**它需要哪个能力**，由 `require_account_permission()` 判定。
新增能力时若忘了登记，`role_allows` 对未知能力名恒返回 False ⇒ 功能用不了
（立刻发现），而不是静默放行（无声越权）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.accounts import (
    ASSIGNABLE_ACCOUNT_ROLES,
    get_visible_account_ids,
    is_platform_admin,
    new_id,
    resolve_account_role,
    require_account_permission,
)
from core.auth.dependencies import require_authenticated_user
from core.database import get_db
from core.identity.account_models import (
    Account,
    AccountMember,
    AccountRole,
    MemberStatus,
)
from core.identity.models import User
from core.stores import StoreRecord


router = APIRouter(prefix="/accounts", tags=["账户与成员"])


# ====== 请求体 ======

class AccountCreateRequest(BaseModel):
    """新建账户（当前用户成为 owner）"""
    name: str = Field(..., min_length=1, max_length=120, description="账户名")


class AccountUpdateRequest(BaseModel):
    """修改账户"""
    name: Optional[str] = Field(None, min_length=1, max_length=120)


class MemberInviteRequest(BaseModel):
    """
    邀请成员

    ★ 用 email 而不是 user_id：邀请人只知道对方的邮箱，不知道（也不该知道）
      对方的 UUID。凭空拿到别人的 user_id 意味着可以枚举用户。
    """
    email: str = Field(..., min_length=3, max_length=255)
    role: str = Field(
        default=AccountRole.MEMBER.value,
        description=f"可分配角色：{sorted(ASSIGNABLE_ACCOUNT_ROLES)}（owner 不可分配）",
    )


class MemberUpdateRequest(BaseModel):
    """修改成员角色 / 状态"""
    role: Optional[str] = Field(None, description=f"可分配角色：{sorted(ASSIGNABLE_ACCOUNT_ROLES)}")
    status: Optional[str] = Field(None, description="active / removed")


# ====== 依赖 ======

async def _current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """
    强制身份（fail-closed）。演示模式（无身份）返回 401 而不是放行。

    ★ 为什么不用 `Depends(get_current_user)`：那条依赖的 401 文案是
      "无效的认证凭据"（OAuth2 标准语义），而本模块最常见的失败场景是
      **本地演示模式没带 token**（`AUTH_REQUIRED=false`）—— 照抄那句文案
      会把人引向"我的 token 是不是过期了"，而真因是"这个环境里账户管理
      本来就不开放"。所以这里给一句能直接指向真因的话。

    ★ 判定逻辑已收敛到 `require_authenticated_user()`（★ 第 100 轮）：
      `core/identity/users_router.py` 需要一模一样的 fail-closed 判定，
      两处各写一份 ⇒ 至少有一份永远测不到。这里只提供**主语**。
    """
    return await require_authenticated_user(request, db, what="账户与成员管理")


# ====== 序列化 ======

async def _store_counts(db: AsyncSession, account_ids: List[str]) -> Dict[str, int]:
    """
    批量统计各账户下的店铺数（一次查询，不做 N+1）。

    ★ 第 140 轮：`StoreRecord` 已归位到 `core/stores/`（同为内核层）。
      本函数原先靠「函数内 import」绕开 core → modules 的反向依赖，
      归位后那条理由消失，导入已提升到文件顶部 import 区。
    """
    if not account_ids:
        return {}

    rows = await db.execute(
        select(StoreRecord.account_id, func.count())
        .where(StoreRecord.account_id.in_(account_ids))
        .group_by(StoreRecord.account_id)
    )
    return {aid: n for aid, n in rows.all() if aid}


async def _member_counts(db: AsyncSession, account_ids: List[str]) -> Dict[str, int]:
    """批量统计各账户的 ACTIVE 成员数（含 owner 那条记录）。"""
    if not account_ids:
        return {}
    rows = await db.execute(
        select(AccountMember.account_id, func.count())
        .where(
            AccountMember.account_id.in_(account_ids),
            AccountMember.status == MemberStatus.ACTIVE.value,
        )
        .group_by(AccountMember.account_id)
    )
    return {aid: n for aid, n in rows.all() if aid}


def _account_to_dict(
    account: Account,
    *,
    role: Optional[str],
    viewer: User,
    store_count: int = 0,
    member_count: int = 0,
) -> Dict[str, Any]:
    return {
        "id": account.id,
        "name": account.name,
        "owner_user_id": account.owner_user_id,
        "is_active": account.is_active,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
        # 当前用户在本账户内的**团队角色**（超管但非成员时为 None）
        "role": role,
        "is_owner": account.owner_user_id == viewer.id,
        "is_platform_admin": is_platform_admin(viewer),
        "store_count": store_count,
        "member_count": member_count,
    }


def _member_to_dict(member: AccountMember, user: Optional[User]) -> Dict[str, Any]:
    return {
        "id": member.id,
        "account_id": member.account_id,
        "user_id": member.user_id,
        "email": getattr(user, "email", None),
        "name": getattr(user, "name", None),
        "role": member.role,
        "status": member.status,
        "invited_by": member.invited_by,
        "created_at": member.created_at.isoformat() if member.created_at else None,
        "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        # ★ 派生字段：owner 那条记录不可被改角色/移除（端点会以 400 拒绝），
        #   前端据此禁用按钮，避免用户点了才知道不行。
        "is_owner": member.role == AccountRole.OWNER.value,
    }


# ====== 我的默认账户 ======

@router.get("/me", response_model=dict)
async def get_my_account(
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    当前用户的默认账户（**幂等 get-or-create**）。

    ★ 为什么这里带写副作用（GET 建账户）：
      新注册用户**一个账户都没有**。"先 GET 拿不到、再 POST 建一个"是两步，
      在这两步之间刷新页面 / 并发请求就会各自走到 POST ⇒ 撞上唯一性语义、
      或造出两个账户（重复账户**不报错**，用户会看到两个一模一样的团队，
      而店铺散落其中）。幂等 get-or-create 一步到位，重复调用零副作用 ——
      与项目里 `ensureShopsLoaded` 的「基础数据幂等保障」同一条判据。

    ★ 为什么不复用注册流程：注册时创建只覆盖"新用户"这一条路径，
      而历史用户（本批改造之前注册的）没有账户记录，仍需要这条兜底。
    """
    from core.auth.accounts import ensure_default_account

    account = await ensure_default_account(db, current_user)
    role = await resolve_account_role(db, current_user, account.id)
    counts = await _store_counts(db, [account.id])
    mcounts = await _member_counts(db, [account.id])

    return {
        "account": _account_to_dict(
            account, role=role, viewer=current_user,
            store_count=counts.get(account.id, 0),
            member_count=mcounts.get(account.id, 0),
        )
    }


# ====== 账户 ======

@router.get("", response_model=dict)
async def list_accounts(
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    我可见的账户列表（自己拥有的 + 我是 ACTIVE 成员的）。

    ★ 平台超管返回**全部**账户并标注 `is_platform_admin=True`：
      「管全部租户」这条链路必须可见，否则超管在界面上找不到任何账户。
      注意它的 `role` 字段仍可能是 None（超管不等于团队成员）。

    ★★★ 可见集合由 `get_visible_account_ids()` 给出，**本函数不自己拼查询**。
      这是反向注入查出来的真缺陷：本函数最初自己写了一份
      `select(AccountMember.account_id).where(user_id, status==ACTIVE)`，
      与真源里那份**重复**。后果是「去掉真源里的 ACTIVE 过滤」这条注入
      对本端点**完全没有影响** —— 也就是说，将来真源改口径时，这里会
      静默地按旧口径继续跑，两边不一致且不报错。
      （判据：同一判定出现两份实现 ⇒ 至少有一份永远测不到。）
    """
    visible = await get_visible_account_ids(db, current_user)

    if visible is None:
        # 平台超管：全部账户
        q = select(Account).order_by(Account.created_at, Account.id)
    else:
        if not visible:
            return {"accounts": [], "total": 0}
        q = (select(Account)
             .where(Account.id.in_(visible))
             .order_by(Account.created_at, Account.id))

    rows = (await db.execute(q)).scalars().all()

    ids = [a.id for a in rows]
    counts = await _store_counts(db, ids)
    mcounts = await _member_counts(db, ids)

    accounts = []
    for a in rows:
        role = await resolve_account_role(db, current_user, a.id)
        accounts.append(_account_to_dict(
            a, role=role, viewer=current_user,
            store_count=counts.get(a.id, 0), member_count=mcounts.get(a.id, 0),
        ))

    return {"accounts": accounts, "total": len(accounts)}


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_account(
    data: AccountCreateRequest,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """新建账户（当前用户成为其 owner）。

    用途：一个用户想额外开一个团队账户（例如"国内组" / "跨境组"），
    与 `GET /accounts/me` 自动创建的默认容器并存。
    """
    from core.auth.accounts import ensure_owner_member

    account = Account(
        id=new_id(),
        name=data.name.strip(),
        owner_user_id=current_user.id,
        is_active=True,
    )
    db.add(account)
    await db.flush()
    await ensure_owner_member(db, account, current_user)
    await db.commit()
    await db.refresh(account)

    logger.info("{} 创建了账户 {}（{}）", current_user.email, account.id, account.name)

    return {
        "account": _account_to_dict(
            account, role=AccountRole.OWNER.value, viewer=current_user,
            store_count=0, member_count=1,
        )
    }


@router.get("/{account_id}", response_model=dict)
async def get_account(
    account_id: str,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """账户详情（需 account.read）"""
    await require_account_permission(db, current_user, account_id, "account.read")

    account = (await db.execute(
        select(Account).where(Account.id == account_id)
    )).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    role = await resolve_account_role(db, current_user, account_id)
    counts = await _store_counts(db, [account_id])
    mcounts = await _member_counts(db, [account_id])
    return {
        "account": _account_to_dict(
            account, role=role, viewer=current_user,
            store_count=counts.get(account_id, 0), member_count=mcounts.get(account_id, 0),
        )
    }


@router.patch("/{account_id}", response_model=dict)
async def update_account(
    account_id: str,
    data: AccountUpdateRequest,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改账户（改名；需 account.manage，即仅 owner）"""
    await require_account_permission(db, current_user, account_id, "account.manage")

    account = (await db.execute(
        select(Account).where(Account.id == account_id)
    )).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    if data.name is not None:
        account.name = data.name.strip()
    account.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(account)

    return {
        "account": _account_to_dict(
            account, role=AccountRole.OWNER.value, viewer=current_user,
            store_count=(await _store_counts(db, [account_id])).get(account_id, 0),
            member_count=(await _member_counts(db, [account_id])).get(account_id, 0),
        )
    }


# ====== 成员 ======

@router.get("/{account_id}/members", response_model=dict)
async def list_members(
    account_id: str,
    include_removed: bool = False,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    成员列表（需 account.read）。

    `include_removed=true` 时一并返回已移除成员（软删保留的审计痕迹）。
    """
    await require_account_permission(db, current_user, account_id, "account.read")

    q = select(AccountMember).where(AccountMember.account_id == account_id)
    if not include_removed:
        q = q.where(AccountMember.status == MemberStatus.ACTIVE.value)
    members = (await db.execute(
        q.order_by(AccountMember.created_at, AccountMember.id)
    )).scalars().all()

    user_ids = [m.user_id for m in members]
    users: Dict[str, User] = {}
    if user_ids:
        rows = (await db.execute(select(User).where(User.id.in_(user_ids)))).scalars().all()
        users = {u.id: u for u in rows}

    return {
        "members": [_member_to_dict(m, users.get(m.user_id)) for m in members],
        "total": len(members),
    }


@router.post("/{account_id}/members", response_model=dict, status_code=status.HTTP_201_CREATED)
async def invite_member(
    account_id: str,
    data: MemberInviteRequest,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    邀请成员（需 member.manage，即 owner/admin）。

    ★ 落库即为 **ACTIVE**，不走"先 INVITED 等对方接受"：
      `MemberStatus.INVITED` 这一档保留给后续「邮件邀请 + 接受链接」，
      在没有邀请邮件通道时把它写进去会让成员**看起来已加入但实际无权限**
      —— 比"直接加进来"更难排查。当前语义 = 管理员直接把人的账号加进团队。

    ★ 对方必须**已注册**（按 email 查 users）：不存在返回 404 而不是
      "先建个占位用户" —— 占位用户会污染 users 表、拿到无法登录的账号。
    """
    await require_account_permission(db, current_user, account_id, "member.manage")

    role = (data.role or "").strip().lower()
    if role not in ASSIGNABLE_ACCOUNT_ROLES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"无效角色：{data.role!r}。可分配角色：{sorted(ASSIGNABLE_ACCOUNT_ROLES)}"
                "（owner 不可分配 —— 账户只能有一个所有者）"
            ),
        )

    email = data.email.strip().lower()
    target = (await db.execute(
        select(User).where(func.lower(User.email) == email)
    )).scalar_one_or_none()
    if target is None:
        raise HTTPException(
            status_code=404,
            detail=f"用户不存在：{email}。请先让对方注册账号，再加入团队。",
        )

    account = (await db.execute(
        select(Account).where(Account.id == account_id)
    )).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=404, detail="账户不存在")

    if account.owner_user_id == target.id:
        raise HTTPException(status_code=400, detail="该用户已是账户所有者，无需邀请")

    existing = (await db.execute(
        select(AccountMember).where(
            AccountMember.account_id == account_id,
            AccountMember.user_id == target.id,
        )
    )).scalar_one_or_none()

    if existing is not None and existing.status == MemberStatus.ACTIVE.value:
        raise HTTPException(
            status_code=409,
            detail=f"{email} 已是该账户成员（角色 {existing.role}）。如需变更请用 PATCH。",
        )

    if existing is not None:
        # ★ 复现而不是插新行：唯一约束 (account_id, user_id) 不允许两条记录，
        #   插新行会撞约束；而且「曾被移除又回来」保持同一条行才有审计连续性。
        existing.role = role
        existing.status = MemberStatus.ACTIVE.value
        existing.joined_at = datetime.utcnow()
        existing.invited_by = current_user.id
        member = existing
    else:
        member = AccountMember(
            id=new_id(),
            account_id=account_id,
            user_id=target.id,
            role=role,
            status=MemberStatus.ACTIVE.value,
            invited_by=current_user.id,
            joined_at=datetime.utcnow(),
        )
        db.add(member)

    await db.commit()
    await db.refresh(member)

    logger.info(
        "{} 将 {} 加入账户 {}（角色 {}）",
        current_user.email, email, account_id, role,
    )

    return {"member": _member_to_dict(member, target)}


@router.patch("/{account_id}/members/{member_id}", response_model=dict)
async def update_member(
    account_id: str,
    member_id: str,
    data: MemberUpdateRequest,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    修改成员角色 / 状态（需 member.manage）。

    ★ 三个硬约束（都在下面显式拒绝，不是靠"前端不该这么点"）：
      1. **owner 记录不可被改** —— 改它的角色会让账户失去 owner
         （`account.manage` 归 owner，降级后**没有任何人**能再管理该账户）；
      2. `role` 必须在 `ASSIGNABLE_ACCOUNT_ROLES` 内 —— 不能把别人提成 owner；
      3. `status` 只接受 active / removed —— INVITED 属于邀请流程，不接受外部指定。
    """
    await require_account_permission(db, current_user, account_id, "member.manage")

    member = (await db.execute(
        select(AccountMember).where(
            AccountMember.id == member_id,
            AccountMember.account_id == account_id,
        )
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")

    if member.role == AccountRole.OWNER.value:
        raise HTTPException(
            status_code=400,
            detail=(
                "账户所有者不可被修改或降级：owner 是 account.manage 的唯一持有者，"
                "降级后该账户将无人可管理。如需转让账户请走账户转让流程。"
            ),
        )

    if data.role is not None:
        role = data.role.strip().lower()
        if role not in ASSIGNABLE_ACCOUNT_ROLES:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"无效角色：{data.role!r}。可分配角色：{sorted(ASSIGNABLE_ACCOUNT_ROLES)}"
                    "（owner 不可分配）"
                ),
            )
        member.role = role

    if data.status is not None:
        st = data.status.strip().lower()
        if st not in {MemberStatus.ACTIVE.value, MemberStatus.REMOVED.value}:
            raise HTTPException(
                status_code=400,
                detail=f"无效状态：{data.status!r}。只接受 active / removed。",
            )
        member.status = st
        if st == MemberStatus.ACTIVE.value and member.joined_at is None:
            member.joined_at = datetime.utcnow()

    await db.commit()
    await db.refresh(member)

    target = (await db.execute(select(User).where(User.id == member.user_id))).scalar_one_or_none()
    logger.info("{} 更新了账户 {} 的成员 {}（role={}, status={}）",
                current_user.email, account_id, member.user_id, member.role, member.status)
    return {"member": _member_to_dict(member, target)}


@router.delete("/{account_id}/members/{member_id}", response_model=dict)
async def remove_member(
    account_id: str,
    member_id: str,
    current_user: User = Depends(_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    移除成员（需 member.manage）—— **软删除**（status=REMOVED，不物理删行）。

    ★ 软删的理由：成员变更属审计范畴（"谁在什么时候把谁踢了"），
      物理删就查不回来了。而权限判定只看 `status == ACTIVE`
      （见 `get_visible_account_ids`），所以软删**不会留下隐式权限**。

    ★ owner 记录不可移除：账户必须有主人。若允许移除，`accounts.owner_user_id`
      会成为悬空引用，且 account.manage 无人持有。
    """
    await require_account_permission(db, current_user, account_id, "member.manage")

    member = (await db.execute(
        select(AccountMember).where(
            AccountMember.id == member_id,
            AccountMember.account_id == account_id,
        )
    )).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")

    if member.role == AccountRole.OWNER.value:
        raise HTTPException(
            status_code=400,
            detail="账户所有者不可被移除（账户必须有主人）。如需解散团队请走账户删除流程。",
        )

    member.status = MemberStatus.REMOVED.value
    await db.commit()

    logger.info("{} 从账户 {} 移除了成员 {}", current_user.email, account_id, member.user_id)
    return {
        "message": "成员已移除",
        "member_id": member_id,
        "user_id": member.user_id,
        "status": member.status,
    }
