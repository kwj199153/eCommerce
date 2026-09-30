"""
Listing 生成优化模块 - 数据模型定义

定义请求/响应的 Pydantic Schema，用于 API 参数校验和序列化。
"""

from typing import List, Optional, Any
from pydantic import BaseModel, Field

# ★ 「本次请求的作用对象」的形状定义在机制层（`ai_infra/context_target.py`）。
#   第 257 轮起三条、第 298 轮起四条（+ 客服）共用同一个形状 ——
#   各写一份的下场是"少一个字段"的那一份不报任何错，只是静默拿不到对象。
from ai_infra.context_target import ContextTargetPayload


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
    # ★ 自定义生成指令（第 273 轮）：存在则**完全替换**默认生成 prompt。
    custom_prompt: Optional[str] = Field(None, description="自定义生成指令，存在则完全替换默认 prompt")


class BulletPointsRequest(BaseModel):
    """生成五点描述请求"""
    product_name: str = Field(..., description="产品名称")
    features: Optional[List[str]] = Field(None, description="产品特性")
    tone: Optional[str] = Field("professional", description="语调：professional/friendly/luxury")
    # ★ 自定义生成指令（第 273 轮）：存在则**完全替换**默认生成 prompt。
    custom_prompt: Optional[str] = Field(None, description="自定义生成指令，存在则完全替换默认 prompt")


class DescriptionRequest(BaseModel):
    """生成产品描述请求"""
    product_name: str = Field(..., description="产品名称")
    features: Optional[List[str]] = Field(None, description="产品特性")
    include_html: bool = Field(True, description="是否包含 HTML 格式")
    style: Optional[str] = Field("storytelling", description="风格：storytelling/technical/benefit-driven")
    # ★ 自定义生成指令（第 273 轮）：存在则**完全替换**默认生成 prompt。
    custom_prompt: Optional[str] = Field(None, description="自定义生成指令，存在则完全替换默认 prompt")


class KeywordRequest(BaseModel):
    """生成后台搜索词请求（第 273 轮从裸标量形参改为 Pydantic 模型）"""
    title: str = Field(..., description="当前标题", min_length=1)
    category: str = Field("", description="产品类目")
    # ★ 自定义生成指令（第 273 轮）：存在则**完全替换**默认生成 prompt。
    custom_prompt: Optional[str] = Field(None, description="自定义生成指令，存在则完全替换默认 prompt")


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
    session_id: Optional[str] = Field(
        None, description="会话 ID（非空 ⇒ 服务端多轮记忆；空 ⇒ 不留记忆）"
    )

    # ★ 点名通道（第 188 轮）：用户点名本次对话要用的技能名（可选）。
    #   留空 ⇒ 只注入技能目录，仍由模型自己判断用哪条（渐进披露的原路径）。
    #   ★ 归属校验不在这里：技能名由服务端在 `read_skill_text` 里按
    #     身份 + 启用 + 对本 Agent 启用 三重过滤，请求体只负责**传递名字**。
    skill: Optional[str] = Field(default=None, description="本次对话指定使用的技能名（可选）")

    # ★ 本次请求的「作用对象」（第 257 轮）。与 `skill` 是**一对**：
    #   `skill` 说「这次用哪条技能」，它说「这次冲着哪个对象来的」。
    #   本 Agent 的对话链路此前靠 `_extract_product_info(query, …)` 从**用户消息
    #   文本**里抽品名 —— 用户在顶部【载入产品】选好了商品、然后只说「帮我优化标题」
    #   时，模型只能猜（而猜错的结论打在别的品上，看不出任何异常）。
    #   ★ 传 `null` 与**不传**含义不同（明确没有 vs 客户端未参与），
    #     判别由 `model_fields_set` 承担，本字段故意不给默认值。
    context_target: Optional[ContextTargetPayload] = Field(
        default=None,
        description="本次请求的作用对象；传 null 表示本次明确没有对象",
    )


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
