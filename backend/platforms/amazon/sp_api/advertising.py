"""
Amazon Advertising API 封装

提供广告数据获取和分析的高级操作方法。

注意：Advertising API 需要额外的 OAuth scope 和配置。
SP-API 提供受限的代理访问方式，完整功能需要直接对接 Advertising API。
"""

import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from .client import SPAPIClient
from .models import (
    Campaign,
    CampaignType,
    CampaignState,
    AdGroup,
    Keyword,
    AdPerformanceMetrics,
    SearchTermReportRow,
)

logger = logging.getLogger(__name__)


class AdvertisingAPI:
    """
    Advertising API 高级封装

    提供面向业务的方法：
    - 广告活动管理
    - 关键词分析
    - 搜索词报告
    - 竞品广告监控
    - 预算优化建议
    """

    def __init__(self, client: SPAPIClient):
        self.client = client

    # ====== 广告活动 ======

    async def get_campaigns(
        self,
        campaign_type: str = "sponsoredProducts",
        state_filter: Optional[str] = None,
    ) -> List[Campaign]:
        """获取广告活动列表"""
        try:
            campaigns = await self.client.get_ad_campaigns(
                campaign_type=campaign_type,
                state_filter=state_filter,
            )
            return campaigns
        except Exception as e:
            logger.warning(f"获取广告活动失败（可能未开通权限）: {e}")
            return []

    async def get_campaign_summary(
        self,
        campaign_type: str = "sponsoredProducts",
    ) -> Dict[str, Any]:
        """获取广告活动汇总"""
        campaigns = await self.get_campaigns(campaign_type=campaign_type)

        if not campaigns:
            return {
                "total_campaigns": 0,
                "active_campaigns": 0,
                "paused_campaigns": 0,
                "total_daily_budget": 0.0,
                "campaign_types": {},
            }

        active = [c for c in campaigns if c.state == CampaignState.ENABLED]
        paused = [c for c in campaigns if c.state == CampaignState.PAUSED]

        total_budget = sum(c.daily_budget or 0 for c in active)
        type_counts: Dict[str, int] = {}
        for c in campaigns:
            ct = c.campaign_type.value if isinstance(c.campaign_type, CampaignType) else str(c.campaign_type)
            type_counts[ct] = type_counts.get(ct, 0) + 1

        return {
            "total_campaigns": len(campaigns),
            "active_campaigns": len(active),
            "paused_campaigns": len(paused),
            "total_daily_budget": round(total_budget, 2),
            "campaign_types": type_counts,
        }

    # ====== 搜索词分析 ======

    async def analyze_search_terms(
        self,
        days_back: int = 30,
        min_clicks: int = 5,
    ) -> Dict[str, Any]:
        """
        分析搜索词表现

        分类：高效词、浪费词、机会词、低量词
        """
        from .reports import ReportsAPI

        reports_api = ReportsAPI(self.client)
        raw_data = await reports_api.get_sp_search_term_report(days_back=days_back)

        if not raw_data:
            return {
                "period_days": days_back,
                "total_terms": 0,
                "categories": {
                    "high_performers": [],
                    "waste": [],
                    "opportunities": [],
                    "low_volume": [],
                },
                "summary": {},
            }

        # 解析并分类搜索词
        terms = []
        for row in raw_data:
            try:
                term = SearchTermReportRow(
                    search_term=row.get("searchTerm", ""),
                    impressions=int(row.get("impressions", 0)),
                    clicks=int(row.get("clicks", 0)),
                    cost=float(row.get("cost", 0)),
                    attributed_conversions_14d=int(row.get("attributedConversions14d", 0)),
                    attributed_sales_14d=float(row.get("attributedSales14d", 0)),
                )
                terms.append(term)
            except (ValueError, TypeError):
                continue

        # 分类逻辑
        categories = {
            "high_performers": [],  # 高转化、ACoS < 20%
            "waste": [],           # 高花费、无转化或 ACoS > 50%
            "opportunities": [],   # 有点击但出价可能偏低
            "low_volume": [],      # 点击太少，数据不足
        }

        for term in terms:
            if term.clicks < min_clicks:
                categories["low_volume"].append(term)
            elif term.acos < 20 and term.attributed_sales_14d > 0:
                categories["high_performers"].append(term)
            elif term.cost > 10 and (term.attributed_conversions_14d == 0 or term.acos > 50):
                categories["waste"].append(term)
            else:
                categories["opportunities"].append(term)

        # 排序
        for key in categories:
            sort_key = "cost" if key == "waste" else "attributed_sales_14d"
            categories[key].sort(key=lambda x: getattr(x, sort_key), reverse=True)

        # 汇总统计
        total_cost = sum(t.cost for t in terms)
        total_sales = sum(t.attributed_sales_14d for t in terms)

        return {
            "period_days": days_back,
            "total_terms": len(terms),
            "categories": {k: [t.model_dump() for t in v[:20]] for k, v in categories.items()},
            "summary": {
                "total_spend": round(total_cost, 2),
                "total_revenue": round(total_sales, 2),
                "overall_acos": round(total_cost / total_sales * 100, 2) if total_sales > 0 else 0,
                "high_performer_count": len(categories["high_performers"]),
                "waste_count": len(categories["waste"]),
                "waste_amount": round(sum(t.cost for t in categories["waste"]), 2),
                "opportunity_count": len(categories["opportunities"]),
            },
        }

    # ====== 出价优化建议 ======

    async def generate_bid_suggestions(
        self,
        campaign_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        基于数据分析生成出价优化建议

        返回格式：
        [
            {
                "keyword": "...",
                "current_bid": 1.23,
                "suggested_bid": 1.50,
                "reason": "...",
                "expected_impact": "+15% CTR",
                "priority": "high/medium/low"
            }
        ]
        """
        analysis = await self.analyze_search_terms()
        suggestions = []

        # 浪费词 → 降低出价或暂停
        for waste_term in analysis["categories"]["waste"][:5]:
            current_bid = 1.0  # 实际应从 API 获取
            suggested_bid = round(current_bid * 0.6, 2)  # 降低 40%

            suggestions.append({
                "keyword": waste_term.search_term,
                "current_bid": current_bid,
                "suggested_bid": suggested_bid,
                "reason": f"高花费(${waste_term.cost:.2f})无转化(ACoS={waste_term.acos:.1f}%)",
                "expected_impact": f"预计节省 ${round(waste_term.cost * 0.4, 2)}",
                "priority": "high",
            })

        # 高效词 → 提高出价
        for hp_term in analysis["categories"]["high_performers"][:3]:
            current_bid = 1.0
            suggested_bid = round(current_bid * 1.2, 2)  # 提高 20%

            suggestions.append({
                "keyword": hp_term.search_term,
                "current_bid": current_bid,
                "suggested_bid": suggested_bid,
                "reason": f"高效词(ACoS={hp_term.acos:.1f}%，销售额=${hp_term.attributed_sales_14d:.2f})",
                "expected_impact": f"+{int((hp_term.ctr or 0) * 0.2):.1f}% CTR 预期提升",
                "priority": "medium",
            })

        # 机会词 → 适度提价
        for opp_term in analysis["categories"]["opportunities"][:3]:
            current_bid = 1.0
            suggested_bid = round(current_bid * 1.1, 2)

            suggestions.append({
                "keyword": opp_term.search_term,
                "current_bid": current_bid,
                "suggested_bid": suggested_bid,
                "reason": f"有潜力但表现一般(CTR={opp_term.ctr:.1f}%)",
                "expected_impaction": "中等改善预期",
                "priority": "low",
            })

        return sorted(suggestions, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 9))

    # ====== 竞品广告监控 ======

    async def monitor_competitor_ads(
        self,
        target_asins: List[str],
        days_back: int = 7,
    ) -> List[Dict[str, Any]]:
        """
        监控指定 ASIN 的广告表现

        注意：此功能需要通过 Share of Voice API 或第三方工具实现，
        这里返回基于公开数据的估算信息。
        """
        results = []

        for asin in target_asins:
            # 获取商品基本信息
            try:
                from .products import ProductsAPI
                products_api = ProductsAPI(self.client)
                product_info = await products_api.get_product_detail(asin)

                results.append({
                    "asin": asin,
                    "title": product_info.get("title", ""),
                    "brand": product_info.get("brand", ""),
                    "estimated_visibility_score": self._estimate_visibility(product_info),
                    "price_range": product_info.get("pricing", {}).get("buy_box_price"),
                    "offer_count": product_info.get("pricing", {}).get("total_offers", 0),
                    "ad_presence_indicators": self._detect_ad_presence(asin),
                    "last_checked": datetime.now().isoformat(),
                })
            except Exception as e:
                logger.warning(f"监控竞品 {asin} 失败: {e}")
                results.append({
                    "asin": asin,
                    "error": str(e),
                })

        return results

    # ====== 预算分配建议 ======

    async def suggest_budget_reallocation(
        self,
        total_budget: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        基于历史表现建议预算重新分配

        Args:
            total_budget: 总日预算（为空则使用当前总额）
        """
        summary = await self.get_campaign_summary()
        search_analysis = await self.analyze_search_terms()

        current_total = summary["total_daily_budget"] or total_budget or 100

        # 基于搜索词分析的 ROI 分配建议
        high_perf_ratio = len(search_analysis["categories"]["high_performers"]) / max(len(search_analysis["categories"]["high_performers"]) + len(search_analysis["categories"]["waste"]), 1)
        waste_ratio = len(search_analysis["categories"]["waste"]) / max(high_perf_ratio + len(search_analysis["categories"]["waste"]), 1)

        suggestion = {
            "current_total_budget": current_total,
            "recommended_allocation": {
                "high_performers": {
                    "percentage": round(min(high_perf_ratio * 100, 70), 1),
                    "amount": round(current_total * min(high_perf_ratio, 0.7), 2),
                    "rationale": "将更多预算投向高 ROI 活动",
                },
                "testing_new": {
                    "percentage": round(20, 1),
                    "amount": round(current_total * 0.2, 2),
                    "rationale": "保留测试新关键词/商品的预算",
                },
                "maintenance": {
                    "percentage": round(max(10, waste_ratio * 100), 1),
                    "amount": round(current_total * max(0.1, waste_ratio), 2),
                    "rationale": "维持现有活动的最低运行",
                },
            },
            "actions": [
                "暂停或大幅降低浪费词的出价",
                "提高高效词的出价和预算",
                "关注机会词的表现变化",
                "每周审查并调整分配比例",
            ],
            "estimated_impact": {
                "acos_improvement": f"-{round(waste_ratio * 30, 1)}%",
                "revenue_increase_potential": f"+{round(high_perf_ratio * 25, 1)}%",
            } if waste_ratio > 0 else {},
        }

        return suggestion

    # ====== 内部工具方法 ======

    @staticmethod
    def _estimate_visibility(product_info: Dict[str, Any]) -> float:
        """估算商品可见度分数 (0-100)"""
        score = 50.0  # 基础分

        # 价格竞争力
        pricing = product_info.get("pricing", {})
        offer_count = pricing.get("total_offers", 0)
        if offer_count <= 3:
            score += 20  # 竞争少，更容易被看到
        elif offer_count <= 8:
            score += 10
        else:
            score -= 10  # 竞争激烈

        # Buy Box 占有率
        buy_box_price = pricing.get("buy_box_price")
        if buy_box_price and buy_box_price < 50:
            score += 15  # 低价格区间通常有更高曝光

        return max(0, min(100, score))

    @staticmethod
    def _detect_ad_presence(asin: str) -> Dict[str, bool]:
        """检测广告存在指标（基于启发式规则）"""
        # 实际实现需要调用 Advertising API 的 Share of Voice
        # 这里返回模拟检测结果
        return {
            "has_sp_ads": True,  # 大部分热销商品都有 SP 广告
            "has_sb_ads": False,
            "has_sd_ads": False,
            "confidence": "estimated",  # estimated / verified
        }
