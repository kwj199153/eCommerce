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

from sqlalchemy import String, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class ShopVoice(Base):
    """店铺客服音色表（/api/v1/voice-clone 数据源）"""
    __tablename__ = "shop_voice"

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
