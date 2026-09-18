"""
账户归属与权限判定的**唯一真源**（P1-c，2026-09-16）

==============================================================================
★ 这个模块替代掉的是什么
==============================================================================
P1-c 收拢前，「这家店归不归你」这个判定被**抄了两份**，且都是同一个错误口径：

    1. `core/tenant/middleware.py::_resolve_current_shop_id`
           if current_user.role.value != "admin":
               if store is None or store.owner_id != current_user.id: 403
    2. `modules/stores/router.py::_check_store_owner`
           if store.owner_id != current_user.id: 403

两份各自演进 ⇒ 新增一个入口就要记得补一次，漏一次就是一个越权口子。
更根本的问题是**口径本身是错的**：`owner_id` 是「一店一人」模型，
团队共享（同一家店两个人要都能进）根本表达不出来。

现在两处都改为调用本模块的 `can_access_store()`，判定口径只有一处。

==============================================================================
★ 判定口径（收拢后的唯一形式）
==============================================================================
    「用户能看到哪些账户」的集合 =
        他自己拥有的账户（Account.owner_user_id == user.id）
      ∪ 他是 ACTIVE 成员的账户（AccountMember.status == 'active'）

    「用户能不能进这家店」 ⇔ store.account_id ∈ 这个集合

    ★ 平台超管（User.role == admin）短路放行**全部**账户 —— 这是**另一条链路**，
      与团队角色无关，见 `is_platform_admin()` 的说明。

    ⚠️ 过渡期兜底：`store.account_id IS NULL` 的存量店铺（历史遗留 / 测试合成）
       回退到 `store.owner_id == user.id`。这条分支的唯一职责是让回填期间的
       数据仍然可用，**不是**新的判定口径；完整性由
       `tests/test_account_store_hierarchy.py` 锁定，回填完成后可删。

==============================================================================
★ 两条权限链路**不能互相推导**（本项目最容易写错的一处）
==============================================================================
    | 链路 | 载体 | 作用范围 |
    |------|------|---------|
    | 平台超管 | `User.role == UserRole.ADMIN` | 跨**全部**账户 |
    | 团队角色 | `account_members.role` / `accounts.owner_user_id` | 只在**本账户**内 |

    一个用户可以在 A 账户是 owner、在 B 账户只是 member，同时**不是**平台超管；
    也可以既是平台超管、又在某个账户里什么角色都没有。

    ⇒ 所以 `resolve_account_role()` **只返回团队角色**，绝不把超管身份伪装成
      "owner" 混进返回值 —— 那会让审计日志说谎，也会让「这个用户到底是不是
      这个团队的人」这个事实被抹掉。

==============================================================================
★ 为什么用字符串角色而不是枚举对象
==============================================================================
`account_members.role` 落库是 String（理由见 account_models.py 的文件头）。
本模块对外一律用**字符串值**（`AccountRole.OWNER.value`），避免调用方
在一个地方拿到枚举、在另一个地方拿到字符串而写错比较。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import List, Optional, Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.identity.account_models import (
    ACCOUNT_PERMISSIONS,
    Account,
    AccountMember,
    AccountRole,
    MemberStatus,
    role_allows,
)
from core.identity.models import User, UserRole


# ====== 常量 ======

#: 平台超管的角色字符串（与 `UserRole.ADMIN.value` 同源，不另写字面量）
PLATFORM_ADMIN_ROLE = UserRole.ADMIN.value

#: 可以被**分配**给成员的角色（不含 owner）
#:
#: ★ owner 不在其中：它是账户创建时由 `ensure_default_account()` 唯一确定的，
#:   只能通过「转让账户」变更（尚未实现），不能走成员管理接口赋给某人 ——
#:   否则会出现「两个 owner」或「owner 被降级后账户无主」两种坏状态。
ASSIGNABLE_ACCOUNT_ROLES: frozenset[str] = frozenset({
    AccountRole.ADMIN.value,
    AccountRole.MEMBER.value,
    AccountRole.VIEWER.value,
})

#: 全部合法角色（含 owner），用于校验落库值
VALID_ACCOUNT_ROLES: frozenset[str] = frozenset({r.value for r in AccountRole})

#: 无权限时的统一文案
NO_ACCESS_DETAIL = "无权访问该账户"


def new_id() -> str:
    """生成账户域实体的主键（UUID 字符串，与既有 users/shops 口径一致）。"""
    return str(uuid.uuid4())


# ====== 平台超管链路 ======

def is_platform_admin(user: Optional[User]) -> bool:
    """
    是否平台超管（跨全部账户）。

    ★ 演示模式下 `require_auth_if_enabled` 会返回 `None` —— 这里返回 False，
      表示"没有身份"，**不是**"是超管"。调用方要自己决定 None 怎么处理
      （业务侧的做法是：None ⇒ 跳过归属校验，保持本地演示行为不变）。
    """
    if user is None:
        return False
    role = getattr(user, "role", None)
    # role 可能是 UserRole 枚举，也可能是裸字符串（构造出来的轻量对象）
    return getattr(role, "value", role) == PLATFORM_ADMIN_ROLE


# ====== 店铺对象访问器（duck typing 的唯一落点）======
#
# 归属判定要同时服务两种"店铺"对象：
#   - `models/store.py::Store`（pydantic，内存 dict `_store_db` 里那种）
#   - `modules/stores/db_model.py::StoreRecord`（ORM 行）
# 二者字段名相同，但 pydantic 侧早期没有 `account_id`。
# 把"取哪个属性"收在这两个函数里，将来加字段只改一处。

def store_account_id(store) -> Optional[str]:
    """取店铺的账户归属（缺失/为空返回 None，走过渡期兜底分支）。"""
    return getattr(store, "account_id", None) or None


def store_owner_id(store) -> Optional[str]:
    """取店铺的创建者用户 id（`owner_id` 降级后的唯一用途：审计 + 过渡期兜底）。"""
    return getattr(store, "owner_id", None) or None


# ====== 可见账户集合 ======

async def get_visible_account_ids(
    db: AsyncSession,
    user: Optional[User],
) -> Optional[frozenset[str]]:
    """
    当前用户可见的账户 id 集合。

    Returns:
        `None`  —— **平台超管**：可见全部账户（调用方据此短路，不做集合判定）；
        `frozenset` —— 其余情况：可能为空集（新注册用户还没有任何账户）。

    ★ 为什么用 `None` 而不是"返回全部账户 id 的集合"：
      后者要在每次请求里把全表账户 id 拉出来（随规模线性增长），
      而"全部"这个语义本来就等价于"不设限"。空集与 None 必须区分开 ——
      空集是"什么都看不到"，None 是"什么都不限"，混起来就是越权。

    ★ 为什么过滤 `Account.is_active`：
      停用账户下的成员不应继续持有访问权。停用是管理动作，必须立刻生效，
      不能等成员记录被逐个清理。
    """
    if user is None:
        return frozenset()

    if is_platform_admin(user):
        return None  # 全部

    owned = await db.execute(
        select(Account.id).where(
            Account.owner_user_id == user.id,
            Account.is_active.is_(True),
        )
    )

    member_of = await db.execute(
        select(AccountMember.account_id)
        .join(Account, Account.id == AccountMember.account_id)
        .where(
            AccountMember.user_id == user.id,
            AccountMember.status == MemberStatus.ACTIVE.value,
            Account.is_active.is_(True),
        )
    )

    return frozenset(owned.scalars().all()) | frozenset(member_of.scalars().all())


async def filter_accessible_stores(
    db: AsyncSession,
    user: Optional[User],
    stores: Sequence,
) -> List:
    """
    按归属筛掉不可访问的店铺（列表端点的唯一筛法）。

    ★ 为什么单独给一个批量函数：`can_access_store()` 每次都要查一次
      "可见账户集合"，列表端点里对 N 家店调用 N 次就是 N 次往返。
      这里只查一次集合、再在内存里过滤。

    ★★★ 守卫：**没有身份 ⇒ 没有数据**（2026-09-17 收紧；改前是 fail-open）

      改前：`user is None` ⇒ `return list(stores)`（**不过滤** ⇒ 全库返回）。
      改后：`user is None` ⇒ `return []`。

      为什么必须收：`auth_required=False`（本地 / 演示档）下，匿名请求能拿到
      **全部真实店铺**。生产档不受影响 —— `main.py::BUSINESS_AUTH` 先用 401
      拦掉匿名，所以 `user is None` 在生产档**不可达**。但"生产不可达"不等于
      "本地安全"：`.env` 漏改一行、或拿演示配置连了真实库，就是全库裸奔。

      为什么返回空列表、而不是在这里抛 401 / 403：
      「放不放行」已由**上游**决定（`require_auth_if_enabled`：生产档无凭据 → 401，
      演示档无凭据 → 放行到本函数）。本函数只负责**数据可见性**，不该反向改写
      上游的鉴权结论。上游放行 + 这里给空集 = "访问被允许，但你看不到任何店铺"。

    ★ 为什么**不动** `can_access_store` / `_matches` 的同一分支：
      那两个函数服务的是**单店**路径（详情 / 写操作 / `X-Shop-ID` 解析）。改它们
      会让演示档下所有单店请求变成 403 —— 那是**另一档**决策（演示档整体
      fail-closed），已作为体检报告 P1-5 单独挂账。本次只收口列表入口，
      不顺手制造第三种语义。
      ⇒ 已知副作用（**有意保留**）：演示档下"列表为空、单店详情仍可读"是
        不一致的。要一致就整档一起收 —— 但那是同一处收口，见 P1-5。
    """
    if user is None:
        return []

    visible = await get_visible_account_ids(db, user)
    if visible is None:
        # 平台超管：全部可见。★ 与上面的空集**不可混淆** ——
        # 空集是"什么都看不到"，None 是"什么都不限"。
        return list(stores)
    return [s for s in stores if _matches(store_account_id(s), store_owner_id(s), visible, user)]


# ====== 单店归属判定（两处重复判定的收敛点）======

def _matches(
    account_id: Optional[str],
    owner_id: Optional[str],
    visible: Optional[frozenset[str]],
    user: Optional[User],
) -> bool:
    """`can_access_store` 的纯函数内核（不碰 IO，便于单测穷尽分支）。"""
    if user is None:
        # 演示模式：放行。调用方负责决定是否走到这里。
        return True

    if visible is None:
        # 平台超管
        return True

    if account_id:
        return account_id in visible

    # ⚠️ 过渡期兜底：无账户归属的存量/合成店铺回退到创建者判定。
    #    这是**唯一**仍读 owner_id 做授权的地方，回填完成后连同本分支一起删。
    return bool(owner_id) and owner_id == user.id


async def can_access_store(
    db: AsyncSession,
    user: Optional[User],
    store,
) -> bool:
    """
    当前用户能否访问该店铺（`_resolve_current_shop_id` 与 `_check_store_owner` 的共用实现）。

    `store` 可以是 pydantic `Store` 或 ORM `StoreRecord`（任意带 `account_id`/`owner_id` 的对象）。
    """
    if user is None or is_platform_admin(user):
        return True

    visible = await get_visible_account_ids(db, user)
    return _matches(store_account_id(store), store_owner_id(store), visible, user)


async def ensure_can_access_store(
    db: AsyncSession,
    user: Optional[User],
    store,
    *,
    detail: str = "无权访问该店铺",
) -> None:
    """
    同 `can_access_store`，但失败直接抛 403。

    ★ 统一 403 而不是 404：404 会泄露「该店铺 ID 是否存在」，帮攻击者枚举有效 ID。
      同时不存在 / 无主 / 归属他人三种情况**响应完全一致**，不提供区分信号。
    """
    if not await can_access_store(db, user, store):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


# ====== 会话归属判定（P0-1，2026-09-18）======
#
# ★ 为什么会话**不**走上面的「店铺 → 账户」链路：
#   `conversations.shop_id` 在本项目**从未被写过**（实测开发库 57 行全 NULL），
#   而 `owner_id` 才是设计时表达的归属。会话是「**某个人的**对话历史」，
#   不是「某家店的业务数据」—— 把它挂到店铺/账户上，等于宣布
#   "同店同事可以互相读聊天记录"，这不是任何一处的产品语义。
#
# ★ 会话是**私有**资源，判定只有一条：
#       conversation.owner_id == user.id      （平台超管短路放行）
#   无主会话（`owner_id IS NULL`，含修复前的存量行）对**任何有身份的人**都不可
#   访问 ⇒ fail-closed。「没有归属的数据」被谁继承都不该发生 ——
#   那正是 P0-1 的原始形态（57 行会话全部 `owner_id=NULL`）。
#
# ★ 判定入口唯一：`modules/conversation/service.py::get_owned_conversation`。
#   其余所有读/写函数都从它进，所以「哪条通道忘了判权」在结构上不可能发生。

def conversation_owner_id(conv) -> Optional[str]:
    """取会话的归属用户 id（duck typing 的唯一落点，与 `store_*` 访问器同形）。"""
    return getattr(conv, "owner_id", None) or None


def can_access_conversation(user: Optional[User], conv) -> bool:
    """
    当前用户能否访问该会话。

    ★ 判定是**纯函数**，刻意不带 `db`：它不查库，也不需要「可见账户集合」
      （`get_visible_account_ids` 是店铺侧的概念，会话用不上）。
      将来若要引入"团队共享会话"，改本函数 + 上面那个唯一入口即可，
      两处就是全部 —— 不需要新增调用点去各自判一遍。

    ★ `user is None` ⇒ True 是**演示档**语义（`config.auth_required=False` 且
      请求完全不带凭据，或带的是 `demo_mode` 下的演示哨兵），与
      `can_access_store` 里 `user is None` 的放行是同一档。
      生产档（`auth_required=True`）下本分支**不可达** —— 匿名请求在
      `BUSINESS_AUTH` 就被 401 拦掉，根本到不了这里。
      ⚠️ 演示档整体 fail-closed 是**另一项**已挂账的债（体检报告 P1-5），
        不要在这里顺手收紧：那会把本地匿名联调一起打死，属于另一轮的议题。
    """
    if user is None:
        return True
    if is_platform_admin(user):
        return True
    owner = conversation_owner_id(conv)
    return bool(owner) and owner == user.id


# ====== 团队角色与能力门 ======

async def resolve_account_role(
    db: AsyncSession,
    user: Optional[User],
    account_id: str,
) -> Optional[str]:
    """
    用户在指定账户内的**团队角色**（owner/admin/member/viewer）；不是成员则 None。

    ★ 平台超管**不**在这里被伪装成 owner —— 返回的永远是"他确实是这个团队的人
      且有这个角色"，否则审计与展示都会说谎。要判断超管请用 `is_platform_admin()`。

    判定优先级：
        1. `Account.owner_user_id == user.id` ⇒ owner（**不查成员表**，它是权威）
        2. `account_members` 里 status=ACTIVE 的行 ⇒ 该行 role
        3. 其余 ⇒ None
    """
    if user is None:
        return None

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None:
        return None

    if account.owner_user_id == user.id:
        return AccountRole.OWNER.value

    member = await db.execute(
        select(AccountMember.role).where(
            AccountMember.account_id == account_id,
            AccountMember.user_id == user.id,
            AccountMember.status == MemberStatus.ACTIVE.value,
        )
    )
    return member.scalar_one_or_none()


async def can_access_account(
    db: AsyncSession,
    user: Optional[User],
    account_id: str,
) -> bool:
    """能否访问该账户（超管短路；否则必须是 owner 或 ACTIVE 成员，且账户未停用）。"""
    if user is None:
        return True

    if is_platform_admin(user):
        return True

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None or not account.is_active:
        return False

    return await resolve_account_role(db, user, account_id) is not None


async def require_account_permission(
    db: AsyncSession,
    user: Optional[User],
    account_id: str,
    permission: str,
) -> Optional[str]:
    """
    团队链路的能力门。不通过则抛 403 / 404。

    Args:
        permission: `ACCOUNT_PERMISSIONS` 里的能力名（account.read / store.write /
                    store.delete / member.manage / account.manage）。

    Returns:
        团队角色字符串（owner/admin/member/viewer）；**平台超管短路放行时返回 None**
        —— 表示"他不是这个团队的人，只是有超管身份"。要展示角色请用
        `resolve_account_role()`，不要把这个返回值当成"没有权限"。

    Raises:
        HTTPException 404: 账户不存在或已停用（对非超管等价于"看不到"）
        HTTPException 403: 是账户的人但没有这个能力
        HTTPException 403: 未知能力名 —— **拒绝而非放行**，理由见
                           `account_models.role_allows` 的 docstring

    ★ 未知能力名在 `role_allows` 里恒为 False ⇒ 走的是下面的 403 分支，
      不会因为"表里查不到"而静默放行。
    """
    if user is None:
        # 演示模式：放行，与业务侧既有行为一致
        return None

    if is_platform_admin(user):
        return None

    result = await db.execute(select(Account).where(Account.id == account_id))
    account = result.scalar_one_or_none()
    if account is None or not account.is_active:
        # 对"看不到"的情况一律 404；不区分不存在/已停用
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="账户不存在")

    role = await resolve_account_role(db, user, account_id)
    if role is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=NO_ACCESS_DETAIL)

    if not role_allows(role, permission):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"当前角色（{role}）无权执行该操作：{permission}",
        )

    return role


def permission_names() -> Sequence[str]:
    """全部已登记的能力名（测试用穷尽断言，避免新增能力漏测）。"""
    return tuple(ACCOUNT_PERMISSIONS.keys())


# ====== 默认容器的创建与幂等获取 ======

def _default_account_name(user: User) -> str:
    """自动创建容器时的默认名（★ 第 110 轮：由「{名} 的账户」改为「{名} 的团队」）。

    ★ 为什么带用户名而不是固定的「我的团队」：容器列表可能被**非本人**看到
      （例如平台超管的账户列表里混着多人的容器），无主名会分不清是谁的。
    ★ 这只是**用户没起名字**时的兜底值 —— 用户自建容器用的是自己填的名字。
    """
    label = (getattr(user, "name", None) or getattr(user, "email", None) or "").strip()
    return f"{label} 的团队" if label else "我的团队"


async def ensure_owner_member(
    db: AsyncSession,
    account: Account,
    user: User,
) -> AccountMember:
    """
    保证「账户所有者」在 `account_members` 里有一条 ACTIVE / owner 的记录。

    ★ 为什么 owner 事实已经在 `accounts.owner_user_id` 里，还要再写一条成员行：
      成员列表端点、成员计数、审计视图都读 `account_members`；缺这条行会让
      账户所有者**在自己团队的成员列表里消失**。迁移 `d1e2f3a4b5c6` 的回填
      （`_BACKFILL_OWNER_MEMBERS`）也是这个口径，两处必须一致。

    ★ 幂等：已存在则原样返回（含"曾被软删、再回来"的情形 —— 走 UPDATE 改回 ACTIVE，
      不插新行，否则撞唯一约束 `uq_account_members_account_user`）。
    """
    result = await db.execute(
        select(AccountMember).where(
            AccountMember.account_id == account.id,
            AccountMember.user_id == user.id,
        )
    )
    existing = result.scalar_one_or_none()

    if existing is not None:
        existing.role = AccountRole.OWNER.value
        existing.status = MemberStatus.ACTIVE.value
        if existing.joined_at is None:
            existing.joined_at = datetime.utcnow()
        return existing

    member = AccountMember(
        id=new_id(),
        account_id=account.id,
        user_id=user.id,
        role=AccountRole.OWNER.value,
        status=MemberStatus.ACTIVE.value,
        invited_by=None,
        joined_at=datetime.utcnow(),
    )
    db.add(member)
    return member


async def ensure_default_account(db: AsyncSession, user: User) -> Account:
    """
    获取（必要时创建）该用户的**默认容器** —— **幂等**。

    调用时机：建店未指定归属时兜底 / `GET /accounts/me` / 运维脚本。

    ==========================================================================
    ★★★ 第 110 轮：这里**不再有**「个人账户」这个概念
    ==========================================================================
    删掉它的理由是它**站不住**：

        「私有」不是一种**容器类型**，而是**成员数的一个取值** ——
        成员数 = 1 时观感上是私有，> 1 就是共享。「一个人也可以是一人团」。

    实测（开发库）直接证伪：老板的容器「跨境1」被回填成 `personal`，
    而里面**坐着另一名成员李航** —— 标签与数据互相矛盾。

    ⇒ `AccountKind` 枚举已删除；`accounts.kind` 列已由迁移 `b7e3f1a9c2d4`
      删除；前端不再展示任何「个人 / 团队」标签，容器一律显示**它自己的名字**。

    ==========================================================================
    那么本函数现在只回答**一个问题**：不指定归属时，新店铺落到哪个容器？
    ==========================================================================
    判据（按顺序）：
      1. 该用户名下**最早创建**的容器（`created_at, id` 全序，保证稳定）；
      2. 一个都没有 ⇒ **新建**，名字取 `_default_account_name()`（"{名} 的团队"）。

    ★ 为什么第 1 条用「最早」是**对**的（而旧实现用它是**错**的）：
      旧实现（第 106 轮之前）用「最早」是拿插入顺序去**冒充一个概念**
      （"最早的那个就是他的个人账户"）—— 概念一换口径就崩。
      现在「最早」是在**显式表达一条产品规则**：「默认落到你最早的容器」。
      规则是明说的、确定性的，不再承担"指代某种隐含语义"的职责。

    ★ 实际使用中这条兜底很少走到：前端建店时会**显式**传当前选中的容器
      （`current_account_id`，见 `frontend/src/stores/account.ts`）。

    ★ 幂等的实现要点：先查已有的容器并复用。非幂等会造出**第二个**容器，
      而重复账户**不会报错** —— 用户会看到两个一模一样的团队，店铺散落其中，
      且没有任何日志提示。（这正是迁移回填 SQL 必须幂等的同一条理由。）

    ★ 查不到时**新建**，而不是把名下某个容器"提升"为默认：
      提升会改变那个容器的语义（它可能已在实际协作使用中），其名下店铺的
      归属含义随之突变。新建则语义清晰、零副作用。
    """
    result = await db.execute(
        select(Account)
        .where(Account.owner_user_id == user.id)
        .order_by(Account.created_at, Account.id)
    )
    existing = result.scalars().first()

    if existing is not None:
        await ensure_owner_member(db, existing, user)
        await db.flush()
        return existing

    account = Account(
        id=new_id(),
        name=_default_account_name(user),
        owner_user_id=user.id,
        is_active=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(account)
    # flush 拿到 account.id 后立刻补 owner 成员行，两者要么一起成功、要么一起回滚
    await db.flush()
    await ensure_owner_member(db, account, user)
    await db.flush()
    return account
