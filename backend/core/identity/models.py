"""
用户基础实体（全系统共用）

★ 为什么住在 core 而不是某个业务模块：
    本模块的 User 被 **26 处** import —— core/（auth 鉴权、tenant 租户中间件、
    database 注册）与多个业务模块（aigc_media / product_research / secretary …）
    以及 tests / scripts。
    判据：**一个模块的模型被 2 个以上别的模块 import ⇒ 它是基础域，不是业务域。**
    修复前它们和 Subscription / Invoice 挤在 modules/user_subscription/models.py，
    于是 core 为了拿到 User 不得不反向 import 业务模块（core → modules
    共 24 条反向依赖，这里是第一大源头）。

    本次拆分（2026-09-16）：实体按**消费者范围**归位，表名与列一律不动
    ⇒ 不需要写任何数据库迁移。

★★★ P1-c 收拢（2026-09-16）：`Shop` / `ShopPlatform` / `User.shops` 已删除
    本项目曾有**两套店铺实体**，ID 空间不同且互不同步：

      | 侧 | 表 | ID 形态 | 谁在读 |
      |----|----|---------|--------|
      | 账户侧 | `shops` | UUID | 只有 core/identity/shop_router.py 的 7 个端点 |
      | 业务侧 | `stores_store` | `store_xxx` | 15 个业务模块的 get_current_shop_id* |

    实测：`/api/v1/shops` 那 7 个端点**生产 0 调用点**（前端只调 `/api/v1/stores`），
    且用 `POST /shops` 建出来的店在业务侧**根本不可用** —— 把它的 UUID 放进
    `X-Shop-ID` 打业务端点，业务侧查 `stores_store` 查不到 ⇒ 403。
    也就是说这条路会**安静地生产一批废店**。

    现在收拢为单一层级（Account / AccountMember 见 core/identity/account_models.py）：

        User ──(owner_user_id)──> Account ──(account_id)──> StoreRecord
                                     │
                                     └──(account_members)──> User  ← 成员共享账户下的店铺

    ★ 关键取舍：**业务侧分区键 store_xxx 一动不动**（16 张业务表的外键、全部前端
      调用、`X-Shop-ID` 语义都不变）。变的只有「凭什么说你归这家店」。
    ⇒ 本模块现在只剩 `User` 这一个实体。
"""

from datetime import datetime
from typing import Optional

import enum

from sqlalchemy import JSON, Boolean, DateTime, Enum as SAEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

# 统一到 core.database.Base（alembic autogenerate 才会看到所有表）
from core.database import Base


# ====== 枚举类型 ======

class UserRole(str, enum.Enum):
    """
    用户角色。

    ★★ 请与「账户内的团队角色」区分开 —— 这是两条**不可互相推导**的权限链路：

      | 链路 | 载体 | 作用域 | 判定入口 |
      |------|------|--------|----------|
      | 平台角色 | `users.role`（本枚举） | **跨全部账户**（平台超管） | `core/auth/accounts.py::is_platform_admin` |
      | 团队角色 | `account_members.role` | **仅本账户内** | `resolve_account_role` / `require_account_permission` |

      两者正交：平台超管可以不是任何团队的成员（`role=None`）；
      账户 owner 也不是平台超管。`resolve_account_role()` **只返回团队角色**。
    """
    ADMIN = "admin"
    USER = "user"


# ====== 用户模型 ======

