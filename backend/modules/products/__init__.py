"""商品主数据（SPU / SKU）门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.products import <name>`；
     `from modules.products.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 第 218 轮扩出口（1 个）：`PRODUCT_SPEC` —— 产品库的**声明式查询元数据**。
  改前 REST `list_skus` 与工具层 `_rows_to_products` **各写一份查询且已漂移**
  （REST 不排序不下推、工具层硬编码排序 + 内存切片），本仓那条「同一能力一份实现」
  的门禁只覆盖「不同 Agent 手里的同名工具」，覆盖不到 REST vs 工具
  ⇒ 两份一直并存。现在两者共用 `PRODUCT_SPEC`（详见 `spec.py` docstring）。

  4. 门面可以 re-export 子模块里的名字（下面两行都是）。但**代价要说清**：
     `import modules.products` 会**连带执行 `router.py`** —— 因为 `spu_to_dict`
     这个纯函数目前住在那里（`modules/candidates/router.py:218` 是它的唯一
     跨模块消费者，没有别的地方可去）。
     ⇒ 门面并不"轻量"：它会拉起 `APIRouter` 等 FastAPI 组件。
       这不是"装配 FastAPI 应用"（本文件没有 `include_router`），但确实有成本。
     ★ 这是**已知代价**，不是新契约。若将来要消除：把 `spu_to_dict` 移到
       `modules/products/serializers.py`，再由 `router.py` 从那里 import，
       门面就只依赖模型与纯函数了。
"""
from modules.products.db_model import SkuRecord, SpuRecord
from modules.products.router import spu_to_dict
from modules.products.spec import PRODUCT_SPEC

__all__ = ["SkuRecord", "SpuRecord", "PRODUCT_SPEC", "spu_to_dict"]
