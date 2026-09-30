"""
选品分析模块 - 业务逻辑层

封装 Agent 调用、数据处理和业务规则。
"""

import json
from typing import List, Optional

from core.library_query import query_library

from modules.product_research.schemas import (
    BlueOceanRequest,
    ProfitAnalysisRequest,
    PainPointRequest,
    CompetitorCompareRequest,
    ChatResponse,
)
from modules.product_research.agent_product_research import ProductResearchAgent
from modules.product_research.context_target_gate import context_target_rejection
from modules.product_research.spec import MARKET_SNAPSHOT_SPEC
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

    async def save_candidate(
        self,
        query: str,
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> dict:
        """
        把商品写入选品库（对话直达）—— **工具路径与面板流程的公共入口**。

        ★ 为什么要有这一层（第 200 轮）：
          此前 `tools.py` 的 `save_candidate` 工具**绕过 service 直调**
          `agent._save_candidate`。于是同一个能力有两个入口形状
          （4 个只读工具走 `_service.x`、写库工具走 `_service.agent.x`），
          而按 service 层做能力盘点**会漏掉它**（第 199 轮的盘点实测就漏了）。
          补上这一层之后，5 个工具的形态统一为「工具 → service → agent」。

        ★ 本层**不做第二份判定**：解析优先级（显式 ASIN / 序数 / 点名 /
          纯指代）、同店铺同 ASIN 判重、必填缺失时的**追问**，全部仍在 Agent 侧
          `_save_candidate` 里。这里只是那条路径的转发 —— 两层各写一份解析逻辑
          迟早会漂移（本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到）。

        `shop_id` 必须是**已校验归属**的店铺 ID（来自 `get_current_shop_id*`
        依赖注入）：拿不到归属时 `_write_candidates` 会**硬拒绝写入**，绝不猜一个。
        `context_id` 用于取本会话的待补槽位与上一轮蓝海结果；
        不传会退化成全局共享（多会话串数据）。
        """
        return await self.agent._save_candidate(
            query, context_id=context_id, shop_id=shop_id
        )

    async def chat(
        self,
        message: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
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
        # ★★★ 第 251 轮：前置条件门禁 —— **在 Agent 之前**。
        #   点名的技能需要「作用对象」而本次没给 ⇒ 直接拒答，连模型都不叫。
        #   理由见 `context_target_gate` 模块 docstring：实测同一个会话里
        #   第一次它正确拒答、第二次（历史里已有上一次的结论）就直接照答，
        #   说明守不守规矩取决于上下文里有什么 ⇒ 不能靠叮嘱，只能靠代码。
        #   两条路径（流式 / 非流式）共用同一个判定：流式不是另一套智能。
        rejection = context_target_rejection()
        if rejection is not None:
            return ChatResponse(reply=rejection, display_type="text", data=None, suggestions=None)

        result = await self.agent.invoke(
            message, context_id=context_id, shop_id=shop_id, user_id=user_id
        )

        return ChatResponse(
            reply=result.content,
            display_type=result.display_type,
            data=result.data,
            suggestions=self._generate_suggestions(result),
        )

    async def resume_approval(
        self,
        context_id: str,
        decision: str,
        *,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
        reason: Optional[str] = None,
        args: Optional[dict] = None,
        feedback: Optional[str] = None,
    ):
        """
        人工审批决策透传（详见 Agent 侧 `ProductResearchAgent.resume_approval`）。

        `shop_id` 与 `user_id` 都必须是**服务端已校验**的值：
        前者来自 `get_current_shop_id_optional` 依赖，后者来自 `current_user.id`。
        续跑时被中断的工具会重新执行并**真的写库**，归属口径与首轮**必须同源**。
        """
        return await self.agent.resume_approval(
            context_id,
            decision,
            user_id=user_id,
            shop_id=shop_id,
            reason=reason,
            args=args,
            feedback=feedback,
        )

    async def stream_chat(
        self,
        message: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ):
        """
        流式对话入口（返回逐 token 异步迭代器）。

        `context_id` 必须一路带到 Agent —— 入库的「待补槽位」与「上一轮蓝海结果」
        都按会话隔离，不传就退化成全局共享（多会话会串数据）。

        `shop_id` 同理必须一路带到写库那一步（**已校验归属**，来自 router 依赖）：
        流的最后一段可能就是"入库回执"，漏传会让写入被拒。
        """
        # ★★★ 第 251 轮：与非流式**同一个**前置门禁（同一判据只允许一份表达）。
        #   流式这里必须 `yield` 正文而不是抛错：前端把非 `delta` 的失败
        #   转译成"随机失败"，而这是**可解释的业务结论**，要能直接读。
        rejection = context_target_rejection()
        if rejection is not None:
            yield rejection
            return

        async for chunk in self.agent.stream_chat(
            message, context_id=context_id, shop_id=shop_id, user_id=user_id
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


# ====== 市场洞察大盘云图（第 305 轮 · 蓝海挖掘大盘云图 · 第 325 轮收口内核）======

async def get_market_insight_treemap(shop_id: "str | None") -> dict:
    """聚合 `market_snapshots` 为 Treemap 节点列表。

    ★ 纯 DB 查询，不挂 Agent —— 大盘云图是「确定性可算」，不是「需判断」，
      按本仓「工具 vs 技能」分界（`analyze_*` 也可能零 LLM 调用）走读库直查。

    ★ 隔离：`MARKET_SNAPSHOT_SPEC` 由内核 `base_select()` 无条件挂 `scoped()`
      （`shop_id=None` ⇒ `col IS NULL` ⇒ 查不到任何行，fail-closed）。

    ★ 真源标记：读出的行若带 `is_demo=True`（演示 mock 快照）⇒ `degraded=True`，
      否则 `degraded=False`。真实账号无 mock 快照 ⇒ 空列表 + degraded=False，
      前端据此显示「空态 + 提示接入第三方数据」，而不是编一个假大盘。

    ★ 第 325 轮：本函数从「**手写** `select` + `scoped()` + 内存 `seen` 集合去重」
      改为调 `core.library_query` 内核 + `MARKET_SNAPSHOT_SPEC`（在
      `modules/product_research/spec.py` 声明）。**同一份声明**也被 Agent 工具
      `query_market_insight` 消费 ⇒ 面板上的数字与对话里的数字必然一致
      （本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到）。

      本函数因此只剩**两件事**：字段投影 + 人话文案。
        · 去重口径 → spec（`dedup_key=(site, category_path)`、
          `dedup_order=(snapshot_date desc, blue_ocean_score desc, id desc)`）
          = 「同一类目取最新快照」，与改前**内存去重**的字典序逐字对齐；
        · 排序 → spec（`default_sort="blue_ocean_score"`，同分由 `tie_breaker` 兜底）。

      ★ 与改前的**可观察差异**只有一处：`nodes` 的**数组顺序**变了
        （改前 `snapshot_date desc, blue_ocean_score desc`）。

        ★ 它**不是**「界面不可见」—— 第一版我在这里这么写过，那半句是**错的**：
          `MarketInsightConfig.vue::reload()` 里有一处 `nodes.value[0]` 做
          「默认选中的类目」，右侧六维度明细就挂在它上面 ⇒ 默认选中项从
          「最新快照日里分最高的」变成「**分最高的**」。这是**有意**换的
          （更贴合大盘的用途）；完整论证与「动它要回来对账」的义务见
          `modules/product_research/spec.py` 的 `default_sort` 段。

        响应形状（`nodes` / `total_categories` / `degraded` / `source` / `message`）
        与 node 的 15 个键**逐字段未动**（判据：
        `.workbuddy/probes/r325/r325_b3_parity_nodb.py` 拿改前实现逐字段比对）。
    """
    rows = await query_library(MARKET_SNAPSHOT_SPEC, shop_id)
    latest = [row[0] for row in rows]

    if not latest:
        return {
            "nodes": [],
            "total_categories": 0,
            "degraded": False,
            "source": "empty",
            "message": "暂无市场洞察数据。请先接入第三方类目数据源，或切换到演示账号查看示例。",
        }

    # 演示 mock 判定：任一行 is_demo=True 即 degraded
    degraded = any(bool(getattr(r, "is_demo", False)) for r in latest)

    nodes = [
        {
            "name": r.category_name or r.category_path.split("/")[-1],
            "value": float(r.search_volume or 0),  # 面积权重 = 搜索热度
            "category_path": r.category_path,
            "site": r.site,
            "listing_count": r.listing_count,
            "price_min": r.price_min,
            "price_max": r.price_max,
            "price_median": r.price_median,
            "seller_count": r.seller_count,
            "search_volume": r.search_volume,
            "new_seller_count": r.new_seller_count,
            "search_growth": r.search_growth,
            "price_trend": r.price_trend,
            "blue_ocean_score": r.blue_ocean_score,
            "snapshot_date": r.snapshot_date,
        }
        for r in latest
    ]

    return {
        "nodes": nodes,
        "total_categories": len(nodes),
        "degraded": degraded,
        "source": "mock_seed" if degraded else "third_party",
        "message": (
            "当前为演示 mock 数据，非真实第三方市场数据，仅用于功能演示。"
            if degraded
            else "市场洞察数据已就绪。"
        ),
    }
