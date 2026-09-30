"""资料库只读工具 —— **同一能力只有一个实现**，由多家 Agent 共用（第 205 轮）。

==============================================================================
★ 为什么是「工厂 + 归属注入」而不是「模块级工具列表」
==============================================================================
1. 秘书的工具是**按请求重建**的（`SecretaryAgent(shop_id=…)`，
   见 `modules/secretary/agent.py` 的「店铺相关工具按请求动态重建」）
   ⇒ 它能在构造期就拿到**已校验**的 shop_id；
2. 选品分析师的路由子层是**懒加载并被缓存**的（`_get_router()` 缓存
   `self._router`），而 `product_research_service` 还是模块级单例
   ⇒ **构造期绑定店铺是错的**（第一个请求的店铺会被粘住）；
   它走的是请求级 ContextVar（`agent_product_research._current_shop_id`，
   唯一写入点是 `_bind_context()`）。

⇒ 归属来源**按宿主注入**，工具本体不自行去猜：
     · `shop_id=`  —— 构造期绑定（秘书）
     · `resolve=`  —— 运行期取值（选品分析师）
   两者**都**不给是**装配点的错**（调用方漏了注入）。这里刻意**不在构造期抛错**
   —— 抛错会让「没注入」与「注入了一个 `None`（用户确实还没选店铺，合法状态）」
   两者都以异常收场，而后者是秘书的正常开局。
   改为：① 工具回一条**可区分**的报错文案（不是含糊的「未选择店铺」）；
        ② 由门禁
           `tests/test_tool_catalog.py::test_every_build_call_site_injects_a_shop_source`
           在**调用点**上钉住「必须写 `shop_id=` 或 `resolve=`」。
   理由同第 204 轮 `ad_analysis` 的教训：工具接了却拿不到归属 ⇒ 永远没数据，
   而调用方看不出自己漏了注入。

==============================================================================
★ 为什么这两个工具必须**共用一份实现**
==============================================================================
它们各自服务 2 家 Agent（见 `tools_catalog.SHARED_TOOL_AGENTS`）。
若每家各写一份，就是「同一判定两份实现 ⇒ 至少一份永远测不到」——
本仓把这条列为铁律。门禁
`tests/test_tool_catalog.py::test_one_capability_has_exactly_one_implementation`
按 `(模块, 函数限定名)` 比对「不同 Agent 手里同名工具的底层实现」，
两份实现会直接转红。

==============================================================================
★ 出参为什么是「投影」而不是 REST 全字段
==============================================================================
REST 契约（`modules/products/router.py::_sku_to_dict`、`candidates/service.record_to_dict`）
面向界面，字段全；工具出参面向**模型**，只给判断所需的字段。
候选库借 `record_to_dict`（同一份实现），产品库按需投影
（先例：`modules/secretary/product_tools.py::_select_product` 也是工具层自查自有投影）。

==============================================================================
★ 第 218 轮（P1）：从 2 库扩到 6 库 —— 资料库全覆盖
==============================================================================
侧边栏「资料库」组的 6 个库（`frontend/src/components/Sidebar/KnowledgeBase.vue`
的 key：`candidates / assets / products / competitors / faq / rules`）现在全部有
只读工具：

    list_candidates      候选选品库    modules.candidates.service（record_to_dict 投影）
    list_products        产品库        modules.products（直走 `PRODUCT_SPEC` + 内核）
    list_assets          营销素材库    modules.assets.service.list_assets
    list_monitors        竞品监控池    modules.monitors.service.list_monitors
    list_faqs            业务话术库    modules.knowledge_base.service.list_faqs
    list_platform_rules  平台规则库    modules.platform_rules.service.list_rules

★ 为什么后 4 个能「一行」接上（P0-1 的直接收益）：
  第 218 轮先把「作用域 / 排序白名单 / limit 归一 / 真实 count / 去重 /
  字段投影 / 出参信封」七件事抽进 `core.library_query`，每个库只登记一份
  `LibrarySpec`。本模块因此**不重写任何查询**，只做四件事：
  「取归属 → 调该库的 service → 投影字段 → 套统一信封」，各一行。

★ 为什么这 4 个也挂给**同样两家**（选品分析师 + 店秘书），而不是按库拆到 4 家宿主：
  ① 归属来源的注入通道**只有这两家接好了**（秘书构造期绑定 `shop_id=`、
     选品分析师运行期 `resolve=`，见上文）。其余业务 Agent 目前整条**没有
     店铺归属通道** —— 给它们挂工具就是造出「接了却永远拿不到归属」的形态
     （同第 204 轮 `ad_analysis` 的教训：工具接了却拿不到归属 ⇒ 永远没数据，
     而调用方看不出自己漏了注入）。
  ② 这 6 个工具是**同一个能力面**（「读当前店铺的资料库」）。按库拆成 4 处
     装配点，只会让「同一能力两份实现」多出 4 个落脚处。
  ⇒ 归属是**有意识的决策**，由 `tools_catalog` 的 `agents` 字段与
     `tests/test_tool_catalog.py` 判据 G 双向钉住（多一家少一家都红）。
     将来某个业务 Agent 真需要其中某几库，正确做法是**先给它接上归属通道**，
     再单独挂，而不是在这里按名字拆。

★ 分层约束（为什么 4 个新 import 在**函数体内**）：
  `modules/library` 是 **SHARED** 层，而这 4 个库都是 **PLUGIN**
  ⇒ `SHARED → PLUGIN` 的**顶层** import 被 `tests/test_module_layering.py` 禁止
  （会成环）。先例：`assets` 只被 `secretary` 的**函数内**工具引用。
  ⇒ 4 个 `_rows_to_*` 一律函数内延迟 import；本模块的顶层依赖仍只有
     `products` / `candidates`（两者都是 SHARED）。
"""

