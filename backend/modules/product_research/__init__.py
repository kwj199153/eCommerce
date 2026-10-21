"""选品研究（市场洞察）模块门面。

★ 第 387 轮之前本文件是**空的** —— 因为本包当时没有跨模块消费者
  （门禁的另一条：只在真有跨模块引用时才要求契约面；给 19 个包都硬加
  `__all__`，在没有消费者时只是装饰）。

第 387 轮第一次有了跨模块消费：`modules/onboarding` 的「加载示例数据」要给
点名店铺补灌市场洞察快照（`only_for_shop_ids`）。按门面契约，跨模块取名字
必须走门面 ⇒ 这里补上契约面。

★ 它 import 期不产生 IO（只定义一个函数引用）。消费方（onboarding）在**函数内**
  延迟 import：本包是 PLUGIN，而 onboarding 也是 PLUGIN，顶层互相 import 会踩
  `test_module_layering.py` 的「PLUGIN → PLUGIN」红线。
"""

from modules.product_research.seed import seed_market_snapshots_if_empty

__all__ = ["seed_market_snapshots_if_empty"]