class User(Base):
    """用户表"""
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(SAEnum(UserRole), default=UserRole.USER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # ★ P1-b（2026-09-16）：此前是**死字段** —— 注册写死 False，全项目
    #   grep 不到任何把它改成 True 的地方（赋值点只有 `=False`）。
    #   现在由 `POST /auth/verify-email` 消费一次性 token 后置 True。
    #   `email_verification_required=True` 时登录会检查它。
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)  # 邮箱验证

    # ====== 凭据撤销与爆破防护（★ P1-b 2026-09-16）======
    #
    # ★★★ token_version —— 「改密后让该用户所有 token 失效」的**唯一**正确实现。
    #
    #   为什么不是「把该用户所有 token 加进黑名单」：
    #     无状态 JWT 的核心特性就是**服务端不知道有哪些 token 在飞**。
    #     要逐个加黑名单，先得有一份「已签发 token 清单」—— 有了它，
    #     JWT 就不再是无状态的了（等于自建一套更差的 session 表）。
    #   版本号的做法：签发时把 `tv` 写进 token，校验时与库里这一列比对。
    #     改密 / 重置密码 / 「登出所有设备」 ⇒ token_version += 1
    #     ⇒ 全部旧 token 的 tv 不再匹配 ⇒ **结构性失效**，
    #       不需要知道它们分别是什么，也不依赖 Redis。
    #
    #   注意这是**整批失效**（所有设备一起下线）。「只登出当前这一台」
    #   由 jti 黑名单承担（见 core/auth/revocation.py 的两级分工）。
    token_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, server_default="1")

    # ★ failed_login_count / locked_until —— 口令爆破防护。
    #   放在 users 表（而不是只放 Redis）的理由：锁定是**安全判定**，
    #   Redis 抖一下不能变成"锁定消失"。Redis 挂掉时这套必须照常生效。
    #   审计明细另存 login_attempts 表（见 auth_models.py）。
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False, server_default="0")
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # ====== 自助管理资料（★ 第 100 轮 2026-09-16）======
    #
    # 这四列服务的是 `frontend/src/views/Settings.vue` 那批此前一直 404 的
    # `/users/*` 端点（详见 core/identity/users_router.py 的模块说明）。
    #
    # ★ 全部 nullable：存量行没有这些值；且它们**都不是任何判定依据**
    #   （不像 token_version / locked_until 那样参与鉴权）。
    #   非空约束在这里只会让回填变得必须，换不来任何安全性。
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    # 通知偏好：{usageAlert: bool, ...}，见 merge_notification_prefs()
    notification_prefs: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # 关系
    # ★ P1-c：`shops` relationship 已随 Shop 删除；店铺归属改走
    #   account → store（见 core/identity/account_models.py）。
    subscription: Mapped[Optional["Subscription"]] = relationship("Subscription", back_populates="user", uselist=False, lazy="selectin")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, role={self.role})>"


# ====== 通知偏好：默认值真源 + 合并（★ 第 100 轮）======
#
# ★ 为什么这两个东西放在 models.py，而不是 `core/identity/users_router.py`：
#   `user_to_dict()`（core/identity/router.py）也要用到它 —— 若让它去 import
#   users_router，就会与 users_router（import user_to_dict）**循环 import**。
#   放在 ORM 模型旁边是唯一不需要任何一方反向依赖的位置。
#
# ★ 值用 camelCase：与前端表单字段一一对应，中间不设映射层
#   （少一层就少一个"两边拼错且不报错"的机会）。

DEFAULT_NOTIFICATION_PREFS: dict = {
    "usageAlert": True,
    "billingAlert": True,
    "weeklyReport": False,
    "systemUpdate": True,
    "taskComplete": True,
    "agentError": True,
}


def merge_notification_prefs(stored) -> dict:
    """
    把库里的偏好合并到默认值上，**保证返回的字典永远是完整的**。

    ★ 为什么要补齐、而不是直接返回 store 里那份：
      ① 本列是后加的，历史行是 NULL；
      ② 将来新增一个偏好项时，老行里没有那个键。
      两种情况都会让前端拿到**少字段**的对象 —— 表现为
      "这个开关点了没反应"（而不是报错），是最难查的那种失效。
    """
    merged = dict(DEFAULT_NOTIFICATION_PREFS)
    if isinstance(stored, dict):
        for k, v in stored.items():
            if k in merged and isinstance(v, bool):
                merged[k] = v
    return merged


# ====== 跨模块模型注册（非业务依赖）======
# User.subscription <-> Subscription.user 是 1:1 双向关系，两侧类必须同处
# 一个 Base.registry，否则 configure_mappers() 会报
#   InvalidRequestError: expression 'Subscription' failed to locate a name
# 这里只做**注册**（导入模块对象、不访问任何属性），因此即使
# modules.billing.models 正处于部分初始化状态也安全，不会循环 import。
import modules.billing.models as _billing_models  # noqa: E402,F401
