# -*- coding: utf-8 -*-
"""选品 Agent 的**分析编排层**（P0-6 第二刀：从 `agent_product_research.py` 外移）。

## 这一层是什么

4 个分析器的**领域逻辑**：取数（adapter）→ 计算（纯逻辑层）→ 组装结果 dict。
原先它们是 `ProductResearchAgent` 上的 4 个私有方法，共 325 行、
约占那个 2375 行 God Class 的七分之一。

## 与第一刀（`agent_helpers.py`）的区别 —— 也是本层的方法论

第一刀的入选判据是「函数体里没有 `self`」，所以能靠**继承**（mixin）做到调用点零改动。
本层不是：它们**必须**用数据源与会话状态。于是这里选**显式传参**，不重施 mixin：

    藏进 mixin 基类 ＝ 让耦合从「可以数的参数」变成「看不见的继承链」，
    门禁再也数不出这个类实际依赖什么 —— 那是自欺。

所以本模块的函数签名本身就是**依赖清单**，每一条都能被门禁与读者直接核对：

    adapter         数据源（原 `self.adapter`）
    query           用户问句
    context_id      会话标识（透传，用于回写缓存）
    session         会话状态容器（原 `self._session(context_id)`）；None ⇒ 不写
    structured_llm  LLM 增强回调（原 `self.llm_structured`）；None ⇒ 跳过增强
    system_prompt   增强用的系统提示词（原 `self.get_prompt_template(...)`）

## 纯逻辑层用**直接函数调用**，不是继承

原先 `self._extract_category(...)` 这些方法来自 mixin；本模块把它们取成
**模块级别名**（见下方 `_extract_category = ResearchHelpersMixin._extract_category`），
于是函数体与改前**只差一个 `self.` 前缀** —— 这既是可读性，也让
「外移是否真的逐字搬走」变成可机检的事（`.workbuddy/probes/r336-p0-6b/ast_parity.py`）。

## 主文件侧

`ProductResearchAgent._analyze_*` 保留**同名薄壳**，体里只做一件事：
把依赖显式传进来再委托。之所以不删掉方法、直接改调用点 ——
`tests/test_product_research_blue_ocean.py` / `..._candidate_flow.py` /
`..._intent_routing.py` 共 13 处按 `agent._analyze_*(...)` 调用，
那是本仓既有的测试契约。

## 归位约束（门禁会钉住）

`tests/test_product_research_analyzer_layer.py` 断言本模块：
  · 4 个 `analyze_*` 函数体里不出现 `self`；
  · 不 import `agent_product_research`（不许反向回流）；
  · 不 import 数据库 / 会话持久化 / 路由 / HIL 相关模块；
  · 只允许依赖 `platforms.base`（adapter 接口与数据类）。
"""
import json
from typing import Any, Awaitable, Callable, List, MutableMapping, Optional

from core.logger import get_logger

from platforms.base import PlatformAdapter, ProductData

from .agent_helpers import ResearchHelpersMixin
from .agent_models import BlueOceanOpportunity, PainPointAnalysis, ProfitAnalysis

logger = get_logger("product_research.analyzers")


# ====== 纯逻辑层别名（与主文件原先的 `self._x` 一一对应）======
#
# ★ 为什么取别名而不是每次写全 `ResearchHelpersMixin._extract_category`：
#   ① 函数体与改前只差 `self.` 前缀 ⇒ 「逐字搬运」可被机检（见 ast_parity 探针）；
#   ② 这些是 `@staticmethod`，通过类访问拿到的就是函数本身，
#      别名与 `ResearchHelpersMixin._x` **是同一对象** ⇒ 不会造出第二份实现。

_extract_category = ResearchHelpersMixin._extract_category
_generate_search_keywords = ResearchHelpersMixin._generate_search_keywords
_calculate_opportunity_score = ResearchHelpersMixin._calculate_opportunity_score
_generate_reason = ResearchHelpersMixin._generate_reason
_estimate_price_range = ResearchHelpersMixin._estimate_price_range
_estimate_margin = ResearchHelpersMixin._estimate_margin
_generate_improvement_suggestions = ResearchHelpersMixin._generate_improvement_suggestions
_extract_product_info = ResearchHelpersMixin._extract_product_info
_extract_asin = ResearchHelpersMixin._extract_asin
_extract_multiple_asins = ResearchHelpersMixin._extract_multiple_asins


