"""
Listing 生成优化模块 - 数据模型定义

定义请求/响应的 Pydantic Schema，用于 API 参数校验和序列化。
"""

from typing import List, Optional, Any
from pydantic import BaseModel, Field


# ====== 请求模型 ======

class GenerateListingRequest(BaseModel):
    """生成完整 Listing 请求"""
    product_name: str = Field(..., description="产品名称", min_length=2, max_length=200)
    brand: Optional[str] = Field(None, description="品牌名称")
    category: Optional[str] = Field(None, description="产品类目")
    features: Optional[List[str]] = Field(None, description="产品特性列表")
    price: Optional[float] = Field(None, gt=0, description="产品售价")
    target_audience: Optional[str] = Field(None, description="目标受众")
    unique_selling_point: Optional[str] = Field(None, description="独特卖点")
    competitor_asins: Optional[List[str]] = Field(None, description="竞品 ASIN 列表")
    generate_ab_variants: bool = Field(False, description="是否生成 A/B 测试变体")
    language: str = Field("en-US", description="输出语言，默认美式英语")


class OptimizeListingRequest(BaseModel):
    """优化现有 Listing 请求"""
    current_listing: dict = Field(
        ...,
        description="当前 Listing 内容",
        example={
            "title": "Current Product Title Here",
            "bullets": ["Bullet 1", "Bullet 2", "Bullet 3", "Bullet 4", "Bullet 5"],
            "description": "Current product description text...",
            "search_terms": "current backend keywords here",
        }
    )
    optimization_focus: Optional[List[str]] = Field(
        None,
        description="优化重点：title/bullets/description/keywords/all"
    )
    competitor_reference: Optional[bool] = Field(False, description="是否参考竞品")


class TitleOptimizationRequest(BaseModel):
    """单独优化标题请求"""
    current_title: str = Field(..., description="当前标题", min_length=5)
    product_name: Optional[str] = Field(None, description="产品名称（辅助理解）")
    main_keyword: Optional[str] = Field(None, description="主关键词")


class BulletPointsRequest(BaseModel):
    """生成五点描述请求"""
    product_name: str = Field(..., description="产品名称")
    features: Optional[List[str]] = Field(None, description="产品特性")
    tone: Optional[str] = Field("professional", description="语调：professional/friendly/luxury")


class DescriptionRequest(BaseModel):
    """生成产品描述请求"""
    product_name: str = Field(..., description="产品名称")
    features: Optional[List[str]] = Field(None, description="产品特性")
    include_html: bool = Field(True, description="是否包含 HTML 格式")
    style: Optional[str] = Field("storytelling", description="风格：storytelling/technical/benefit-driven")


class SEOAnalysisRequest(BaseModel):
    """SEO 分析请求"""
    title: str = Field(..., description="当前标题")
    bullets: List[str] = Field(..., description="当前五点描述列表", min_items=1)
    description: str = Field(..., description="当前产品描述")
    search_terms: str = Field("", description="当前后台搜索词")
    main_keyword: Optional[str] = Field(None, description="主关键词")
    platform: str = Field("amazon", description="目标平台")


class ABTestRequest(BaseModel):
    """A/B 测试请求"""
    base_listing: dict = Field(..., description="基础 Listing 内容")
    variant_count: int = Field(3, ge=2, le=5, description="生成变体数量")
    test_hypothesis: Optional[str] = Field(None, description="测试假设")


class ListingChatRequest(BaseModel):
    """自然语言对话请求"""
    message: str = Field(..., description="用户消息")
    context: Optional[dict] = Field(None, description="上下文信息（可选）")


# ====== 响应模型 ======

class TitleOptimizationResponse(BaseModel):
    """标题优化响应"""
    original_title: str
    optimized_title: str
    character_count: int
    seo_score: float
    improvements: List[str]
    optimization_notes: List[str]


class BulletPointsResponse(BaseModel):
    """五点描述响应"""
    product_name: str
    bullets: List[dict]
    total_characters: int
    coverage_score: float
    tips: List[str]


class DescriptionResponse(BaseModel):
    """产品描述响应"""
    product_name: str
    plain_text: str
    html_content: Optional[str]
    word_count: int
    sections: List[dict]


class SearchTermsResponse(BaseModel):
    """搜索词响应"""
    terms: List[str]
    total_bytes: int
    is_valid: bool
    usage_tips: List[str]


class CompleteListingResponse(BaseModel):
    """完整 Listing 响应"""
    product_name: str
    generated_at: str
    platform: str
    title: dict
    bullet_points: dict
    description: dict
    search_terms: dict
    seo_score: dict
    ab_variants: Optional[List[dict]]


class SEOAnalysisResponse(BaseModel):
    """SEO 分析响应"""
    overall_score: float
    title_score: float
    bullet_score: float
    description_score: float
    keywords_score: float
    checklist: dict
    improvement_areas: List[str]
    grade: str  # A/B/C/D/F


class OptimizationSuggestionResponse(BaseModel):
    """优化建议响应"""
    suggestions: List[dict]
    summary: str
    high_priority_count: int


class ABTestResponse(BaseModel):
    """A/B 测试响应"""
    variants: List[dict]
    summary: str
    testing_recommendations: List[str]


# ====== 包装模型 ======

class ApiResponse(BaseModel):
    """通用成功响应"""
    success: bool = True
    data: Any
    message: str = "OK"


class ErrorResponse(BaseModel):
    """通用错误响应"""
    success: bool = False
    error: str
    details: Optional[Any] = None
