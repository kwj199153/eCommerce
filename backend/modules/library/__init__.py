"""资料库**只读**工具门面包（第 205 轮；第 218 轮扩到 6 个库）。

★ 覆盖范围（第 218 轮 P1）：侧边栏「资料库」组的 **6 个库**全部可读 ——
  候选选品库 / 产品库 / 营销素材库 / 竞品监控池 / 业务话术库 / 平台规则库。
  在此之前只有前两个（产品库 / 选品库）。

★ 这个包解决的是什么问题
--------------------------------------------------------------------------
第 204 轮的原子工具盘点发现两组「**同端点多名**」：

    GET /api/v1/candidates   被选品分析师与店秘书各提议成 `list_candidates`
    GET /api/v1/skus         被选品分析师提议 `list_products`、
                             Listing 优化师提议 `list_skus`、店秘书提议 `list_products`

按「一个能力两个名字 ⇒ 模型在两处乱选、而测试只覆盖其中一条」这条既有判据
（同族：`authz-truth-source-consolidation` 的「同一判定两份实现」），
第 205 轮裁决：**一个能力只留一个工具名，该工具注册给多家 Agent 共用。**

⇒ 于是需要一个「**跨 Agent 共用**」的工具落点。它不能住在任何一家宿主里：
   `product_research` / `listing_generator` / `secretary` **都是 PLUGIN**，
   而 `test_module_layering.py` 禁止 PLUGIN 之间在 import 期互相 import
   ⇒ 谁也不能 import 谁的 `tools.py`。

⇒ 本包是 **SHARED 层**（`MODULE_LAYERS["library"] = SHARED`）：
   它只顶层依赖 `products` / `candidates`（两个都是 SHARED）⇒ 方向合法，
   而三个 PLUGIN 顶层 import 本包（PLUGIN → SHARED）也合法。

★ 门面契约（与 `test_module_facades.py` 同族）
--------------------------------------------------------------------------
跨模块引用**只允许** `from modules.library import build_library_tools`；
`__all__` 就是本包允许被其它 `modules/*` 取用的名字全集。
"""

from modules.library.tools import (
    LIBRARY_TOOL_NAMES,
    build_library_tools,
)

__all__ = [
    "LIBRARY_TOOL_NAMES",
    "build_library_tools",
]
