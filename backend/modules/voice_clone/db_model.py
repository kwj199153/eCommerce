"""语音克隆持久化 ORM 模型。

独立表 `shop_voice`：一个店铺一条记录（MVP：单店铺单音色）。
**不 ALTER 任何既有表** —— 这是「可插拔」的数据层要求。

字段说明：
- voice_id / target_model：CosyVoice 音色 ID 与创建时绑定的模型名。
  ★ 音色与模型死绑：合成时必须用同一个 target_model，跨模型不可复用 → 必须落库。
- status：pending / ready / failed；failed 时必须同时有 error_msg（禁止静默退回默认音色）。
- authorized_at / authorized_by / agreement_snapshot：授权三件套。
  ★ agreement_snapshot 存的是「用户勾选那一刻的前端文案原文」——
  日后前端改了措辞，也能证明当时授权的是哪一版文本。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Index, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ShopVoice(Base):
    """店铺客服音色表（/api/v1/voice-clone 数据源）"""
    __tablename__ = "shop_voice"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_shop_voice_shop_id_stores_store",
        ),
        # 业务约束：一个店铺一条音色记录（MVP 单店铺单音色）
        # ★ 原只写在手写迁移 a8c9d0e1f2b3 的裸 SQL 里，ORM 未声明 ⇒ squash 后会丢。
        Index("uq_shop_voice_shop", "shop_id", unique=True),

    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # voice-xxx
    # 归属店铺（多租户隔离）：store_xxx，绑定 stores_store.id。一个店铺一条。
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # --- 音色本体 ---
    voice_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # ★ 创建音色时指定的 target_model，合成时必须一致，不可跨模型复用
    target_model: Mapped[str] = mapped_column(String(64), default="")
    voice_name: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    # pending / ready / failed
    error_msg: Mapped[str] = mapped_column(Text, default="")

    # --- 音频样本 ---
    sample_url: Mapped[str] = mapped_column(Text, default="")      # /static/voice/xxx.wav
    sample_name: Mapped[str] = mapped_column(String(255), default="")
    sample_size: Mapped[int] = mapped_column(Integer, default=0)   # bytes
    sample_duration: Mapped[float] = mapped_column(Integer, default=0)  # 秒（前端测得，可空）

    # --- 授权留痕（三件套）---
    authorized_at: Mapped[str] = mapped_column(String(64), default="")
    authorized_by: Mapped[str] = mapped_column(String(36), default="")  # users.id
    # ★ 勾选那一刻的前端文案快照（原文，不改写）
    agreement_snapshot: Mapped[str] = mapped_column(Text, default="")

    # --- 试听偏好 ---
    preview_text: Mapped[str] = mapped_column(Text, default="")

    createdAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updatedAt: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'shop_voice.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.voice_clone.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
