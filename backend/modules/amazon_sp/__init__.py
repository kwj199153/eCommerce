"""Amazon SP-API 数据模块门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.amazon_sp import <name>`；
     `from modules.amazon_sp.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 出口一 —— `get_data_source`：本包曾对外的唯一契约是「给我一个数据源」。
  上层（Agent / ingest）只依赖 `AmazonDataSource` 接口，切换 Mock / 真实
  SP-API 不改业务代码。模型层（`db_model`）不对外。
  ★ `modules.amazon_sp.data_sources` **自己也有门面**；跨模块消费者不必知道
    这条内部层级，从本包取即可。

★ 出口二 —— `load_competitor_snapshots`（第 172 轮新增，实现在 `snapshot_repo`）：
  竞品快照的真源是**表** `amazon_competitor_snapshots`，不再经数据源工厂。
  出口仍然是**函数**，不是 ORM 模型 —— 「模型层不对外」这条不改：消费方拿到的
  是行，拿不到可以任意拼 SQL 的类；`WHERE store_id = ...` 的租户过滤因此在包内
  **只有一份**实现（原先两个消费方各有一份查询副本，其中一份在单模块门禁的
  盲区里继续走 mock）。详见 `snapshot_repo.py` 的 docstring。
"""
from modules.amazon_sp.data_sources import get_data_source
from modules.amazon_sp.snapshot_repo import load_competitor_snapshots

__all__ = ["get_data_source", "load_competitor_snapshots"]
