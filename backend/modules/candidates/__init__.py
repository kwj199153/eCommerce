"""候选 / 选品记忆域门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.candidates import <name>`；
     `from modules.candidates.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 为什么只导出这 4 个函数：它们正是 `product_research` 这个跨模块消费者
  实际需要的**校验与落库原语**（多轮槽位补齐 / 去重 / 写库）。
  其余行内读写留在 `service.py` 内部，不构成跨模块契约。
"""
from modules.candidates.service import (
    candidate_exists,
    create_candidate,
    describe_missing_fields,
    missing_required_fields,
)

__all__ = [
    "candidate_exists",
    "create_candidate",
    "describe_missing_fields",
    "missing_required_fields",
]
