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
