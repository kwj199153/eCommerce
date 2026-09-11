"""
选品分析 Agent (Product Research Agent)

继承 BaseAgent 基类，实现跨境电商选品分析的核心能力。

功能模块：
1. 蓝海品类挖掘 - 发现高潜力低竞争的细分市场
2. 痛点机会识别 - 分析竞品评论提取用户痛点
3. SKU 利润计算 - FBA费用/定价策略/ROI分析
4. 竞品深度对比 - 多维度对比竞品优劣势
5. 季节性趋势 - 市场热度时间轴
6. 避坑指南 - 侵权风险/合规检查

设计来源：
- 推理循环：继承 ai_infra.base_agent.BaseAgent
- 工具调用：使用 platforms.amazon.AmazonAdapter 获取数据
- HITL 机制：关键操作（如导出报告）需人工审批

升级特性（Phase 8）：
- ✅ DashScope Qwen LLM 智能增强分析
- ✅ 自动降级到模拟响应
"""

import json
from typing import List, Dict, Any, Optional, AsyncIterable
from datetime import datetime

from pydantic import BaseModel, Field

from platforms import get_platform_adapter, PlatformType
from platforms.base import (
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
    CompetitorAnalysis,
)

# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    class LLMEnabledAgent:
        ENABLE_LLM = False
        def __init__(self): pass


# ====== 数据模型 ======

class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型：table/chart/text/report


class BlueOceanOpportunity(BaseModel):
    """蓝海机会"""
    category: str = Field(..., description="品类名称")
    search_volume: int = Field(..., description="月搜索量")
    competition: float = Field(..., description="竞争指数（0-1）")
    trend: str = Field(default="", description="趋势方向")
    opportunity_score: float = Field(..., description="机会评分（0-100）")
    reason: str = Field(default="", description="推荐理由")
    suggested_price_range: str = Field(default="", description="建议售价区间")
    estimated_margin: str = Field(default="", description="预估利润率")


class ProfitAnalysis(BaseModel):
    """利润分析结果"""
    product_name: str
    cost_price: float  # 采购成本
    selling_price: float  # 售价
    fees: FeeStructure
    total_cost: float
    net_profit: float
    roi_percentage: float
    break_even_quantity: int  # 盈亏平衡销量


class PainPointAnalysis(BaseModel):
    """痛点分析结果"""
    product_asin: str
    total_reviews_analyzed: int
    negative_review_count: int
    pain_points: List[Dict[str, Any]]  # [{pain_point, count, percentage}]
    improvement_suggestions: List[str]
    market_gap_score: float  # 市场空白度评分


class ResearchReport(BaseModel):
    """选品研究报告"""
    report_id: str
    created_at: str
    query: str
    platform: str
    summary: str
    opportunities: List[BlueOceanOpportunity] = []
    profit_analysis: Optional[ProfitAnalysis] = None
    pain_point_analysis: Optional[PainPointAnalysis] = None
    competitor_analysis: List[CompetitorAnalysis] = []
    recommendations: List[str] = []
    confidence_level: str  # high / medium / low


# ====== System Prompt ======

PRODUCT_RESEARCH_SYSTEM_PROMPT = """
你是一位专业的**跨境电商选品分析师**，拥有 8 年 Amazon 运营经验，擅长：

## 核心能力

### 1️⃣ 蓝海品类挖掘
- 通过关键词数据分析发现高搜索量、低竞争的细分市场
- 识别新兴趋势和季节性机会
- 评估市场容量和进入门槛

### 2️⃣ 竞品深度分析
- 拆解竞品的 Listing 质量、价格策略、用户反馈
- 提取差评中的共性痛点和未满足需求
- 发现差异化切入点和市场空白

### 3️⃣ 利润与风险评估
- 精确计算 FBA 费用、广告成本、净利润
- 评估供应链风险和资金周转周期
- 判断侵权风险和合规要求

## 工作原则

1. **数据驱动**：所有结论必须有数据支撑，不凭感觉
2. **结构化输出**：用表格、列表、评分等方式清晰呈现
3. **可执行建议**：给出具体的行动项，而非空泛的建议
4. **风险提示**：主动指出潜在风险和避坑要点
5. **诚实客观**：不确定的信息标注 confidence: low

## 输出格式

根据用户问题类型，选择合适的输出格式：
- **蓝海分析**：表格 + 机会评分 + 推荐理由
- **利润计算**：明细表 + ROI + 盈亏平衡点
- **痛点分析**：痛点云图 + 改进方向 + 市场空白
- **竞品对比**：雷达图数据 + 优劣势列表
- **综合报告**：完整的研究报告结构

## 当前平台

当前聚焦 **Amazon 美国站**，使用美元计价。
"""