async def analyze_blue_ocean(
    adapter: PlatformAdapter,
    query: str,
    context_id: Optional[str] = None,
    *,
    session: Optional[MutableMapping] = None,
    structured_llm: Optional[Callable[..., Awaitable[Any]]] = None,
    system_prompt: str = "",
) -> dict:
    """
    蓝海品类挖掘（支持 LLM 增强）

    类目识别为 None 时**不再兜底成 "general" 泛词表**（那批词在关键词库中
    命中不到，会走「未匹配 → 随机估算」路径，分数随机、结论不可信），
    改用跨类目精选的全类目高潜关键词（`_TRENDING_KEYWORDS`）。

    `context_id` 用于把本轮结果**按会话**缓存（经 `session` 回写），
    供「把第 1 个加进选品库」这类指代解析；不传则落在默认会话。
    """
    # 1. 提取目标类目（None = 未识别出具体类目 → 全类目扫描）
    category = _extract_category(query)

    # 2. 获取相关关键词数据
    keywords_to_check = _generate_search_keywords(category)
    keyword_data_list = []
    for kw in keywords_to_check[:8]:  # 检查前8个关键词
        data = await adapter.get_keyword_data(kw)
        keyword_data_list.append(data)

    # 3. 计算机会评分并排序
    opportunities = []
    for kd in keyword_data_list:
        score = _calculate_opportunity_score(kd)
        if score >= 50:  # 只保留高分机会
            opp = BlueOceanOpportunity(
                category=kd.keyword,
                search_volume=kd.search_volume,
                competition=kd.competition,
                trend=kd.trend_direction,
                opportunity_score=score,
                reason=_generate_reason(kd),
                suggested_price_range=_estimate_price_range(category),
                estimated_margin=_estimate_margin(kd.competition),
            )
            opportunities.append(opp)

    # 按分数降序排列
    opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

    top_opportunities = opportunities[:5]  # Top 5
    total = len(opportunities)

    # ===== 词 → 商品：把「方向」落到「具体的货」 =====
    #
    # 为什么必须做这一步：词级机会**没有 ASIN**，而候选选品库以 `asin` 为核心
    # 标识。只给词，老板既存不进库、也没法横向对比；「把这个品加进选品库」
    # 这类指令也就无从解析。这里把每条机会回查商品池，并把**该词的市场层指标**
    # 随商品带下去（市场层 + 商品层两个维度都要留，不是二选一）。
    opp_dicts: List[dict] = []
    products: List[dict] = []
    seen_asins: set = set()

    for opp in top_opportunities:
        try:
            matched = await adapter.match_products(opp.category, limit=2)
        except Exception as e:
            logger.warning(f"[product_research] match_products failed for {opp.category}: {e}")
            matched = []

        opp_dict = opp.dict()
        opp_dict["matched_count"] = len(matched)
        opp_dicts.append(opp_dict)

        for m in matched:
            asin = m.get("asin")
            if not asin or asin in seen_asins:
                continue
            seen_asins.add(asin)
            products.append({
                **m,
                "source_keyword": opp.category,
                "keyword_search_volume": opp.search_volume,
                "keyword_competition": opp.competition,
                "keyword_trend": opp.trend,
                "keyword_opportunity_score": opp.opportunity_score,
            })

    # 面向老板的文案：绝不回显内部标识（如 general）；未指定类目时说人话
    where = f"在「{category}」领域" if category else "全类目高潜方向"
    prefix = where if category else "未识别出具体类目，已按全类目高潜方向扫描，"
    if total == 0:
        summary = f"{where}暂未发现评分达标的蓝海机会，建议换个类目或放宽筛选条件"
    elif products:
        summary = f"{prefix}发现 {total} 个蓝海方向，对应 {len(products)} 个候选商品"
    else:
        summary = f"{prefix}发现 {total} 个蓝海方向，但商品池里暂无匹配的具体商品"

    result = {
        "type": "blue_ocean_analysis",
        "query": query,
        "category": category or "all",
        # 主列表（商品层）：可直接对比 / 入库
        "products": products,
        # 市场层：词与其搜索量/竞争度/趋势（词不再是独立卡片，降级为商品的来源标注）
        "opportunities": opp_dicts,
        "summary": summary,
    }

    # 缓存本轮结果，供「把第 N 个 / 这个品加进选品库」这类指代解析。
    # 按会话存 —— 否则 A 会话挖的蓝海会被 B 会话的「第 1 个」取走。
    #
    # ★ 由调用方把容器传进来（`session`），本函数不持有会话机制：
    #   没有容器就只是「不缓存」，而不是「退化去写一个全局字典」。
    if session is not None:
        session["last_blue_ocean"] = result

    # ====== LLM 增强：智能总结与建议 ======
    #
    # ★ 回传 `structured_llm=None` ⇒ 跳过增强（等价于主类 `ENABLE_LLM=False`）：
    #   原先判的是 `self.ENABLE_LLM` 这个类常量，现在判「依赖是否被注入」——
    #   语义相同，但「有没有 LLM」变成签名里看得见的一件事。
    if structured_llm is not None:
        try:
            llm_result = await structured_llm(
                user_message=f"""
基于以下蓝海分析数据，请提供：
1. **市场机会总结**（2-3句话概括）
2. **Top 3 推荐进入的细分品类**（附理由）
3. **风险提示**（可能的市场壁垒或竞争威胁）
4. **行动建议**（具体的下一步行动）

数据：
{json.dumps([{'keyword': o['category'], 'score': o['opportunity_score'], 'volume': o['search_volume']} for o in result['opportunities']], ensure_ascii=False)}
""",
                system_prompt=system_prompt,
                output_format="json",
            )

            if llm_result.success and isinstance(llm_result.content, dict):
                result["llm_insights"] = llm_result.content
                result["enhanced"] = True
                result["llm_fallback"] = llm_result.fallback

        except Exception as e:
            logger.warning(f"Blue ocean LLM enhancement failed: {e}")

    return result


