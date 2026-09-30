"""营销素材库 —— 业务逻辑层（查询侧，第 218 轮 · P1 新建）。

★ 为什么新建本文件：改前「读素材库」只有 `assets/router.py::list_assets`
  一处**内联实现**（handler 体里直接拼 `select`），Agent 侧够不着、也无从复用 ——
  本仓判据「后端有端点 ≠ Agent 够得着」。现在查询收口到这里，
  由本模块调 `core.library_query` 内核；REST 与 Agent 工具共用同一条路径。

★ 为什么 REST 出参不变：本文件只让「查什么、怎么排序、总共几条」有唯一实现，
  不碰 `_record_to_dict`（那是**面向界面**的投影，字段全）。
  面向模型的投影在工具层另做（只留判断所需字段）。
"""

from typing import List, Optional

from core.library_query import count_library, query_library
from modules.assets.db_model import AssetRecord
from modules.assets.spec import ASSET_SPEC

__all__ = ["count_assets", "list_assets"]


async def list_assets(
    shop_id: Optional[str],
    *,
    order_by: Optional[str] = None,
    kind: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    limit: Optional[int] = None,
) -> List[AssetRecord]:
    """素材列表（**唯一实现**）。

    Args:
        shop_id: **已校验归属**的店铺 ID。
        order_by: 排序维度（见 `ASSET_SPEC.sort_fields`）；None/空 = 默认（最新在前）。
        kind / category / source: 过滤维度；`kind` / `source` 传值域外的值**显式报错**。
        limit: 最多返回多少条（None = 不限）。
    Raises:
        core.library_query.LibraryQueryError: 排序 / 过滤参数非法。
    """
    rows = await query_library(
        ASSET_SPEC,
        shop_id,
        order_by=order_by,
        filters={"kind": kind, "category": category, "source": source},
        limit=limit,
    )
    return [row[0] for row in rows]


async def count_assets(
    shop_id: Optional[str],
    *,
    kind: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
) -> int:
    """素材**真实**条数（与 `list_assets` 同口径，两者都走内核）。"""
    return await count_library(
        ASSET_SPEC,
        shop_id,
        filters={"kind": kind, "category": category, "source": source},
    )