import json
from typing import Any, Callable, List, Optional

from langchain_core.tools import StructuredTool

from ai_infra.tools.side_effects import READ_ONLY_METADATA
from core.library_query import (
    LibraryQueryError,
    count_library as _svc_count_library,
    query_library as _svc_query_library,
)
from modules.candidates import (
    CANDIDATE_SORT_KEYS,
    REVIEW_STATUSES,
    count_candidates as _svc_count_candidates,
    list_candidates as _svc_list_candidates,
)
from modules.products import PRODUCT_SPEC

__all__ = ["LIBRARY_TOOL_NAMES", "build_library_tools"]

#: 本包产出的工具名（**唯一真源**，供门禁与目录对账）。
#: ★ 第 218 轮（P1）从 2 → 6：侧边栏「资料库」组的 6 个库全覆盖。
#:   ★ 改前这份「唯一真源」其实**没有任何门禁读过**（只被 `__all__` re-export）
#:     —— 一句没有反例的断言等于没有断言。第 218 轮补上
#:     `tests/test_tool_catalog.py::test_library_tool_names_are_truthfully_declared`，
#:     把它与运行时真值（底层实现在 `modules.library.tools` 的工具集合）双向钉死。
LIBRARY_TOOL_NAMES: tuple = (
    "list_candidates",
    "list_products",
    "list_assets",
    "list_monitors",
    "list_faqs",
    "list_platform_rules",
)

#: 「调用方没给归属来源」的哨兵。
#: ★ 必须与「显式传了 `shop_id=None`」区分开：后者是**合法**状态
#:   （秘书在用户还没选店铺时就是 `shop_id=None`），必须能构建成功并回
#:   「请先选店铺」；前者是**调用方漏了注入**，必须在构造期就炸。
_UNSET: Any = object()

#: 未选择店铺时的统一文案（工具回给模型看，模型原样转达给老板）。
_NO_SHOP_HINT = "未选择店铺：请先在界面左上角选择一个店铺，再让我读资料库。"

#: **装配点漏注入归属来源**时的文案 —— 刻意与 `_NO_SHOP_HINT` 不同：
#: 前者是**代码问题**（该报给开发者），后者是**使用状态**（该提示老板去选店铺）。
#: 用同一句话会让「代码漏注入」永远伪装成「用户没选店铺」。
_NO_SOURCE_HINT = (
    "资料库工具没有被注入店铺归属来源（装配点漏写 shop_id= / resolve=）。"
    "这是装配缺陷，不是「用户没选店铺」——请修 `build_library_tools()` 的调用点。"
)

#: 单次最多返回条数（模型上下文有限，列表类工具必须封顶）。
MAX_ITEMS = 50


