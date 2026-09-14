"""
店铺群持久化 ORM 模型 (Phase 10 + PG 落库)

为 /api/v1/stores 提供 PostgreSQL 持久化。
设计：内存 dict `_store_db` 作为读缓存（利润引擎等同步代码读取），
此 ORM 表作为权威存储，所有写操作双写内存 + DB，启动时从 DB 回灌内存。

字段与 models/store.py 的 pydantic Store 对齐。
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
#   1. `stores/router.py: load_stores_into_memory()` —— 决定内存 dict 插入顺序
#   2. `stores/router.py: list_stores()` —— 显式排序（不依赖 dict 顺序，双重保险）
#   3. `secretary/shop_tools.py: _list_shops()` —— LLM 侧序号来源
SHOP_ORDER_BY = ("created_at", "id")


class StoreRecord(Base):
    """店铺持久化表（/api/v1/stores 数据源）"""
    __tablename__ = "stores_store"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # store_xxx
    # 租户标识（历史遗留：恒为 default_tenant）
    # 说明：数据隔离已由 owner_id（指向 users.id）承担，tenant_id 保留仅作兼容，
    #       真实「租户」语义（多用户共享一个组织）尚未启用，后续如需企业版再映射。
    tenant_id: Mapped[str] = mapped_column(String(64), default="default_tenant")
    # 店铺归属用户（打通用户→店铺归属，数据隔离最后一环）
    # nullable：存量店铺无主（回填脚本统一处理）；新建店铺从登录用户注入
    owner_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
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
