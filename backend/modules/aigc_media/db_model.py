"""AIGC 长任务（异步作业）持久化模型。

背景：AIGC 出图原本是**同步阻塞**在 HTTP 请求里的（``/aigc/asset/generate``）。
实测代价（2026-09-15 复核代码常量得出）：

- 单张出图 15-25s，``image_client.MAX_CONCURRENCY = 2``（3 并发会被服务端 429），
  单次最多 ``asset_gen.MAX_TOTAL = 8`` 张 ⇒ 最坏 ``8/2 × 180s = 720s``
  （``image_client.wait_for_images`` 的超时是 180s/张）。
- 而前端 axios 超时是 **300s**（``aigcMedia.ts`` 里为这条接口单独放宽过）。
  ⇒ **720 > 300**：极端情况下用户看到「请求超时」，但后端仍在继续出图、
  DashScope 已经按张计了费（≈¥0.14/张）—— **钱花了，结果丢了**。

## 为什么不直接用 Celery 的 result backend 当状态源

``core/redis.py`` 里 ``result_expires = 3600`` —— 结果**只保留 1 小时**。
但出图产物是落盘的 ``/static`` **长期**链接；任务记录若 1 小时后蒸发，
用户刷新页面就再也查不到自己的图（钱已经花了）。

⇒ 任务状态必须落 DB。**Celery 只负责「执行」，不负责「记录」**：
本表是任务状态的唯一权威源，``GET /aigc/jobs/{id}`` 只读本表，不读 result backend。

## 状态机

``pending → running → succeeded | failed``

- 终态不可回退（worker 重试/迟到回调可能乱序写，见 :func:`is_terminal`）
- ``pending`` 只表示「已落库、待投递」；投递失败会被显式改写成 ``failed``，
  **绝不允许任务永远停在 pending**（那是最难排查的一种故障：
  用户看到「排队中」转圈，而其实队列里根本没有这个任务）。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, JSON, String, Text, text, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


# ====== 状态常量（前后端共用口径，勿各处硬编码字符串）======

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"

#: 未结束的状态（用于「进行中任务去重」的部分唯一索引）
INFLIGHT_STATUSES: tuple[str, ...] = (STATUS_PENDING, STATUS_RUNNING)
#: 终态（已结束，不会再变）
TERMINAL_STATUSES: tuple[str, ...] = (STATUS_SUCCEEDED, STATUS_FAILED)

#: 支持的任务类型 → 中文名（前端直接渲染，避免前端再维护一份映射）
KIND_LABELS: dict[str, str] = {
    "asset_generate": "静态素材批量出图",
    "image_generate": "AI 生成产品图",
}


def is_terminal(status: str) -> bool:
    """终态判断 —— 终态记录不允许再被 worker 覆写。"""
    return status in TERMINAL_STATUSES


class AIGCJobRecord(Base):
    """AIGC 异步任务表（``/api/v1/aigc/jobs`` 数据源）"""

    __tablename__ = "aigc_jobs"
    __table_args__ = (
        # ★ 进行中任务去重：同一用户 + 同一 dedupe_key 只允许存在**一条未结束**的任务。
        #
        # 为什么必须是 DB 约束而不是「先查再插」：
        #   出图是要花钱的（≈¥0.14/张 × 最多 8 张）。用户连点两次「开始生成素材」，
        #   两个请求并发走到「查无进行中任务 → 插入」之间会**双双通过检查**，
        #   结果就是两份任务、双倍计费。这与 P1-4 支付链路里
        #   「连点两次扣两次钱」是同一类缺陷，解法也相同：把唯一性下沉到 DB。
        #
        # 只对 inflight 状态生效（部分唯一索引）：
        #   终态任务不参与去重，否则用户第二次生成同样的素材会被历史记录永久挡住。
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_aigc_jobs_shop_id_stores_store",
        ),
        Index(
            "uq_aigc_jobs_inflight",
            "user_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        # 任务列表按「最近创建优先」翻页
        Index("ix_aigc_jobs_user_created", "user_id", "created_at"),
    )

    #: job_<hex12>，对前端完全可见，因此**不可猜**（不要用自增序号）
    id: Mapped[str] = mapped_column(String(40), primary_key=True)

    #: 任务类型，取值见 KIND_LABELS
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)

    #: pending / running / succeeded / failed
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=STATUS_PENDING, index=True
    , server_default='pending')

    # ====== 归属（授权用，不只用于统计）======
    # ★ 按 P0-1 教训：任何「按 ID 取单条」的新端点都必须按归属过滤，
    #   否则拿到 job_id 的人就能读到别人店铺的素材链接（BOLA/IDOR）。
    user_id: Mapped[str] = mapped_column(String(36), default="", index=True, server_default='')
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True, server_default='')

    #: 发起请求的 request_id —— 让「一次点击」在 API 日志与 worker 日志里能串起来。
    #: ★ ContextVar 跨进程读不到，必须在入队时**显式带上**（见 observability/context.py 的注意事项）。
    request_id: Mapped[str] = mapped_column(String(64), default="", server_default='')

    #: 去重指纹（由 kind + payload 稳定序列化得出，见 job_service.build_dedupe_key）
    dedupe_key: Mapped[str] = mapped_column(String(128), default="", index=True, server_default='')

    #: 任务的完整入参。★ 任务函数**只收 job_id**，参数从本列读 ——
    #: 原因：图生图的 source_image 是 base64 data URI，可达数 MB；
    #: 若塞进 broker 消息（Redis）会白占一份内存，且重试时要在消息里重复传输。
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    #: 成功时的业务结果（原样给前端，与同步端点的 response 结构一致）
    result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    #: 失败原因（人可读）。**禁止静默失败**：宁可显式报错也不要留空。
    error: Mapped[str] = mapped_column(Text, default="", server_default='')

    #: Celery 侧任务 ID（排查时用于在 worker 日志/Flower 里定位）
    celery_task_id: Mapped[str] = mapped_column(String(64), default="", server_default='')

    #: 成功产出的素材张数（列表页展示用，省得把 result 整个拉出来）
    assets_count: Mapped[int] = mapped_column(Integer, default=0, server_default='0')

    #: 重试次数（Celery 侧 retries，落库便于判断「一直失败」是不是可恢复错误）
    retries: Mapped[int] = mapped_column(Integer, default=0, server_default='0')

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
