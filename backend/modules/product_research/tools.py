"""
选品分析模块 → 主 Agent 工具注册表

把 ProductResearchService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 listing_tools.py 一致）：
- 只包「语义明确」的细粒度方法（蓝海挖掘 / 利润计算 / 痛点分析 / 竞品对比 / 选品大盘），
  **不包** `chat` / `stream_chat` 这类粗粒度入口（交给 agent 内部 _classify_intent
  关键词表再判断一次，会与主 Agent 的 LLM 判断冲突）。
- 参数用扁平字段（照 listing 范式），工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
  ★ 第 200 轮：`save_candidate` 此前直调 `_service.agent._save_candidate`，
  是这条约定的唯一例外（按 service 层盘点会漏掉它）；现已改走
  `_service.save_candidate`。
"""

import json
from typing import List, Optional

from core.library_query import LibraryQueryError, count_library, query_library

from langchain_core.tools import StructuredTool
from ai_infra.tools.serialization import dump_result as _dump
from ai_infra.tools.side_effects import READ_ONLY_METADATA, SIDE_EFFECT_METADATA
from modules.candidates import (
    approve_candidate as _approve_candidate,
    get_candidate as _get_candidate,
    review_candidate as _review_candidate,
)
from modules.library import build_library_tools

from .service import product_research_service
from .spec import MARKET_SNAPSHOT_SPEC
from .schemas import (
    BlueOceanRequest,
    ProfitAnalysisRequest,
    PainPointRequest,
    CompetitorCompareRequest,
)

# service 单例：**与 router 真正同源**（同一个实例）。
# 早前这里又 `ProductResearchService()` 了一次，与 router 各持一个 Agent，
# 导致会话状态（蓝海结果 / 待补槽位）在工具路径上不可见。
_service = product_research_service


async def _analyze_blue_ocean_tool(
    marketplace: str = "amazon_us",
    category: Optional[str] = None,
    price_min: Optional[float] = None,
    price_max: Optional[float] = None,
    max_reviews: int = 100,
    min_monthly_sales: int = 100,
    min_roi: float = 20,
    exclude_seasonal: bool = False,
    exclude_brand_dominant: bool = False,
) -> str:
    """蓝海品类挖掘：按低竞争 + 有需求 + 有利润的标准筛选候选商品。

    Args:
        marketplace: 目标站点，如 amazon_us / shopee_my（默认 amazon_us）。
        category: 类目键，取值 home_kitchen / electronics / sports / beauty / toys / pet（可选）。
        price_min: 最低售价（USD，可选）。
        price_max: 最高售价（USD，可选）。
        max_reviews: 评论数上限（控制低竞争，默认 100）。
        min_monthly_sales: 最小月销量（保证需求，默认 100）。
        min_roi: 最低目标 ROI（%，默认 20）。
        exclude_seasonal: 是否排除季节性商品（默认否）。
        exclude_brand_dominant: 是否排除品牌垄断商品（默认否）。
    """
    req = BlueOceanRequest(
        marketplace=marketplace,
        category=[category] if category else None,
        price_min=price_min,
        price_max=price_max,
        max_reviews=max_reviews,
        min_monthly_sales=min_monthly_sales,
        min_roi=min_roi,
        exclude_seasonal=exclude_seasonal,
        exclude_brand_dominant=exclude_brand_dominant,
    )
    resp = await _service.analyze_blue_ocean(req)
    return _dump(resp)


async def _analyze_profit_tool(
    selling_price: float,
    cost_price: float,
    product_name: str = "",
    asin: Optional[str] = None,
    weight_lbs: float = 1.5,
    dimensions: str = "10x7x5",
    category: str = "",
    ad_acos_pct: float = 15.0,
) -> str:
    """利润分析：按售价、成本、FBA 费用、广告费计算净利润 / ROI / 盈亏平衡点。

    Args:
        selling_price: 售价（USD，必填）。
        cost_price: 采购成本（USD，必填）。
        product_name: 产品名称（可选）。
        asin: 产品 ASIN（可选，有则查询真实数据）。
        weight_lbs: 重量（磅，默认 1.5）。
        dimensions: 尺寸（长x宽x高 英寸，默认 10x7x5）。
        category: 类目（影响佣金比例）。
        ad_acos_pct: 预期广告 ACOS（%，默认 15）。
    """
    req = ProfitAnalysisRequest(
        selling_price=selling_price,
        cost_price=cost_price,
        product_name=product_name,
        asin=asin,
        weight_lbs=weight_lbs,
        dimensions=dimensions,
        category=category,
        ad_acos_pct=ad_acos_pct,
    )
    resp = await _service.analyze_profit(req)
    return _dump(resp)


