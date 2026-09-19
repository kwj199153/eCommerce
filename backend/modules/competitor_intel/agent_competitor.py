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

from typing import Optional, List, Dict, Any, AsyncIterable
from datetime import date, datetime, timedelta
import re
from dataclasses import dataclass, asdict

from core.logger import get_logger
from ai_infra.sse import progress

logger = get_logger(__name__)


# ====== 数据源接入（唯一取数点）======

def _days_of(time_range) -> int:
    """把 "7d" / "30d" / "90d" 解析成天数（解析不出按 30）。"""
    m = re.match(r"(\d+)\s*d", str(time_range or ""), re.I)
    return int(m.group(1)) if m else 30


def _load_competitor_rows(store_id, time_range="30d", asins=None) -> List[Dict]:
    """取本店铺的竞品快照（唯一入口，经工厂）。

    ★ 为什么必须经 `get_data_source()`：配好 SP-API 凭据后这里会自动切到真实现；
      绕过工厂直连 Mock（模块级单例那种写法）会让「配了凭据也永远跑假数据且不报错」。

    ★ 拿不到 `store_id`（未选店铺）时**不猜测、不取默认店**，直接返回空列表，
      由调用方给显式空状态。

    ★ `asins` 透传给数据源做过滤。注意数据源只能在**它自己的竞品集合内**过滤，
      查不到的 ASIN 会落空 —— 这是事实，不由本层编造补上。
    """
    if not store_id:
        return []
    from modules.amazon_sp import get_data_source

    src = get_data_source(prefer="auto", seed=42)
    d_to = date.today()
    d_from = d_to - timedelta(days=_days_of(time_range) - 1)
    kw = {"asins": list(asins)} if asins else {}
    try:
        return list(src.fetch_competitors(store_id, d_from, d_to, **kw))
    except Exception as e:  # 数据源故障不得伪装成「无数据」
        logger.error(f"[competitor_intel] 取竞品快照失败 store={store_id}: {e}")
        raise


# 结构化意图 → 阶段进度文案（stream_chat 在耗时分析前发给前端，避免空转）
_INTENT_PROGRESS = {
    "monitor": "正在拉取竞品最新动态…",
    "compare": "正在对比竞品数据…",
    "track_batch": "正在批量追踪竞品…",
    "market_share": "正在测算市场份额…",
    "pricing": "正在分析竞品定价策略…",
    "reviews": "正在分析竞品评论…",
    "buy_box": "正在分析 Buy Box 归属…",
    "intruder": "正在识别新进入者…",
}


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


# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.competitor_intel import prompts as _prompts  # noqa: F401


