"""平台规则库的声明式查询元数据（第 218 轮 · P1）。

★ `key="rules"` 与侧边栏菜单 key（`key="rules"`，中文「平台规则库」）对齐。

★ `default_sort="effective_date"`（倒序）= 改前 service 的
  `order_by(PlatformRuleRecord.effective_date.desc())`，逐字不变 ——
  那条注释写明「与前端 `filteredItems` 的排序一致：生效日期倒序」。

★ **过滤维度不给值域**，与其 service docstring 的第 1 条取舍同源：
  「不校验 platform / category 枚举白名单 —— 它们是前端配置驱动的
  （`PLATFORMS` / `RULE_CATEGORIES` 定义在 `stores/platformRules.ts`）」。
  ★ 注意 `effective_date` 是 `String(32)` 列 ⇒ 排序是**字符串**比较。
    ISO-8601（`2026-09-22`）恰好单调所以现在正确；若将来写入
    `2026/09/22` 这类格式，排序会**静默错乱** —— 这是「换数据源第一个爆发」
    的点，与候选库的日期列同一族问题（记在案，本轮不动数据模型）。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.platform_rules.db_model import PlatformRuleRecord

#: 平台规则库的声明式元数据（唯一真源）。
RULE_SPEC = LibrarySpec(
    key="rules",
    label="平台规则库",
    model=PlatformRuleRecord,
    sort_fields={
        "effective_date": ("effective_date", "desc"),
        "created_at": ("created_at", "desc"),
        "updated_at": ("updated_at", "desc"),
        "title": ("title", "asc"),
    },
    default_sort="effective_date",
    filters={
        "platform": FilterSpec("platform"),
        "category": FilterSpec("category"),
        "status": FilterSpec("status"),
    },
)