async def _analyze_pain_points_tool(
    asin: str,
    analyze_positive: bool = False,
) -> str:
    """痛点分析：分析某产品 ASIN 的用户评论，提炼痛点与改进方向。

    Args:
        asin: 产品 ASIN（必填）。
        analyze_positive: 是否同时分析好评（默认否，只分析差评痛点）。
    """
    req = PainPointRequest(asin=asin, analyze_positive=analyze_positive)
    resp = await _service.analyze_pain_points(req)
    return _dump(resp)


async def _compare_competitors_tool(
    asins: list[str],
    include_reviews: bool = True,
) -> str:
    """竞品对比：对比多个竞品 ASIN 的 Listing 质量、价格、优劣势。

    Args:
        asins: 竞品 ASIN 列表（2-5 个，必填）。
        include_reviews: 是否包含评论分析（默认 True）。
    """
    req = CompetitorCompareRequest(asins=asins, include_reviews=include_reviews)
    resp = await _service.compare_competitors(req)
    return _dump(resp)


async def _save_candidate_tool(
    asin: str = "",
    title: str = "",
    source_keyword: Optional[str] = None,
) -> str:
    """把商品写入候选选品库（待评审）。

    这是前端「蓝海结果卡 → 勾选 → 选分组 → 保存」那条**面板流程的对话版**，
    字段契约与面板一致（必填 ASIN + 商品标题），差别只在交互方式：
      - 必填缺失 → 返回的是**追问**（`type=candidate_save_failed` + `error` 文案）。
        请把这句追问**原样转达给用户**并等下一轮补充；**不要**自己编一个 ASIN
        或标题填进去，也不要改存别的商品充数。
      - 可选字段（售价/月销/蓝海评分/ROI/备注/分组）留空即可，后台按默认值补齐。

    修复记录：此前「保存到选品库」只是前端卡片上的一个按钮，Agent 侧
    **没有任何写入口**——对话里说「把这个品加进选品库」没有工具可调，
    只能靠关键词猜意图，会被误判成蓝海挖掘又跑一遍。

    Args:
        asin: 商品 ASIN（形如 B0KLMN3456）。不知道就留空，工具会引导用户补。
        title: 商品标题。能从蓝海结果或用户原话里拿到就带上。
        source_keyword: 该商品来自哪个机会词（可选，便于回溯成色来源）。
    """
    parts: List[str] = []
    if title:
        parts.append(title)
    if asin:
        parts.append(f"ASIN {asin}")
    if source_keyword:
        parts.append(f"来源机会词 {source_keyword}")
    query = f"把 {'，'.join(parts)} 加入选品库" if parts else "帮我入库"

    # 会话 ID **与店铺 ID** 都靠 ContextVar 传递（工具入参由 LLM 生成，塞不进去）；
    # 两者都由 `ProductResearchAgent._bind_context()` 在**入口处**写入：
    #   · 缺 context_id → 工具会在 `_default` 会话里找不到蓝海结果与待补槽位；
    #   · 缺 shop_id    → `_write_candidates` **硬拒绝写入**（拿不到归属就不写）。
    # ★★★ 第 131 轮修复：此前这里**只读了 `_current_context_id`**，漏读
    #     `_current_shop_id` ⇒ 工具路径 **100% 写不进库**，且返回的文案是
    #     「请先在界面左上角选一个店铺，再说一次…」——用户明明选过店铺，
    #     这是一句**归因错误的假拒绝**（让人去查一个不存在的问题）。
    #     实测（`_r131_a2_savecand_probe.py`）：`shop_id=probe-shop-A` 已绑定，
    #     工具路径仍被拒、`create_candidate` 零调用；而当时 Agent 自带的
    #     `_tool_save_candidate`（同样读双 ContextVar）同场次正常落库。
    #     ★ 第 200 轮：那个 Agent 内部旧工具已删（整簇零调用），本工具成了
    #     **唯一**写入口，并改走 `_service.save_candidate` ——
    #     5 个工具的形状至此统一为「工具 → service → agent」。
    from .agent_product_research import _current_context_id, _current_shop_id

    return _dump(await _service.save_candidate(
        query,
        context_id=_current_context_id.get(),
        shop_id=_current_shop_id.get(),
    ))