def _fallback(reason: str) -> str:
    """失败/降级出参：**显式**给出 `type` 与原因，绝不回一个空列表充数。

    ★ 为什么不能回 `{"items": []}`：那会让「没有店铺上下文」与
      「店铺确实没有数据」在模型看来完全一样 —— 前者该让老板去选店铺，
      后者该让老板去建数据，处置完全不同（同族判据：`failclosed-returns-200`）。
    """
    return json.dumps({"type": "library_read_failed", "error": reason}, ensure_ascii=False)


def _invalid(reason: str) -> str:
    """**参数非法**出参：与 `library_read_failed` 分开。

    ★ 为什么必须分开：`library_read_failed` 的处置是「读不到，别指望了」，
      而参数非法的处置是「换个值再试一次」。两者用同一个 `type` ⇒
      模型会把「你 order_by 写错了」转述成「资料库读不出来」，
      老板就去查一个不存在的问题（归因错方向）。
    ★ 第 216 轮新增：改前工具只暴露 `limit` / `review_status`，
      而 `review_status` 的合法值**只写在 docstring 里**（`args_schema` 无 `enum`）
      ⇒ 传「通过」「APPROVED」静默回**空列表**，与「真的没有」长得一样。
      现在服务层显式报错，工具层把它转成可自我纠正的人话。
    """
    return json.dumps({"type": "invalid_argument", "error": reason}, ensure_ascii=False)


