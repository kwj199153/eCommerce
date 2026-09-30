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

## ★★ 「为空时不过滤」不是防御性冗余，是**可利用的读越权**

本模块原先写着：「接入这些端点的模块都在严格档里，缺 `X-Shop-ID` 时
`get_current_shop_id` 会先 400，那些 `if shop_id:` 是**不可达的防御性冗余**」。

**这个论证是错的**，它让一批真实越权活了三个版本。错在哪：

400 空值守卫（`core/tenant/middleware.py::_resolve_current_shop_id`）**只对写方法
生效** —— 它判的是 `request.method in WRITE_METHODS`（POST/PUT/PATCH/DELETE），
**GET 不在里面**。GET 缺头走的是 `return None` 那条支线。于是

    if shop_id:
        q = scoped(q, M, shop_id)     # GET 缺头 ⇒ 条件整个不发 ⇒ 全库可读

⇒ **带任意有效 token、不带 `X-Shop-ID`，凭 id 即可读任意租户的详情。**

### 第 283 轮实测的证据链（不是推理，是数出来的）

· 有洞的不是一处而是五处：`platform_rules.get_rule_by_id` / `get_doc_by_id`、
  `knowledge_base` 里 9 处 `scoped_if`、`candidates._load_scoped`；
· 还有一个更隐蔽的：`monitors.get_monitor_by_id` —— 它与 `router.get_monitor`
  那份无条件版是「同一判定两份实现」，而且**零调用点**：正因为没人调用，
  它带着旧形态既测不到也没人发现；
· 那些函数的 docstring 写着「带租户校验：**给了** shop_id 就必须匹配」
  —— 一半语义藏在默认值里，注释把漏洞写成了契约。这类注释最难被发现。

### ⇒ 结论

本模块**不提供**「为空即不过滤」的变体。原 `scoped_if()` 已于第 283 轮删除
（危险语义不该有名字 —— 有名字，下一次就会被顺手用上）。缺店铺时的正确出口
是**上游就 400（写）/ 404（读）**，而不是把查询放宽。

## 门禁

`tests/test_tenant_scoping.py` 用 AST 断言两件事（反向注入均已验证）：

  1. 业务层不得再出现手写的 `<Model>.shop_id == ...` 比较
     （`is None` / `is not None` 那种身份守卫不算，它们不是作用域过滤）；
  2. **全仓扫描**：`modules/**` 下任何 `scoped(...)` 调用都不得被 `if shop_id:`
     包住 —— 用**形态判据**，不用手写端点名单。

★ 第 2 条为什么必须是全仓扫描：这里曾经用「四处详情端点」的手写字典做门禁
  （`tests/test_shop_id_guard.py`），而名单外的 platform_rules / knowledge_base /
  candidates 三个 service **从未进过名单** ⇒ 同形态的洞一个都没被守到。
  手写名单必然漂移（本仓判据：「恰好 N 处」是钉住旧形态的负资产）。
"""

from typing import Any

__all__ = ["scoped", "scope_condition"]

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

# ★ 第 283 轮移除：这里原有一个 `scoped_if()`（「shop_id 为空 ⇒ 不加过滤」变体）。
#   它有 9 处调用点，全部在 `modules/knowledge_base/service.py` —— 其中 GET 类的
#   `get_kb_by_id` / `get_kb_dict` / `get_faq_by_id` / `get_doc_by_id` 缺
#   `X-Shop-ID` 时可跨租户读取。详见本文件顶部「不是防御性冗余」一节。
#   危险语义不该有名字：留着它，下一次「顺手用一下」就会把洞重新挖开。