# ====== 候选生命周期（第 205 轮接线）======
#
# ★ 为什么这三条落在本模块：消费者只有选品分析师（`ProductResearcher`），
#   而实现住在 SHARED 层的 `modules.candidates.service`。
#   PLUGIN → SHARED 是分层表允许的方向；反过来（把工具塞进 `candidates`）
#   会让 SHARED 层反过来知道 Agent 的存在，方向就倒了。
# ★ 归属一律走 `_resolve_shop_id()`（与 `library_tools` 同一条 ContextVar 通道）：
#   工具入参由 LLM 生成，**塞不进** shop_id。缺归属时工具**硬拒绝**，
#   绝不「拿个默认店铺兜底」—— 那会让候选落进**不属于任何人**的店铺，
#   比拒做危险得多（本仓既有守卫 `_write_candidates` 同此语义）。
# ★ 三条里 `review_candidate` / `approve_candidate` 会写库 ⇒ 声明
#   `SIDE_EFFECT_METADATA`，由 `BaseAgent._wrap_hitl_tools()` 按副作用
#   **自动**包进人工审批（业务侧不手写名单）。

_NO_SHOP_HINT = (
    "没有拿到店铺归属，这个动作我不做。"
    "请先在界面左上角选一个店铺，再说一次。"
)


async def _get_candidate_tool(candidate_id: str) -> str:
    """查看某个候选选品的完整详情（评审前核对用）。

    Args:
        candidate_id: 候选 ID（从 list_candidates 的结果里取）。
    """
    shop_id = _resolve_shop_id()
    if not shop_id:
        return _NO_SHOP_HINT
    item = await _get_candidate(candidate_id, shop_id)
    if item is None:
        # ★「不存在」与「不属于你」同一文案：否则可拿 id 逐个试探，
        #   把「存在但不是我的」与「不存在」区分开 ⇒ 可枚举别人的候选。
        return f"没找到这个候选（id={candidate_id}），也可能它不属于当前店铺。"
    return _dump(item)


async def _review_candidate_tool(
    candidate_id: str,
    review_status: str,
    review_notes: str = "",
) -> str:
    """给候选选品打评审结论（淘汰 / 转评审中 / 退回待评审）。

    Args:
        candidate_id: 候选 ID。
        review_status: 只能是 pending / under_review / approved / rejected。
            ★ 「通过并推进产品库」不要用本条 —— 那要走 `approve_candidate`，
              它才会真的在产品库建 SPU 草稿。
        review_notes: 评审理由（可选，建议写上为什么）。
    """
    shop_id = _resolve_shop_id()
    if not shop_id:
        return _NO_SHOP_HINT
    item = await _review_candidate(
        candidate_id,
        shop_id,
        review_status=review_status,
        review_notes=review_notes,
    )
    if item is None:
        return f"没找到这个候选（id={candidate_id}），也可能它不属于当前店铺。"
    return _dump({"type": "candidate_reviewed", "candidate": item})


async def _approve_candidate_tool(candidate_id: str) -> str:
    """评审通过：把候选**正式推进自有产品库**（建一条待完善 Listing 的 SPU 草稿）。

    ★ 这是「候选 → 产品库」的**唯一通道**。候选本身会保留并标记 approved，
      作为不可覆盖的原始评估基线 ⇒ 这条**不会**删掉任何东西。

    Args:
        candidate_id: 候选 ID。先用 list_candidates / get_candidate 确认是哪一个，
            不要凭印象猜 id。
    """
    shop_id = _resolve_shop_id()
    if not shop_id:
        return _NO_SHOP_HINT
    result = await _approve_candidate(candidate_id, shop_id)
    if result is None:
        return f"没找到这个候选（id={candidate_id}），也可能它不属于当前店铺。"
    return _dump({"type": "candidate_approved", **result})


def _resolve_shop_id() -> Optional[str]:
    """本 Agent 的**请求级**归属（唯一写入点 = `ProductResearchAgent._bind_context`）。

    ★ 为什么用**函数内**延迟 import：`agent_product_research` 在 `_build_router()`
      里 `from .tools import product_research_tools` —— 顶层互相 import 会成环。
      本仓既有做法同 `_save_candidate_tool`（同文件上方）。
    ★ 为什么不能用构造期绑定：路由子层是**懒加载并被缓存**的
      （`_get_router()` 缓存 `self._router`），而 `product_research_service`
      还是模块级单例 —— 构造期绑定会把**第一个请求**的店铺粘住。
    """
    from .agent_product_research import _current_shop_id

    return _current_shop_id.get()


