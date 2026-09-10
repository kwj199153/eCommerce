"""
AIGC 媒体生成模块 - 数据模型 (Schemas)
======================================
Pydantic 模型用于 API 请求/响应验证
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from enum import Enum


# ============================================================
# 枚举类型
# ============================================================

class ImageType(str, Enum):
    MAIN = "main"
    LIFESTYLE = "lifestyle"
    INFOGRAPHIC = "infographic"
    COMPARISON = "comparison"
    PACKAGING = "packaging"
    SIZE_CHART = "size_chart"


class ContentType(str, Enum):
    BRAND_STORY = "brand_story"
    PRODUCT_DESCRIPTION = "product_description"
    A_PLUS_CONTENT = "a_plus_content"
    SOCIAL_MEDIA = "social_media"
    EMAIL_COPY = "email_copy"


class VideoFormat(str, Enum):
    SHORT_FORM = "short_form"       # 短视频（TikTok/Reels）
    PRODUCT_DEMO = "product_demo"   # 产品演示
    TESTIMONIAL = "testimonial"     # 用户见证
    TUTORIAL = "tutorial"           # 教程类


class TargetPlatform(str, Enum):
    TIKTOK = "tiktok"
    REELS = "reels"
    YOUTUBE_SHORTS = "youtube_shorts"


# ============================================================
# 图片生成相关
# ============================================================

class ImageGenerationRequest(BaseModel):
    """图片生成请求"""
    product_name: str = Field(..., min_length=2, max_length=200, description="产品名称")
    category: str = Field(..., description="产品类目")
    brand: str = Field(default="", max_length=100, description="品牌名称")
    target_market: str = Field(default="US", description="目标市场")
    image_type: str = Field(default="main", description="图片类型")
    style: str = Field(default="professional", description="风格")
    color_scheme: str = Field(default="", description="配色方案")
    keywords: List[str] = Field(default_factory=list, description="关键词列表")
    reference_description: str = Field(default="", description="参考描述")
    dimensions: str = Field(default="2000x2000", description="尺寸")


class ImageCaption(BaseModel):
    """图片标题建议"""
    caption: str
    type: str  # seo-focused/emotion-driven/benefit-oriented


class GeneratedImageResponse(BaseModel):
    """生成图片响应"""
    success: bool
    image_id: str
    prompt: str
    image_type: str
    style: str
    dimensions: str
    description: str
    suggested_captions: List[str]
    seo_keywords: List[str]
    usage_tips: List[str]
    variation_suggestions: List[Dict[str, Any]]
    style_guide: Dict[str, str]
    generation_params: Dict[str, Any]
    note: str


# ============================================================
# 主图分析相关
# ============================================================

class MainImageAnalysisRequest(BaseModel):
    """主图分析请求"""
    image_url: str = Field(..., description="图片URL或路径")
    product_category: str = Field(default="", description="产品类目")


class VisualScore(BaseModel):
    """视觉评分"""
    visual_appeal: float
    clarity: float
    color_quality: float
    composition: float
    brand_presence: float


class ComplianceCheckItem(BaseModel):
    """合规检查项"""
    check: str
    severity: str
    suggestion: str


class ComplianceCheckResult(BaseModel):
    """合规检查结果"""
    score: float
    passed: List[str]
    issues: List[ComplianceCheckItem]


class ABTestVariant(BaseModel):
    """A/B测试变体"""
    variant: str
    description: str
    predicted_ctr: float


class MainImageAnalysisResponse(BaseModel):
    """主图分析响应"""
    overall_score: float = Field(..., ge=0, le=100)
    ctr_prediction: float = Field(..., ge=0, le=1)
    visual_appeal: VisualScore
    compliance_check: ComplianceCheckResult
    improvement_suggestions: List[str]
    ab_test_variants: List[ABTestVariant]


# ============================================================
# A+ 内容相关
# ============================================================

class APlusContentRequest(BaseModel):
    """A+内容生成请求"""
    product_name: str = Field(..., min_length=2, description="产品名称")
    brand: str = Field(..., min_length=1, description="品牌名")
    features: List[str] = Field(..., min_length=1, description="产品特性列表")
    specifications: Optional[Dict[str, str]] = Field(default=None, description="规格参数")
    target_audience: str = Field(default="", description="目标受众")


class APlusModuleResponse(BaseModel):
    """A+内容模块响应"""
    module_id: str
    module_type: str
    title: str
    content: str
    images_needed: int
    character_count: int
    seo_score: float


class APlusContentResponse(BaseModel):
    """A+内容完整响应"""
    product_asin: str
    brand_name: str
    modules: List[APlusModuleResponse]
    total_modules: int
    estimated_read_time: int
    optimization_tips: List[str]


# ============================================================
# 品牌故事相关
# ============================================================

class BrandStoryRequest(BaseModel):
    """品牌故事生成请求"""
    brand_name: str = Field(..., min_length=1, description="品牌名称")
    industry: str = Field(..., description="所属行业")
    products: List[str] = Field(..., min_length=1, description="主要产品线")
    values: Optional[List[str]] = Field(default=None, description="品牌价值观")
    founding_story: str = Field(default="", description="创立背景")


class StorytellingAngle(BaseModel):
    """叙事角度"""
    angle: str
    narrative: str


class BrandStoryResponse(BaseModel):
    """品牌故事响应"""
    brand_name: str
    brand_positioning: str
    brand_mission: str
    brand_values: List[str]
    origin_story: str
    unique_selling_proposition: str
    tagline_options: List[str]
    about_brand_text: str
    storytelling_angles: List[StorytellingAngle]


# ============================================================
# 翻译相关
# ============================================================

class TranslationRequest(BaseModel):
    """翻译请求"""
    content: str = Field(..., min_length=1, description="待翻译内容")
    source_lang: str = Field(default="zh", description="源语言代码")
    target_lang: str = Field(..., description="目标语言代码")
    context: str = Field(default="ecommerce", description="翻译上下文")
    keywords: Optional[List[str]] = Field(default=None, description="需保留的关键词")


class KeywordInclusion(BaseModel):
    """关键词包含情况"""
    keyword: str
    position: str


class AlternativeVersion(BaseModel):
    """替代版本"""
    version: str
    text: str


class TranslationResponse(BaseModel):
    """翻译响应"""
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    seo_optimized: bool
    keyword_inclusion: List[KeywordInclusion]
    cultural_notes: List[str]
    alternative_versions: List[AlternativeVersion]


# ============================================================
# 信息图相关
# ============================================================

class InfographicRequest(BaseModel):
    """信息图生成请求"""
    topic: str = Field(..., min_length=1, description="主题")
    data_points: Optional[List[Dict]] = Field(default=None, description="数据点")
    infographic_type: str = Field(default="benefit", description="信息图类型")
    brand_colors: Optional[List[str]] = Field(default=None, description="品牌色板")


class InfographicSection(BaseModel):
    """信息图区块"""
    type: str
    content: Optional[str] = None
    icon: Optional[str] = None
    items: Optional[List[str]] = None
    rows: Optional[int] = None
    number: Optional[int] = None
    text: Optional[str] = None
    value: Optional[str] = None
    label: Optional[str] = None


class InfographicSpecResponse(BaseModel):
    """信息图规格响应"""
    title: str
    type: str
    dimensions: str
    sections: List[InfographicSection]
    color_palette: List[str]
    text_content: Dict[str, str]
    call_to_action: str


# ============================================================
# 合规检查相关
# ============================================================

class ComplianceCheckRequest(BaseModel):
    """合规检查请求"""
    image_url: str = Field(..., description="图片URL")
    platform: str = Field(default="amazon", description="目标平台")
    category: str = Field(default="", description="产品类目")


class ComplianceIssueItem(BaseModel):
    """合规问题项"""
    issue_type: str
    severity: str
    description: str
    suggestion: str
    affected_area: str


class ComplianceReportResponse(BaseModel):
    """合规报告响应"""
    overall_status: str  # pass/warning/fail
    score: float
    issues: List[ComplianceIssueItem]
    passed_checks: List[str]
    recommendations: List[str]


# ============================================================
# 视频脚本相关
# ============================================================

class VideoScriptRequest(BaseModel):
    """视频脚本生成请求"""
    product_name: str = Field(..., min_length=2, description="产品名称")
    product_category: str = Field(..., description="产品类目")
    key_features: List[str] = Field(..., min_length=1, description="核心特性")
    target_platform: str = Field(default="tiktok", description="目标平台")
    video_type: str = Field(default="product_demo", description="视频类型")
    duration_target: int = Field(default=30, ge=10, le=120, description="目标时长(秒)")


class VideoSceneResponse(BaseModel):
    """视频场景响应"""
    scene_number: int
    duration: int
    visual_description: str
    text_overlay: str
    voiceover: str
    background_music: str
    transition: str


class VideoScriptResponse(BaseModel):
    """视频脚本完整响应"""
    title: str
    total_duration: int
    format: str
    target_platform: str
    scenes: List[VideoSceneResponse]
    hook_lines: List[str]
    cta_suggestions: List[str]
    hashtag_recommendations: List[str]
    production_notes: List[str]


# ============================================================
# 通用响应模型
# ============================================================

class AgentResponse(BaseModel):
    """Agent 通用响应"""
    success: bool = True
    agent: str = "aigc_media"
    intent: str = ""
    response: Optional[Any] = None
    message: str = ""
    timestamp: str = ""


class ChatRequest(BaseModel):
    """聊天请求"""
    message: str = Field(..., description="用户消息")
    session_id: Optional[str] = Field(default=None, description="会话ID")
    context: Optional[Dict[str, Any]] = Field(default=None, description="上下文信息")
