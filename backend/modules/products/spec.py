"""产品库（SKU 粒度）的声明式查询元数据。

★ 为什么产品库需要一个 spec（第 218 轮 · P0-2）
==============================================================================
改前产品库**有两份查询实现，且已经漂移**：

  | 落点 | 排序 | limit | total |
  |---|---|---|---|
  | REST `products/router.py::list_skus` | 无 | 不下推 | `len(items)` |
  | 工具 `library/tools.py::_rows_to_products` | 硬编码 `created_at, id` | **内存切片** | `len(rows)` |

本仓那条「同一能力一份实现」的门禁
（`tests/test_tool_catalog.py::test_one_capability_has_exactly_one_implementation`）
按 `(模块, 函数限定名)` 比对「**不同 Agent 手里同名工具**的底层实现」——
它**覆盖不到「REST 端点 vs 工具」**这种组合，所以这两份一直并存、没人拦。
第 218 轮把它们一起收到 `core/library_query` 内核上（`PRODUCT_SPEC` 是第二个登记项）。

★ 作用域承载列是 **SPU** 的 `shop_id`（SKU 通过 `spu_id` 归属 SPU）——
  与 REST 原实现 `scoped(..., SpuRecord, shop_id)` 的口径逐字一致。

★ `default_sort="created_at"`（**升序**）是**有意选的边**，不是随手填的默认值：
  REST 端点的既有行为就是 `order_by(SkuRecord.created_at, SkuRecord.id)`，
  改成 `updated_at` 会让「不传参」时的响应顺序**静默变样**（前端页面跟着变）。
  ★ 注意它与**前端 `sortBy` 的默认值（`updated_at`）不同** —— 那是**既存差异**，
    本轮**不"顺手统一"**：改它属于语义变更，要单独评估（对齐门禁的登记另议）。

★ `sales` → `daily_sales_avg` 的映射与前端 `stores/productLibrary.ts` 的
  `case 'sales': return b.daily_sales_avg - a.daily_sales_avg` 一致 ——
  对外契约名与前端 `sortBy` 同名，内部列名各自映射。
"""

from core.library_query import FilterSpec, LibrarySpec
from modules.products.db_model import SkuRecord, SpuRecord

#: 产品库的**声明式元数据**（唯一真源）—— REST 与 Agent 工具同走它。
PRODUCT_SPEC = LibrarySpec(
    key="products",
    label="产品库",
    model=SkuRecord,
    # SKU 通过 spu_id 归属 SPU ⇒ 作用域挂 SPU（与 REST 原口径逐字一致）
    scope_model=SpuRecord,
    joins=((SpuRecord, SkuRecord.spu_id == SpuRecord.id),),
    # 工具层要把 SPU 标题拼进 SKU 的展示名，所以一起 select 出来
    select_extra=(SpuRecord,),
    sort_fields={
        "created_at": ("created_at", "asc"),
        "updated_at": ("updated_at", "desc"),
        "price": ("price", "desc"),
        "sales": ("daily_sales_avg", "desc"),
        "rating": ("rating", "desc"),
        "roi": ("roi", "desc"),
        "review_count": ("review_count", "desc"),
    },
    default_sort="created_at",
    filters={
        # 值域暂不约束（`None` = 自由文本）：`spu_id` 是任意主键；
        # `listing_status` 的合法值散在写入侧，等 P1 逐库收值域时一并定真源。
        "spu_id": FilterSpec("spu_id"),
        "listing_status": FilterSpec("listing_status"),
    },
)
