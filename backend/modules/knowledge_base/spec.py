"""业务话术库的声明式查询元数据（第 218 轮 · P1）。

★ `key="faq"` 与侧边栏菜单 key（`key="faq"`，中文「业务话术库」）对齐。

★ `default_sort="created_at"`（**升序**）= 改前 service 的
  `order_by(KnowledgeFaqRecord.created_at.asc())`，逐字不变。

★ **过滤维度不给值域**，这与其 service docstring 的第 1 条取舍**同源**：
  「不校验 category / priority / status 枚举白名单 —— 它们是前端配置驱动的
  （`FAQ_CATEGORIES` 定义在 `stores/knowledge.ts`），后端再硬编码一份，
  前端加一个分类就要改两处、还会『前端能选、后端拒收』」。
  给值域会让 `resolve_filters` 把「前端新加的分类」判成非法 ⇒ 正是那条取舍要避免的。
  ⇒ 这里保持自由文本（`FilterSpec(attr)` 不带 values），**但排序维度仍是白名单**
    （排序值直接进 `order_by`，那是注入面，必须收）。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.knowledge_base.db_model import KnowledgeFaqRecord

#: 业务话术库的声明式元数据（唯一真源）。
FAQ_SPEC = LibrarySpec(
    key="faq",
    label="业务话术库",
    model=KnowledgeFaqRecord,
    sort_fields={
        "created_at": ("created_at", "asc"),
        "updated_at": ("updated_at", "desc"),
        "usage_count": ("usage_count", "desc"),
        "question": ("question", "asc"),
    },
    default_sort="created_at",
    filters={
        "kb_id": FilterSpec("kb_id"),
        "category": FilterSpec("category"),
        "priority": FilterSpec("priority"),
        "status": FilterSpec("status"),
    },
)
