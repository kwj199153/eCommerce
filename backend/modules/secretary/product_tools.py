"""
店秘书「产品选择工具」

把「选中产品库里的某个产品」包装成工具，让主 Agent 能在「切 Agent」之前
先把目标商品设置为「工作商品」，实现「选产品 → 切到 listing」的连贯动作。

设计要点（与 navigation_tools.py 一致）：
- 工具本身不直接改前端状态（后端够不着前端的 currentWorkingProduct），
  只查库 + 返回一个结构化标记，由 orchestrator 端点透传给前端，
  前端 dispatchAppAction 落地为「写 currentWorkingProduct + 切 Agent」。
- 数据源：PostgreSQL 的 skus 表（与产品库 /api/v1/skus 同源），
  按当前店铺（shop_id）过滤，取第一条作为「第一个产品」。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from core.database import async_session_factory
from modules.products.db_model import SkuRecord, SpuRecord


async def _select_product(shop_id: str, nth: int = 1) -> str:
    """选中产品库里的第 N 个产品（默认第一个），作为后续操作的「工作商品」。

    Args:
        shop_id: 当前店铺 ID（由系统注入，LLM 无需关心）。
        nth: 第几个产品（从 1 开始，默认 1 即第一个）。
    """
    async with async_session_factory() as session:
        q = (
            select(SkuRecord, SpuRecord.title)
            .join(SpuRecord, SkuRecord.spu_id == SpuRecord.id)
            .where(SpuRecord.shop_id == shop_id)
            .order_by(SkuRecord.created_at, SkuRecord.id)
        )
        rows = (await session.execute(q)).all()

    if not rows:
        return json.dumps({"action": "select_product", "product": None, "reason": "产品库为空"})

    idx = max(0, min(int(nth), len(rows)) - 1)
    sku, spu_title = rows[idx]

    # 标题与前端 skuToRow 一致：SPU 标题 + 规格值
    title = spu_title or ""
    if sku.spec_value:
        title = f"{title} - {sku.spec_value}"

    return json.dumps(
        {
            "action": "select_product",
            "product": {
                "id": sku.id,
                "title": title,
                "asin": sku.asin,
                "spu_id": sku.spu_id,
            },
            "index": idx + 1,
            "total": len(rows),
        },
        ensure_ascii=False,
    )


def build_product_tools(shop_id: Optional[str]) -> list:
    """构建产品选择工具（按当前店铺绑定 shop_id）。

    shop_id 为空（未选店铺）时，工具会返回「产品库为空」的标记，
    由前端提示用户先选择店铺。
    """
    bound_shop_id = shop_id or ""

    async def _select(shop_id: str = bound_shop_id, nth: int = 1) -> str:
        return await _select_product(shop_id, nth)

    return [
        StructuredTool.from_function(
            coroutine=_select,
            name="select_product",
            description=(
                "选中产品库里的第 N 个产品（默认第一个）作为「工作商品」。"
                "当用户说「选第一个产品」「选第 N 个产品」「选产品库里的 XX」"
                "并配合后续 listing 操作时使用。返回选中产品的 id / 标题 / ASIN。"
            ),
        ),
    ]
