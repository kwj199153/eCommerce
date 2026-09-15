"""
业务话术库（KnowledgeBase）持久化 ORM 模型

为 /api/v1/knowledge-base 提供 PostgreSQL 持久化。
数据源：DB 唯一权威（前端 store 每次操作调 API，不再有内存默认数据回灌）。

三张表：
1. `knowledge_bases` —— 知识库容器（顶层文件夹：通用库 / 店铺库 / 平台库）
2. `knowledge_faqs`  —— 结构化话术条目（智能客服 RAG 的一路检索源）
3. `knowledge_docs`  —— 文档素材（RAG 补充资料，正文供后续切片检索）

**三个刻意的设计取舍**：

① `is_default` 用显式布尔列，不用「id 等于某个字面量」判断。
   前端原来写的是 `kb.id !== 'kb-default'`，而 id 一旦加上店铺后缀
   （`kb-default-{shop_id}`，单主键表多店铺灌入必须加后缀，否则第二个店铺主键冲突）
   这类比较会全部失效且**静默**（不报错，只是按钮突然都出现了）。改成显式列后
   前端读 `kb.is_default`，与 id 编码方式解耦。

② `faq_count` / `doc_count` **不落库**，读取时实时统计。
   存冗余计数就得在「增删 FAQ / 导入 / 批量删 / 删库」每条路径上同步维护，
   漏一处数字就永远对不上（前端原来的 `refreshKbCounts()` 就是在打这个补丁）。
   计数是派生数据，读时 count 一次的成本远低于维护一致性。

③ 删知识库**级联删**其下 FAQ 与文档 —— 与 platform_rules 的
   「删文档不级联删规则」看似矛盾，其实边界不同：
   平台规则文档是**溯源附件**（规则本身是独立业务实体，没了附件照样有效）；
   而 kb_id 是话术条目的**唯一归属维度**，容器没了条目在任何视图里都不可达
   （前端 `currentItems` 按 kb_id 过滤）。留一堆查不到的孤儿行只会污染统计。
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, Boolean, JSON, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column

from core.database import Base


def _now() -> str:
    return datetime.utcnow().isoformat()


class KnowledgeBaseRecord(Base):
    """知识库容器表（/api/v1/knowledge-base 数据源）"""

    __tablename__ = "knowledge_bases"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_knowledge_bases_shop_id_stores_store",
        ),
    )

    # `kb-default-{shop_id}` / `kb-{ts}-{rand}-{shop_id}`
    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    # 租户隔离维度（空串 = 无租户上下文）
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)

    name: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    icon: Mapped[str] = mapped_column(String(16), default="📚")
    # shop / platform / custom
    type: Mapped[str] = mapped_column(String(16), default="custom")

    # 默认库：前端据此隐藏「删除」按钮、并在文档面板显示「通用」（见模块 docstring ①）
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


class KnowledgeFaqRecord(Base):
    """话术条目表（/api/v1/knowledge-base/faqs 数据源）"""

    __tablename__ = "knowledge_faqs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_knowledge_faqs_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    kb_id: Mapped[str] = mapped_column(String(160), default="", index=True)

    question: Mapped[str] = mapped_column(Text, default="")
    answer: Mapped[str] = mapped_column(Text, default="")
    # shipping / return / product / payment / account / policy / review / other
    category: Mapped[str] = mapped_column(String(32), default="other", index=True)

    keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    # high / medium / low
    priority: Mapped[str] = mapped_column(String(16), default="medium")
    # active / draft / archived
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)

    # 命中次数（智能客服回答命中时累加；当前只读展示）
    usage_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[str] = mapped_column(String(64), default=_now)
    updated_at: Mapped[str] = mapped_column(String(64), default=_now)


class KnowledgeDocRecord(Base):
    """话术库文档素材表（/api/v1/knowledge-base/docs 数据源）

    与 FAQ 分表：FAQ 是「一问一答」结构化条目，文档是「整篇素材」，
    字段差异大（filename/size/file_type vs question/answer/priority），
    合并会得到一半字段恒为 NULL 的宽表。
    """

    __tablename__ = "knowledge_docs"

    __table_args__ = (
        ForeignKeyConstraint(
            ["shop_id"],
            ["stores_store.id"],
            ondelete="RESTRICT",  # ★ 删店铺是低频高风险：宁可提示先清理，不连带删业务数据
            name="fk_knowledge_docs_shop_id_stores_store",
        ),
    )

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    shop_id: Mapped[str] = mapped_column(String(64), default="", index=True)
    kb_id: Mapped[str] = mapped_column(String(160), default="", index=True)

    filename: Mapped[str] = mapped_column(String(500), default="")
    # pdf / md / excel / txt / other
    file_type: Mapped[str] = mapped_column(String(16), default="other")
    size: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[str] = mapped_column(String(64), default=_now)
    description: Mapped[str] = mapped_column(Text, default="")

    # 文档正文（文本类文件上传时提取）；智能客服 RAG 切片检索的输入源。
    # 列表接口不返回（整篇动辄数千字符），需要时按 id 单独取。
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
