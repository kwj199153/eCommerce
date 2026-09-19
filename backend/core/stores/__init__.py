"""店铺内核域 —— `StoreRecord`（`stores_store` 表）+ 全项目排序真源。

★ 为什么这个包有门面（re-export），而 `core/identity` 没有
  包只有 re-export，才能让「从**包**取名字」成为唯一消费方式。
  否则消费方只能 `from core.stores.models import StoreRecord` —— 那是
  **伸手进包内部**；而「从包取」与「伸手进包」在 AST 上长得一样，
  门禁就没法禁止越界取内部文件（这是「边界未定义」那个缺口的一个侧面）。
  本包先立这个契约，作为第 684 项「模块门面」的样板。

★ 公开面（改这里必须同步核对全部消费点）
  - `StoreRecord`   —— `stores_store` 表 ORM 实体（入度 7 的内核实体）
  - `SHOP_ORDER_BY` —— 店铺序号排序真源 `("created_at", "id")`
"""
from core.stores.models import SHOP_ORDER_BY, StoreRecord

__all__ = ["SHOP_ORDER_BY", "StoreRecord"]