def _dump(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


async def _rows_to_products(
    shop_id: str,
    limit: int,
    spu_id: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读产品库（SKU 列表）—— 与 `GET /api/v1/skus` **同走一个内核**。

    ★ 第 218 轮（P0-2）：改前本函数与 REST 端点**各写一份查询且已漂移** ——
      这里硬编码 `order_by(created_at, id)` 且把 limit 做在**内存切片**
      （`rows[:limit]`，库大时全量拉回），而 REST 既不排序也不下推。
      本仓那条「同一能力一份实现」的门禁只覆盖「不同 Agent 手里的同名工具」，
      **覆盖不到 REST vs 工具**，所以两份一直并存。
      现在两者都走 `core.library_query`（`PRODUCT_SPEC`），查询口径只有一份。
    ★ `limit` 因此从「内存切片」变成**下推 SQL**。
    ★ `total` 是**真实总数**（`count_library`，与列表同口径）——
      改前是 `len(rows)`，在不传 limit 时恰好相等，所以看不出问题。
    """
    rows = await _svc_query_library(
        PRODUCT_SPEC,
        shop_id,
        order_by=order_by,
        filters={"spu_id": spu_id},
        limit=limit,
    )
    total = await _svc_count_library(PRODUCT_SPEC, shop_id, filters={"spu_id": spu_id})
    items = []
    for sku, spu in rows:
        title = spu.title or ""
        if sku.spec_value:
            title = f"{title} - {sku.spec_value}"
        items.append(
            {
                "sku_id": sku.id,
                "spu_id": sku.spu_id,
                "title": title,
                "asin": sku.asin,
                "sku_code": sku.sku_code,
                "price": sku.price,
                "listing_status": sku.listing_status,
            }
        )
    return {
        "type": "product_list",
        "total": total,
        "returned": len(items),
        "items": items,
    }


#: 工具出参保留的候选字段（**投影**，不是删数据）。
#: 真源 `record_to_dict` 有 40 个字段，全塞给模型既浪费上下文又稀释注意力；
#: 这里只留「判断这条候选是什么、走到哪一步」所需的那些。
_CANDIDATE_TOOL_FIELDS: tuple = (
    "id",
    "asin",
    "title",
    "brand",
    "category",
    "price",
    "currency",
    "estimated_monthly_sales",
    "rating",
    "review_count",
    "blue_ocean_score",
    "roi_estimated",
    "review_status",
    "source",
    "created_at",
)


#: 素材库工具出参保留的字段（真源：`assets/db_model.AssetRecord`，
#: 面向界面的全字段投影在 `assets/router.py::_record_to_dict`）。
_ASSET_TOOL_FIELDS: tuple = (
    "id",
    "name",
    "kind",
    "category",
    "source",
    "url",
    "thumbnail",
    "asin",
    "productName",
    "createdAt",
)

#: 竞品监控池工具出参保留的字段（真源：`monitors/service.record_to_dict`）。
_MONITOR_TOOL_FIELDS: tuple = (
    "id",
    "asin",
    "title",
    "brand",
    "marketplace",
    "currency",
    "latest_price",
    "price_change_7d",
    "latest_bsr",
    "bsr_category",
    "rating",
    "review_count",
    "stock_status",
    "est_monthly_sales",
    "added_at",
)

#: 话术库工具出参保留的字段（真源：`knowledge_base/service.faq_to_dict`）。
_FAQ_TOOL_FIELDS: tuple = (
    "id",
    "kb_id",
    "question",
    "answer",
    "category",
    "priority",
    "status",
    "usage_count",
    "created_at",
)

#: 平台规则库工具出参保留的字段（真源：`platform_rules/service.rule_to_dict`）。
_RULE_TOOL_FIELDS: tuple = (
    "id",
    "platform",
    "category",
    "title",
    "content",
    "effective_date",
    "expiry_date",
    "status",
    "tags",
    "source",
    "created_at",
)


async def _rows_to_candidates(
    shop_id: str,
    limit: int,
    review_status: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读候选选品库。

    ★ 查询与序列化都走 `modules.candidates.service.list_candidates`（**唯一实现**）——
      REST 的 `GET /api/v1/candidates` 走的是同一个函数，不另抄一份查询。
      本函数只做**字段投影**（面向模型），不重做查询。

    ★ 第 216 轮：`total` 改成**真实总数**（`service.count_candidates`，
      与列表**共用**同一套过滤/去重口径），并新增 `returned` = 本次实际返回条数。
      改前 `total = len(rows)` 是 `LIMIT` **之后**的长度 ⇒
      模型答「评审通过有几个」时给的是被截断的数
      （本库 11 条时 `list_candidates(limit=1)` 报 `total=1`）。
      两个字段各有名字之后，「店里有几个」与「这次给你看了几个」不再共用一句话。
    """
    rows = await _svc_list_candidates(
        shop_id, limit=limit, review_status=review_status, order_by=order_by
    )
    total = await _svc_count_candidates(shop_id, review_status=review_status)
    items = [{k: r.get(k) for k in _CANDIDATE_TOOL_FIELDS} for r in rows]
    return {
        "type": "candidate_list",
        "total": total,
        "returned": len(items),
        "items": items,
    }


def _pick(row: Any, key: str) -> Any:
    """从 ORM 对象或**已序列化的 dict** 里取字段。

    ★ 为什么需要它：6 个库的 service 出参形态**不统一** ——
      `candidates` / `products` / `assets` / `monitors` 返回 ORM 对象
      （面向界面的投影在各自的 router 里做），而 `knowledge_base` /
      `platform_rules` 的 `list_*` 直接返回**已序列化的 dict**
      （`faq_to_dict` / `rule_to_dict` —— 它们此前没有跨模块消费者，
      REST 契约本来就是 dict）。
      ★ 不为这个差异在工具层写两份取值代码 —— 那正是「同一判定两份实现」的入口。
    """
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _project(rows, fields: tuple) -> List[dict]:
    """按 `fields` 做**投影**（不是删数据）：工具出参面向**模型**，字段要少而准。"""
    return [{k: _pick(r, k) for k in fields} for r in rows]


def _sort_hint(spec: Any) -> str:
    """把 spec 的排序白名单渲染成给模型看的一句话。

    ★ 维度**从 spec 取**，不在本文件再抄一份：P0-1 抽内核时，
      「合法值只写在 docstring 里、`args_schema` 无 `enum`」被列为一次真实
      缺陷的成因（传「通过」静默回空列表，与「真的没有」长得一样）。
      抄一份就会与内核真正校验的那份漂移。
    """
    return " / ".join(spec.sort_keys) + f"（默认 {spec.default_sort}）"


def _filter_hint(spec: Any) -> str:
    """把 spec 的过滤维度 + **值域**渲染成给模型看的一句话（同上：值域也从 spec 取）。"""
    parts = []
    for key in spec.filter_keys:
        values = getattr(spec.filters.get(key), "values", None)
        if values:
            parts.append(f"{key}（可选：{' / '.join(values)}）")
        else:
            parts.append(f"{key}（自由文本）")
    return "、".join(parts) if parts else "（无）"


async def _rows_to_assets(
    shop_id: str,
    limit: int,
    kind: Optional[str],
    category: Optional[str],
    source: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读营销素材库（第 218 轮 P1）。

    ★ 查询走 `modules.assets.service.list_assets`（**唯一实现**）——
      REST 的 `GET /api/v1/assets` 与工具走同一个函数，本函数只做**字段投影**。
    ★ `total` 用 `count_assets`，与列表**共用同一个 base query**；
      `limit` 是**下推 SQL**，不是内存切片。
    """
    from modules.assets import count_assets, list_assets  # PLUGIN：只许函数内延迟

    rows = await list_assets(
        shop_id,
        order_by=order_by,
        kind=kind,
        category=category,
        source=source,
        limit=limit,
    )
    total = await count_assets(shop_id, kind=kind, category=category, source=source)
    items = _project(rows, _ASSET_TOOL_FIELDS)
    return {"type": "asset_list", "total": total, "returned": len(items), "items": items}


async def _rows_to_monitors(
    shop_id: str,
    limit: int,
    stock_status: Optional[str],
    marketplace: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读竞品监控池（第 218 轮 P1）。查询走 `modules.monitors.service.list_monitors`。"""
    from modules.monitors import count_monitors, list_monitors  # PLUGIN：只许函数内延迟

    rows = await list_monitors(
        shop_id,
        order_by=order_by,
        stock_status=stock_status,
        marketplace=marketplace,
        limit=limit,
    )
    total = await count_monitors(shop_id, stock_status=stock_status, marketplace=marketplace)
    items = _project(rows, _MONITOR_TOOL_FIELDS)
    return {"type": "monitor_list", "total": total, "returned": len(items), "items": items}


async def _rows_to_faqs(
    shop_id: str,
    limit: int,
    kb_id: Optional[str],
    category: Optional[str],
    priority: Optional[str],
    status: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读业务话术库（第 218 轮 P1）。查询走 `modules.knowledge_base.service.list_faqs`。"""
    from modules.knowledge_base import count_faqs, list_faqs  # PLUGIN：只许函数内延迟

    rows = await list_faqs(
        shop_id,
        order_by=order_by,
        kb_id=kb_id,
        category=category,
        priority=priority,
        status=status,
        limit=limit,
    )
    total = await count_faqs(
        shop_id, kb_id=kb_id, category=category, priority=priority, status=status
    )
    items = _project(rows, _FAQ_TOOL_FIELDS)
    return {"type": "faq_list", "total": total, "returned": len(items), "items": items}


async def _rows_to_rules(
    shop_id: str,
    limit: int,
    platform: Optional[str],
    category: Optional[str],
    status: Optional[str],
    order_by: Optional[str] = None,
) -> dict:
    """读平台规则库（第 218 轮 P1）。查询走 `modules.platform_rules.service.list_rules`。"""
    from modules.platform_rules import count_rules, list_rules  # PLUGIN：只许函数内延迟

    rows = await list_rules(
        shop_id,
        order_by=order_by,
        platform=platform,
        category=category,
        status=status,
        limit=limit,
    )
    total = await count_rules(shop_id, platform=platform, category=category, status=status)
    items = _project(rows, _RULE_TOOL_FIELDS)
    return {"type": "rule_list", "total": total, "returned": len(items), "items": items}


def build_library_tools(
    shop_id: Any = _UNSET,
    resolve: Optional[Callable[[], Optional[str]]] = None,
) -> List[StructuredTool]:
    """构建资料库只读工具（按宿主注入归属来源）。

    Args:
        shop_id: 构造期绑定的店铺 ID（可为 None = 用户还没选店铺）。
        resolve: 运行期取归属的可调用对象（宿主自己的 ContextVar 读取器）。

    ★ 「两个都不给」不会抛错，但**每次调用**都会回一条指名道姓的装配缺陷文案
      （`_NO_SOURCE_HINT`），而不是含糊的「未选择店铺」——
      调用点由门禁钉住（见模块 docstring）。
    """
    # ★ SHARED → PLUGIN **只允许函数内延迟 import**（`tests/test_module_layering.py`
    #   禁止顶层 SHARED → PLUGIN，会成环）。这里取 spec 只为一件事：
    #   把各库的**排序白名单 + 过滤维度（含值域）**写进 description ——
    #   也就是「模型能按什么排、按什么筛」的唯一真源。
    #   ★ 维度**不在本文件再抄一份**：抄一份必然与内核真正校验的那份漂移
    #     （第 216 轮实测过这个形态的代价：传「通过」静默回空列表）。
    from modules.assets import ASSET_SPEC
    from modules.knowledge_base import FAQ_SPEC
    from modules.monitors import MONITOR_SPEC
    from modules.platform_rules import RULE_SPEC

    injected = not (shop_id is _UNSET and resolve is None)
    bound = None if shop_id is _UNSET else shop_id

    def _shop() -> Optional[str]:
        """本次调用的归属（运行期取值优先，其次构造期绑定）。

        ★ 归一化用 `.strip() or None`：HTTP 头解析不保证调用方不发纯空白值，
          而 `"   "` 若原样放行会被当成合法店铺 ID 带去查库 ⇒ 空匹配
          ⇒ 回一个**空列表**，看起来像「店铺确实没数据」（归因错方向）。
          同族真源：`core/tenant/middleware.py::_resolve_current_shop_id`。
        """
        if resolve is not None:
            got = (resolve() or "").strip()
            if got:
                return got
        return (bound or "").strip() or None

    def _fail() -> str:
        return _fallback(_NO_SHOP_HINT if injected else _NO_SOURCE_HINT)

    async def _list_candidates(
        limit: int = 20,
        review_status: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**候选选品库**（草稿池，待评审）。

        用途：老板说「看看我的选品库」「候选库里有哪些品」「有没有评分 80 以上的候选」
        时先取列表；后续要评审 / 通过入库的动作都要先拿到这里的 `id`。
        ★ 问「销量前 3 / 售价前 5 / 蓝海评分最高的几个」这类**排行榜**问题时，
          `order_by` 与 `limit` 必须一起给。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            review_status: 只看某个评审状态，不传则返回全部。
            order_by: 排序维度，不传则按最近更新倒序。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(await _rows_to_candidates(sid, n, review_status, order_by))
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    async def _list_products(
        limit: int = 20,
        spu_id: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**产品库**（自有商品主数据，SKU 粒度）。

        用途：老板说「我的产品库有什么」「店铺里有哪些产品 / SKU」
        「这个 SPU 下有哪些规格」「最贵的几个 SKU」时使用；拿到 `sku_id`
        之后才能做 Listing 相关的读写动作。
        ★ 问「售价最高 / 评分最高 / 销量最好的前几名」这类**排行榜**问题时，
          `order_by` 与 `limit` 必须一起给：只给 limit 拿到的是「默认排序的前 N 条」。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            spu_id: 只看某个 SPU 下的 SKU（可选）。
            order_by: 排序维度，不传则按创建时间正序（与 REST 原行为一致）。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(await _rows_to_products(sid, n, spu_id, order_by))
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    async def _list_assets(
        limit: int = 20,
        kind: Optional[str] = None,
        category: Optional[str] = None,
        source: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**营销素材库**（图片 / 视频素材）。

        用途：老板说「素材库里有什么」「我上传的图呢」「有没有某类素材」
        「这个 ASIN 的素材在哪」时使用；也是「准备出图 / 出视频」前的盘点动作。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            kind: 只看某一类素材（图片 / 视频）。
            category: 按素材分类过滤（自由文本）。
            source: 按来源过滤（AIGC 生成 / 上传 / 视频生成 / 手工添加）。
            order_by: 排序维度，不传则按创建时间倒序（最新在前）。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(await _rows_to_assets(sid, n, kind, category, source, order_by))
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    async def _list_monitors(
        limit: int = 20,
        stock_status: Optional[str] = None,
        marketplace: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**竞品监控池**（正在盯的竞品）。

        用途：老板说「我的竞品池里有什么」「竞品监控里盯了哪些」
        「哪个竞品降价了 / 断货了」「BSR 最差的那几个」时使用。
        ★ 问「价格最低 / 评分最高 / 销量最好 / BSR 最好的前几名」这类**排行榜**
          问题时，`order_by` 与 `limit` 必须一起给（BSR 是**越小越好**）。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            stock_status: 只看某个库存状态（如 有货 / 断货）。
            marketplace: 只看某个站点（如 us / uk）。
            order_by: 排序维度，不传则按入池时间倒序（新增的在前）。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(await _rows_to_monitors(sid, n, stock_status, marketplace, order_by))
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    async def _list_faqs(
        limit: int = 20,
        kb_id: Optional[str] = None,
        category: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**业务话术库**（客服问答条目）。

        用途：老板说「话术库里有什么」「客服标准答案在哪」「有哪些高优先级的
        话术」「某分类下的话术」时使用；也是「回答客户前先找标准话术」的入口。
        ★ 这里返回的是**列表**（可筛可排）；只要问「有几条」这类计数，
          直接看出参的 `total`（**真实**条数），别数 `items`。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            kb_id: 只看某个知识库容器下的条目。
            category: 按话术分类过滤（自由文本）。
            priority: 按优先级过滤（自由文本，如 高 / 中 / 低）。
            status: 按状态过滤（自由文本，如 启用 / 停用）。
            order_by: 排序维度，不传则按创建时间正序。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(
                await _rows_to_faqs(sid, n, kb_id, category, priority, status, order_by)
            )
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    async def _list_platform_rules(
        limit: int = 20,
        platform: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> str:
        """列出当前店铺的**平台规则库**（各平台的政策 / 规则条目）。

        用途：老板说「平台规则里怎么规定的」「这个平台有什么新规」
        「有哪些生效中的规则」「亚马逊的规则有哪些」时使用；
        也是「上架 / 改价 / 做活动前先核对平台规则」的入口。

        Args:
            limit: 最多返回多少条（默认 20，上限 50）。
            platform: 只看某个平台的规则（如 亚马逊 / 虾皮）。
            category: 按规则分类过滤（自由文本）。
            status: 按状态过滤（自由文本，如 生效中 / 已废止）。
            order_by: 排序维度，不传则按生效日期倒序（最新生效的在前）。
        """
        sid = _shop()
        if not sid:
            return _fail()
        try:
            n = max(1, min(int(limit or 20), MAX_ITEMS))
            return _dump(await _rows_to_rules(sid, n, platform, category, status, order_by))
        except LibraryQueryError as e:
            return _invalid(str(e))
        except (TypeError, ValueError) as e:
            return _invalid(f"参数类型不对：{e}")

    return [
        StructuredTool.from_function(
            coroutine=_list_candidates,
            name="list_candidates",
            description=(
                "列出当前店铺候选选品库里的候选（草稿池）。"
                "当用户想看选品库/候选库/候选池里有什么、想按评审状态筛候选、"
                "想要某个维度的**排行榜**（销量最高 / 售价最高 / 评分最高 / "
                "蓝海评分最高 / ROI 最高的前几名）时使用。"
                "排序维度 order_by 可选："
                + " / ".join(CANDIDATE_SORT_KEYS)
                + "（默认 updated_at = 最近更新）；"
                "过滤维度 review_status 可选："
                + " / ".join(REVIEW_STATUSES)
                + "，两者传了值域外的值会返回 type=invalid_argument，请换个值重试。"
                "返回每条候选的 id / ASIN / 标题 / 售价 / 评审状态 / 蓝海评分 / ROI。"
                "出参含 total（本店**真实**条数，已按 ASIN 去重、已按 review_status 筛）"
                "与 returned（本次实际返回条数，受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「有几个」时答 total，不要答 returned。"
                "★ 问「销量前 3」这类排行榜时必须**同时**给 order_by 与 limit："
                "只给 limit 拿到的只是「最近更新的 N 条」，不是「销量最高的 N 条」。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_list_products,
            name="list_products",
            description=(
                "列出当前店铺产品库里的产品（SKU 粒度，含所属 SPU 标题）。"
                "当用户想看产品库/自有商品/店铺里有哪些 SKU、想按 SPU 看规格、"
                "想要某个维度的**排行榜**（售价最高 / 评分最高 / 销量最高 / "
                "ROI 最高的前几名）时使用。"
                "排序维度 order_by 可选："
                + " / ".join(PRODUCT_SPEC.sort_keys)
                + "（默认 created_at = 创建时间正序）；"
                "过滤维度 spu_id（只看某个 SPU 下的 SKU）与 listing_status；"
                "两者传了值域外的值会返回 type=invalid_argument，请换个值重试。"
                "返回每条 SKU 的 sku_id / spu_id / 标题 / ASIN / 售价 / Listing 状态。"
                "出参含 total（本店**真实**条数）与 returned（本次实际返回条数，"
                "受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「有几个」时答 total，不要答 returned。"
                "★ 问「最贵的 3 个」这类排行榜时必须**同时**给 order_by 与 limit："
                "只给 limit 拿到的只是「默认排序的前 N 条」，不是「售价最高的 N 条」。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_list_assets,
            name="list_assets",
            description=(
                "列出当前店铺**营销素材库**里的素材（图片 / 视频，含 URL）。"
                "当用户想看素材库里有什么、想找某个商品/ASIN 的素材、"
                "想按类型或来源筛素材时使用。"
                "排序维度 order_by 可选："
                + _sort_hint(ASSET_SPEC)
                + "；过滤维度："
                + _filter_hint(ASSET_SPEC)
                + "。传了值域外的值会返回 type=invalid_argument，请换个值重试。"
                "返回每条素材的 id / 名称 / 类型 / 分类 / 来源 / URL / 缩略图 / 关联 ASIN。"
                "出参含 total（本店**真实**条数）与 returned（本次实际返回条数，"
                "受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「有几个」时答 total，不要答 returned。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_list_monitors,
            name="list_monitors",
            description=(
                "列出当前店铺**竞品监控池**里正在盯的竞品。"
                "当用户想看竞品池/竞品监控里有什么、想按库存状态或站点筛竞品、"
                "想要某个维度的**排行榜**（售价最高 / 评分最高 / 评论最多 / "
                "销量最好 / BSR 最好的前几名）时使用。"
                "排序维度 order_by 可选："
                + _sort_hint(MONITOR_SPEC)
                + "（★ BSR 是排名，**越小越好**）；过滤维度："
                + _filter_hint(MONITOR_SPEC)
                + "。传了值域外的值会返回 type=invalid_argument，请换个值重试。"
                "返回每个竞品的 id / ASIN / 标题 / 售价 / 7 日价格变化 / BSR / "
                "评分 / 评论数 / 库存状态 / 预估月销。"
                "出参含 total（本店**真实**条数）与 returned（本次实际返回条数，"
                "受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「盯了几个」时答 total，不要答 returned。"
                "★ 问「BSR 最差的前 3 个」这类排行榜时必须**同时**给 order_by 与 limit。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_list_faqs,
            name="list_faqs",
            description=(
                "列出当前店铺**业务话术库**里的客服问答条目（问题 + 标准答案）。"
                "当用户想看话术库/知识库里有什么、想按分类或优先级筛话术、"
                "想找某类问题的标准答法、想找使用最多的话术时使用。"
                "排序维度 order_by 可选："
                + _sort_hint(FAQ_SPEC)
                + "；过滤维度："
                + _filter_hint(FAQ_SPEC)
                + "。"
                "返回每条话术的 id / 所属知识库 / 问题 / 答案 / 分类 / 优先级 / "
                "状态 / 使用次数 / 创建时间。"
                "出参含 total（本店**真实**条数）与 returned（本次实际返回条数，"
                "受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「有几条话术」时答 total，不要答 returned。"
                "★ 这是**读列表**；要按关键词检索单个问题请用客服的检索工具。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=_list_platform_rules,
            name="list_platform_rules",
            description=(
                "列出当前店铺**平台规则库**里的规则条目（各平台政策 / 规则原文）。"
                "当用户问「平台规则里怎么规定的」「有什么新规」「哪些规则生效中」"
                "「某平台的规则有哪些」时使用。"
                "排序维度 order_by 可选："
                + _sort_hint(RULE_SPEC)
                + "；过滤维度："
                + _filter_hint(RULE_SPEC)
                + "。"
                "返回每条规则的 id / 平台 / 分类 / 标题 / 正文 / 生效日期 / 失效日期 / "
                "状态 / 标签 / 来源。"
                "出参含 total（本店**真实**条数）与 returned（本次实际返回条数，"
                "受 limit 与上限 "
                + str(MAX_ITEMS)
                + " 约束）；用户问「有几条规则」时答 total，不要答 returned。"
            ),
            metadata=READ_ONLY_METADATA,
        ),
    ]