# ====== 选品 Agent 实现 ======

class ProductResearchAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
    """
    选品分析 Agent

    Phase 2: 独立实现核心功能（不依赖 BaseAgent 的 LLM 调用）
    Phase 3: 集成 BaseAgent 实现完整的 LangGraph 推理循环
    Phase 8: 接入 DashScope Qwen LLM 实现智能增强

    使用示例：
        agent = ProductResearchAgent()

        # 蓝海挖掘
        result = await agent.invoke("帮我找厨房用品类的蓝海机会")

        # 利润计算
        result = await agent.invoke("分析便携式咖啡研磨器的利润空间")
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-max"       # 分析任务用最强模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    def __init__(self, platform: str = "amazon"):
        """
        初始化选品 Agent

        Args:
            platform: 目标平台（默认 amazon）
        """
        # 初始化 LLM 基类
        if LLM_AVAILABLE:
            super().__init__()

        self.platform = platform
        self.adapter = get_platform_adapter(platform)
        self.agent_name = "ProductResearcher"
        self.system_prompt = PRODUCT_RESEARCH_SYSTEM_PROMPT

    async def invoke(self, query: str, context_id: str = None) -> AgentResponse:
        """
        同步调用 Agent（简单任务）

        Args:
            query: 用户查询
            context_id: 会话上下文 ID（可选）

        Returns:
            AgentResponse 包含结果和展示数据
        """
        return await self._process_query(query)

    async def stream(self, query: str, context_id: str = None) -> AsyncIterable[dict]:
        """
        流式调用 Agent（复杂任务，支持进度推送）

        Yields:
            进度事件：{type: "thinking"|"tool_call"|"result", data: ...}
        """
        yield {"type": "thinking", "data": f"正在分析: {query}"}

        # 1. 意图识别
        intent = await self._classify_intent(query)
        yield {"type": "progress", "data": f"已识别意图: {intent}"}

        # 2. 执行对应工具
        if intent == "blue_ocean":
            yield {"type": "tool_call", "data": "正在挖掘蓝海品类..."}
            result = await self._analyze_blue_ocean(query)
        elif intent == "profit":
            yield {"type": "tool_call", "data": "正在计算利润..."}
            result = await self._analyze_profit(query)
        elif intent == "pain_points":
            yield {"type": "tool_call", "data": "正在分析用户痛点..."}
            result = await self._analyze_pain_points(query)
        elif intent == "competitor":
            yield {"type": "tool_call", "data": "正在对比竞品..."}
            result = await self._analyze_competitors(query)
        else:
            # 通用对话
            result = await self._general_chat(query)

        yield {"type": "result", "data": result}

    # ====== 意图分类 ======

    async def _classify_intent(self, query: str) -> str:
        """
        分类用户意图

        Returns:
            blue_ocean / profit / pain_points / competitor / general
        """
        query_lower = query.lower()

        # 关键词匹配规则
        blue_ocean_keywords = ["蓝海", "机会", "选品", "挖掘", "品类", "趋势", "什么好卖"]
        profit_keywords = ["利润", "费用", "FBA", "成本", "ROI", "售价", "定价", "赚钱"]
        pain_keywords = ["痛点", "差评", "评论", "问题", "不满意", "抱怨"]
        competitor_keywords = ["对比", "竞品", "比较", "竞争对手", "analysis"]

        for kw in blue_ocean_keywords:
            if kw in query_lower:
                return "blue_ocean"

        for kw in profit_keywords:
            if kw in query_lower:
                return "profit"

        for kw in pain_keywords:
            if kw in query_lower:
                return "pain_points"

        for kw in competitor_keywords:
            if kw in query_lower:
                return "competitor"

        return "general"

    # ====== 核心分析方法 ======

    async def _analyze_blue_ocean(self, query: str) -> dict:
        """蓝海品类挖掘（支持 LLM 增强）"""
        # 1. 提取目标类目
        category = self._extract_category(query) or "general"

        # 2. 获取相关关键词数据
        keywords_to_check = self._generate_search_keywords(category)
        keyword_data_list = []
        for kw in keywords_to_check[:8]:  # 检查前8个关键词
            data = await self.adapter.get_keyword_data(kw)
            keyword_data_list.append(data)

        # 3. 计算机会评分并排序
        opportunities = []
        for kd in keyword_data_list:
            score = self._calculate_opportunity_score(kd)
            if score >= 50:  # 只保留高分机会
                opp = BlueOceanOpportunity(
                    category=kd.keyword,
                    search_volume=kd.search_volume,
                    competition=kd.competition,
                    trend=kd.trend_direction,
                    opportunity_score=score,
                    reason=self._generate_reason(kd),
                    suggested_price_range=self._estimate_price_range(category),
                    estimated_margin=self._estimate_margin(kd.competition),
                )
                opportunities.append(opp)

        # 按分数降序排列
        opportunities.sort(key=lambda x: x.opportunity_score, reverse=True)

        result = {
            "type": "blue_ocean_analysis",
            "query": query,
            "category": category,
            "opportunities": [opp.dict() for opp in opportunities[:5]],  # Top 5
            "summary": f"在「{category}」领域发现 {len(opportunities)} 个蓝海机会",
        }

        # ====== LLM 增强：智能总结与建议 ======
        if LLM_AVAILABLE and self.ENABLE_LLM:
            try:
                llm_result = await self.llm_structured(
                    user_message=f"""
