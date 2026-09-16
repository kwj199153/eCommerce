"""
选品分析模块 - 业务逻辑层

封装 Agent 调用、数据处理和业务规则。
"""

import json
from typing import List, Optional

from modules.product_research.schemas import (
    BlueOceanRequest,
    ProfitAnalysisRequest,
    PainPointRequest,
    CompetitorCompareRequest,
    ChatResponse,
)
from modules.product_research.agent_product_research import ProductResearchAgent
from platforms import get_platform_adapter
from platforms.amazon.client import CATEGORY_KEYS, get_mock_products


class ProductResearchService:
    """
    选品分析服务层

    职责：
    - 接收 API 请求参数
    - 调用 Agent 执行分析
    - 格式化返回数据
    - 处理异常情况
    """

    def __init__(self, platform: str = "amazon"):
        self.platform = platform
        self.agent = ProductResearchAgent(platform=platform)
        self.adapter = get_platform_adapter(platform)

    async def analyze_blue_ocean(self, request: BlueOceanRequest) -> dict:
        """
        执行蓝海品类挖掘（MVP 完整版）

        Args:
            request: 蓝海分析请求参数

        Returns:
            分析结果（包含商品列表和蓝海评分）
        """
        import time
        start_time = time.time()

        # MVP 阶段：使用 Mock 数据模拟蓝海挖掘结果
        # TODO: 接入真实数据源（SP-API / Shopee API / 爬虫）
        mock_products = self._generate_mock_blue_ocean_products(request)

        # 根据筛选条件过滤
        filtered = self._apply_filters(mock_products, request)

        # 计算蓝海评分并排序
        scored_products = self._calculate_blue_ocean_scores(filtered, request)

        # 统计各等级数量
        premium_count = sum(1 for p in scored_products if p.blue_ocean_score >= 70)
        moderate_count = sum(1 for p in scored_products if 40 <= p.blue_ocean_score < 70)
        high_competition_count = sum(1 for p in scored_products if p.blue_ocean_score < 40)

        execution_time = round(time.time() - start_time, 2)

        return {
            "total_candidates": len(scored_products),
            "premium_count": premium_count,
            "moderate_count": moderate_count,
            "high_competition_count": high_competition_count,
            "products": [p.model_dump() if hasattr(p, 'model_dump') else p for p in scored_products],
            "analysis_summary": (
                f"基于 {request.marketplace or 'amazon_us'} 站点 "
                f"{request.category[-1] if request.category else '全类目'} 的蓝海挖掘完成，"
                f"共发现 {len(scored_products)} 个候选商品，"
                f"其中 {premium_count} 个优质蓝海机会（评分≥70）。"
            ),
            "filters_applied": {
                "marketplace": request.marketplace,
                "category": request.category,
                "price_range": f"${request.price_min or 0} - ${request.price_max or '不限'}",
                "max_reviews": request.max_reviews,
                "min_monthly_sales": request.min_monthly_sales,
                "min_roi": f"{request.min_roi}%",
                "exclude_seasonal": request.exclude_seasonal,
                "exclude_brand_dominant": request.exclude_brand_dominant,
                "exclude_high_risk": request.exclude_high_risk,
            },
            "execution_time_seconds": execution_time,
        }

    def _generate_mock_blue_ocean_products(self, request: BlueOceanRequest) -> List[dict]:
        """
        取候选商品池（MVP 阶段）。

        修复记录：原先此处内联了一份 ~18 条、ASIN 为 `B0CXXXX00N` 的自有商品池，
        与 `platforms/amazon/client.py::MOCK_PRODUCTS`（选品 Agent 用的池子）互不相通，
        且类目键用了 `sports_outdoors`/`pet_supplies`/`toys_games`，而前端下发的是
        `sports`/`pet`/`toys` → `category_pool.get()` 永远落空，选任何类目都退回
        `home_kitchen`。

        现统一改为读 `get_mock_products()`（唯一权威源），类目键以 `CATEGORY_KEYS`
        为准。字段名同步规范化为 `review_count` / `estimated_monthly_sales`。
        """
        # 目标类目：request.category 形如 ['home_kitchen', 'kitchen_dining']，取顶层键
        target_category = (request.category[0] if request.category else None) or None
        products = get_mock_products(target_category)

        # 无价格限制时混合多个类目，避免结果过度集中在单一类目
        # （仅在指定了具体类目时补混合；未指定类目时全池已在手，重复追加会出重）
        if target_category and not request.price_min and not request.price_max:
            extra: List[dict] = []
            for key in CATEGORY_KEYS:
                if key != target_category:
                    extra.extend(get_mock_products(key)[:2])
            products = products + extra

        return products

    def _apply_filters(self, products: List[dict], request: BlueOceanRequest) -> List[dict]:
        """
        应用筛选条件。

        字段名使用统一池的规范名（`review_count` / `estimated_monthly_sales`），
        不再使用旧的 `reviews` / `sales` 别名。
        """
        filtered = []
        for p in products:
            # 价格过滤
            if request.price_min and p["price"] < request.price_min:
                continue
            if request.price_max and p["price"] > request.price_max:
                continue
            # 评论数过滤
            if p["review_count"] > request.max_reviews:
                continue
            # 月销量过滤
            if p["estimated_monthly_sales"] < request.min_monthly_sales:
                continue
            # ROI 过滤
            if p["roi"] < request.min_roi:
                continue
            # 高级筛选：季节性、品牌垄断、高风险（Mock 阶段简化处理）
            if request.exclude_seasonal and "Christmas" in p.get("title", ""):
                continue
            if request.exclude_brand_dominant and p["review_count"] > 500:
                continue

            filtered.append(p)

        # 如果过滤后为空，放宽条件返回部分结果作为建议
        if len(filtered) == 0 and len(products) > 0:
            # 返回 ROI 最高的前 5 个作为"接近匹配"
            filtered = sorted(products, key=lambda x: x["roi"], reverse=True)[:5]

        return filtered

    def _calculate_blue_ocean_scores(self, products: List[dict], request: BlueOceanRequest):
        """计算蓝海评分"""
        from modules.product_research.schemas import BlueOceanProductItem

        scored = []
        for p in products:
            # 蓝海评分算法（综合维度）
            # 1. 需求分 (0-40)：月销量越高需求越大
            demand_score = min((p["estimated_monthly_sales"] / 3000) * 40, 40)

            # 2. 竞争分 (0-40)：评论越少竞争越小
            competition_score = max(40 - (p["review_count"] / 5), 5)

            # 3. 利润分 (0-20)：ROI 越高利润空间越大
            profit_score = min((p["roi"] / 50) * 20, 20)

            blue_ocean_score = int(demand_score + competition_score + profit_score)
            blue_ocean_score = max(min(blue_ocean_score, 98), 5)  # 限制在 5-98 范围

            scored.append(BlueOceanProductItem(
                asin=p["asin"],
                title=p["title"],
                price=p["price"],
                estimated_monthly_sales=p["estimated_monthly_sales"],
                review_count=p["review_count"],
                roi_estimated=round(p["roi"], 1),
                blue_ocean_score=blue_ocean_score,
                marketplace=request.marketplace or "amazon_us",
                category=p["category"],
            ))

        # 按蓝海评分降序排列
        return sorted(scored, key=lambda x: x.blue_ocean_score, reverse=True)

    async def analyze_profit(self, request: ProfitAnalysisRequest) -> dict:
        """
        执行利润分析

        Args:
            request: 利润分析请求参数

        Returns:
            利润计算结果
        """
        # 解析尺寸
        try:
            dims = [float(x) for x in request.dimensions.split("x")]
            dimensions_tuple = tuple(dims) if len(dims) == 3 else (10, 7, 5)
        except ValueError:
            dimensions_tuple = (10, 7, 5)

        # 如果有 ASIN，获取产品信息补充
        product_name = request.product_name
        if request.asin:
            product = await self.adapter.get_product_detail(request.asin)
            if product:
                product_name = product.title
                # 使用真实售价覆盖用户输入（如果用户想用默认值）
                if request.selling_price <= 0:
                    request.selling_price = product.price

        # 计算费用
        fees = self.adapter.calculate_fees(
            price=request.selling_price,
            category=request.category,
            weight_lbs=request.weight_lbs,
            dimensions_inch=dimensions_tuple,
        )

        # 计算各项成本
        referral_fee = fees.referral_fee_pct * request.selling_price / 100
        ad_cost = request.selling_price * (request.ad_acos_pct / 100)
        total_cost = request.cost_price + fees.total_fees + ad_cost
        net_profit = request.selling_price - total_cost
        roi = (net_profit / total_cost * 100) if total_cost > 0 else 0
        margin_pct = (net_profit / request.selling_price * 100) if request.selling_price > 0 else 0
        break_even = int(total_cost / net_profit) if net_profit > 0 else 99999

        return {
            "type": "profit_analysis",
            "product": product_name or f"自定义产品 (${request.selling_price})",
            "analysis": {
                "product_name": product_name or "未知产品",
                "cost_price": round(request.cost_price, 2),
                "selling_price": request.selling_price,
                "fees": fees.dict(),
                "total_cost": round(total_cost, 2),
                "net_profit": round(net_profit, 2),
                "roi_percentage": round(roi, 1),
                "break_even_quantity": break_even,
            },
            "fees_breakdown": {
                "采购成本": round(request.cost_price, 2),
                "平台佣金": round(referral_fee, 2),
                "FBA配送费": fees.fba_fulfillment_fee,
                "仓储费": fees.storage_fee_monthly,
                "广告费": round(ad_cost, 2),
            },
            "margin_percentage": round(margin_pct, 1),
        }

    async def analyze_pain_points(self, request: PainPointRequest) -> dict:
        """
        执行痛点分析

        Args:
            request: 痛点分析请求参数

        Returns:
        """
        query = f"分析 {request.asin} 的用户痛点"
        result = await self.agent.invoke(query)

        return result.data

    async def compare_competitors(self, request: CompetitorCompareRequest) -> dict:
        """
        执行竞品对比

        Args:
            request: 竞品对比请求参数

        Returns:
            对比结果
        """
        query = f"对比这些产品: {', '.join(request.asins)}"
        result = await self.agent.invoke(query)

        # 添加对比总结
        competitors = result.data.get("competitors", [])
        if len(competitors) >= 2:
            best = max(competitors, key=lambda c: c.get("listing_quality_score", 0))
            worst = min(competitors, key=lambda c: c.get("listing_quality_score", 100))

            result.data["comparison_summary"] = (
                f"共对比 {len(competitors)} 个竞品。"
                f"最佳 Listing：{best.get('title', 'N/A')[:30]}... "
                f"(评分 {best.get('listing_quality_score', 0)})"
            )
            result.data["recommendation"] = (
                f"建议参考「{best.get('title', 'N/A')[:20]}...」的优点，"
                f"同时避免「{worst.get('title', 'N/A')[:20]}...」的短板。"
            )

        return result.data

    async def chat(
        self,
        message: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
    ) -> ChatResponse:
        """
        自然语言对话接口

        Args:
            message: 用户消息
            context_id: 会话上下文 ID
            shop_id: **已校验归属**的店铺 ID（由 router 的依赖注入传入）。
                     入库类意图必需；缺失时 `_write_candidates` 会拒绝写入。

        Returns:
            对话响应
        """
        result = await self.agent.invoke(
            message, context_id=context_id, shop_id=shop_id
        )

        return ChatResponse(
            reply=result.content,
            display_type=result.display_type,
            data=result.data,
            suggestions=self._generate_suggestions(result),
        )

    async def stream_chat(
        self,
        message: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
    ):
        """
        流式对话入口（返回逐 token 异步迭代器）。

        `context_id` 必须一路带到 Agent —— 入库的「待补槽位」与「上一轮蓝海结果」
        都按会话隔离，不传就退化成全局共享（多会话会串数据）。

        `shop_id` 同理必须一路带到写库那一步（**已校验归属**，来自 router 依赖）：
        流的最后一段可能就是"入库回执"，漏传会让写入被拒。
        """
        async for chunk in self.agent.stream_chat(
            message, context_id=context_id, shop_id=shop_id
        ):
            yield chunk

    @staticmethod
    def _generate_suggestions(agent_response) -> List[str]:
        """基于响应生成后续建议"""
        display_type = getattr(agent_response, 'display_type', 'general')
        data = getattr(agent_response, 'data', {}) or {}

        suggestions_map = {
            "blue_ocean_analysis": [
                "深入分析某个品类的利润空间",
                "查看该品类的竞品情况",
                "导出完整选品报告",
            ],
            "profit_analysis": [
                "调整售价重新计算",
                "查看同类产品的市场定价",
                "分析该产品的用户评价",
            ],
            "pain_point_analysis": [
                "基于痛点设计改进方案",
                "对比其他竞品的痛点",
                "评估改进后的市场机会",
            ],
            "competitor_analysis": [
                "深入分析某个竞品的评论",
                "计算进入该市场的成本",
                "寻找差异化切入点",
            ],
        }

        base_suggestions = suggestions_map.get(display_type, [
            "挖掘更多蓝海机会",
            "分析某个产品的利润空间",
            "了解竞品的优劣势",
        ])

        return base_suggestions


# ====== 全局单例 ======
#
# router 与 tools **必须共用同一个实例**：Agent 的会话状态（待补入库槽位、
# 上一轮蓝海结果）按 context_id 挂在实例上。
# 早前 router 与 tools 各 `ProductResearchService()` 一次（tools.py 里那句
# 「单例 service（与 router 同源）」的注释其实从未成立）→ 两个 Agent 实例 →
# 「先对话挖蓝海，再让 LLM 工具路由去入库」时，工具那边看不到这份蓝海结果，
# 只能退化成「找不到要入库的商品」。
product_research_service = ProductResearchService()
