"""
平台规则库（PlatformRules）持久化 ORM 模型

为 /api/v1/platform-rules 提供 PostgreSQL 持久化。
设计：DB 是唯一权威数据源（前端 store 每次操作调 API，不再有内存缓存回灌）。

两张表：
1. `platform_rules`      —— 规则本体（平台/分类/标题/正文/生效期/状态/标签/来源）
2. `platform_rule_docs`  —— 规则来源文档素材（RAG 补充资料，含正文供 AI 拆分）

**为什么 `status` 存原值、不存算好的状态**：
前端的 `getResolvedStatus()` 按「生效日期 vs 今天」实时解析
（auto → active / upcoming / expired），这是**展示期计算**而非数据。
若后端存解析结果，跨天后旧数据就与当天不符，且需要定时刷库。
所以后端只持久化用户设定的原值（auto/active/upcoming/expired），解析仍在前端做。

**为什么文档正文用 Text 整篇存、不切块入库**：
AI 拆分是「取整篇文档 → 让 LLM 提取结构化规则」的**整体读取**模式，
没有「按段落检索」的需求（真正的检索走 customer_service 的 RAG 库里，是另一条链路）。
故整篇存 Text —— 与 monitors 的 7 维时序用 JSON 列同理：贴合真实访问模式。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


class PlatformRuleRecord(Base):
    """平台规则表（/api/v1/platform-rules 数据源）"""
    __tablename__ = "platform_rules"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_platform_rules_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    # 租户隔离维度（空串 = 无租户上下文）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    # amazon / shopee / tiktok / temu / lazada
    platform: Mapped[str] = mapped_column(String(32), default="amazon", index=True)
    # listing / policy / compliance / payment / logistics / review / ad
    category: Mapped[str] = mapped_column(String(32), default="policy", index=True)

    title: Mapped[str] = mapped_column(String(500), default="")
    content: Mapped[str] = mapped_column(Text, default="")

    # 生效日期 / 失效日期（YYYY-MM-DD；失效为空 = 永不过期）
    effective_date: Mapped[str] = mapped_column(String(32), default="")
    expiry_date: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # auto = 前端按生效日期实时解析；active/upcoming/expired = 用户手动覆盖
    status: Mapped[str] = mapped_column(String(16), default="auto")

    tags: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(Text, default="")
    source_doc_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    created_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    updated_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())


class PlatformRuleDocRecord(Base):
    """平台规则文档素材表（/api/v1/platform-rule-docs 数据源）

    与规则表**分开建表**，而不是加一个 `is_doc` 标志合并：
    两者字段差异大（文档有 filename/size/file_type，规则有 category/status/effective_date），
    合并会得到一张一半字段恒为 NULL 的宽表，且每个查询都要带 `WHERE is_doc = 0` 兜底。
    """

    __tablename__ = "platform_rule_docs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_platform_rule_docs_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    platform: Mapped[str] = mapped_column(String(32), default="amazon", index=True)
    filename: Mapped[str] = mapped_column(String(500), default="")
    # pdf / md / excel / txt / other
    file_type: Mapped[str] = mapped_column(String(16), default="other")
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[str] = mapped_column(String(64), default=lambda: datetime.utcnow().isoformat())
    description: Mapped[str] = mapped_column(String(500), default="")

    # 文档正文（上传时提取 / 用户粘贴）；AI 拆分的输入源，为空时 ai-split 明确报错而非编造
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

# ====== 外键目标表的 metadata 注册（★ 必须留在文件末尾）======
#
# 本模块的 `shop_id` 是**字符串**外键，指向 `stores_store.id`。SQLAlchemy 解析时
# 要在当前 `MetaData` 里按表名找到 `stores_store`；缺了**不在 import 时**报错，
# 而是在某一次 flush 的拓扑排序里抛：
#
#     NoReferencedTableError: Foreign key associated with column
#     'platform_rules.shop_id' could not find table 'stores_store'
#
# 报错还指向**外键本身** —— 看起来像「外键写错了」，极难定位。
#
# ★ 第 140 轮实测：单独 `import modules.platform_rules.db_model` 时，`Base.metadata.sorted_tables`
#   直接失败；同类共 8 个 db_model。
#   （此前没人发现，是因为测试从来都是"全量导入"，目标表当然都在。）
#
# ⇒ 由**声明方自己**把目标表带进来（自洽），不依赖「某个入口恰好先 import 了它」。
#   同一模式见 `core/stores/models.py`、`modules/amazon_sp/db_model.py` 末尾。
#   配套回归：`tests/test_schema_parity.py::test_every_model_module_is_self_sufficient_for_fk_targets`
from core.stores import StoreRecord  # noqa: E402,F401  注册 stores_store
