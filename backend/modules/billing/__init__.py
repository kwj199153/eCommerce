"""计费域（订阅 / 套餐 / 计价 / 额度）门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.billing import <name>`；
     `from modules.billing.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 为什么 billing 的实体仍住在 `modules/`（没有像 `StoreRecord` 那样搬进 `core/`）：
  用**项目自己那条判据**量 —— 「被 2 个以上别的模块 import ⇒ 基础域」。
  `modules.billing.models` 的**跨模块**消费者只有 1 处（secretary 的订阅工具），
  不足 2 ⇒ 它是业务域实体，归属正确。
  ★ 别混淆两类消费者：`core/metering` 与 `core/identity` 也在读 billing 的模型，
    但那是「内核读业务域」的**函数内延迟导入**（由 tests/test_core_layering.py 管），
    与本门面管的「模块间横向引用」是**两个不同的轴**。
"""
from modules.billing.models import Subscription, SubscriptionPlan

__all__ = ["Subscription", "SubscriptionPlan"]
