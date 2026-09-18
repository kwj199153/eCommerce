"""店铺作用域过滤 —— 唯一真源

★ 为什么必须集中：`shop_id` 过滤曾经在 **71 处各自手写**（12 个文件），
  于是「哪个列承载店铺作用域」这个决定被重复做了 71 次。将来店铺作用域
  改口径（例如像 `stores_store` 那样升级到 account 级），就得改 71 个地方。

## 本模块定义的两个决定

1. **哪个列**：店铺作用域列一律是 `Model.shop_id`。要按店铺收窄查询，
   用 `scoped(stmt, Model, shop_id)` —— 传**模型**而不是列，这样列名
   这个知识只存在于本文件一处。
2. **`shop_id` 为 None 时**：`scoped()` **照样加条件** ⇒ SQL 里是 `col IS NULL`，
   匹配不到任何行（安全失败方向：宁可查不到，不可查全部）。

## 已知的形态不统一（本轮**不改变**语义，仅记录）

调用点历史上存在三种形态。收敛时**逐点保持原行为**，不做「顺手修复」：

| 形态 | `shop_id` 为空时的行为 | 收敛方式 |
|---|---|---|
| `stmt.where(M.shop_id == shop_id)` | 返回 0 行 | `scoped(stmt, M, shop_id)` |
| `if shop_id: stmt = stmt.where(M.shop_id == shop_id)` | **不加过滤 ⇒ 返回全部店铺** | 守卫**原样保留**，只换函数 |
| `stmt.where(M.shop_id == (shop_id or ""))` | 匹配 `shop_id` 为空串的行 | 实参**原样保留** `shop_id or ""` |

⚠️ 上表第二行「为空时返回全部店铺」在**当前不可达**：接入这些端点的模块都在
   `tests/test_shop_id_guard.py::EXPECTED_STRICT_MODULES` 的严格档里，
   缺 `X-Shop-ID` 时 `get_current_shop_id` 会先 400。那些 `if shop_id:` 是
   **防御性冗余**，本轮**刻意不删** —— 删掉等于改变「shop_id 为 None」分支的
   可达性，属语义变更，需要单独评估。

## 门禁

`tests/test_tenant_scoping.py` 用 AST 断言：业务层不得再出现手写的
`<Model>.shop_id == ...` 比较（`is None` / `is not None` 那种身份守卫不算，
它们不是作用域过滤）。反向注入验证过。
"""

from typing import Any

__all__ = ["scoped", "scoped_if", "scope_condition"]

#: 承载店铺作用域的列名 —— 唯一真源。
#: 所有按店铺收窄的查询都必须经由本模块，而不是各自写列名。
SHOP_SCOPE_ATTR = "shop_id"


def scope_condition(model: Any, shop_id: Any):
    """返回「店铺作用域」这个条件表达式本身。

    用于条件不能独占一次 `where()` 的场景：
      - 既有多参数 `where(id == x, <这里>)`；
      - 动态拼接 `conditions.append(<这里>)`。

    只做一件事：把 `Model.shop_id == shop_id` 这个知识收口到本模块。
    """
    return getattr(model, SHOP_SCOPE_ATTR) == shop_id


def scoped(stmt: Any, model: Any, shop_id: Any):
    """给查询挂上店铺作用域过滤 —— **无条件**添加。

    ★ `shop_id` 为 None 时条件照样挂 ⇒ SQL 里是 `col IS NULL` ⇒ 匹配不到任何行
      （安全失败方向：宁可查不到，不可查全部）。

    ★ 传**模型**而不是列：调用点写 `scoped(stmt, SpuRecord, shop_id)`，
      即使查询主体是 join 出来的 `SkuRecord`，也读作「按 SPU 的店铺收窄」，
      与原先 `SpuRecord.shop_id == shop_id` 的意图一致。
    """
    return stmt.where(scope_condition(model, shop_id))


def scoped_if(stmt: Any, model: Any, shop_id: Any):
    """给查询挂上店铺作用域过滤 —— `shop_id` 为假值时**跳过**（不加条件）。

    ★ 这个变体的存在本身就是一条**已定决策**，不是"顺手加个方便函数"：
      历史上有 9 处调用点（原 `knowledge_base/service.py::_scoped`，
      私有 helper）要的是「空 shop_id ⇒ 不加过滤」。与其让每个模块各写一份
      私有 helper，不如把这个语义**命名**并收口到这里。

    ⚠️ 安全语义提示：跳过滤 = `shop_id` 为空时查询**不受店铺限制**。
      调用点必须自己保证「shop_id 为空」这条路径不可达或已被上游拒绝
      （严格档模块缺 `X-Shop-ID` 时 `get_current_shop_id` 会先 400）。
      新调用点优先用 `scoped()`；只有在确实需要"为空即不过滤"时才用本函数，
      并在调用点写一句为什么。
    """
    if not shop_id:
        return stmt
    return stmt.where(scope_condition(model, shop_id))