基于以下蓝海分析数据，请提供：
1. **市场机会总结**（2-3句话概括）
2. **Top 3 推荐进入的细分品类**（附理由）
3. **风险提示**（可能的市场壁垒或竞争威胁）
4. **行动建议**（具体的下一步行动）

数据：
{json.dumps([{'keyword': o['category'], 'score': o['opportunity_score'], 'volume': o['search_volume']} for o in result['opportunities']], ensure_ascii=False)}
""",
                    system_prompt=self.get_prompt_template("product_research", market="全球"),
                    output_format="json",
                )

                if llm_result.success and isinstance(llm_result.content, dict):
                    result["llm_insights"] = llm_result.content
                    result["enhanced"] = True
                    result["llm_fallback"] = llm_result.fallback

            except Exception as e:
                logger.warning(f"Blue ocean LLM enhancement failed: {e}")

        return result

    async def _analyze_profit(self, query: str) -> dict:
        """SKU 利润分析"""
        # 1. 尝试从查询中提取产品信息
        product_info = self._extract_product_info(query)

        # 2. 如果有 ASIN，获取产品详情
        if product_info.get("asin"):
            product = await self.adapter.get_product_detail(product_info["asin"])
        else:
            # 使用模拟数据或用户提供的参数
            product = ProductData(
                product_id="estimated",
                title=product_info.get("name", "待定产品"),
                price=product_info.get("price", 29.99),
                platform=self.adapter.platform_type,
            )

        # 3. 计算费用
        fees = self.adapter.calculate_fees(
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
        }

    async def _analyze_pain_points(self, query: str) -> dict:
        """痛点机会识别"""
        # 1. 提取 ASIN 或产品名称
        asin = self._extract_asin(query)
        if not asin:
            return {"error": "请提供产品 ASIN 进行痛点分析"}

        # 2. 获取评论（重点看差评）
        reviews_1_2_star = await self.adapter.get_reviews(asin, rating_filter=2)
        reviews_3_star = await self.adapter.get_reviews(asin, rating_filter=3)
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
        suggestions = self._generate_improvement_suggestions(pain_points_formatted)

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
        }

    async def _analyze_competitors(self, query: str) -> dict:
        """竞品对比分析"""
        # 1. 提取多个 ASIN
        asins = self._extract_multiple_asins(query)
        if len(asins) < 2:
            return {"error": "请提供至少 2 个产品 ASIN 进行对比"}

        # 2. 批量分析竞品
        competitor_results = await self.adapter.analyze_competitors(asins)

        return {
            "type": "competitor_analysis",
            "query": query,
            "competitors": [c.dict() for c in competitor_results],
            "summary": f"已完成 {len(competitor_results)} 个竞品的深度对比",
        }

    async def _general_chat(self, query: str) -> dict:
        """通用对话（调用 LLM）"""
        # TODO: 集成真实 LLM 调用
        return {
            "type": "general_response",
            "query": query,
            "response": f"收到您的关于「{query}」的问题。作为选品分析师，我可以帮您：\n\n"
                       f"1. 🔍 挖掘蓝海品类机会\n"
                       f"2. 💰 计算 SKU 利润空间\n"
                       f"3. 📊 分析竞品用户痛点\n"
                       f"4. ⚔️ 对比多个竞品\n\n"
                       f"请告诉我您想了解哪个方面？",
        }

    async def stream_chat(self, query: str) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        对话类意图走 LLM 流式；结构化意图（蓝海/利润/痛点/竞品）退化为一次性文本。

        Yields:
            文本片段（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        intent = await self._classify_intent(query)

        # 结构化意图：走 invoke 一次性返回（含结构化数据）
        if intent in ("blue_ocean", "profit", "pain_points", "competitor"):
            result = await self.invoke(query)
            yield result.content
            return

        # 对话类：走 LLM 流式
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
            result = await self._general_chat(query)
            yield result.get("response", "")
            return

        try:
            async for chunk in self.llm_stream(
                query,
                system_prompt=self.get_prompt_template("product_research", market="全球"),
                model=self.DEFAULT_MODEL,
                temperature=0.7,
                max_tokens=1024,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[product_research] stream_chat failed: {e}")
            result = await self._general_chat(query)
            yield result.get("response", "")

    # ====== 工具函数（供 LLM 调用）======

    async def _tool_search_blue_ocean(self, category: str) -> List[BlueOceanOpportunity]:
        """工具：搜索蓝海品类"""
        result = await self._analyze_blue_ocean(f"帮我找{category}类的蓝海机会")
        return [BlueOceanOpportunity(**opp) for opp in result["opportunities"]]

    async def _tool_analyze_profit(self, asin: str, cost_price: float = None) -> ProfitAnalysis:
        """工具：分析 SKU 利润"""
        query = f"分析 {asin} 的利润"
        if cost_price:
            query += f"，采购成本 ${cost_price}"
        result = await self._analyze_profit(query)
        return ProfitAnalysis(**result["analysis"])

    async def _tool_extract_pain_points(self, asin: str) -> PainPointAnalysis:
        """工具：提取产品痛点"""
        result = await self._analyze_pain_points(f"分析 {asin} 的用户痛点")
        return PainPointAnalysis(**result["analysis"])

    async def _tool_compare_competitors(self, asins: List[str]) -> List[CompetitorAnalysis]:
        """工具：对比竞品"""
        result = await self._analyze_competitors(f"对比这些产品: {', '.join(asins)}")
        return [CompetitorAnalysis(**c) for c in result["competitors"]]

    async def _tool_get_keyword_data(self, keyword: str) -> KeywordData:
        """工具：获取关键词数据"""
        return await self.adapter.get_keyword_data(keyword)

    async def _tool_search_products(self, query: str) -> List[ProductData]:
        """工具：搜索产品"""
        return await self.adapter.search_products(query)

    # ====== 内部辅助方法 ======

    @staticmethod
    def _extract_category(query: str) -> Optional[str]:
        """从查询中提取类目"""
        categories = {
            "厨房": "kitchen", "家居": "home", "电子": "electronics",
            "户外": "outdoor", "运动": "sports", "宠物": "pet",
            "美妆": "beauty", "办公": "office", "母婴": "baby",
            "服装": "clothing", "玩具": "toys", "园艺": "garden",
        }
        for cn, en in categories.items():
            if cn in query or en in query.lower():
                return en
        return None

    @staticmethod
    def _generate_search_keywords(category: str) -> List[str]:
        """生成搜索关键词列表"""
        keyword_templates = {
            "kitchen": ["coffee grinder", "portable blender", "air fryer accessories"],
            "home": ["desk organizer", "storage bins", "led strip lights"],
            "electronics": ["wireless charger", "bluetooth speaker", "usb hub"],
            "outdoor": ["camping gear", "solar lights", "garden tools"],
            "sports": ["yoga mat", "resistance bands", "water bottle"],
            "pet": ["automatic feeder", "cat tree", "dog harness"],
            "general": ["smart home", "organizer", "portable", "wireless"],
        }
        base = keyword_templates.get(category, keyword_templates["general"])
        # 添加修饰词
        modifiers = ["portable", "smart", "mini", "professional", "premium"]
        return base + [f"{m} {b}" for m in modifiers[:2] for b in base[:2]]

    @staticmethod
    def _calculate_opportunity_score(keyword_data: KeywordData) -> float:
        """
        计算机会评分（0-100）

        公式：
        score = (search_volume_factor * 40) +
               (low_competition_factor * 35) +
               (trend_factor * 25)
        """
        # 搜索量因子（对数缩放）
        import math
        if keyword_data.search_volume > 0:
            sv_normalized = min(math.log10(keyword_data.search_volume + 1) / 5, 1)
        else:
            sv_normalized = 0
        sv_score = sv_normalized * 40

        # 低竞争因子（竞争越低越好）
        comp_score = (1 - keyword_data.competition) * 35

        # 趋势因子
        trend_scores = {"rising": 25, "stable": 15, "declining": 0}
        trend_score = trend_scores.get(keyword_data.trend_direction, 15)

        return round(sv_score + comp_score + trend_score, 1)

    @staticmethod
    def _generate_reason(keyword_data: KeywordData) -> str:
        """生成推荐理由"""
        reasons = []

        if keyword_data.trend_direction == "rising":
            reasons.append(f"搜索量呈上升趋势 (+{keyword_data.search_volume:,}/月)")

        if keyword_data.competition < 0.5:
            reasons.append(f"竞争度较低 ({keyword_data.competition:.0%})")

        if keyword_data.search_volume > 20000:
            reasons.append("市场需求充足")

        if keyword_data.suggested_bid and keyword_data.suggested_bid < 1.5:
            reasons.append(f"广告成本低 (${keyword_data.suggested_bid:.2f})")

        return "；".join(reasons) if reasons else "综合指标表现良好"

    @staticmethod
    def _estimate_price_range(category: str) -> str:
        """估算建议售价区间"""
        ranges = {
            "kitchen": "$15-$45", "home": "$12-$35", "electronics": "$20-$80",
            "outdoor": "$18-$55", "sports": "$15-$40", "pet": "$20-$60",
        }
        return ranges.get(category, "$15-$50")

    @staticmethod
    def _estimate_margin(competition: float) -> str:
        """估算利润率"""
        if competition < 0.4:
            return "35%-50%"
        elif competition < 0.7:
            return "25%-35%"
        else:
            return "15%-25%"

    @staticmethod
    def _extract_product_info(query: str) -> dict:
        """从查询中提取产品信息"""
        info = {}

        # 尝试提取价格
        import re
        prices = re.findall(r'\$(\d+\.?\d*)', query)
        if prices:
            info["price"] = float(prices[0])

        # 尝试提取 ASIN
        asin_match = re.search(r'[Bb]\d{9}', query)
        if asin_match:
            info["asin"] = asin_match.group().upper()
        else:
            # 尝试提取产品名称（简化处理）
            info["name"] = query.replace("分析", "").replace("利润", "").strip()[:50]

        return info

    @staticmethod
    def _extract_asin(query: str) -> Optional[str]:
        """提取单个 ASIN"""
        import re
        match = re.search(r'[Bb]\d{9}', query)
        return match.group().upper() if match else None

    @staticmethod
    def _extract_multiple_asins(query: str) -> List[str]:
        """提取多个 ASIN"""
        import re
        return re.findall(r'[Bb]\d{9}', query.upper())

    @staticmethod
    def _generate_improvement_suggestions(pain_points: List[dict]) -> List[str]:
        """基于痛点生成改进建议"""
        suggestions = []
        pain_mapping = {
            "电池续航不足": "开发长续航版本或支持快充",
            "连接不稳定": "优化蓝牙/WiFi模块，强调稳定连接",
            "质量问题": "提升材质和工艺，增加质保期",
            "APP问题": "重构 APP，简化操作流程",
            "缺少功能": "调研用户需求，补充核心功能",
            "使用困难": "优化产品设计，提供详细教程",
            "速度慢": "升级硬件配置，提升性能",
            "性价比低": "优化供应链降低成本，或提升附加值",
        }

        seen = set()
        for pp in pain_points[:5]:
            pain = pp["pain_point"]
            if pain in pain_mapping and pain not in seen:
                suggestions.append(pain_mapping[pain])
                seen.add(pain)

        return suggestions[:4]  # 最多返回4条建议

    async def _process_query(self, query: str) -> AgentResponse:
        """处理查询（内部方法）"""
        intent = await self._classify_intent(query)

        if intent == "blue_ocean":
            result = await self._analyze_blue_ocean(query)
        elif intent == "profit":
            result = await self._analyze_profit(query)
        elif intent == "pain_points":
            result = await self._analyze_pain_points(query)
        elif intent == "competitor":
            result = await self._analyze_competitors(query)
        else:
            result = await self._general_chat(query)

        return AgentResponse(
            content=result.get("summary") or json.dumps(result, ensure_ascii=False, indent=2),
            data=result,
            display_type=result.get("type", "general"),
        )
