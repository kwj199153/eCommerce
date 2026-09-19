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
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.side_effects import READ_ONLY_METADATA
from sqlalchemy import select

from core.database import async_session_factory
from core.stores import StoreRecord, SHOP_ORDER_BY

logger = logging.getLogger(__name__)


def _platform_family(platform: str) -> str:
    """把具体站点归到平台家族：`shopee_my` / `shopee_tw` → `shopee`。

    为什么需要：老板说「虾皮」「亚马逊」时指的是**平台家族**，而库里存的是
    带站点的 `shopee_my` / `shopee_tw`。子串匹配时「虾皮2」不能命中
    「虾皮1 shopee_my」，但「shopee」能命中全部虾皮店铺 —— 需要一个统一的
    家族名来做筛选与分组。
    """
    p = (platform or "").lower()
    for fam in ("shopee", "amazon", "temu", "tiktok", "shopify"):
        if p.startswith(fam):
            return fam
    return p


async def _list_shops() -> list[dict]:
    """读取所有店铺（按创建时间排序），返回轻量字典列表。

    ★ 排序键复用 `SHOP_ORDER_BY` 真源 —— 与 `/api/v1/stores` 同源。
    老板说「切到第 2 个店铺」时，序号就是**这里**数出来的（LLM 读 tool 返回值），
    而用户看的是 `/api/v1/stores` 的顺序。两者必须一致，否则静默切错店。

    ★ 同时标注**平台内序号**（`platform_index` / `platform_total`）：
    老板说「第二个虾皮店铺」时指的是平台内第 2 个，而 `index` 是全局序号 ——
    历史上 LLM 拿全局序号去猜「虾皮2」，猜成了全局第 3 个（= 虾皮1），静默切错店。
    给出平台内序号后，LLM 无需自己数。
    """
    async with async_session_factory() as session:
        q = select(StoreRecord).order_by(*[getattr(StoreRecord, k) for k in SHOP_ORDER_BY])
        rows = (await session.execute(q)).scalars().all()

    # 先按平台家族分组计数（保持 SHOP_ORDER_BY 的全局顺序）
    fam_counter: dict[str, int] = {}
    fam_total: dict[str, int] = {}
    for r in rows:
        fam = _platform_family(r.platform)
        fam_total[fam] = fam_total.get(fam, 0) + 1

    out: list[dict] = []
    for i, r in enumerate(rows):
        fam = _platform_family(r.platform)
        fam_counter[fam] = fam_counter.get(fam, 0) + 1
        out.append({
            "id": r.id,
            "name": r.name,
            "platform": r.platform,
            "index": i + 1,                       # 全局序号（从 1 开始）
            "platform_family": fam,               # shopee / amazon / temu ...
            "platform_index": fam_counter[fam],   # 平台内序号（从 1 开始）
            "platform_total": fam_total[fam],     # 该平台店铺总数
            "total": len(rows),
        })
    return out


async def _switch_shop(
    nth: int = 1,
    shop_name: str = "",
    platform: str = "",
    platform_nth: int = 0,
) -> str:
    """切换到目标店铺（按 名称 > 平台内序号 > 全局序号 依次匹配）。

    Args:
        nth: 全局第几个店铺（从 1 开始）。未给更精确条件时的兜底。
        shop_name: 店铺名关键词（如「虾皮1」「Amazon US」）。优先级最高。
        platform: 平台家族名（`shopee` / `amazon` / `temu` ...）。用于限定范围。
        platform_nth: **平台内**第几个（从 1 开始）。老板说「第二个虾皮店铺」时用这个。
    """
    shops = await _list_shops()

    if not shops:
        return json.dumps(
            {"action": "switch_shop", "shop": None, "reason": "还没有任何店铺，请先在侧栏「店铺群」里添加"},
            ensure_ascii=False,
        )

    # ★ 入参留痕：切错店时这是唯一能定论的证据（LLM 传了什么 vs 我们怎么解析）。
    #   历史事故：老板说「虾皮2」，工具按 nth 命中到全局第 3 个（虾皮1）。
    #   没有这行日志，只能靠猜。
    logger.info(
        "[shop_tools] switch_shop 入参 nth=%r shop_name=%r platform=%r platform_nth=%r 候选=%s",
        nth, shop_name, platform, platform_nth,
        [f"{x['index']}:{x['name']}({x['platform_family']}#{x['platform_index']})" for x in shops],
    )

    target: Optional[dict] = None
    index = 0

    # ① 店铺名关键词（最精确）：全字匹配优先，其次子串（避免「虾皮1」误配「虾皮10」）
    if shop_name:
        kw = shop_name.strip().lower()
        target = next((x for x in shops if kw == x["name"].lower()), None)
        if target is None:
            target = next(
                (x for x in shops if kw in f"{x['name']} {x['platform']}".lower()),
                None,
            )
        if target is not None:
            index = target["index"] - 1

    # ② 平台内序号（老板说「第二个虾皮店铺」走这条）
    if target is None and platform_nth and platform:
        fam = _platform_family(platform)
        cands = [x for x in shops if x["platform_family"] == fam]
        if cands:
            pos = max(1, min(int(platform_nth), len(cands))) - 1
            target = cands[pos]
            index = target["index"] - 1

    # ③ 全局序号（兜底）
    if target is None:
        idx = max(0, min(int(nth), len(shops)) - 1)
        target = shops[idx]
        index = idx

    logger.info(
        "[shop_tools] switch_shop 命中 -> %s (index=%d/%d)",
        target["name"], index + 1, len(shops),
    )

    logger.info(
        "[shop_tools] switch_shop 命中 -> %s (全局 %d/%d, %s#%d)",
        target["name"], index + 1, len(shops),
        target["platform_family"], target["platform_index"],
    )

    return json.dumps(
        {
            "action": "switch_shop",
            "shop": {"id": target["id"], "name": target["name"], "platform": target["platform"]},
            "index": target["index"],
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
                "「切到第 2 个店铺」「第二个虾皮店铺」等时使用。\n"
                "参数选择（按精确度从高到低，**优先用更精确的**）：\n"
                "  1) shop_name：店铺全名或片段（如「虾皮1」「Amazon US」）—— 最精确，能用就用。\n"
                "  2) platform + platform_nth：平台家族 + **平台内**序号。老板说「第二个虾皮店铺」"
                "时传 platform='shopee', platform_nth=2（**不要**用全局序号去猜）。\n"
                "  3) nth：全局序号（仅当老板明确说「第 N 个店铺」且不涉平台时用）。\n"
                "可用店铺与它们的全局/平台内序号见工具返回；切换后，后续所有选品/产品/广告/"
                "竞品等操作都在该店铺数据源下进行。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
    ]
