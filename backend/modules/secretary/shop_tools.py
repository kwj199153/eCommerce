"""
店秘书「店铺切换工具」

把「切换当前店铺」包装成工具，让主 Agent 能一句话切到目标店铺。
这是「AI 原生」的核心能力之一：店铺数据源切换是高频操作，不应只藏在侧栏。

设计要点（与 navigation_tools.py / product_tools.py 一致）：
- 工具本身不直接改前端状态（后端够不着前端的 shopStore），只查库 + 返回结构化标记，
  由 orchestrator 端点透传给前端，前端 dispatchAppAction 落地为 shopStore.setCurrentShop。
- 数据源：PostgreSQL 的 stores_store 表（与 /api/v1/stores 同源）。
- 与 select_product 不同：switch_shop 要列出**所有**店铺（而非按当前 shop 过滤），
  因此不依赖请求注入的 shop_id，用独立 build_shop_tools() 构建。
"""

import json
from typing import Optional

from langchain_core.tools import StructuredTool
from sqlalchemy import select

from core.database import async_session_factory
from modules.stores.db_model import StoreRecord


async def _list_shops() -> list[dict]:
    """读取所有店铺（按创建时间排序），返回轻量字典列表。"""
    async with async_session_factory() as session:
        q = select(StoreRecord).order_by(StoreRecord.created_at, StoreRecord.id)
        rows = (await session.execute(q)).scalars().all()

    return [
        {
            "id": r.id,
            "name": r.name,
            "platform": r.platform,
        }
        for r in rows
    ]


async def _switch_shop(nth: int = 1, shop_name: str = "") -> str:
    """切换到目标店铺（按序号或名称匹配）。

    Args:
        nth: 第几个店铺（从 1 开始；未指定 shop_name 时按序号选，默认第 1 个）。
        shop_name: 店铺名称关键词（模糊匹配；优先于 nth）。
    """
    shops = await _list_shops()

    if not shops:
        return json.dumps(
            {"action": "switch_shop", "shop": None, "reason": "还没有任何店铺，请先在侧栏「店铺群」里添加"},
            ensure_ascii=False,
        )

    target: Optional[dict] = None
    index = 0

    # 优先按名称模糊匹配（老板常说的是店铺名或平台/站点名）
    if shop_name:
        kw = shop_name.strip().lower()
        for i, s in enumerate(shops):
            haystack = f"{s['name']} {s['platform']}".lower()
            if kw in haystack:
                target = s
                index = i
                break

    # 名称未命中则回退按序号
    if target is None:
        idx = max(0, min(int(nth), len(shops)) - 1)
        target = shops[idx]
        index = idx

    return json.dumps(
        {
            "action": "switch_shop",
            "shop": target,
            "index": index + 1,
            "total": len(shops),
        },
        ensure_ascii=False,
    )


def build_shop_tools() -> list:
    """构建店铺切换工具（列出所有店铺，不绑定当前 shop_id）。"""
    return [
        StructuredTool.from_function(
            coroutine=_switch_shop,
            name="switch_shop",
            description=(
                "切换当前工作的店铺（数据源）。老板说「切到 XX 店」「换个店铺」「用我的美国店」"
                "「切到第 2 个店铺」等时使用。"
                "shop_name 传店铺名或站点关键词（如「美国」「Amazon US」「shopee」），"
                "nth 传序号（第几个店铺，从 1 开始）。"
                "切换后，后续所有选品/产品/广告/竞品等操作都在该店铺数据源下进行。"
            ),
        ),
    ]
