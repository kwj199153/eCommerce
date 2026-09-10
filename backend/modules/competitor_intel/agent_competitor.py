"""
竞品情报监控 Agent - Competitor Intelligence Agent
======================================
核心能力：
1. 竞品 Listing 监控（价格/排名/评论数变化）
2. ASIN 批量追踪与对比
3. 市场份额估算（基于 BSR）
4. 定价策略分析（价格弹性/促销节奏）
5. 竞品评论深度分析（优劣势对比）
6. 入侵者检测（新竞争者识别）
7. Buy Box 竞争分析
"""

from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import random
import re
from dataclasses import dataclass, asdict

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CompetitorProduct:
    """竞品数据模型"""
    asin: str
    title: str
    brand: str
    price: float
    currency: str = "USD"
    bsr_rank: int = 0
    review_count: int = 0
    rating: float = 0.0
    category: str = ""
    image_url: str = ""
    is_prime: bool = False
    buy_box_price: Optional[float] = None
    buy_box_seller: str = ""
    stock_status: str = "In Stock"
    last_updated: str = ""


@dataclass
class PriceHistory:
    """价格历史记录"""
    date: str
    price: float
    was_in_stock: bool = True


@dataclass
class RankingHistory:
    """排名历史记录"""
    date: str
    bsr_rank: int


@dataclass
class ReviewInsight:
    """评论洞察"""
    aspect: str  # positive/negative/neutral
    topic: str
    sentiment_score: float  # -1 to 1
    mention_count: int
    example_quotes: List[str]


@dataclass
class MarketShareEstimate:
    """市场份额估算"""
    competitor_asin: str
    brand_name: str
    estimated_market_share: float  # percentage
    bsr_rank: int
    revenue_estimate: float
    trend: str  # rising/stable/declining


@dataclass
class PricingStrategy:
    """定价策略分析"""
    strategy_type: str  # premium/economy/competitive/dynamic
    base_price: float
    avg_discount: float
    promo_frequency: str  # high/medium/low
    price_elasticity: float
    price_volatility: float
    recommendations: List[str]


@dataclass
class IntruderAlert:
    """入侵者警报"""
    asin: str
    title: str
    brand: str
    entry_date: str
    price: float
    threat_level: str  # high/medium/low
    reasons: List[str]
    our_product_affected: bool = False


# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    class LLMEnabledAgent:
        ENABLE_LLM = False
        def __init__(self): pass


class CompetitorIntelligenceAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
    """
    竞品情报监控 Agent

    升级特性（Phase 8）：
    - ✅ DashScope Qwen LLM 智能竞品分析
    - ✅ 自动降级到规则引擎
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-max"       # 分析任务用最强模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    # 模拟竞品数据库
    _competitor_db: Dict[str, CompetitorProduct] = {}

    # 价格历史数据库
    _price_history_db: Dict[str, List[PriceHistory]] = {}

    # 排名历史数据库
    _ranking_history_db: Dict[str, List[RankingHistory]] = {}

    def __init__(self):
        # 初始化 LLM 基类
        if LLM_AVAILABLE:
            super().__init__()

        self.agent_name = "competitor_intel"
        self._initialize_mock_data()

    async def _llm_insights(self, context: str, max_tokens: int = 800) -> Optional[str]:
        """
        LLM 增强：基于竞品数据生成专业洞察结论。

        LLM 不可用或失败时返回 None，由调用方降级到规则生成。
        """
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
            return None
        try:
            result = await self.llm_chat(
                user_message=context,
                system_prompt=self.get_prompt_template("competitor_intel"),
                model=self.DEFAULT_MODEL,
                temperature=0.6,
                max_tokens=max_tokens,
            )
            if result.success and not result.fallback and result.content:
                return result.content.strip()
        except Exception as e:
            logger.warning(f"[competitor_intel] LLM insights failed: {e}")
        return None

    def _initialize_mock_data(self):
        """初始化模拟数据"""
        competitors = [
            CompetitorProduct(
                asin="B08ABC1234",
                title="Premium Wireless Bluetooth Earbuds with Active Noise Cancellation",
                brand="SoundMax Pro",
                price=79.99,
                bsr_rank=1523,
                review_count=12456,
                rating=4.5,
                category="Electronics > Headphones",
                is_prime=True,
                buy_box_price=79.99,
                buy_box_seller="SoundMax Pro",
            ),
            CompetitorProduct(
                asin="B08DEF5678",
                title="Wireless Earbuds Bluetooth 5.3 IPX7 Waterproof 40H Playtime",
                brand="TechBeat",
                price=49.99,
                bsr_rank=892,
                review_count=8234,
                rating=4.3,
                category="Electronics > Headphones",
                is_prime=True,
                buy_box_price=49.99,
                buy_box_seller="TechBeat Official",
            ),
            CompetitorProduct(
                asin="B08GHI9012",
                title="True Wireless Earbuds Hi-Fi Sound Quality Touch Control",
                brand="AudioElite",
                price=129.99,
                bsr_rank=3456,
                review_count=3421,
                rating=4.7,
                category="Electronics > Headphones",
                is_prime=True,
                buy_box_price=129.99,
                buy_box_seller="AudioElite Store",
            ),
            CompetitorProduct(
                asin="B08JKL3456",
                title="Budget Bluetooth Earbuds Long Battery Life Microphone",
                brand="ValueSound",
                price=29.99,
                bsr_rank=456,
                review_count=15678,
                rating=4.1,
                category="Electronics > Headphones",
                is_prime=False,
                buy_box_price=29.99,
                buy_box_seller="ValueSound Direct",
            ),
            CompetitorProduct(
                asin="BMNO789012",
                title="Pro Studio Monitor Headphones Noise Cancelling Over Ear",
                brand="StudioMaster",
                price=199.99,
                bsr_rank=5678,
                review_count=892,
                rating=4.8,
                category="Electronics > Headphones",
                is_prime=True,
                buy_box_price=189.99,
                buy_box_seller="Third-Party Seller",
            ),
        ]

        for comp in competitors:
            self._competitor_db[comp.asin] = comp
            comp.last_updated = datetime.now().isoformat()
            self._generate_history_data(comp.asin)

    def _generate_history_data(self, asin: str):
        """生成历史数据（模拟30天）"""
        base_date = datetime.now() - timedelta(days=30)
        base_price = self._competitor_db[asin].price

        # 价格历史（带随机波动）
        price_history = []
        for i in range(30):
            date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            # 随机波动 ±10%，偶尔有促销
            if random.random() < 0.1:
                price = base_price * 0.85  # 促销价
            else:
                price = base_price * (1 + random.uniform(-0.05, 0.08))
            price_history.append(PriceHistory(date=date, price=round(price, 2)))
        self._price_history_db[asin] = price_history

        # 排名历史（带趋势）
        base_bsr = self._competitor_db[asin].bsr_rank
        ranking_history = []
        current_rank = base_bsr
        for i in range(30):
            date = (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
            # 排名随机波动 ±20%
            change = int(current_rank * random.uniform(-0.15, 0.2))
            current_rank = max(1, current_rank + change)
            ranking_history.append(RankingHistory(date=date, bsr_rank=current_rank))
        self._ranking_history_db[asin] = ranking_history

    async def analyze(self, query: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        主入口：意图分类 + 路由到对应能力
        """
        intent = self._classify_intent(query)

        handlers = {
            "monitor": self._monitor_competitor,
            "track_batch": self._track_batch_asins,
            "market_share": self._analyze_market_share,
            "pricing": self._analyze_pricing_strategy,
            "reviews": self._analyze_competitor_reviews,
            "intruder": self._detect_intruders,
            "buy_box": self._analyze_buy_box,
            "compare": self._compare_competitors,
        }

        handler = handlers.get(intent, self._general_analysis)
        result = await handler(query, context)
        result["intent"] = intent
        return result

    def _classify_intent(self, query: str) -> str:
        """意图分类"""
        q = query.lower()

        # 更具体的意图优先匹配
        if any(kw in q for kw in ["buy box", "购物车", "buybox"]):
            return "buy_box"
        if any(kw in q for kw in ["新进入", "入侵者", "intruder", "新卖家", "新品牌"]):
            return "intruder"
        if any(kw in q for kw in ["评论", "review", "评价", "口碑"]):
            return "reviews"
        if any(kw in q for kw in ["定价", "价格策略", "pricing", "price strategy", "调价"]):
            return "pricing"
        if any(kw in q for kw in ["市场份额", "market share", "市场占比", "格局"]):
            return "market_share"
        if any(kw in q for kw in ["批量", "batch", "多个", "一批", "对比", "compare"]):
            return "track_batch" if "asin" in q or "追踪" in q else "compare"
        if any(kw in q for kw in ["监控", "monitor", "追踪", "track", "跟踪", "变化"]):
            return "monitor"

        return "compare"  # 默认：竞品对比

    async def _monitor_competitor(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力1：竞品 Listing 监控"""
        asin = self._extract_asin(query) or context.get("asin") if context else None

        if not asin:
            # 返回所有竞品的最新状态
            monitored = []
            for comp in self._competitor_db.values():
                price_change = self._calculate_price_change(comp.asin)
                rank_change = self._calculate_rank_change(comp.asin)

                monitored.append({
                    "asin": comp.asin,
                    "title": comp.title[:60] + "...",
                    "brand": comp.brand,
                    "current_price": comp.price,
                    "price_change_7d": price_change,
                    "current_bsr": comp.bsr_rank,
                    "rank_change_7d": rank_change,
                    "review_count": comp.review_count,
                    "rating": comp.rating,
                    "stock_status": comp.stock_status,
                    "buy_box_owner": comp.buy_box_seller,
                    "last_updated": comp.last_updated,
                    "alerts": self._generate_alerts(comp),
                })

            summary = self._generate_monitor_summary(monitored)

            # ====== LLM 增强：监控总结 ======
            llm_context = f"""请基于以下竞品监控数据，生成一段专业的市场监控总结（150字以内，中文）：
- 共监控 {len(monitored)} 个竞品
- 价格变动: {', '.join(f'{m["brand"]}({m["price_change_7d"]:+.1f}%)' for m in monitored[:4])}
- 需要关注: {', '.join(m['brand'] for m in monitored if m['alerts'])[:50] or '无'}
请聚焦最值得关注的竞品动态和应对建议。"""
            llm_summary = await self._llm_insights(llm_context)
            if llm_summary:
                summary = llm_summary

            return {
                "type": "monitor_dashboard",
                "total_competitors": len(monitored),
                "competitors": monitored,
                "summary": summary,
            }

        # 单个ASIN深度监控
        comp = self._competitor_db.get(asin)
        if not comp:
            return {"error": f"未找到竞品 ASIN: {asin}"}

        return {
            "type": "single_monitor",
            "product": asdict(comp),
            "price_trend": [asdict(p) for p in self._price_history_db.get(asin, [])[-14:]],
            "ranking_trend": [asdict(r) for r in self._ranking_history_db.get(asin, [])[-14:]],
            "analysis": {
                "price_stability": self._analyze_price_stability(asin),
                "ranking_momentum": self._analyze_ranking_momentum(asin),
                "stock_pattern": self._analyze_stock_pattern(asin),
            },
        }

    async def _track_batch_asins(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力2：ASIN 批量追踪"""
        asins = self._extract_multiple_asins(query) or (context.get("asins") if context else [])

        if not asins:
            # 返回所有竞品的对比视图
            asins = list(self._competitor_db.keys())

        tracked = []
        for asin in asins:
            comp = self._competitor_db.get(asin)
            if comp:
                tracked.append({
                    "asin": asin,
                    "brand": comp.brand,
                    "title": comp.title[:50],
                    "price": comp.price,
                    "bsr": comp.bsr_rank,
                    "reviews": comp.review_count,
                    "rating": comp.rating,
                    "price_30d_low": min(p.price for p in self._price_history_db.get(asin, [])),
                    "price_30d_high": max(p.price for p in self._price_history_db.get(asin, [])),
                    "bsr_30d_best": min(r.bsr_rank for r in self._ranking_history_db.get(asin, [])),
                    "score": self._calculate_competitiveness_score(asin),
                })

        # 按综合得分排序
        tracked.sort(key=lambda x: x["score"], reverse=True)

        return {
            "type": "batch_track",
            "tracked_count": len(tracked),
            "competitors": tracked,
            "comparison_matrix": self._generate_comparison_matrix(tracked),
        }

    async def _analyze_market_share(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力3：市场份额分析"""
        category = self._extract_category(query) or context.get("category") if context else "Headphones"

        estimates = []
        total_revenue_estimate = 0

        for asin, comp in self._competitor_db.items():
            # 基于 BSR 估算市场份额（简化算法）
            # BSR 越低，市场份额越大
            base_share = max(0.5, 100 / (comp.bsr_rank ** 0.5))
            noise = random.uniform(0.8, 1.2)
            market_share = base_share * noise

            # 估算月营收（基于评论数和价格）
            daily_sales_est = comp.review_count * 0.02  # 假设每天销量约为评论数的2%
            monthly_revenue = daily_sales_est * 30 * comp.price

            trend = self._detect_trend(asin)

            estimates.append(MarketShareEstimate(
                competitor_asin=asin,
                brand_name=comp.brand,
                estimated_market_share=round(market_share, 2),
                bsr_rank=comp.bsr_rank,
                revenue_estimate=round(monthly_revenue, 2),
                trend=trend,
            ))
            total_revenue_estimate += monthly_revenue

        # 归一化市场份额
        total_share = sum(e.estimated_market_share for e in estimates)
        for e in estimates:
            e.estimated_market_share = round((e.estimated_market_share / total_share) * 100, 2)

        # 按市场份额排序
        estimates.sort(key=lambda x: x.estimated_market_share, reverse=True)

        return {
            "type": "market_share",
            "category": category,
            "total_market_estimate": round(total_revenue_estimate, 2),
            "competitors": [asdict(e) for e in estimates],
            "insights": self._generate_market_insights(estimates),
            "concentration_ratio": self._calculate_concentration_ratio(estimates),
        }

    async def _analyze_pricing_strategy(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力4：定价策略分析"""
        asin = self._extract_asin(query) or (context.get("asin") if context else None)

        target_asins = [asin] if asin else list(self._competitor_db.keys())

        strategies = []
        for comp_asin in target_asins:
            comp = self._competitor_db.get(comp_asin)
            if not comp:
                continue

            price_hist = self._price_history_db.get(comp_asin, [])
            if not price_hist:
                continue

            prices = [p.price for p in price_hist]
            avg_price = sum(prices) / len(prices)
            min_price = min(prices)
            max_price = max(prices)

            # 检测促销频率
            promo_days = sum(1 for p in price_hist if p.price < avg_price * 0.92)
            promo_freq = "high" if promo_days > 5 else ("medium" if promo_days > 2 else "low")

            # 计算平均折扣
            discounts = [(avg_price - p.price) / avg_price * 100 for p in price_hist if p.price < avg_price]
            avg_discount = sum(discounts) / len(discounts) if discounts else 0

            # 判断策略类型
            if avg_price > 100:
                strategy_type = "premium"
            elif avg_price < 40:
                strategy_type = "economy"
            elif promo_freq == "high":
                strategy_type = "dynamic"
            else:
                strategy_type = "competitive"

            # 价格波动率
            volatility = (max_price - min_price) / avg_price * 100 if avg_price > 0 else 0

            # 价格弹性（模拟）
            elasticity = round(random.uniform(-1.5, -2.5), 2)

            recommendations = self._generate_pricing_recommendations(
                strategy_type, avg_price, volatility, promo_freq
            )

            strategies.append(PricingStrategy(
                strategy_type=strategy_type,
                base_price=round(avg_price, 2),
                avg_discount=round(avg_discount, 1),
                promo_frequency=promo_freq,
                price_elasticity=elasticity,
                price_volatility=round(volatility, 1),
                recommendations=recommendations,
            ))

        return {
            "type": "pricing_strategy",
            "analyzed_count": len(strategies),
            "strategies": [asdict(s) for s in strategies],
            "market_positioning_map": self._generate_positioning_map(strategies),
        }

    async def _analyze_competitor_reviews(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力5：竞品评论深度分析"""
        asin = self._extract_asin(query) or (context.get("asin") if context else None)

        target_asins = [asin] if asin else list(self._competitor_db.keys())[:3]

        analyses = []
        for comp_asin in target_asins:
            comp = self._competitor_db.get(comp_asin)
            if not comp:
                continue

            # 模拟评论分析结果
            insights = self._mock_review_analysis(comp)
            analyses.append({
                "asin": comp_asin,
                "brand": comp.brand,
                "product": comp.title[:50],
                "overall_rating": comp.rating,
                "total_reviews": comp.review_count,
                "insights": [asdict(i) for i in insights],
                "swot": self._generate_review_swot(insights),
                "actionable_intelligence": self._extract_actionable_intel(insights, comp),
            })

        return {
            "type": "review_analysis",
            "analyzed_products": len(analyses),
            "analyses": analyses,
        }

    async def _detect_intruders(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力6：入侵者检测（新竞争者）"""
        category = self._extract_category(query) or (context.get("category") if context else "Headphones")

        # 模拟检测到的新进入者
        intruders = [
            IntruderAlert(
                asin="B0NEW001",
                title="Ultra Bass Wireless Earbuds 60H Battery graphene drivers",
                brand="NewWave Audio",
                entry_date=(datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                price=39.99,
                threat_level="high",
                reasons=[
                    "价格低于市场均价35%",
                    "7天内获得200+评论",
                    "使用石墨烯单元作为差异化卖点",
                    "Prime包邮 + 闪电发货",
                ],
                our_product_affected=True,
            ),
            IntruderAlert(
                asin="B0NEW002",
                title="AI-Powered Smart Earbuds Translation Health Monitoring",
                brand="FutureTech",
                entry_date=(datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d"),
                price=159.99,
                threat_level="medium",
                reasons=[
                    "AI功能作为差异化卖点",
                    "定位高端市场",
                    "健康监测功能创新",
                    "目前评论较少但增长快",
                ],
                our_product_affected=False,
            ),
            IntruderAlert(
                asin="B0NEW003",
                title="Kids Safe Volume Limited Wireless Earbuds Cute Design",
                brand="KidSound",
                entry_date=(datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d"),
                price=19.99,
                threat_level="low",
                reasons=[
                    "定位细分市场（儿童）",
                    "超低价策略",
                    "与我们目标客群重叠度低",
                ],
                our_product_affected=False,
            ),
        ]

        # 生成应对建议
        response_strategies = []
        for intruder in intruders:
            if intruder.threat_level == "high":
                response_strategies.append({
                    "target": intruder.asin,
                    "strategy": "immediate_response",
                    "actions": [
                        "立即分析其供应链成本结构",
                        "评估是否需要临时降价应对",
                        "加强我们产品的差异化营销",
                        "监控其评论寻找弱点",
                    ],
                    "priority": "P0",
                })
            elif intruder.threat_level == "medium":
                response_strategies.append({
                    "target": intruder.asin,
                    "strategy": "monitor_and_prepare",
                    "actions": [
                        "持续跟踪其销售趋势",
                        "准备差异化卖点材料",
                        "关注其广告投放策略",
                    ],
                    "priority": "P1",
                })
            else:
                response_strategies.append({
                    "target": intruder.asin,
                    "strategy": "watch_only",
                    "actions": ["定期检查其排名变化"],
                    "priority": "P2",
                })

        return {
            "type": "intruder_detection",
            "category": category,
            "detection_date": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "new_competitors": [asdict(i) for i in intruders],
            "threat_summary": {
                "high_threat": sum(1 for i in intruders if i.threat_level == "high"),
                "medium_threat": sum(1 for i in intruders if i.threat_level == "medium"),
                "low_threat": sum(1 for i in intruders if i.threat_level == "low"),
            },
            "response_strategies": response_strategies,
        }

    async def _analyze_buy_box(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力7：Buy Box 竞争分析"""
        asin = self._extract_asin(query) or (context.get("asin") if context else None)

        target_asins = [asin] if asin else list(self._competitor_db.keys())

        analyses = []
        for comp_asin in target_asins:
            comp = self._competitor_db.get(comp_asin)
            if not comp:
                continue

            # 模拟 Buy Box 数据
            buy_box_data = self._mock_buy_box_data(comp)

            analyses.append({
                "asin": comp_asin,
                "brand": comp.brand,
                "product": comp.title[:50],
                "buy_box_analysis": buy_box_data,
                "competitiveness_score": self._calculate_buy_box_competitiveness(buy_box_data),
            })

        return {
            "type": "buy_box_analysis",
            "analyzed_count": len(analyses),
            "analyses": analyses,
            "best_practices": self._generate_buy_box_best_practices(),
        }

    async def _compare_competitors(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力8：多维度竞品对比"""
        asins = self._extract_multiple_asins(query) or (context.get("asins") if context else [])

        if not asins:
            asins = list(self._competitor_db.keys())[:4]

        competitors = []
        for asin in asins:
            comp = self._competitor_db.get(asin)
            if comp:
                competitors.append(comp)

        if len(competitors) < 2:
            return {"error": "至少需要2个竞品进行对比"}

        recommendations = self._generate_comparison_recommendations(competitors)

        # ====== LLM 增强：对比结论 ======
        llm_context = f"""请基于以下竞品对比数据，生成 2-3 条关键竞争结论与建议（中文）：
- 对比竞品: {', '.join(f'{c.brand}(价格${c.price},评分{c.rating})' for c in competitors)}
- 差异化: {self._analyze_differentiation(competitors).get('key_differentiators', '无') if isinstance(self._analyze_differentiation(competitors), dict) else '待分析'}
请聚焦「哪个竞品最有威胁」和「如何差异化竞争」。"""
        llm_recs = await self._llm_insights(llm_context)
        if llm_recs:
            recommendations = [llm_recs] + recommendations[:2]

        # 多维度对比
        comparison = {
            "price_comparison": self._compare_dimension(competitors, "price", "lower_better"),
            "rating_comparison": self._compare_dimension(competitors, "rating", "higher_better"),
            "review_count_comparison": self._compare_dimension(competitors, "review_count", "higher_better"),
            "bsr_comparison": self._compare_dimension(competitors, "bsr_rank", "lower_better"),
            "value_score": self._calculate_value_scores(competitors),
            "overall_ranking": self._generate_overall_ranking(competitors),
            "differentiation_analysis": self._analyze_differentiation(competitors),
            "recommendations": recommendations,
        }

        return {
            "type": "competitor_comparison",
            "compared_count": len(competitors),
            "competitors": [{"asin": c.asin, "brand": c.brand, "title": c.title[:40]} for c in competitors],
            "comparison": comparison,
        }

    async def _general_analysis(self, query: str, context: Optional[Dict] = None) -> Dict:
        """通用分析（兜底）"""
        return {
            "type": "general",
            "message": "请明确您的需求，例如：'监控竞品 B08ABC1234' 或 '分析耳机类目市场份额'",
            "available_capabilities": [
                "竞品 Listing 监控（价格/排名/库存变化）",
                "ASIN 批量追踪对比",
                "市场份额分析",
                "定价策略分析",
                "竞品评论深度分析",
                "新竞争者入侵检测",
                "Buy Box 竞争分析",
                "多维度竞品对比",
            ],
        }

    # ==================== 工具方法 ====================

    def _extract_asin(self, text: str) -> Optional[str]:
        """提取 ASIN"""
        patterns = [r'\b([A-Z0-9]{10})\b', r'(?:asin|ASIN)[:\s]*([A-Z0-9]{10})']
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return match.group(1).upper()
        return None

    def _extract_multiple_asins(self, text: str) -> List[str]:
        """提取多个 ASIN"""
        asins = re.findall(r'\b([A-Z0-9]{10})\b', text.upper())
        # 过滤掉明显不是 ASIN 的（如纯数字）
        return [a for a in asins if not a.isdigit() and a in self._competitor_db]

    def _extract_category(self, text: str) -> Optional[str]:
        """提取类目"""
        categories = {
            "headphone": "Headphones", "earbud": "Earbuds",
            "phone case": "Phone Cases", "charger": "Chargers",
            "watch": "Smart Watches", "camera": "Cameras",
        }
        text_lower = text.lower()
        for key, cat in categories.items():
            if key in text_lower:
                return cat
        return None

    def _calculate_price_change(self, asin: str, days: int = 7) -> float:
        """计算价格变化百分比"""
        history = self._price_history_db.get(asin, [])
        if len(history) < days:
            return 0.0
        old_price = history[-days].price
        new_price = history[-1].price
        return round((new_price - old_price) / old_price * 100, 1)

    def _calculate_rank_change(self, asin: str, days: int = 7) -> int:
        """计算排名变化"""
        history = self._ranking_history_db.get(asin, [])
        if len(history) < days:
            return 0
        old_rank = history[-days].bsr_rank
        new_rank = history[-1].bsr_rank
        return new_rank - old_rank  # 正值表示排名下降

    def _generate_alerts(self, comp: CompetitorProduct) -> List[str]:
        """生成警报"""
        alerts = []
        price_change = self._calculate_price_change(comp.asin)
        rank_change = self._calculate_rank_change(comp.asin)

        if abs(price_change) > 15:
            direction = "降价" if price_change < 0 else "涨价"
            alerts.append(f"⚠️ 价格大幅{direction} {abs(price_change):.1f}%")

        if rank_change > 500:
            alerts.append(f"📉 排名下降 {rank_change} 位")
        elif rank_change < -300:
            alerts.append(f"📈 排名上升 {abs(rank_change)} 位")

        if comp.stock_status != "In Stock":
            alerts.append(f"🔴 库存状态: {comp.stock_status}")

        return alerts

    def _generate_monitor_summary(self, monitored: List[Dict]) -> Dict:
        """生成监控摘要"""
        price_drops = [m for m in monitored if m["price_change_7d"] < -5]
        rank_improvers = [m for m in monitored if m["rank_change_7d"] < -200]
        stock_issues = [m for m in monitored if m["stock_status"] != "In Stock"]

        return {
            "competitors_with_price_drops": len(price_drops),
            "competitors_improving_rank": len(rank_improvers),
            "stock_alerts": len(stock_issues),
            "key_events": [
                f"{len(price_drops)} 个竞品近期降价超过5%",
                f"{len(rank_improvers)} 个竞品排名显著提升",
                f"{len(stock_issues)} 个竞品有库存问题",
            ],
        }

    def _analyze_price_stability(self, asin: str) -> Dict:
        """分析价格稳定性"""
        history = self._price_history_db.get(asin, [])[-14:]
        if len(history) < 7:
            return {"stability": "unknown", "reason": "数据不足"}

        prices = [h.price for h in history]
        avg = sum(prices) / len(prices)
        variance = sum((p - avg) ** 2 for p in prices) / len(prices)
        std_dev = variance ** 0.5
        cv = (std_dev / avg * 100) if avg > 0 else 0

        if cv < 3:
            stability = "very_stable"
        elif cv < 8:
            stability = "stable"
        elif cv < 15:
            stability = "moderate"
        else:
            stability = "volatile"

        return {
            "stability": stability,
            "coefficient_of_variation": round(cv, 1),
            "avg_price": round(avg, 2),
            "min_price": round(min(prices), 2),
            "max_price": round(max(prices), 2),
        }

    def _analyze_ranking_momentum(self, asin: str) -> Dict:
        """分析排名动量"""
        history = self._ranking_history_db.get(asin, [])[-14:]
        if len(history) < 7:
            return {"momentum": "unknown", "reason": "数据不足"}

        recent = history[-7:]
        older = history[-14:-7]

        avg_recent = sum(r.bsr_rank for r in recent) / len(recent)
        avg_older = sum(r.bsr_rank for r in older) / len(older)
        change_pct = (avg_recent - avg_older) / avg_older * 100 if avg_older > 0 else 0

        if change_pct < -10:
            momentum = "strong_up"  # 排名上升（数值变小）
        elif change_pct < -3:
            momentum = "up"
        elif change_pct < 5:
            momentum = "stable"
        elif change_pct < 15:
            momentum = "down"
        else:
            momentum = "strong_down"

        return {
            "momentum": momentum,
            "change_percentage": round(change_pct, 1),
            "recent_avg_rank": round(avg_recent),
            "previous_avg_rank": round(avg_older),
        }

    def _analyze_stock_pattern(self, asin: str) -> Dict:
        """分析库存模式"""
        comp = self._competitor_db.get(asin)
        if not comp:
            return {"pattern": "unknown"}

        # 模拟库存历史分析
        return {
            "pattern": "generally_available",
            "current_status": comp.stock_status,
            "out_of_stock_days_30d": 0,
            "restock_frequency": "normal",
        }

    def _calculate_competitiveness_score(self, asin: str) -> float:
        """计算综合竞争力得分（0-100）"""
        comp = self._competitor_db.get(asin)
        if not comp:
            return 0

        # 多维度评分
        price_score = max(0, 100 - comp.price)  # 价格越低分越高（简化）
        rating_score = comp.rating * 20  # 5分制转百分制
        review_score = min(50, comp.review_count / 500)  # 评论数量分
        bsr_score = max(0, 100 - comp.bsr_rank / 100)  # BSR越低分越高

        # 加权平均
        score = (
            price_score * 0.25 +
            rating_score * 0.25 +
            review_score * 0.20 +
            bsr_score * 0.30
        )
        return round(score, 1)

    def _generate_comparison_matrix(self, tracked: List[Dict]) -> Dict:
        """生成对比矩阵"""
        if not tracked:
            return {}

        dimensions = ["price", "rating", "reviews", "bsr", "score"]
        matrix = {}
        for dim in dimensions:
            values = [t[dim] for t in tracked]
            matrix[dim] = {
                "best": max(values) if dim in ["rating", "reviews", "score"] else min(values),
                "worst": min(values) if dim in ["rating", "reviews", "score"] else max(values),
                "average": round(sum(values) / len(values), 1),
            }
        return matrix

    def _detect_trend(self, asin: str) -> str:
        """检测趋势"""
        ranking_hist = self._ranking_history_db.get(asin, [])[-14:]
        if len(ranking_hist) < 7:
            return "stable"

        recent_avg = sum(r.bsr_rank for r in ranking_hist[-7:]) / 7
        older_avg = sum(r.bsr_rank for r in ranking_hist[-14:-7]) / 7
        change = (recent_avg - older_avg) / older_avg * 100 if older_avg > 0 else 0

        if change < -10:
            return "rising"
        elif change > 10:
            return "declining"
        return "stable"

    def _generate_market_insights(self, estimates: List[MarketShareEstimate]) -> List[str]:
        """生成市场洞察"""
        insights = []

        top_player = estimates[0] if estimates else None
        if top_player and top_player.estimated_market_share > 30:
            insights.append(f"🏆 {top_player.brand_name} 占据主导地位（{top_player.estimated_market_share}%市场份额）")

        rising = [e for e in estimates if e.trend == "rising"]
        if len(rising) >= 2:
            insights.append(f"📈 {len(rising)} 个品牌呈上升趋势，市场竞争加剧")

        declining = [e for e in estimates if e.trend == "declining"]
        if declining:
            brands = ", ".join([d.brand_name for d in declining[:2]])
            insights.append(f"📉 {brands} 等品牌市场份额下滑，可能存在机会")

        insights.append("💡 建议：关注高增长品牌的产品策略和定价模式")
        return insights

    def _calculate_concentration_ratio(self, estimates: List[MarketShareEstimate]) -> Dict:
        """计算市场集中度"""
        sorted_by_share = sorted(estimates, key=lambda x: x.estimated_market_share, reverse=True)

        cr4 = sum(e.estimated_market_share for e in sorted_by_share[:4])
        hhi = sum(e.estimated_market_share ** 2 for e in estimates)

        if hhi < 1500:
            concentration = "competitive"
        elif hhi < 2500:
            concentration = "moderate_concentration"
        else:
            concentration = "high_concentration"

        return {
            "CR4": round(cr4, 2),  # 前4名集中度
            "HHI": round(hhi, 2),   # 赫芬达尔指数
            "market_type": concentration,
        }

    def _generate_pricing_recommendations(self, strategy: str, avg_price: float,
                                          volatility: float, promo_freq: str) -> List[str]:
        """生成定价建议"""
        recs = []

        if strategy == "premium":
            recs.extend([
                "维持高端定位，避免频繁打折影响品牌形象",
                "通过增值服务（如延长保修）提升感知价值",
                "关注竞品动态但不要盲目跟价",
            ])
        elif strategy == "economy":
            recs.extend([
                "低价策略需确保供应链成本优势",
                "考虑捆绑销售提升客单价",
                "关注利润空间，避免恶性价格战",
            ])
        elif strategy == "dynamic":
            recs.extend([
                "高频促销可能培养用户等待习惯",
                "建议设置促销日历，建立可预期性",
                "结合 Prime Day、Black Friday 等大促规划",
            ])
        else:
            recs.extend([
                "保持市场价格敏感度",
                "设置自动调价规则跟随竞品",
                "关注 Buy Box 价格竞争力",
            ])

        if volatility > 15:
            recs.append("⚠️ 价格波动较大，建议制定更稳定的定价策略")

        return recs

    def _generate_positioning_map(self, strategies: List[PricingStrategy]) -> Dict:
        """生成定位图数据"""
        positions = []
        for i, s in enumerate(strategies):
            # 基于策略类型确定位置
            type_coords = {
                "premium": {"x": 80, "y": 80},
                "economy": {"x": 20, "y": 30},
                "competitive": {"x": 50, "y": 55},
                "dynamic": {"x": 60, "y": 40},
            }
            pos = type_coords.get(s.strategy_type, {"x": 50, "y": 50})
            positions.append({
                "id": i,
                "strategy": s.strategy_type,
                "price_level": s.base_price,
                "x": pos["x"] + random.randint(-5, 5),
                "y": pos["y"] + random.randint(-5, 5),
            })

        return {
            "positions": positions,
            "axes": {
                "x_axis": "价格水平 →",
                "y_axis": "品质感知 ↑",
            },
        }

    def _mock_review_analysis(self, comp: CompetitorProduct) -> List[ReviewInsight]:
        """模拟评论分析"""
        # 根据产品特性生成不同的评论洞察
        base_insights = [
            ReviewInsight(
                aspect="positive",
                topic="音质表现",
                sentiment_score=0.75,
                mention_count=int(comp.review_count * 0.35),
                example_quotes=["音质超出预期", "低音效果很好", "清晰度高"],
            ),
            ReviewInsight(
                aspect="positive",
                topic="佩戴舒适度",
                sentiment_score=0.65,
                mention_count=int(comp.review_count * 0.28),
                example_quotes=["戴着很舒服", "长时间不累", "耳塞尺寸合适"],
            ),
            ReviewInsight(
                aspect="negative",
                topic="电池续航",
                sentiment_score=-0.45,
                mention_count=int(comp.review_count * 0.22),
                example_quotes=["续航没有宣传的那么长", "用一天就得充电"],
            ),
            ReviewInsight(
                aspect="negative",
                topic="连接稳定性",
                sentiment_score=-0.35,
                mention_count=int(comp.review_count * 0.18),
                example_quotes=["偶尔断连", "距离远了会卡"],
            ),
            ReviewInsight(
                aspect="neutral",
                topic="外观设计",
                sentiment_score=0.15,
                mention_count=int(comp.review_count * 0.15),
                example_quotes=["外观一般", "中规中矩的设计"],
            ),
        ]

        # 根据品牌调整
        if comp.brand == "ValueSound":
            base_insights[0].sentiment_score = 0.5  # 便宜货音质一般
            base_insights.append(ReviewInsight(
                aspect="positive",
                topic="性价比",
                sentiment_score=0.8,
                mention_count=int(comp.review_count * 0.4),
                example_quotes=["这个价位很值了", "便宜好用"],
            ))
        elif comp.brand == "AudioElite":
            base_insights[2].sentiment_score = -0.2  # 高端产品电池问题少
            base_insights.append(ReviewInsight(
                aspect="positive",
                topic="降噪效果",
                sentiment_score=0.85,
                mention_count=int(comp.review_count * 0.3),
                example_quotes=["降噪很厉害", "地铁上完全听不到"],
            ))

        return base_insights

    def _generate_review_swot(self, insights: List[ReviewInsight]) -> Dict:
        """从评论生成 SWOT"""
        strengths = [i.topic for i in insights if i.aspect == "positive" and i.sentiment_score > 0.6]
        weaknesses = [i.topic for i in insights if i.aspect == "negative" and i.sentiment_score < -0.3]

        return {
            "strengths": strengths[:3],
            "weaknesses": weaknesses[:3],
            "opportunities": ["针对竞品弱点的差异化机会"],
            "threats": ["竞品优势对我们的压力"],
        }

    def _extract_actionable_intel(self, insights: List[ReviewInsight], comp: CompetitorProduct) -> List[str]:
        """提取可行动的情报"""
        intel = []

        negative_high_impact = [i for i in insights if i.aspect == "negative" and i.mention_count > comp.review_count * 0.15]
        for item in negative_high_impact:
            intel.append(f"🎯 竞品在'{item.topic}'方面被大量投诉（{item.mention_count}条），可作为我们的差异化重点")

        positive_unique = [i for i in insights if i.aspect == "positive" and i.sentiment_score > 0.7]
        for item in positive_unique:
            intel.append(f"📌 竞品的'{item.topic}'是核心卖点，我们需要达到或超越此水平")

        return intel[:5]

    def _mock_buy_box_data(self, comp: CompetitorProduct) -> Dict:
        """模拟 Buy Box 数据"""
        # 模拟多个卖家
        sellers = [
            {"seller_name": comp.brand + " Official", "price": comp.price, "shipping": 0, "in_stock": True},
            {"seller_name": "Third-Party Pro", "price": comp.price * 1.05, "shipping": 4.99, "in_stock": True},
            {"seller_name": "Discount Seller", "price": comp.price * 0.95, "shipping": 9.99, "in_stock": True},
        ]

        # Buy Box 赢家
        winner = sellers[0]

        return {
            "current_winner": winner["seller_name"],
            "winning_price": winner["price"],
            "our_price_competitiveness": round(comp.price / winner["price"] * 100, 2),
            "all_sellers": sellers,
            "buy_box_percentage": round(random.uniform(70, 98), 1),  # 品牌方通常占比较高
            "price_to_win": round(winner["price"] * 0.98, 2),  # 需要多少价格才能赢
            "featured_offer_reason": "Lowest price + Prime shipping",
        }

    def _calculate_buy_box_competitiveness(self, data: Dict) -> float:
        """计算 Buy Box 竞争力得分"""
        score = 100

        # 价格因素
        if data.get("our_price_competitiveness", 100) > 105:
            score -= 20
        elif data.get("our_price_competitiveness", 100) > 102:
            score -= 10

        # Buy Box 占有率
        bb_pct = data.get("buy_box_percentage", 0)
        if bb_pct < 80:
            score -= (80 - bb_pct) / 2

        return round(max(0, score), 1)

    def _compare_dimension(self, competitors: List[CompetitorProduct], dimension: str, mode: str) -> Dict:
        """对比单个维度"""
        values = []
        for c in competitors:
            val = getattr(c, dimension, 0)
            values.append({"asin": c.asin, "brand": c.brand, "value": val})

        if mode == "lower_better":
            best = min(values, key=lambda x: x["value"])
        else:
            best = max(values, key=lambda x: x["value"])

        return {
            "dimension": dimension,
            "values": values,
            "best": best["brand"],
            "best_value": best["value"],
        }

    def _calculate_value_scores(self, competitors: List[CompetitorProduct]) -> List[Dict]:
        """计算性价比得分"""
        scores = []
        for c in competitors:
            # 性价比 = 评分 / 价格
            value = (c.rating * 20) / c.price * 100 if c.price > 0 else 0
            scores.append({
                "asin": c.asin,
                "brand": c.brand,
                "value_score": round(value, 1),
                "rating": c.rating,
                "price": c.price,
            })

        scores.sort(key=lambda x: x["value_score"], reverse=True)
        return scores

    def _generate_overall_ranking(self, competitors: List[CompetitorProduct]) -> List[Dict]:
        """生成总体排名"""
        rankings = []
        for c in competitors:
            # 综合得分
            score = (
                self._calculate_competitiveness_score(c.asin) * 0.5 +
                ((c.rating * 20) / c.price * 100 if c.price > 0 else 0) * 0.3 +
                (5000 / max(c.bsr_rank, 1)) * 0.2
            )
            rankings.append({
                "asin": c.asin,
                "brand": c.brand,
                "overall_score": round(score, 1),
                "rank": 0,  # 后面填入
            })

        rankings.sort(key=lambda x: x["overall_score"], reverse=True)
        for i, r in enumerate(rankings):
            r["rank"] = i + 1

        return rankings

    def _analyze_differentiation(self, competitors: List[CompetitorProduct]) -> Dict:
        """分析差异化"""
        price_range = max(c.price for c in competitors) - min(c.price for c in competitors)
        rating_spread = max(c.rating for c in competitors) - min(c.rating for c in competitors)

        segments = []
        for c in competitors:
            if c.price >= 100:
                segment = "premium"
            elif c.price <= 40:
                segment = "budget"
            else:
                segment = "mid-range"
            segments.append({"brand": c.brand, "segment": segment})

        return {
            "price_spread": round(price_range, 2),
            "rating_spread": round(rating_spread, 1),
            "market_segments": segments,
            "gap_opportunities": self._find_gap_opportunities(competitors),
        }

    def _find_gap_opportunities(self, competitors: List[CompetitorProduct]) -> List[str]:
        """发现市场空白机会"""
        opportunities = []

        prices = [c.price for c in competitors]
        # 寻找价格区间空白
        if max(prices) - min(prices) > 80:
            mid_point = (max(prices) + min(prices)) / 2
            nearby = [c for c in competitors if abs(c.price - mid_point) < 20]
            if not nearby:
                opportunities.append(f"💰 ${mid_point:.0f}附近存在价格空白区间")

        # 寻找评分空白
        ratings = [c.rating for c in competitors]
        if max(ratings) < 4.6:
            opportunities.append("⭐ 高端高品质产品存在市场空白")

        return opportunities

    def _generate_comparison_recommendations(self, competitors: List[CompetitorProduct]) -> List[str]:
        """生成对比建议"""
        recs = []

        best_value = min(competitors, key=lambda c: c.price / c.rating if c.rating > 0 else 999)
        recs.append(f"💡 最佳性价比: {best_value.brand} (${best_value.price:.2f}, ⭐{best_value.rating})")

        highest_rated = max(competitors, key=lambda c: c.rating)
        recs.append(f"🏆 最高评分: {highest_rated.brand} (⭐{highest_rated.rating})")

        lowest_priced = min(competitors, key=lambda c: c.price)
        recs.append(f"💰 最低价格: {lowest_priced.brand} (${lowest_priced.price:.2f})")

        recs.append("📊 建议：根据目标客户群体选择合适的竞品对标对象")
        return recs

    def _generate_buy_box_best_practices(self) -> List[str]:
        """生成 Buy Box 最佳实践"""
        return [
            "✅ 保持具有竞争力的价格（建议在最低价+3%以内）",
            "✅ 使用 Fulfillment by Amazon (FBA)",
            "✅ 维持良好的卖家指标（延迟发货率<4%, OPR<1%）",
            "✅ 提供可靠的库存（缺货会严重影响 Buy Box）",
            "✅ 优化产品页面转化率",
            "⚠️ 避免频繁更改价格",
            "⚠️ 注意跟卖风险，注册 Brand Registry",
        ]
