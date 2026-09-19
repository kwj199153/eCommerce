"""Amazon SP-API 数据模块门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.amazon_sp import <name>`；
     `from modules.amazon_sp.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 为什么门面出口落在 `data_sources` 子包：本包对外的唯一契约就是
  「给我一个数据源」—— 上层（Agent / ingest）只依赖 `AmazonDataSource` 接口，
  切换 Mock / 真实 SP-API 不改业务代码。模型层（`db_model`）不对外。
  ★ `modules.amazon_sp.data_sources` **自己也有门面**；跨模块消费者不必知道
    这条内部层级，从本包取即可。
"""
from modules.amazon_sp.data_sources import get_data_source

__all__ = ["get_data_source"]
