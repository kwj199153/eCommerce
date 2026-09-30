"""
店秘书「产品选择工具」

把「选中产品库里的某个产品」包装成工具，让主 Agent 能在「切 Agent」之前
先把目标商品设置为「工作商品」，实现「选产品 → 切到 listing」的连贯动作。

设计要点（与 navigation_tools.py 一致）：
- 工具本身不直接改前端状态（后端够不着前端的 currentWorkingProduct），
  只查库 + 返回一个结构化标记，由 orchestrator 端点透传给前端，
  前端 dispatchAppAction 落地为「写 currentWorkingProduct + 切 Agent」。
- 数据源：**`modules.products.spec.PRODUCT_SPEC`（唯一真源）** ——
  与 `/api/v1/skus`（`products/router.py`）和 `library/tools.py::list_products`
  同走 `core.library_query` 内核；取第 N 条作为「工作商品」。
- ★ 第 326 轮修复：改前本工具**绕开 `PRODUCT_SPEC` 自写了一份
  `scoped(select(...))`**，而 `products/spec.py` 的 docstring 明写
  「REST 与 Agent 工具同走它」⇒ **声明与实现相反**。
  且 `_select()` 把 `shop_id` 暴露成**工具形参**，等于让 LLM 自报租户 ——
  与第 204 轮修掉的 `create_ticket` 同形。现在 shop_id 由闭包捕获、不进 schema。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.side_effects import READ_ONLY_METADATA

from core.library_query import MAX_LIMIT, count_library, query_library
from modules.products import PRODUCT_SPEC


async def _select_product(shop_id: str, nth: int = 1) -> str:
    """选中产品库里的第 N 个产品（默认第一个），作为后续操作的「工作商品」。

    ★ 排序口径 = `PRODUCT_SPEC.default_sort`（`created_at` 升序、tie_breaker `id`
      升序），与改前 `order_by(SkuRecord.created_at, SkuRecord.id)` **逐字一致** ——
      「第 N 个」的语义没变，只是查询改由内核出。

    ★ `limit=nth` + 取最后一行 ⇒ 第 N 个。内核 `MAX_LIMIT`（50）是硬上限：
      N 超上限时**夹住并在出参里说明**，不静默改语义、也不把异常抛给模型。

    Args:
        shop_id: 当前店铺 ID（由系统注入，LLM 无需关心）。
        nth: 第几个产品（从 1 开始，默认 1 即第一个）。
    """
    nth_i = max(1, int(nth or 1))
    capped = min(nth_i, MAX_LIMIT)

    rows = await query_library(
        PRODUCT_SPEC,
        shop_id,
        order_by="created_at",
        limit=capped,
    )
    if not rows:
        return json.dumps({"action": "select_product", "product": None, "reason": "产品库为空"})

    # 「前 capped 条」的最后一条 == 第 capped 个
    idx = len(rows) - 1
    sku, spu = rows[idx]

    # 标题与前端 skuToRow 一致：SPU 标题 + 规格值
    title = spu.title or ""
    if sku.spec_value:
        title = f"{title} - {sku.spec_value}"

    payload = {
        "action": "select_product",
        "product": {
            "id": sku.id,
            "title": title,
            "asin": sku.asin,
            "spu_id": sku.spu_id,
        },
        "index": idx + 1,
        # ★ 真实总数（与列表同口径）—— 改前是 `len(rows)`，在「拉全量再切片」
        #   的实现里恰好相等；换成下推 limit 后必须显式查，否则就是「返回了几条」。
        "total": await count_library(PRODUCT_SPEC, shop_id),
    }
    if capped != nth_i:
        payload["note"] = (
            f"请求第 {nth_i} 个超出一次可查询上限 {MAX_LIMIT}，已按第 {capped} 个返回。"
        )
    return json.dumps(payload, ensure_ascii=False)


def build_product_tools(shop_id: Optional[str]) -> list:
    """构建产品选择工具（按当前店铺绑定 shop_id）。

    shop_id 为空（未选店铺）时，工具会返回「产品库为空」的标记，
    由前端提示用户先选择店铺。
    """
    bound_shop_id = shop_id or ""

    # ★ 第 326 轮：`shop_id` 不再出现在工具签名里 —— 它是**闭包捕获**的。
    #   改前写成 `async def _select(shop_id: str = bound_shop_id, ...)`，
    #   StructuredTool 会把带默认值的形参照旧暴露成**可选入参**
    #   ⇒ 模型可以传一个别家店铺 ID，把自己"搬"到别人的租户上。
    #   归属只能由服务端注入（与 `customer_service/tools.py::_shop_id` 同范式）。
    async def _select(nth: int = 1) -> str:
        return await _select_product(bound_shop_id, nth)

    return [
        StructuredTool.from_function(
            coroutine=_select,
            name="select_product",
            description=(
                "选中产品库里的第 N 个产品（默认第一个）作为「工作商品」。"
                "当用户说「选第一个产品」「选第 N 个产品」「选产品库里的 XX」"
                "并配合后续 listing 操作时使用。返回选中产品的 id / 标题 / ASIN。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
    ]