# ====== 选品大盘（市场洞察快照）只读工具（第 325 轮接线）======
#
# 老板原话（第 324 → 325 轮）：
#   「他不是有选品大盘吗 为什么会回答不出来这个问题」
#   「让 agent 可以读数据库，**解耦前端界面大盘**。用户不可能只问我这一个问题
#     蓝海分，也可能其他大盘相关问题。」
#
# ★ 改前这条数据**只有一条消费通道**：前端 `MarketInsightConfig.vue` 经
#   `GET /product-research/market-insight/treemap` 读。Agent 侧**一个工具都没有**
#   ⇒ 「现在哪个品类蓝海分最高」必然答不出来，还会被关键词短路拉去挖蓝海
#   （「品类」在 `blue_ocean` 关键词表里 ⇒ 命中即 `return`，LLM 一行都不执行）。
#
# ★ 为什么**不**登记成 `build_library_tools()` 的第 7 个库（三条理由）：
#   ① 语义：那 6 个是「资料库」—— 用户在侧边栏能看到、能增删的**自有资产**；
#      而选品大盘是**类目级市场快照**（站点 × 类目 × 日期），不属于谁的资产；
#   ② 分层：`modules/library` 是 SHARED，把 `MARKET_SNAPSHOT_SPEC`（PLUGIN）
#      收进它的库清单常量 = SHARED 顶层枚举 PLUGIN 的符号 ⇒ 要给分层门禁开豁免，
#      而豁免会连带放松真正的边界（`tests/test_module_layering.py`）；
#   ③ 语域：**通用名单**生成的那句 description 答不了「蓝海分最高的是哪个品类」——
#      那句话必须点明「读的是**类目级大盘**」以及与 `analyze_blue_ocean`
#      （返回**商品级**候选）的分工，否则模型会在两条工具之间选错。
#
# ★ 与前端端点**共用同一份真源** `MARKET_SNAPSHOT_SPEC`：
#   REST 端点走 `service.get_market_insight_treemap`（投影成 treemap 节点），
#   本工具走 `core.library_query` 内核（投影成紧凑记录 + **真实** `total`）。
#   **投影不同是有意的**（内核 docstring：「不做投影 —— 投影是每库特有的语义，
#   由调用方负责」），但「查哪张表 / 怎么去重 / 能按什么排 / 能按什么筛」只有
#   spec 一份 ⇒ 面板上的数字与对话里的数字必然一致。
#   （前端 treemap 不消费数组顺序 ⇒ 两处排序口径归一化对界面不可见。）

#: 出参字段（面向**模型**的投影：少而准；`is_demo` 不逐条给，提成顶层标志）。
_MARKET_SNAPSHOT_FIELDS = (
    "site", "category_name", "category_path", "snapshot_date",
    "blue_ocean_score", "search_volume", "search_growth",
    "price_min", "price_max", "price_median", "price_trend",
    "listing_count", "seller_count", "new_seller_count",
)

#: 大盘「空」的两种含义必须**分开说** —— 处置完全不同（同族论证见 `_NO_SHOP_HINT`）：
#: 「没选店铺」该去选店铺，「选品大盘真没数据」该去接数据源。
_MARKET_INSIGHT_EMPTY_HINT = (
    "当前店铺的选品大盘里没有任何类目快照（店铺归属已确认，是**真的没数据**，"
    "不是没选店铺）。可以接入第三方类目数据源，或切到演示账号看示例。"
)

#: 单次最多返回条数（与 `modules/library/tools.py::MAX_ITEMS` 同值）。
_MAX_MARKET_ITEMS = 50


def _invalid_argument(reason: str) -> str:
    """**参数非法**出参：与「读不到」分开。

    ★ 为什么必须分开：`read_failed` 的处置是「读不到，别指望了」，而参数非法的
      处置是「**换个值再试一次**」。两者共用一个 `type` ⇒ 模型会把
      「你 order_by 写错了」转述成「选品大盘坏了」，老板就去查一个不存在的问题
      （归因错方向 —— 第 216 轮 ③ 的教训）。
    ★ `type` 字面量 `invalid_argument` 与 `modules/library/tools.py::_invalid`
      **逐字一致**：模型只认这一个词。两处一致性由
      `tests/test_market_insight_tool.py` 钉住（跨模块比对，不靠注释承诺）。
    """
    return json.dumps({"type": "invalid_argument", "error": reason}, ensure_ascii=False)


