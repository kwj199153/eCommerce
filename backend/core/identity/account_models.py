"""
账户域模型：Account（账户/团队） + AccountMember（成员与角色）

==============================================================================
★ 这一层解决的是什么（P1-c，2026-09-16）
==============================================================================
改造前本项目有**两套店铺实体**，ID 空间不同且互不同步：

    | 侧 | 表 | ID 形态 | 谁在读 |
    |----|----|---------|--------|
    | 账户侧 | `shops` | UUID | 只有 shop_router.py 的 7 个端点（已于同批 C4 删除） |
    | 业务侧 | `stores_store` | `store_xxx` | 15 个业务模块的 get_current_shop_id* |

实测：`/api/v1/shops` 那 7 个端点**生产 0 调用点**，且用 `POST /shops` 建出来的
店在业务侧**根本不可用**（UUID 放进 X-Shop-ID 打业务端点 → 403）
⇒ 那条路会**安静地生产一批废店**。

现在收拢为单一层级：

    User ──(owner_user_id)──> Account ──(account_id)──> StoreRecord
                                 │
                                 └──(account_members)──> User   ← 成员可共享账户下的店铺

★ 关键取舍：**业务侧分区键 store_xxx 一动不动**。
  16 张业务表的外键、全部前端调用、X-Shop-ID 语义都不变；
  变的只有「凭什么说你归这家店」—— 从
      `stores_store.owner_id == 当前用户`
  升级为
      `stores_store.account_id ∈ 当前用户可见的账户集合`。
  这就是「团队共享店铺」的形态，也是成员表存在的意义。

==============================================================================
★ 为什么 role / status 用 String 而不是 SAEnum
==============================================================================
SQLAlchemy 的 `Enum(SomePyEnum)` 默认按枚举成员的 **.name** 落库（不是 .value），
项目里已经踩过一次（见 tests/test_auth_and_tenant.py 里对 platform 的注释）。
本模块与 `modules/stores/db_model.py`（StoreRecord 的 status/sync_status 也是
String）保持一致：**String 落库 + Python 侧枚举做校验与类型提示**。
少一层隐式转换，迁移和手写 SQL 都不会踩到 name/value 不一致。
"""

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.database import Base


# ====== 枚举（Python 侧校验真源；落库为下面各常量的字符串值）======

class AccountRole(str, enum.Enum):
    """
    账户内角色（**权限矩阵**的真源）

    ★ 与 `User.role`（平台级 superadmin）是**两条独立的链路**：
        - `UserRole.ADMIN`  = 平台超管，可跨**全部**账户
        - `AccountRole.OWNER/ADMIN` = 团队管理员，只在**本账户**内有效
      两者不能互相推导：一个用户可以在 A 账户是 owner、在 B 账户只是 member，
      同时**不是**平台超管。判据见 core/auth/accounts.py。
    """
    OWNER = "owner"      # 账户所有者（唯一，不可被移除/降级）
    ADMIN = "admin"      # 团队管理员（可管店铺与成员，但动不了 owner）
    MEMBER = "member"    # 成员（可读写店铺及其业务数据）
    VIEWER = "viewer"    # 只读（可看，任何写操作 403）


class MemberStatus(str, enum.Enum):
    """成员状态"""
    INVITED = "invited"  # 已邀请，对方尚未接受
    ACTIVE = "active"    # 正常
    REMOVED = "removed"  # 已移除（软删除：保留审计痕迹，不物理删行）


# ====== 权限矩阵（唯一真源，端点与依赖都读它，禁止各自写 if）======

# 每个动作允许的角色。键是「能力名」，值是允许的角色集合。
#
# ★ 为什么做成表而不是散落的 if：
#   改造前的鉴权写法是 `if current_user.role.value != "admin"` 这类
#   随处可见的判断，新增一个动作就要在若干处补一遍，必然漂移。
#   收成一张表后，「谁能做什么」只有一处定义，测试也只需要对着它做穷尽断言。
ACCOUNT_PERMISSIONS: dict[str, frozenset[str]] = {
    # 查看账户与店铺
    "account.read":   frozenset({AccountRole.OWNER.value, AccountRole.ADMIN.value,
                                 AccountRole.MEMBER.value, AccountRole.VIEWER.value}),
    # 新建/修改店铺
    "store.write":    frozenset({AccountRole.OWNER.value, AccountRole.ADMIN.value,
                                 AccountRole.MEMBER.value}),
    # 删除店铺（不可逆，收紧到 owner/admin）
    "store.delete":   frozenset({AccountRole.OWNER.value, AccountRole.ADMIN.value}),
    # 管理成员（邀请/改角色/移除）
    "member.manage":  frozenset({AccountRole.OWNER.value, AccountRole.ADMIN.value}),
    # 改账户本身（改名/转让/删除账户）
    "account.manage": frozenset({AccountRole.OWNER.value}),
}


def role_allows(role: Optional[str], permission: str) -> bool:
    """
    判定某角色是否拥有某能力。

    ★ 未知能力名**一律拒绝**（而不是抛 KeyError 或默认放行）：
      新增能力时如果忘了登记，宁可新功能用不了（立刻发现），
      也不能因为"表里查不到"就默认放行（无声越权）。
    """
    allowed = ACCOUNT_PERMISSIONS.get(permission)
    if allowed is None:
        return False
    return (role or "") in allowed


# ====== 账户 ======

class Account(Base):
    """
    账户（团队）。店铺的上级实体，取代原 `shops` 表在架构中的位置。

    ★ 与已删除的 `shops` 的关键差异：
      `shops` 既是「店铺」又要承担「归属校验的锚点」，于是业务侧不得不
      再建一套 `stores_store` —— 两套实体各自演进，最终互不同步。
      现在把「归属锚点」这一职责单独抽成 Account，`stores_store` 就只是
      「账户下的一个店铺」，概念不再重叠。
    """
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_accounts_owner_user_id_users"),
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    members: Mapped[List["AccountMember"]] = relationship(
        "AccountMember", back_populates="account", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Account(id={self.id}, name={self.name!r}, owner={self.owner_user_id})>"


# ====== 成员 ======

class AccountMember(Base):
    """
    账户成员（含角色）。**这是团队共享店铺的落点**。

    ★ `status=REMOVED` 用软删除而不是物理删行：
      成员变更属审计范畴（"谁在什么时候把谁踢了"），物理删掉就查不回来了。
      而权限判定只看 `status == ACTIVE`，所以软删不会留下隐式权限。

    ★ 唯一约束 (account_id, user_id)：
      同一人不能在同一账户里有两条成员记录 —— 否则会出现
      「一条 ACTIVE、一条 REMOVED」时到底算不算成员的二义性。
      重新邀请走 UPDATE 把 status 改回 ACTIVE，不是插新行。
    """
    __tablename__ = "account_members"
    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_account_members_account_user"),
        Index("ix_account_members_user_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    account_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("accounts.id", ondelete="CASCADE", name="fk_account_members_account_id_accounts"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_account_members_user_id_users"),
        nullable=False,
        index=True,
    )
    # 角色：AccountRole 的字符串值（owner / admin / member / viewer）
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=AccountRole.MEMBER.value)
    # 状态：MemberStatus 的字符串值（invited / active / removed）
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=MemberStatus.ACTIVE.value)
    invited_by: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_account_members_invited_by_users"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    joined_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    account: Mapped["Account"] = relationship("Account", back_populates="members")

    def __repr__(self) -> str:
        return (
            f"<AccountMember(account={self.account_id}, user={self.user_id}, "
            f"role={self.role}, status={self.status})>"
        )
