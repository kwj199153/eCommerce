"""
选品分析模块 → 主 Agent 工具注册表

把 ProductResearchService 的细粒度能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 listing_tools.py 一致）：
- 只包「语义明确」的细粒度方法（蓝海挖掘 / 利润计算 / 痛点分析 / 竞品对比），
  **不包** `chat` / `stream_chat` 这类粗粒度入口（交给 agent 内部 _classify_intent
  关键词表再判断一次，会与主 Agent 的 LLM 判断冲突）。
- 参数用扁平字段（照 listing 范式），工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

import json
from typing import List, Optional

from langchain_core.tools import StructuredTool

from .service import product_research_service
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


def _dump(resp) -> str:
    """统一序列化：dict 直接 dump，Pydantic 走 model_dump。"""
    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False, default=str)
    if hasattr(resp, "model_dump"):
        return json.dumps(resp.model_dump(), ensure_ascii=False, default=str)
    return str(resp)


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
    #     工具路径仍被拒、`create_candidate` 零调用；而 Agent 自带的
    #     `_tool_save_candidate`（读双 ContextVar）同场次正常落库。
    from .agent_product_research import _current_context_id, _current_shop_id

    return _dump(await _service.agent._save_candidate(
        query,
        context_id=_current_context_id.get(),
        shop_id=_current_shop_id.get(),
    ))


# ====== 工具注册表 ======

product_research_tools = [
    StructuredTool.from_function(
        coroutine=_analyze_blue_ocean_tool,
        name="analyze_blue_ocean",
        description=(
            "蓝海品类挖掘：按低竞争 + 有需求 + 有利润的标准筛选候选商品，返回蓝海评分排序列表。"
            "当用户想找蓝海机会/选品/挖掘蓝海品类/看有没有竞争小又赚钱的品类时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_profit_tool,
        name="analyze_profit",
        description=(
            "利润分析：按售价、成本、FBA 费用、广告费计算净利润/ROI/盈亏平衡点。"
            "当用户想算利润/算 ROI/看这个产品赚不赚钱/算成本时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_analyze_pain_points_tool,
        name="analyze_pain_points",
        description=(
            "痛点分析：分析某产品 ASIN 的用户评论，提炼痛点与改进方向。"
            "当用户想分析用户痛点/看差评/找产品改进点时使用。"
        ),
    ),
    StructuredTool.from_function(
        coroutine=_compare_competitors_tool,
        name="compare_competitors",
        description=(
            "竞品对比：对比多个竞品 ASIN 的 Listing 质量、价格、优劣势，给出参考建议。"
            "当用户想对比竞品/分析竞争对手/看竞品优劣势时使用。"
        ),
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
    ),
]