def _market_sort_hint() -> str:
    """把 spec 的排序白名单渲染成给模型看的一句话。"""
    return " / ".join(MARKET_SNAPSHOT_SPEC.sort_keys)


def _market_filter_hint() -> str:
    """把 spec 的过滤维度 + **值域**渲染成给模型看的一句话。

    ★ 白名单 / 值域**从 spec 取**，不在本文件再抄一份字面量 —— 抄一份必然与
      内核真正校验的那份漂移（第 216 轮实测过代价：合法值只写在 docstring 里、
      `args_schema` 无 `enum` ⇒ 传错值静默回空列表，与「真的没有」长得一样）。
    """
    parts = []
    for key in MARKET_SNAPSHOT_SPEC.filter_keys:
        values = getattr(MARKET_SNAPSHOT_SPEC.filters.get(key), "values", None)
        parts.append(
            f"{key}（{' / '.join(values)}）" if values else f"{key}（自由文本，精确匹配）"
        )
    return "、".join(parts)


def _snapshot_item(r) -> dict:
    """一行快照 → 出参记录（`name` 与前端 treemap 用**同一兜底口径**）。"""
    item = {k: getattr(r, k, None) for k in _MARKET_SNAPSHOT_FIELDS}
    item["name"] = r.category_name or (r.category_path or "").split("/")[-1]
    return item


async def _query_market_insight_tool(
    order_by: Optional[str] = None,
    limit: int = 10,
    site: Optional[str] = None,
    price_trend: Optional[str] = None,
    category_path: Optional[str] = None,
) -> str:
    """读**选品大盘**（市场洞察快照）：类目级的蓝海机会 / 需求 / 竞争 / 价格数据。

    ★ 本工具回答「**哪些类目**值得做 / 哪个类目最热 / 竞争最松 / 价格带如何」，
      数据来自**已入库的类目快照**（站点 × 类目），**不是**现挖的候选商品 ——
      要「挖出一批可入库的候选商品」用 `analyze_blue_ocean`。

    ★ 归属一律走 `_resolve_shop_id()`（与候选生命周期三条工具同一条 ContextVar
      通道）：工具入参由 LLM 生成，**塞不进** shop_id。缺归属时**硬拒绝**，
      绝不「拿个默认店铺兜底」（那会读到**不属于任何人**的数据）。
      并且「没选店铺」与「大盘确实没数据」**两种空必须分开说**。

    Args:
        order_by: 排序维度（可选值见工具 description，由 spec 渲染）。
        limit: 返回前几条（默认 10，上限 50）。做「最高 / 前几名」排行时由它定格。
        site: 只看某个站点（可选值由 spec 渲染）。
        price_trend: 只看某个价格趋势（可选值由 spec 渲染）。
        category_path: 类目路径，**必须完整精确匹配**（例如
            `home_kitchen/home_decor/lighting`）。本工具**不支持模糊匹配** ——
            不确定路径时**先不要传这个参数**，把列表取回来自己挑，或先问用户。
    """
    sid = _resolve_shop_id()
    if not sid:
        return _NO_SHOP_HINT
    filters = {"site": site, "price_trend": price_trend, "category_path": category_path}
    try:
        n = max(1, min(int(limit or 10), _MAX_MARKET_ITEMS))
        rows = await query_library(
            MARKET_SNAPSHOT_SPEC, sid, order_by=order_by, filters=filters, limit=n
        )
        total = await count_library(MARKET_SNAPSHOT_SPEC, sid, filters=filters)
    except LibraryQueryError as e:
        return _invalid_argument(str(e))
    except (TypeError, ValueError) as e:
        return _invalid_argument(f"参数类型不对：{e}")

    items = [_snapshot_item(row[0]) for row in rows]
    payload = {
        "type": "market_insight",
        "total": total,
        "returned": len(items),
        "order_by": order_by or MARKET_SNAPSHOT_SPEC.default_sort,
        "filters": {k: v for k, v in filters.items() if v},
        # ★ 演示数据如实标注：不让 mock 快照冒充真实第三方数据（同 REST 的 degraded）。
        "degraded": any(bool(getattr(row[0], "is_demo", False)) for row in rows),
        "items": items,
    }
    if not items:
        payload["note"] = _MARKET_INSIGHT_EMPTY_HINT
    return _dump(payload)