class CompetitorIntelligenceAgent(BaseAgent):
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

    # ★ 竞品视图这三个 dict 改造前是**类属性**，且 `__init__` 会调
    #   `_initialize_mock_data()` 写死 5 个耳机竞品 ⇒ 两个后果：
    #     ① 所有实例共享同一份可变 dict，后建的实例把先建的覆盖掉；
    #     ② `store_id` 在整个模块里**零出现** —— 「看哪个店铺」无从谈起。
    #   现在改为**实例级**，由 `_ensure_source(context)` 按「店铺 + 时间范围」装载。

    def __init__(self):
        # 初始化 LLM 基类
        super().__init__()

        self.agent_name = "competitor_intel"
        self._competitor_db: Dict[str, CompetitorProduct] = {}
        self._price_history_db: Dict[str, List[PriceHistory]] = {}
        self._ranking_history_db: Dict[str, List[RankingHistory]] = {}
        self._loaded_key: Optional[tuple] = None
        self._data_status: str = "no_data"
        self._data_reason: Optional[str] = None

    async def _llm_insights(self, context: str, max_tokens: int = 800) -> Optional[str]:
        """
        LLM 增强：基于竞品数据生成专业洞察结论。

        LLM 不可用或失败时返回 None，由调用方降级到规则生成。
        """
        if not (self.ENABLE_LLM and self.llm_client):
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

    # ==================== 数据源装载（唯一入口）====================

    def _ensure_source(self, context: Optional[Dict] = None) -> bool:
        """按「店铺 + 时间范围」把数据源快照装载进**实例**视图。

        True  ⇒ 本实例已有可用竞品数据，可继续分析。
        False ⇒ 应走显式空状态（`self._data_reason` 说明原因）。

        同一 (store_id, time_range) 重复调用不重复取数。
        """
        ctx = context or {}
        store_id = ctx.get("store_id")
        time_range = ctx.get("time_range") or f"{ctx.get('days') or 30}d"
        key = (store_id, time_range)

        if key == self._loaded_key:
            return bool(self._competitor_db)

        self._competitor_db = {}
        self._price_history_db = {}
        self._ranking_history_db = {}
        self._loaded_key = key

        if not store_id:
            self._data_status = "no_data"
            self._data_reason = "未绑定店铺上下文（请求缺少 X-Shop-ID）"
            return False

        rows = _load_competitor_rows(store_id, time_range)
        if not rows:
            self._data_status = "no_data"
            self._data_reason = f"店铺 {store_id} 在当前数据源中暂无竞品快照"
            return False

        self._build_from_rows(rows)
        self._data_status = "ok"
        self._data_reason = None
        return True

    def _build_from_rows(self, rows: List[Dict]) -> None:
        """按 `competitor_asin` 归组：最新一行 → 当前视图，全序列 → 价格/排名历史。

        字段口径与 `amazon_sp.data_sources.*.fetch_competitors()` 一致。
        改造前这些历史是 `_generate_history_data()` 用 `random.uniform` 现编 30 天的；
        数据源本身按「每 2 天一个点」给出**真实快照序列**，无需再编。
        """
        grouped: Dict[str, List[Dict]] = {}
        for r in rows:
            asin = r.get("competitor_asin")
            if asin:
                grouped.setdefault(str(asin).upper(), []).append(r)

        for asin, recs in grouped.items():
            recs.sort(key=lambda x: str(x.get("snapshot_date") or ""))
            last = recs[-1]
            has_bb = bool(last.get("has_buybox"))
            bb_price = last.get("buybox_price")
            self._competitor_db[asin] = CompetitorProduct(
                asin=asin,
                title=str(last.get("title") or ""),
                brand=str(last.get("brand") or ""),
                price=float(last.get("price") or 0.0),
                bsr_rank=int(last.get("bsr_rank") or 0),
                review_count=int(last.get("review_count") or 0),
                rating=float(last.get("rating") or 0.0),
                # ★ 数据源不含类目 / 主图字段 ⇒ 留空，不编造
                category="",
                image_url="",
                is_prime=(last.get("fulfillment") == "FBA"),
                buy_box_price=(float(bb_price) if bb_price is not None else None),
                buy_box_seller=(str(last.get("brand") or "") if has_bb else ""),
                stock_status="In Stock",
                last_updated=str(last.get("snapshot_date") or ""),
            )
            self._price_history_db[asin] = [
                PriceHistory(date=str(r.get("snapshot_date") or ""),
                             price=float(r.get("price") or 0.0))
                for r in recs
            ]
            self._ranking_history_db[asin] = [
                RankingHistory(date=str(r.get("snapshot_date") or ""),
                               bsr_rank=int(r.get("bsr_rank") or 0))
                for r in recs
            ]

    def _no_data(self, what: str, status: str = "no_data",
                 reason: Optional[str] = None) -> Dict:
        """显式空状态：拿不到数据就**明说**，绝不返回编出来的报告。"""
        r = reason or self._data_reason or "数据源未返回可用数据"
        return {
            "type": status,
            "success": False,
            "data_status": status,
            "data_reason": r,
            "message": f"{what}未执行：{r}",
        }

    async def analyze(self, query: str, context: Optional[Dict] = None) -> Dict[str, Any]:
        """
        主入口：意图分类 + 路由到对应能力
        """
        intent = self._classify_intent(query)

        # ★ 一切能力都以真实竞品数据为前提：装载失败 ⇒ 显式空状态，不进 handler。
        if not self._ensure_source(context):
            out = self._no_data("竞品分析")
            out["intent"] = intent
            return out

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
        if not self._ensure_source(context):
            return self._no_data("竞品 Listing 监控")
        asin = self._resolve_asin(query, context)

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
        if not self._ensure_source(context):
            return self._no_data("ASIN 批量追踪")
        asins = self._resolve_asins(query, context)

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
        if not self._ensure_source(context):
            return self._no_data("市场份额分析")
        category = self._extract_category(query) or context.get("category") if context else "Headphones"

        estimates = []
        total_revenue_estimate = 0

        for asin, comp in self._competitor_db.items():
            # 基于 BSR 估算市场份额（简化算法）
            # BSR 越低，市场份额越大
            # ★ 改造前这里乘了 `random.uniform(0.8, 1.2)` 的「噪声」——纯人工抖动，
            #   同一店铺连点两次份额不同。现改为**纯由 BSR 推导**，可复现。
            base_share = max(0.5, 100 / (comp.bsr_rank ** 0.5))
            market_share = base_share

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
        if not self._ensure_source(context):
            return self._no_data("定价策略分析")
        asin = self._resolve_asin(query, context)

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

            # ★ 价格弹性需要「价格 → 销量」配对，而竞品快照**不含销量**
            #   ⇒ 不编造数字：置 0，由调用方按「不可估」呈现
            #   （改造前是 `random.uniform(-1.5, -2.5)` 的假弹性）。
            elasticity = 0.0

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
        if not self._ensure_source(context):
            return self._no_data("竞品评论深度分析")
        asin = self._resolve_asin(query, context)

        target_asins = [asin] if asin else list(self._competitor_db.keys())[:3]

        analyses = []
        for comp_asin in target_asins:
            comp = self._competitor_db.get(comp_asin)
            if not comp:
                continue

            # 由数据源可得字段推导（数据源不含评论正文）
            insights = self._review_insights_from_data(comp)
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
            "data_status": "partial",
            "data_reason": "数据源仅提供评论数量与评分，不含评论正文 ⇒ 主题级洞察与"
                           "原文引用不可得；本结果只含由评分推导的口碑档位。",
        }

    async def _detect_intruders(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力6：入侵者检测（新竞争者）—— **显式不可用**。

        ★ 改造前这里返回 3 个硬编码的假新进入者（B0NEW001/002/003，
          「7 天内获得 200+ 评论」之类的理由全是编的）。
        ★ 竞品快照数据源**没有「新进入者」这个维度**：它给出的是当前竞品集合的
          快照序列，无法回答「谁是最近才出现的」。要恢复此能力需要接
          ① 商品上架时间（Listings 的 created_at）或 ② 类目新品榜。
          在那之前宁可明说不可用，也不返回编出来的入侵者名单。
        """
        return self._no_data(
            "入侵者检测",
            status="unsupported",
            reason="当前数据源不提供「新进入竞品」维度（仅有竞品快照序列），"
                   "本能力暂不可用；接入商品上架时间或类目新品榜后恢复。",
        )

    async def _analyze_buy_box(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力7：Buy Box 竞争分析"""
        if not self._ensure_source(context):
            return self._no_data("Buy Box 竞争分析")
        asin = self._resolve_asin(query, context)

        target_asins = [asin] if asin else list(self._competitor_db.keys())

        analyses = []
        for comp_asin in target_asins:
            comp = self._competitor_db.get(comp_asin)
            if not comp:
                continue

            # 由数据源可得字段推导
            buy_box_data = self._buy_box_from_data(comp)

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
            "data_status": "partial",
            "data_reason": "数据源不含卖家清单与 Buy Box 占有率，仅含归属与价格。",
        }

    async def _compare_competitors(self, query: str, context: Optional[Dict] = None) -> Dict:
        """能力8：多维度竞品对比"""
        if not self._ensure_source(context):
            return self._no_data("多维度竞品对比")
        asins = self._resolve_asins(query, context)

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

    async def stream_chat(self, query: str,
                          context: Optional[Dict] = None) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        对话/通用意图走 LLM 流式；结构化意图（监控/对比/份额等）退化为一次性文本，
        但开跑前先发阶段进度，避免长任务期间「AI 正在思考…」空转。

        Yields:
            文本片段 / progress 事件（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        intent = self._classify_intent(query)

        # 结构化意图：走 analyze 一次性返回（含结构化数据）
        if intent != "general":
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析竞品数据…"))
            result = await self.analyze(query, context)
            # 提取可读文本（message 或摘要字段）
            text = result.get("message") or result.get("summary") or result.get("analysis", "")
            if isinstance(text, str) and text:
                yield text
            else:
                yield f"已生成「{intent}」分析结果，详情见右侧结构化面板。"
            return

        # 对话类：走 LLM 流式
        if not (self.ENABLE_LLM and self.llm_client):
            result = await self._general_analysis(query)
            yield result.get("message", "")
            return

        try:
            async for chunk in self.llm_stream(
                query,
                system_prompt=self.get_prompt_template("competitor_intel"),
                model=self.DEFAULT_MODEL,
                temperature=0.6,
                max_tokens=800,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[competitor_intel] stream_chat failed: {e}")
            result = await self._general_analysis(query)
            yield result.get("message", "")

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

    def _resolve_asin(self, query: str, context: Optional[Dict] = None) -> Optional[str]:
        """
        解析单个 ASIN：query 优先，其次 context，统一大写。

        为什么需要它（2026-09-12 修复两个 bug）：
        1. 各能力原先内联写 `self._extract_asin(query) or (context.get("asin")
           if context else None)`，`_monitor_competitor` 漏了括号 → 被解析成
           `(extract or context) if context else None`，context=None 时整条短路成
           None，**已提取到的 ASIN 被丢弃** → `/analyze` 的「监控 B08ABC1234」
           实际返回全量仪表盘，路由文档承诺的单品监控失效。
        2. 竞品库以**大写** ASIN 为键，`_extract_asin` 提取时 `.upper()`，但 context
           传入的值原样使用，而 `GET /reviews/{asin}` 又主动 `.upper()` —— 同一个
           ASIN 小写走 POST 是「未找到竞品 ASIN」，走 GET 却正常。这里统一归一。
        """
        raw = self._extract_asin(query) or (context.get("asin") if context else None)
        return raw.upper() if isinstance(raw, str) and raw else None

    def _resolve_asins(self, query: str, context: Optional[Dict] = None) -> List[str]:
        """解析多个 ASIN（query 优先，其次 context），统一大写"""
        raw = self._extract_multiple_asins(query) or (context.get("asins") if context else None) or []
        return [a.upper() for a in raw if isinstance(a, str) and a]

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
            # ★ 改造前这里还叠加 `random.randint(-5, 5)` 的散点抖动（纯装饰性随机）⇒ 去掉。
            positions.append({
                "id": i,
                "strategy": s.strategy_type,
                "price_level": s.base_price,
                "x": pos["x"],
                "y": pos["y"],
            })

        return {
            "positions": positions,
            "axes": {
                "x_axis": "价格水平 →",
                "y_axis": "品质感知 ↑",
            },
        }

    def _review_insights_from_data(self, comp: CompetitorProduct) -> List[ReviewInsight]:
        """从**数据源可得字段**推导评论洞察（不编造评论主题与原句）。

        ★ 口径（重要）：竞品快照数据源只提供 `review_count` / `rating`，
          **不提供评论正文**。因此这里只输出**可由评分推导**的结论：
          `topic` 用中性档位标签、`example_quotes` 一律为空。
          真实的「评论主题 / 原文引用」需要另接评论数据源，属**已知缺口**，
          不在本层用编造数据填补。

        ★ 改造前 `_mock_review_analysis` 硬编码了「音质表现 / 佩戴舒适度 /
          电池续航 / 连接稳定性 / 外观设计」5 个主题 + 假引文，且按
          0.35/0.28/0.22/0.18/0.15 的比例把 `review_count` 凭空拆成 5 份 ——
          那些比例没有任何数据依据。
        """
        rating = float(comp.rating or 0.0)
        # 评分 → 情感分（-1..1）：4.3 是亚马逊类目常见中位，以此为中性锚
        sentiment = round(max(-1.0, min(1.0, (rating - 4.3) / 0.7)), 2)
        if sentiment > 0.15:
            aspect = "positive"
        elif sentiment < -0.15:
            aspect = "negative"
        else:
            aspect = "neutral"

        return [ReviewInsight(
            aspect=aspect,
            topic="整体口碑",
            sentiment_score=sentiment,
            mention_count=int(comp.review_count or 0),
            example_quotes=[],
        )]

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

    def _buy_box_from_data(self, comp: CompetitorProduct) -> Dict:
        """从**数据源可得字段**推导 Buy Box 竞争情况（不编造卖家清单）。

        ★ 口径：竞品快照提供 `has_buybox` 与 `buybox_price`，**不提供**
          卖家清单、各卖家报价、Buy Box 占有率。因此：
          - `current_winner` 只能是**品牌级归属**（由 has_buybox 判定），不是卖家账号
          - `all_sellers` 一律为空列表
          - `buy_box_percentage` 退化为「是否持有」的 0/100
          改造前这里硬编 3 个卖家（Official / Third-Party Pro / Discount Seller）
          并给 `buy_box_percentage` 配 `random.uniform(70, 98)`。
        """
        ref_price = comp.buy_box_price if comp.buy_box_price else comp.price
        holds = bool(comp.buy_box_seller)
        return {
            "current_winner": comp.buy_box_seller or None,
            "winning_price": ref_price,
            "our_price_competitiveness": (
                round(comp.price / ref_price * 100, 2) if ref_price else 100.0
            ),
            "all_sellers": [],
            "buy_box_percentage": 100.0 if holds else 0.0,
            "price_to_win": round(ref_price * 0.98, 2) if ref_price else None,
            "featured_offer_reason": None,
            "data_status": "partial",
            "data_reason": "数据源仅提供 Buy Box 归属与价格，卖家清单/占有率不可得",
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
