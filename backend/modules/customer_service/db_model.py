"""
智能客服工单持久化 ORM 模型（第 143 轮 A4 新增）

为什么要有这张表
----------------
`CustomerServiceService.create_ticket` 此前**只在内存里造一个 TicketInfo 就返回**：

    · 工单号 `TKT-YYYYMMDD-NNNNN` 是即时随机生成的；
    · 没有任何持久化 —— 响应写着「工单 XXX 创建成功！」，刷新一下它就不存在了；
    · `create_ticket_endpoint` 连 `X-Shop-ID` 都不取 ⇒ 即便有表也无从落租户维度。

这是「伪成功」的典型形态：`success=True` + 可读文案 + 一个**不可追溯**的 ID。
表建起来之后，工单号才第一次指向一条真实记录。

设计取舍
--------
1. **`shop_id` 带 `stores_store` 外键，`ondelete=RESTRICT`** —— 与 monitors /
   candidates 等表一致：删店铺是低频高风险动作，宁可提示先清理，不连带删业务数据。
   （外键名沿用 `fk_<table>_shop_id_stores_store` 命名，`test_schema_parity.py`
   的不变量按这个名字查 `pg_constraint`。）

2. **时间字段用 `String(64)` 存 ISO 串**，与仓里既有业务表（monitors / candidates /
   aigc_jobs）一致。换 `DateTime` 会引入「时区/naive-aware」议题，而本表的用途
   是「原样吐给前端」，不需要按时间做 SQL 计算。

3. **`attachments` / `tags` / `auto_replies` 用 JSON 列整体存取** ——
   访问模式是「取整条工单」，没有「按 tags 的某一项查」的需求。

4. **`id` 就是那串 `TKT-...`**（不做自增代理键）：它对用户可见、需要可被直接引用，
   再套一层 UUID 只会让客服报单号时多一次翻译。
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, String, Text, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class TicketRecord(Base):
    """客服工单表（cs_tickets）—— `/api/v1/customer-service/ticket/create` 的落点。"""
    __tablename__ = "cs_tickets"
    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_cs_tickets_shop_id_stores_store",
        ),
    )

    # TKT-YYYYMMDD-NNNNN（Agent 生成）—— 冲突时由 service 追加 `-xxxx` 后缀重试
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    # 租户隔离维度：由 router 的 strict 守卫注入（**不是**请求体里的值）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # 售后/物流/质量/投诉/咨询/支付/订单/general
    category: Mapped[str] = mapped_column(String(32), default="general")
    # low/medium/high/urgent
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    # open/in_progress/resolved/closed
    status: Mapped[str] = mapped_column(String(16), default="open")

    customer_id: Mapped[str] = mapped_column(String(64), default="")
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    sla_deadline: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # 派生物：创建时的自动回复建议与 SLA 承诺（原样存档，便于事后核对当时承诺了什么）
    estimated_response_time: Mapped[str] = mapped_column(String(16), default="")
    auto_replies: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    attachments: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)


# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时要在
# 当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时报错**，而是在某一次
# flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'cs_tickets.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身**（看起来像「外键写错了」），极难定位。
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
