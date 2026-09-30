"""业务话术库模块（知识库容器 / 话术条目 / 文档素材，持久化到 PG）

★ 门面契约（由 `tests/test_module_facades.py` 机械校验）：第 218 轮（P1）
  建 `__all__` —— 此前本包只有上面这行 docstring、没有跨模块消费者。
  资料库工具要读话术库之后第一次有了跨模块引用，按门禁要求补契约面。
"""

from modules.knowledge_base.service import count_faqs, list_faqs
from modules.knowledge_base.spec import FAQ_SPEC
# ★ 第 287 轮扩出口：两张表的 ORM 类。客服话术真源（`customer_service/faq_source.py`）
#   要查这两张表 —— 跨模块只许走门面（`tests/test_module_facades.py` 机械校验）。
from modules.knowledge_base.db_model import KnowledgeBaseRecord, KnowledgeFaqRecord

#: ★ 第 218 轮（P1b）扩出口：`FAQ_SPEC` —— 资料库工具用它生成排序 / 过滤维度说明。
__all__ = [
    "FAQ_SPEC", "count_faqs", "list_faqs",
    "KnowledgeBaseRecord", "KnowledgeFaqRecord",
]
