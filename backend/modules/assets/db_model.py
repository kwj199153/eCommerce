"""
素材库持久化 ORM 模型

为 /api/v1/assets 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API）。

字段与 frontend/src/stores/assetLibrary.ts 的 AssetItem 对齐。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Boolean, Text, Integer, JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class AssetRecord(Base):
    """营销素材表（/api/v1/assets 数据源）"""
    __tablename__ = "assets"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_assets_shop_id_stores_store",
        ),
    )

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
    # 归属店铺（多租户隔离）：store_xxx，绑定 stores_store.id
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True, server_default='')
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class AssetGroupRecord(Base):
    """素材库分组表"""
    __tablename__ = "asset_groups"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_asset_groups_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # asset-group-xxx
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    color: Mapped[str] = mapped_column(String(16), default="#1890ff")
    # 归属店铺（多租户隔离）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True, server_default='')
    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'assets.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.assets.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
