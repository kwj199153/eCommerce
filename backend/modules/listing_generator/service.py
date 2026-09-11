"""
Listing 生成优化模块 - 业务逻辑层

封装 ListingGeneratorAgent 的调用，处理业务规则和后处理逻辑。
"""

import logging
from typing import List, Optional, Dict, Any

from .agent_listing import ListingGeneratorAgent, CompleteListing
from .schemas import (
    GenerateListingRequest,
    OptimizeListingRequest,
    TitleOptimizationRequest,
    BulletPointsRequest,
    DescriptionRequest,
    SEOAnalysisRequest,
    ABTestRequest,
    TitleOptimizationResponse,
    BulletPointsResponse,
    DescriptionResponse,
    SearchTermsResponse,
    CompleteListingResponse,
    SEOAnalysisResponse,
    OptimizationSuggestionResponse,
    ABTestResponse,
)

logger = logging.getLogger(__name__)


class ListingGeneratorService:
    """Listing 生成优化服务"""

    def __init__(self, platform: str = "amazon"):
        self.agent = ListingGeneratorAgent(platform=platform)

    async def generate_complete_listing(
        self, request: GenerateListingRequest
    ) -> CompleteListingResponse:
        """
        生成完整 Listing

        流程：标题 → 五点 → 描述 → 关键词 → SEO评分 → (可选)A/B变体
        """
        context = {
            "name": request.product_name,
            "brand": request.brand,
            "category": request.category or "",
            "features": request.features or [],
            "price": request.price or 29.99,
            "generate_ab_variants": request.generate_ab_variants,
        }

        result = await self.agent.invoke(
            query=f"生成 {request.product_name} 的完整 Listing",
            context=context,
        )

        listing_data = result.data.get("listing", {})

        return CompleteListingResponse(
            product_name=listing_data.get("product_name", request.product_name),
            generated_at=listing_data.get("generated_at", ""),
            platform=listing_data.get("platform", "amazon"),
            title=listing_data.get("title", {}),
            bullet_points=listing_data.get("bullet_points", {}),
            description=listing_data.get("description", {}),
            search_terms=listing_data.get("search_terms", {}),
            seo_score=listing_data.get("seo_score", {}),
            ab_variants=listing_data.get("ab_variants"),
        )

    async def optimize_listing(
        self, request: OptimizeListingRequest
    ) -> OptimizationSuggestionResponse:
        """
        优化现有 Listing

        返回逐项优化建议，按优先级排序
        """
        result = await self.agent.invoke(
            query="优化我的现有 Listing",
            context={"current_listing": request.current_listing},
        )

        opt_data = result.data

        return OptimizationSuggestionResponse(
            suggestions=opt_data.get("suggestions", []),
            summary=opt_data.get("summary", ""),
            high_priority_count=opt_data.get("high_priority_count", 0),
        )

    async def optimize_title(
        self, request: TitleOptimizationRequest
    ) -> TitleOptimizationResponse:
        """单独优化标题"""
        # 复用 Agent 的标题生成能力
        result = await self.agent._generate_title(
            product_name=request.product_name or request.current_title[:50],
            brand="",
            category="",
            features=[],
        )

        # 同时分析原标题的问题
        current_issues = []
        if len(request.current_title) > 200:
            current_issues.append(f"原标题超长 ({len(request.current_title)}字符)")
        if request.current_title.isupper():
            current_issues.append("原标题全大写")

        return TitleOptimizationResponse(
            original_title=request.current_title,
            optimized_title=result.title,
            character_count=result.character_count,
            seo_score=result.seo_score,
            improvements=result.optimization_notes,
            optimization_notes=current_issues,
        )

    async def generate_bullet_points(
        self, request: BulletPointsRequest
    ) -> BulletPointsResponse:
        """生成五点描述"""
        result = await self.agent._generate_bullet_points(
            product_name=request.product_name,
            features=request.features,
        )

        tips = []
        if result.coverage_score < 80:
            tips.append(f"卖点覆盖度 {result.coverage_score:.1f}%，建议补充更多产品特性")
        if result.total_characters > 2000:
            tips.append("总字符数偏多，可适当精简每条内容")
        tips.append("每条五点以大写标题开头，便于移动端快速浏览")

        return BulletPointsResponse(
            product_name=request.product_name,
            bullets=[b.dict() for b in result.bullets],
            total_characters=result.total_characters,
            coverage_score=result.coverage_score,
            tips=tips,
        )

    async def generate_description(
        self, request: DescriptionRequest
    ) -> DescriptionResponse:
        """生成产品描述"""
        result = await self.agent._generate_description(
            product_name=request.product_name,
            features=request.features,
        )

        return DescriptionResponse(
            product_name=request.product_name,
            plain_text=result.plain_text,
            html_content=result.html_content,
            word_count=result.word_count,
            sections=result.sections,
        )

    async def generate_search_terms(
        self, title: str, category: str = ""
    ) -> SearchTermsResponse:
        """生成后台搜索词"""
        from .agent_listing import ListingTitle

        # 构建临时标题对象
        title_obj = ListingTitle(
            title=title,
            character_count=len(title),
            word_count=len(title.split()),
            main_keyword=title.split()[0] if title else "",
            seo_score=0,
        )

        result = await self.agent._generate_search_terms(title_obj, category)

        usage_tips = [
            "使用空格分隔各个关键词",
            "不要重复标题中已有的词",
            "包含同义词和拼写变体",
            "不要使用逗号分隔",
        ]

        return SearchTermsResponse(
            terms=result.terms,
            total_bytes=result.total_bytes,
            is_valid=result.is_valid,
            usage_tips=usage_tips,
        )

    async def analyze_seo(
        self, request: SEOAnalysisRequest
    ) -> SEOAnalysisResponse:
        """
        SEO 诊断分析

        返回多维度评分 + 改进建议 + 等级评定
        """
        result = await self.agent.invoke(
            query="分析这个 Listing 的 SEO 表现",
            context={
                "title": request.title,
                "bullets": request.bullets,
                "description": request.description,
                "search_terms": request.search_terms,
                "main_keyword": request.main_keyword,
            },
        )

        seo_data = result.data.get("seo_score", {})

        # 计算等级
        overall = seo_data.get("overall_score", 0)
        grade = self._calculate_grade(overall)

        return SEOAnalysisResponse(
            overall_score=overall,
            title_score=seo_data.get("title_score", 0),
            bullet_score=seo_data.get("bullet_score", 0),
            description_score=seo_data.get("description_score", 0),
            keywords_score=seo_data.get("keywords_score", 0),
            checklist=seo_data.get("checklist", {}),
            improvement_areas=seo_data.get("improvement_areas", []),
            grade=grade,
        )

    async def generate_ab_test_variants(
        self, request: ABTestRequest
    ) -> ABTestResponse:
        """生成 A/B 测试变体"""
        result = await self.agent.invoke(
            query="生成 A/B 测试变体",
            context={"base_listing": request.base_listing},
        )

        variants = result.data.get("variants", [])

        recommendations = [
            f"建议对 {len(variants)} 个变体进行为期 2 周的 A/B 测试",
            "主要监测指标：点击率(CTR)、转化率(CVR)、页面停留时间",
            "确保每个变体获得足够的流量（至少 1000 次展示）后再做决策",
            "可同时测试标题变体或主图变体",
        ]

        return ABTestResponse(
            variants=variants,
            summary=result.data.get("summary", ""),
            testing_recommendations=recommendations,
        )

    async def chat(self, message: str, context: dict = None) -> dict:
        """自然语言对话入口"""
        result = await self.agent.invoke(message, context=context)
        return {
            "response": result.content,
            "data": result.data,
            "display_type": result.display_type,
        }

    async def stream_chat(self, message: str):
        """流式对话入口（返回逐 token 异步迭代器）"""
        async for chunk in self.agent.stream_chat(message):
            yield chunk

    @staticmethod
    def _calculate_grade(score: float) -> str:
        """根据分数计算等级"""
        if score >= 90:
            return "A"
        elif score >= 80:
            return "B"
        elif score >= 70:
            return "C"
        elif score >= 60:
            return "D"
        else:
            return "F"
