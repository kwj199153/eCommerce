"""
素材库持久化 ORM 模型

为 /api/v1/assets 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API）。

字段与 frontend/src/stores/assetLibrary.ts 的 AssetItem 对齐。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Text, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AssetRecord(Base):
    """营销素材表（/api/v1/assets 数据源）"""
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # asset-xxx
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="image")  # image / video
    category: Mapped[str] = mapped_column(String(32), default="other")  # white-bg / three-view / ...
    url: Mapped[str] = mapped_column(Text, nullable=False)
    videoUrl: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    thumbnail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    productId: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    productName: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    asin: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # aigc / upload / video-gen / manual
    width: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    groups: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class AssetGroupRecord(Base):
    """素材库分组表"""
    __tablename__ = "asset_groups"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # asset-group-xxx
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#1890ff")
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
