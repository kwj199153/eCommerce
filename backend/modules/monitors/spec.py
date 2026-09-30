"""竞品监控池的声明式查询元数据（第 218 轮 · P1）。

★ `key="competitors"` 而不是 `"monitors"`：与**侧边栏菜单 key**
  （`Sidebar/KnowledgeBase.vue` 的 `key="competitors"`，中文「竞品监控池」）
  对齐 —— 跨端对齐门禁按同一张表核对。
  ★ 但**模块名仍是 `monitors`**：`key` 是「对用户的库标识」，
    模块名是「代码里的领域名」，两者不必同名；这个差异是**有意保留**的，
    不是漏改（改模块名会牵动分层表、门禁、门面包等一大片）。
  ★ 注意 `stores/competitorPool.ts`（内存里的「竞品池」编辑器）**不是**本库 ——
    那条路没有后端，是宿主记录上 `competitor_asins` JSON 列的编辑视图。

★ `default_sort="created_at"`（倒序）= 改前 REST 的 `order_by(created_at.desc())`，
  逐字不变（前端文案「新增的排在前面」）。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.monitors.db_model import MonitorRecord

#: 竞品监控池的声明式元数据（唯一真源）。
MONITOR_SPEC = LibrarySpec(
    key="competitors",
    label="竞品监控池",
    model=MonitorRecord,
    sort_fields={
        "created_at": ("created_at", "desc"),
        "updated_at": ("updated_at", "desc"),
        # 与前端 `stores/monitorPool.ts` 的 `a.asin.localeCompare(b.asin)` 同向
        "asin": ("asin", "asc"),
        "price": ("latest_price", "desc"),
        "rating": ("rating", "desc"),
        "review_count": ("review_count", "desc"),
        "sales": ("est_monthly_sales", "desc"),
        # BSR 是**排名**：数字越小越好 ⇒ 升序（与「评分/销量越高越好」方向相反）
        "bsr": ("latest_bsr", "asc"),
    },
    default_sort="created_at",
    filters={
        "stock_status": FilterSpec("stock_status"),
        "marketplace": FilterSpec("marketplace"),
    },
)
