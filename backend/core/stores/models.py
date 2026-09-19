"""
店铺群持久化 ORM 模型 —— **平台内核实体**（第 140 轮「实体归位」后落点）

==============================================================================
★ 为什么住在 `core/stores/` 而不是 `modules/stores/`
==============================================================================
判据不是我定的，是**本项目自己写下的那一条**（见 `core/identity/models.py` 顶部）：

    一个模块的模型被 2 个以上别的模块 import ⇒ 它是基础域，不是业务域。

拿同一把尺子量 `StoreRecord`，实测入度 = **7**（全仓最高；次高的 `products` 才 2）：

    在顶层 import 它的消费方：assets / candidates / knowledge_base /
                              monitors / platform_rules / products / secretary

当初就是这条判据把 `User` 从 `modules/user_subscription/` 搬进
`core/identity/` 的。这次只是把它用在同一类事实上 —— 一个住在业务目录里、
却被 7 个模块伸手去取的内核实体。

==============================================================================
★ 归位消掉了什么：四处「位置错位」的补丁，全部可枚举
==============================================================================
  ① `core/tenant/middleware.py`   —— 函数内 import，注释写「避免循环依赖」
  ② `core/auth/accounts_router.py` —— 函数内 import，`# noqa: PLC0415`
  ③ `modules/*/seed.py` × 6        —— 顶层抓内核实体，但只为取一个 ID
  ④ 本文件末尾的 `import core.identity.account_models` —— 注册外键目标表

  ⇒ ①② 是因为「内核层要伸手进业务目录」才被迫加的**函数边界**。
     归位后是 core → core，两处都提升为顶层 import，补丁与注释一并消失。
     ③ 与位置无关（数据种子本来就该写业务数据），保留。
     ④ 与位置无关（是 metadata 注册义务），保留。

==============================================================================
★ 数据事实：搬迁前后**可观测行为完全不变**（均已实测）
==============================================================================
  · `__tablename__ = "stores_store"` —— **表名不动** ⇒ Alembic autogenerate 零 diff
  · 本类的 `relationship()` 调用数 = **0** ⇒ 不牵动 `Base.registry` 的 1:1 地雷
    （第 135 轮搬 models 跨界时崩的正是这一条；这次不适用）
  · HTTP 面 `modules/stores/router.py` **原地不动** ⇒ `/api/v1/stores` 契约不变
  · `core.stores.models` 的 import 期可达集 = {core.database,
    core.identity.account_models} ⇒ **无环**，故上面①②可以提升为顶层

为 `/api/v1/stores` 提供 PostgreSQL 持久化。
设计：内存 dict `_store_db`（在 `modules/stores/router.py`）作为读缓存
（利润引擎等同步代码读取），此 ORM 表作为权威存储，所有写操作双写内存 + DB，
启动时从 DB 回灌内存。

字段与 `models/store.py` 的 pydantic `Store` 对齐。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

# 复用 core.database 的 Base（与 engine / async_session_factory 同源）
from core.database import Base


# ★★ 店铺「序号」排序真源（唯一）—— 全项目禁止各自写 order_by
#
# 为什么必须集中：老板说「切到第 2 个店铺」时，**序号由两个不同链路各自数出来的**：
#   - LLM 工具链路：`secretary/shop_tools._list_shops()` 查 PG
#   - 界面展示链路：`GET /api/v1/stores` → `list(_store_db.values())`（内存 dict 顺序）
# 两边顺序不一致 ⇒ AI 按 A 顺序数、界面按 B 顺序显示 ⇒ **切错店**（且不报错，静默错）。
#
# 排序键选 (created_at, id)：
#   - created_at：与用户「添加顺序」直觉一致
#   - id：created_at 相同（同批 seed）时的决定性 tie-breaker，保证全序、稳定
#
# 消费点（改这里必须同步核对）：
#   1. `modules/stores/router.py: load_stores_into_memory()` —— 决定内存 dict 插入顺序
#   2. `modules/stores/router.py: list_stores()` —— 显式排序（不依赖 dict 顺序，双重保险）
#   3. `modules/secretary/shop_tools.py: _list_shops()` —— LLM 侧序号来源
#
# ★ 第 140 轮：本常量随 `StoreRecord` 一并搬到 `core/stores/`。
#   它与模型同住一个文件不是偶然 —— 「序号口径」必须与「序号所依据的行」同源。
#   拆开放两处，正是当初「切错店」那个 bug 的形态。
SHOP_ORDER_BY = ("created_at", "id")


class StoreRecord(Base):
    """店铺持久化表（/api/v1/stores 数据源）"""
    __tablename__ = "stores_store"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # store_xxx
    # 租户标识（历史遗留：恒为 default_tenant）
    # 说明：数据隔离已由 owner_id（指向 users.id）承担，tenant_id 保留仅作兼容，
    #       真实「租户」语义（多用户共享一个组织）尚未启用，后续如需企业版再映射。
    #
    # ★★ P1-c（2026-09-16）更新：真实「租户」语义**已经启用** —— 落点是下面的
    #    `account_id`，不是这一列。tenant_id 现在只剩「历史兼容」这一个职责，
    #    不参与任何判定。新代码不要再读它。
    tenant_id: Mapped[str] = mapped_column(String(64), default="default_tenant")
    # 店铺归属用户（打通用户→店铺归属，数据隔离最后一环）
    # nullable：存量店铺无主（回填脚本统一处理）；新建店铺从登录用户注入
    #
    # ★★ P1-c：归属判定**已改看 account_id**（见 core/tenant/middleware.py）。
    #    本列保留为「创建者」这一事实记录（审计/展示用），
    #    **不再**是访问控制的依据 —— 否则团队共享永远做不成。
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey(
            "users.id", ondelete="SET NULL", name="fk_stores_store_owner_id_users"
        ), nullable=True, index=True
    )

    # ★★★ P1-c（2026-09-16）：账户归属 —— 「正式建 account → store 层级」的落点。
    #
    #   为什么不直接用 owner_id 做归属：owner_id 是**一店一人**的模型，
    #   团队共享（同一家店两个人都要能进）根本表达不出来，只能靠
    #   「把 owner 改成另一个人」这种破坏性手段。
    #   account_id 把「店铺」与「账户」解耦：多人通过 account_members
    #   共享同一账户名下的全部店铺。
    #
    #   nullable 的理由：迁移期间先加列 → 回填 → 才可能收紧为 NOT NULL。
    #   回填由迁移 d1e2f3a4b5c6 完成（为每个有店铺的 owner 建个人账户）。
    #   ⚠️ 归属校验带 owner_id 兜底分支（account_id 为空时回退），
    #      但那条分支是**过渡期**的，回填完整性由
    #      tests/test_account_store_hierarchy.py 的用例锁定。
    account_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey(
            "accounts.id", ondelete="SET NULL", name="fk_stores_store_account_id_accounts"
        ), nullable=True, index=True
    )

    # ★★★ P1-a 的加密终于接上真实路径（P1-c 收拢的附带收益）。
    #
    #   收拢前的错位（实测）：
    #     - 唯一存平台凭证的地方是**账户侧** `shops.api_credentials`
    #       —— 而 `POST /api/v1/shops/{id}/connect` 生产 0 调用点；
    #     - 业务侧（前端真正在用的）`POST /api/v1/stores/{id}/connect`
    #       收下 `credentials` 后**直接丢弃**，只把 has_credentials 置 True。
    #   ⇒ P1-a 那一轮辛苦加密的通道，挂在一个没人用的实体上；
    #     而真实路径收下凭据后扔掉。
    #
    #   现在本列成为平台凭证的**唯一**存放处，读写一律走
    #   `core.security.credentials`（Fernet 密文，`enc:v1:` 前缀）。
    #   直接给本列赋明文 = 重新引入 P1-a 已修的缺陷。
    api_credentials: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Fernet 密文（enc:v1: 前缀），禁止明文"
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    marketplace_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    region_code: Mapped[str] = mapped_column(String(16), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")
    fee_template_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    discount_template_id: Mapped[str] = mapped_column(String(32), default="default")

    # 状态（字符串存储，与 StoreStatus/ConnectionStatus/SyncStatus 枚举值一致）
    status: Mapped[str] = mapped_column(String(16), default="active")
    connection_status: Mapped[str] = mapped_column(String(16), default="disconnected")
    sync_status: Mapped[str] = mapped_column(String(16), default="idle")
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    has_credentials: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 冗余列（避免超长 Text 主键问题之外的扩展，预留）
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# ★★★ 为什么声明了字符串外键还不够，必须显式 import 目标模块（实测，别删）：
#
#   `ForeignKey("accounts.id")` 是**字符串**目标，SQLAlchemy 在解析时会在
#   当前 `MetaData` 里按表名查找 `accounts`。本模块若只是"声明"了它而
#   `accounts` 表从未被任何模块 import 过，则**任何一次 flush** 都会抛：
#
#       NoReferencedTableError: Foreign key associated with column
#       'stores_store.account_id' could not find table 'accounts'
#
#   注意它抛在 flush 时（SQLAlchemy 要对表做拓扑排序 `sorted_tables`），
#   而不是 import 时；而且报错指向**外键本身**，看起来像"外键写错了"。
#
#   实测影响面：P1-b/P1-c 加上这一列后，**整个 pytest 套件在 setup 阶段全 ERROR**
#   （100% 失败），因为测试进程不走 `main.py` 的 lifespan ⇒ `init_db()` 没跑
#   ⇒ `register_all_models()` 没被调用 ⇒ 没有任何地方 import 过 account_models。
#   生产同样有隐患：Celery worker / 运维脚本若直接用 ORM 而不走 lifespan，
#   一旦 flush 到 StoreRecord 就会崩。
#
#   ⇒ 修法是让**声明外键的模块自己负责把目标表带进来**（自洽），
#     而不是依赖"某个入口恰好先 import 了它"。
#     ★ 第 140 轮：本文件已在 `core/` 下，这一句现在是 **core → core**（同层内核），
#       方向天然正确，不再涉及「反向依赖」的讨论。
#       同一模式见 `core/identity/models.py` 末尾对 `modules.billing.models` 的注册。
#
#   ★★ 第 140 轮实证：这条"意外依赖承重"缺陷，别把它改回去 ★★
#
#   本文件搬进 `core/stores/` 之前，消费者写的是
#       `from modules.stores.db_model import StoreRecord`
#   —— 这会**先执行父包** `modules/stores/__init__.py`，而它 import 了 router，
#   router 又 import `core.auth.dependencies`，后者 import `core.identity.models`
#   ⇒ `users` 表其实是被那条**与本模块无关**的链路顺带注册的。
#
#   归位后消费者改成 `from core.stores import StoreRecord`，父包只剩本文件，
#   那条链路整体断掉 ⇒ 立即暴露：本模块声明的**两个**外键目标里，
#   `accounts` 有人注册，`users` **没人注册**。
#
#   实测症状（很能说明问题，值得记住）：
#     · 在**全量** pytest 里看不出来 —— collection 期别的测试模块先 import 了
#       `core.identity.models`，把 `users` 顺手带进来了；
#     · 只有**定向**跑一个不碰 DB 的用例文件时才炸，且在
#       `tests/conftest.py::_synthetic_test_shops`（会话级 autouse 夹具）的
#       setup 阶段 ERROR，报 `NoReferencedTableError`，看起来像"外键写错了"。
#   ⇒ 教训：`import X` 能跑 ≠ "X 的依赖都被声明了"，可能只是某条无关链路
#     顺手带来的。**自洽**必须靠显式声明，不能靠调用顺序的巧合。
#
#   ⇒ 两个外键目标表都必须在**本模块**里显式注册（自洽，与调用顺序无关）：
#       · `stores_store.account_id -> accounts.id`   （account_models）
#       · `stores_store.owner_id   -> users.id`      （identity.models）
#
#   ★ 配套回归：`tests/test_schema_parity.py` 里三条用例守着它（★ 第 140 轮校正过的名字，
#     原文写的是两个**不存在**的用例名，属"注释指向不存在的门禁"）：
#       `test_every_orm_foreign_key_target_is_registered`（register_all_models 口径）
#       `test_every_model_module_is_self_sufficient_for_fk_targets`（import 期闭包口径）
#       `test_self_sufficiency_holds_in_a_fresh_interpreter`（**真实子进程单独 import** 口径）
#
#   ★★ 第 140 轮反向注入实测（别把结论反过来用）★★
#     摘掉**本行**（users 注册）后门禁**不会红** —— 因为
#     `core.identity.account_models` 末尾也 `import core.identity.models`，
#     users 经 `core.stores.models -> account_models -> models` 这条**第二链路**
#     仍在 import 期闭包内。要复现原事故必须**同时**摘掉两条
#     （见 `.workbuddy/probes/r683_reverse_inject.py` 的 R7，双文件注入）。
#     ⇒ 两个推论，都很重要：
#       ① 本行是**有意保留的冗余**。不能改成"靠 account_models 的尾 import 承重"
#          —— 那正是本文件上面批判的"意外依赖承重"，只是把运气换了个来源。
#       ② 判据**容忍冗余链路**是正确的性质，不是漏洞。别为了"能被单点打穿"
#          把它改成"必须显式写在本模块里"的按行判定 —— 那会把判据从
#          "事实是否成立"降级成"某一行在不在"，从此任何等价重构都会假报警。
import core.identity.account_models  # noqa: E402,F401  注册 accounts / account_members
import core.identity.models  # noqa: E402,F401  注册 users（stores_store.owner_id -> users.id）