async def analyze_profit(adapter: PlatformAdapter, query: str) -> dict:
    """SKU 利润分析"""
    # 1. 尝试从查询中提取产品信息
    product_info = _extract_product_info(query)

    # 2. 如果有 ASIN，获取产品详情
    product = None
    if product_info.get("asin"):
        product = await adapter.get_product_detail(product_info["asin"])
        if product is None and not product_info.get("price"):
            # 查不到详情又没给售价 → 没法算，别抛 AttributeError（会变成 500）
            return {
                "type": "profit_analysis",
                "query": query,
                "error": "查不到该 ASIN 的售价",
                "summary": (
                    f"没查到 {product_info['asin']} 的售价，先算不了利润。"
                    f"你可以把售价一起告诉我，比如「分析 {product_info['asin']} 的利润，售价 $29.99」。"
                ),
            }

    if product is None:
        # 使用用户提供的参数估算
        product = ProductData(
            product_id=product_info.get("asin") or "estimated",
            title=(
                product_info.get("name")
                or (f"ASIN {product_info['asin']}" if product_info.get("asin") else "待定产品")
            ),
            price=product_info.get("price", 29.99),
            platform=adapter.platform_type,
        )

    # 3. 计算费用
    fees = adapter.calculate_fees(
        price=product.price,
        category=product.category or "",
        weight_lbs=product_info.get("weight", 1.5),
    )

    # 4. 计算利润（假设采购成本为售价的 30%）
    cost_price = product.price * 0.30
    ad_cost = product.price * 0.15  # 广告 ACOS 15%
    total_cost = cost_price + fees.total_fees + ad_cost
    net_profit = product.price - total_cost
    roi = (net_profit / total_cost) * 100 if total_cost > 0 else 0
    break_even = int(total_cost / net_profit) if net_profit > 0 else 9999

    analysis = ProfitAnalysis(
        product_name=product.title,
        cost_price=round(cost_price, 2),
        selling_price=product.price,
        fees=fees,
        total_cost=round(total_cost, 2),
        net_profit=round(net_profit, 2),
        roi_percentage=round(roi, 1),
        break_even_quantity=break_even,
    )

    return {
        "type": "profit_analysis",
        "query": query,
        "product": product.title if product else "未知产品",
        "analysis": analysis.dict(),
        "fees_breakdown": {
            "采购成本": round(cost_price, 2),
            "平台佣金": round(fees.referral_fee_pct * product.price / 100, 2),
            "FBA配送费": fees.fba_fulfillment_fee,
            "仓储费": fees.storage_fee_monthly,
            "广告费": round(ad_cost, 2),
        },
        "summary": (
            f"{product.title}：售价 ${product.price:.2f}，"
            f"总成本 ${analysis.total_cost:.2f}"
            f"（采购 ${analysis.cost_price:.2f} + 平台费 ${fees.total_fees:.2f} + 广告 ${ad_cost:.2f}），"
            f"净利润 ${analysis.net_profit:.2f}，ROI {analysis.roi_percentage:.1f}%，"
            f"约 {break_even} 件回本。"
        ),
    }


