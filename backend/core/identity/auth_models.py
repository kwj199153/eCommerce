"""
认证辅助模型：EmailToken（邮箱验证 / 密码重置） + LoginAttempt（登录审计）

==============================================================================
★ 为什么 token 存哈希而不是明文（P1-b，2026-09-16）
==============================================================================
邮箱验证与密码重置链接里带的是**具备实际权限的凭据** ——
拿到重置 token 就等于能改那个账号的密码。若明文落库：

    数据库被拖库（备份泄露 / 只读副本 / SQL 注入读到该表）
      ⇒ 攻击者直接用现成的 token 改任意用户密码，**不需要破解任何东西**。

代价对比很清楚：存哈希只多一次 sha256（微秒级），而明文泄露是不可逆的账号沦陷。
判据与口令一致：**凡是被验证方持有的秘密，库里都不该有它的原文。**

★ 为什么必须在同一列上区分 purpose：
    验证邮箱的 token 若能拿去重置密码，等于把「能收信」升级成「能改密码」——
    而这两个动作的可信度并不相同（邮箱可能只是转发规则临时加的）。
    故 purpose 参与消费判据，不是装饰字段。

==============================================================================
★ 一次性（one-time）为什么必须靠一条 UPDATE 而不是"先查后改"
==============================================================================
用户双击邮件链接、或邮件客户端预先抓取链接（Outlook/安全网关会做），
都会让同一 token 被并发消费。若写成：

    row = SELECT ... WHERE token_hash=:h          # ① 两边都查到 used_at IS NULL
    if row.used_at is None: UPDATE ... SET used_at=now()   # ② 两边都写

则两条请求都会通过 ①，token 被用两次（典型 TOCTOU）。
所以消费判据全部压进**一条** UPDATE：

    UPDATE email_tokens SET used_at = now()
     WHERE token_hash = :h AND purpose = :p
       AND used_at IS NULL AND expires_at > now()
    RETURNING user_id

影响行数为 0 = 无效/过期/已用过（三者对外统一话术，不区分）。
PostgreSQL 的行锁保证并发的第二条会等到第一条提交后发现 `used_at` 已非空 ⇒ 影响 0 行。
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class EmailTokenPurpose(str, enum.Enum):
    """一次性 token 的用途（参与消费判据，不可混用）"""
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"


class EmailToken(Base):
    """邮箱验证 / 密码重置的一次性 token（只存 sha256 哈希）"""
    __tablename__ = "email_tokens"
    __table_args__ = (
        Index("ix_email_tokens_user_purpose", "user_id", "purpose"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_email_tokens_user_id_users"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(24), nullable=False)
    # ★ 唯一：同一个哈希不能对应两条有效记录（否则消费时影响行数不确定）
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # 非空 = 这条 token 已被消费（一次性判据就落在这里）
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    # 申请来源 IP（风控排查用；不参与判定）
    requested_ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:
        return f"<EmailToken(user={self.user_id}, purpose={self.purpose}, used={bool(self.used_at)})>"


class LoginAttempt(Base):
    """
    登录尝试审计（每次登录一条）。

    ★ 与 `users.failed_login_count` 的分工（**别把两者混为一谈**）：
        - `users.failed_login_count` / `locked_until` = **判定**用。
          锁定必须在 DB 上、且必须查得到，Redis 抖一下不能让锁定消失。
          它只保当前值（成功即清零），没有历史。
        - 本表 = **审计**用。回答的是「昨晚 3 点是谁在撞我的账号」这类问题，
          以及「锁定机制到底触发过没有」的可验证证据（用例据此断言）。
          它是 append-only 的，不做判定。

    为什么不做「按 IP 计数」的锁定：
      本项目限流按 IP 已经做了（core/middleware/rate_limit.py，60 次/分钟）。
      再叠一层 IP 锁定会把 NAT 后的一整个办公室一起锁掉，
      而攻击者换 IP 成本极低 —— 收益小、误伤大。所以锁定只针对**账号**。
    """
    __tablename__ = "login_attempts"
    __table_args__ = (
        Index("ix_login_attempts_email_created", "email", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    # 用邮箱而非 user_id 作为主查询键：登录失败时**用户可能根本不存在**，
    # 而「谁在撞哪些邮箱」恰恰是最需要看见的信息。
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL", name="fk_login_attempts_user_id_users"),
        nullable=True,
        index=True,
    )
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 失败原因（ok / bad_password / unknown_email / locked / inactive / unverified）
    reason: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False, index=True
    )

    def __repr__(self) -> str:
        return f"<LoginAttempt(email={self.email!r}, success={self.success}, reason={self.reason})>"


class UserApiKey(Base):
    """
    用户自建 API 密钥（**只存 sha256 哈希与掩码串**）。

    ★ 与 `EmailToken` 同一条判据：凡是被验证方持有的秘密，库里都不该有原文。
      明文 key 是「持有即有权」的凭据，明文落库 ⇒ 拖库即沦陷，
      攻击者不需要破解任何东西。代价只是一次 sha256（微秒级）。

    ★ 为什么要额外存 `key_masked`：
      列表接口每次都要给出**稳定一致**的掩码（`sk-abcD****wxyz`）。
      库里只有哈希 ⇒ 前缀/后 4 位这类信息已经不可复原，
      必须在创建时一并存下来，否则列表只能显示成 `****`。

    ★ 软删（`is_active=False` + `revoked_at`）而不是物理 DELETE：
      密钥可能已被写进客户的 CI/CD、环境变量、第三方集成。
      真删掉这行之后，「这枚 key 存在过吗 / 什么时候被撤的」就查不到了 ——
      出事时的排查成本远高于留一行的存储成本。
    """
    __tablename__ = "user_api_keys"
    __table_args__ = (
        Index("ix_user_api_keys_user_active", "user_id", "is_active"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="CASCADE", name="fk_user_api_keys_user_id_users"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # ★ 唯一：同一枚 key 不能对应两条记录（否则撤销时影响行数不确定）
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # 掩码串（创建时生成后固定下来，列表直接回显）
    key_masked: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:
        return f"<UserApiKey(user={self.user_id}, name={self.name!r}, active={self.is_active})>"

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块声明的外键用的是**字符串**目标（`ForeignKey("users.id")`），SQLAlchemy
# 解析时要在当前 `MetaData` 里按表名找到 `users`。若从未有人 import 过定义
# `users` 的模块，则**任何一次 flush** 都会抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'account_members.user_id' could not find table 'users'
#
# 注意它抛在 flush 的**拓扑排序**（`sorted_tables`）里，不在 import 时；
# 而且报错指向**外键本身**，看起来像"外键写错了"。
#
# ★ 第 140 轮实测：单独 `import core.identity.account_models` 时
#   `Base.metadata.sorted_tables` 直接失败 —— 上面这段原则在本模块从未落实。
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖"某个入口恰好先 import 了它"。
#   同一模式见 `core/stores/models.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
import core.identity.models  # noqa: E402,F401  注册 users