# ====== 工具注册表 ======
#
# ★ 第 205 轮：尾部追加**跨 Agent 共用**的资料库只读工具（`list_candidates` /
#   `list_products`）。它们与店秘书手里的是**同一个实现**
#   （`modules/library/tools.py`，SHARED 层）——
#   若各家各写一份，就是「同一判定两份实现 ⇒ 至少一份永远测不到」。
product_research_tools = [
    StructuredTool.from_function(
        coroutine=_analyze_blue_ocean_tool,
        name="analyze_blue_ocean",
        description=(
            "蓝海品类挖掘：按低竞争 + 有需求 + 有利润的标准筛选候选商品，返回蓝海评分排序列表。"
            "当用户想找蓝海机会/挖掘蓝海品类/看某个品类值不值得做/"
            "看有没有竞争小又赚钱的品类时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_analyze_profit_tool,
        name="analyze_profit",
        description=(
            "利润分析：按售价、成本、FBA 费用、广告费计算净利润/ROI/盈亏平衡点。"
            "当用户想算利润/算 ROI/看这个产品赚不赚钱/算成本时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_analyze_pain_points_tool,
        name="analyze_pain_points",
        description=(
            "痛点分析：分析某产品 ASIN 的用户评论，提炼痛点与改进方向。"
            "当用户想分析用户痛点/看差评/找产品改进点时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_compare_competitors_tool,
        name="compare_competitor_listings",
        description=(
            "竞品 Listing 对比（选品视角）：对比多个竞品 ASIN 的 Listing 质量、价格、优劣势，给出参考建议。"
            "当用户想对比竞品/分析竞争对手/看竞品优劣势时使用。"
            "★ 与竞品情报模块的 compare_competitors 区分：那个是多维指标对比（价格/评分/评论/BSR/性价比），本工具聚焦 Listing 质量与选品参考。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_save_candidate_tool,
        name="save_candidate",
        description=(
            "把商品加入候选选品库（草稿池，待评审）。"
            "当用户想把某个商品加进选品库/候选库/候选池/入库/保存到选品库时使用。"
            "能拿到 ASIN 或商品标题就带上；都拿不到也**可以直接调用**（参数留空），"
            "工具会返回一句**追问**，把它原样转达给用户即可 —— 不要自己编 ASIN，"
            "也不要改存别的商品充数。"
        ),
        metadata=SIDE_EFFECT_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_get_candidate_tool,
        name="get_candidate",
        description=(
            "查看某个候选选品的完整详情（ASIN/售价/评分/评审状态/备注等）。"
            "当用户想细看某个候选/这个品到底怎么样/把它的情况调出来时使用。"
            "先用 list_candidates 拿到候选，再用本工具看详情。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_review_candidate_tool,
        name="review_candidate",
        description=(
            "给候选选品打评审结论：淘汰 / 转评审中 / 退回待评审。"
            "当用户说这个品不要了/淘汰掉/先挂起来再评审时使用。"
            "★「通过并推进产品库」要用 approve_candidate，不要用本工具。"
        ),
        metadata=SIDE_EFFECT_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_approve_candidate_tool,
        name="approve_candidate",
        description=(
            "评审通过：把候选选品正式推进自有产品库（建一条待完善 Listing 的 SPU 草稿），"
            "候选保留为已通过基线。"
            "当用户说通过/录取/就定这个了/推进产品库/准备上架物料时使用。"
            "★ 这是候选进产品库的唯一通道，会改库。"
        ),
        metadata=SIDE_EFFECT_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_query_market_insight_tool,
        name="query_market_insight",
        description=(
            "读**选品大盘**（类目级市场洞察快照）：回答「哪些类目值得做 / 哪个类目"
            "蓝海分最高 / 哪个类目需求最旺 / 哪个类目竞争最松 / 类目价格带如何」"
            "这类**类目层面**的问题。"
            f"可按 {_market_sort_hint()} 排序（不传则按 "
            f"{MARKET_SNAPSHOT_SPEC.default_sort}）；"
            f"可按 {_market_filter_hint()} 过滤。"
            "★ 与 analyze_blue_ocean 的分工：本工具读**已入库的类目大盘数据**"
            "（蓝海评分 / 搜索量 / 卖家数 / 价格带…）；analyze_blue_ocean 是"
            "**现挖一批可入库的候选商品**。问「哪个品类蓝海分最高」用本工具。"
            "★ category_path 必须**完整精确匹配**、不支持模糊匹配："
            "不确定路径就先别传这个参数，把类目列表取回来自己挑。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
] + build_library_tools(resolve=_resolve_shop_id)
