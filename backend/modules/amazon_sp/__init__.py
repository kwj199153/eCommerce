"""Amazon SP-API 数据模块门面包。

★ 门面契约（第 140 轮 T-684 门禁钉住）：
  1. 跨模块引用**只允许** `from modules.amazon_sp import <name>`；
     `from modules.amazon_sp.<子模块> import ...` 一律禁止（那是伸手进包内部）。
  2. `<name>` 必须在下面的 `__all__` 里 —— `__all__` 就是**本包允许被
     其它 `modules/*` 取用**的名字全集（新增出口必须同步扩它）。
  3. `__all__` 里的名字**不得是子模块**（防「re-export 一个模块」把门禁架空）。

★ 出口一 —— `open_data_source(store_id)`（第 386 轮，取代 `get_data_source`）：
  上层（Agent / Celery / 脚本）只依赖 `AmazonDataSource` 接口与这一个函数。
  **旧的 `get_data_source()` 已删除**，理由写在 `data_sources/__init__.py` 顶部：
  它没有 `store_id`，问的是「这个进程有没有凭据」，于是配了凭据时全店共用一把
  钥匙、没配凭据时给真实客户编造数据。删掉它才能让漏改的调用点当场报错。
  模型层（`db_model`）不对外。

★ 出口二 —— `load_competitor_snapshots`（第 172 轮新增，实现在 `snapshot_repo`）：
  竞品快照的真源是**表** `amazon_competitor_snapshots`，不再经数据源工厂。
  出口仍然是**函数**，不是 ORM 模型 —— 「模型层不对外」这条不改：消费方拿到的
  是行，拿不到可以任意拼 SQL 的类；`WHERE store_id = ...` 的租户过滤因此在包内
  **只有一份**实现（原先两个消费方各有一份查询副本，其中一份在单模块门禁的
  盲区里继续走 mock）。详见 `snapshot_repo.py` 的 docstring。

★ 出口三 —— 凭据层的异常与读取口（第 386 轮）：
  `StoreNotConnected` / `UnsupportedMarketplace` 必须能被**调用方**分辨，
  否则「该店未授权」只能被译成一句笼统的「取数失败」，前端也就做不出
  「去授权」的空态。所以它们与 `load_store_credential` 一起出口。
"""
from modules.amazon_sp.data_sources import (
    AmazonDataSource,
    MockAmazonDataSource,
    SpApiDataSource,
    StoreCredential,
    StoreNotConnected,
    UnsupportedMarketplace,
    load_store_credential,
    open_data_source,
)
from modules.amazon_sp.snapshot_repo import load_competitor_snapshots

__all__ = [
    # ★ 接口与 Mock 也出口：`prefer="mock"` 的返回类型必须可被调用方 isinstance 判断
    #   （`sync_all_shops` 要区分「演示店走 mock」与「真实店」，脚本要造演示数据）。
    #   两者都是**类**，不违反门面契约第 3 条（禁 re-export 子模块）。
    "AmazonDataSource",
    "MockAmazonDataSource",
    "SpApiDataSource",
    "open_data_source",
    "load_competitor_snapshots",
    "load_store_credential",
    "StoreCredential",
    "StoreNotConnected",
    "UnsupportedMarketplace",
]
