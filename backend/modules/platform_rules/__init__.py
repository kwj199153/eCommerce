"""平台规则库模块（/api/v1/platform-rules）

★ 门面契约（由 `tests/test_module_facades.py` 机械校验）：第 218 轮（P1）
  建 `__all__` —— 此前本包只有上面这行 docstring、没有跨模块消费者。
  资料库工具要读平台规则库之后第一次有了跨模块引用，按门禁要求补契约面。
"""

from modules.platform_rules.service import count_rules, list_rules
from modules.platform_rules.spec import RULE_SPEC

#: ★ 第 218 轮（P1b）扩出口：`RULE_SPEC` —— 资料库工具用它生成排序 / 过滤维度说明。
__all__ = ["RULE_SPEC", "count_rules", "list_rules"]
