"""平台规则库模块（/api/v1/platform-rules）

★ 门面契约（由 `tests/test_module_facades.py` 机械校验）：第 218 轮（P1）
  建 `__all__` —— 此前本包只有上面这行 docstring、没有跨模块消费者。
  资料库工具要读平台规则库之后第一次有了跨模块引用，按门禁要求补契约面。
"""

from modules.platform_rules.service import count_rules, list_rules
from modules.platform_rules.spec import RULE_SPEC

#: ★ 第 218 轮（P1b）扩出口：`RULE_SPEC` —— 资料库工具用它生成排序 / 过滤维度说明。
#: ★ 第 387 轮：注册即播种 / 「加载示例数据」按**点名店铺**灌数（`only_for_shop_ids`）。
#: 消费方是 `modules/onboarding`，它在**函数内**延迟 import（本包多为 PLUGIN，
#: 顶层互相引用会踩 `test_module_layering.py` 的 PLUGIN→PLUGIN 红线）。
from modules.platform_rules.seed import seed_platform_rules_if_empty

__all__ = ["RULE_SPEC", "count_rules", "list_rules", "seed_platform_rules_if_empty"]