async def analyze_pain_points(adapter: PlatformAdapter, query: str) -> dict:
    """痛点机会识别"""
    # 1. 提取 ASIN 或产品名称
    asin = _extract_asin(query)
    if not asin:
        return {
            "type": "pain_point_analysis",
            "query": query,
            "error": "需要产品 ASIN",
            "summary": (
                "痛点分析得先知道是哪个产品——把产品 ASIN（形如 B0C1234567）发我，"
                "我就去看它的中差评、提炼可改进点。"
            ),
        }

    # 2. 获取评论（重点看差评）
    reviews_1_2_star = await adapter.get_reviews(asin, rating_filter=2)
    reviews_3_star = await adapter.get_reviews(asin, rating_filter=3)
    all_negative = reviews_1_2_star + reviews_3_star

    # 3. 统计痛点频率
    pain_point_counts = {}
    for review in all_negative:
        for pp in review.pain_points:
            pain_point_counts[pp] = pain_point_counts.get(pp, 0) + 1

    total_reviews = len(all_negative)
    pain_points_sorted = sorted(
        pain_point_counts.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    pain_points_formatted = [
        {
            "pain_point": pp,
            "count": count,
            "percentage": round(count / total_reviews * 100, 1) if total_reviews > 0 else 0,
        }
        for pp, count in pain_points_sorted
    ]

    # 4. 生成改进建议
    suggestions = _generate_improvement_suggestions(pain_points_formatted)

    # 5. 计算市场空白度评分
    gap_score = min(100, sum([pp["percentage"] for pp in pain_points_formatted[:3]]))

    analysis = PainPointAnalysis(
        product_asin=asin,
        total_reviews_analyzed=len(all_negative),
        negative_review_count=len(reviews_1_2_star),
        pain_points=pain_points_formatted,
        improvement_suggestions=suggestions,
        market_gap_score=gap_score,
    )

    return {
        "type": "pain_point_analysis",
        "query": query,
        "asin": asin,
        "analysis": analysis.dict(),
        "top_pain_points": pain_points_formatted[:5],
        "summary": (
            f"{asin} 共分析 {len(all_negative)} 条中差评，"
            + (
                # 只报「最集中的 1 个」等于没说全——老板问「有哪些痛点」要的是清单
                "主要痛点：" + "、".join(
                    f"「{pp['pain_point']}」({pp['percentage']}%)"
                    for pp in pain_points_formatted[:3]
                )
                if pain_points_formatted else "暂未提炼出明显痛点"
            )
            + f"，市场空白度评分 {gap_score}。"
        ),
    }


async def analyze_competitors(adapter: PlatformAdapter, query: str) -> dict:
    """竞品对比分析"""
    # 1. 提取多个 ASIN
    asins = _extract_multiple_asins(query)
    if len(asins) < 2:
        return {
            "type": "competitor_analysis",
            "query": query,
            "competitors": [],
            "error": "需要至少 2 个产品 ASIN",
            "summary": (
                "竞品对比需要至少 2 个产品 ASIN（形如 B0C1234567）。"
                "把两个竞品的 ASIN 发我即可；也可以在右侧「竞品圈选」里挑好，再让我对比。"
            ),
        }

    # 2. 批量分析竞品
    competitor_results = await adapter.analyze_competitors(asins)
    if not competitor_results:
        return {
            "type": "competitor_analysis",
            "query": query,
            "competitors": [],
            "error": "未取到竞品数据",
            "summary": (
                f"拿到了 ASIN（{', '.join(asins)}），但平台没返回可对比的竞品数据。"
                "换个 ASIN 或稍后重试。"
            ),
        }

    return {
        "type": "competitor_analysis",
        "query": query,
        "competitors": [c.dict() for c in competitor_results],
        "summary": f"已对比 {len(competitor_results)} 个竞品：{', '.join(asins)}。",
    }
