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
    # —— 追问字段（子 Agent 接管后逐项追问补齐，缺省视为"未提供"）——
    material: str = Field(default="", description="产品材质（如不锈钢/玻璃/塑料/陶瓷）")
    shape: str = Field(default="", description="产品造型（如圆柱/方形/流线型）")
    view_angle: str = Field(default="", description="拍摄视角（如正面/45度/俯视/三视图）")
    need_logo: bool | None = Field(default=None, description="是否需要展示 logo")
    product_detail: str = Field(default="", description="产品细节描述（需突出展示的设计/功能点）")
    background_rule: str = Field(default="", description="背景规则（如纯白底/允许阴影/场景背景）")


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


class SelectionTranslateRequest(BaseModel):
    """划词翻译请求（面向阅读辅助：用户选中一段文字，只要一个能直接读的译文）"""
    text: str = Field(..., min_length=1, max_length=2000, description="选中的文本")
    target_lang: str = Field(
        default="auto",
        description="目标语言代码；auto = 按原文自动判断（含中文则译英，否则译中）"
    )
    context: str = Field(
        default="ecommerce",
        description="翻译上下文，决定术语口味（如 ecommerce / listing / customer_service）"
    )


class SelectionTranslateResponse(BaseModel):
    """
    划词翻译响应。

    刻意**不含** seo_optimized / keyword_inclusion / cultural_notes / alternative_versions
    —— 那些是内容生产（`TranslationResponse`）需要的，划词场景背上它们只会拖慢首字。
    """
    original_text: str
    translation: str
    source_lang: str = Field(description="实际判定的源语言")
    target_lang: str = Field(description="实际使用的目标语言")
    degraded: bool = Field(
        default=False,
        description="LLM 不可用时为 True，此时 translation 为空字符串（绝不编造译文）"
    )


class EnhancePromptRequest(BaseModel):
    """
    提示词增强请求。

    面向**输入框辅助**：用户在对话框里写了一句口语化需求，点一下变成更可执行的提示词。
    与 `SelectionTranslateRequest` 并列，但改的不是语言，是需求的完备度。
    """
    draft: str = Field(..., min_length=1, max_length=2000, description="用户原始输入")
    context: str = Field(
        default="ecommerce",
        description="业务上下文，决定补齐哪些维度（如 ecommerce / listing / ad / customer_service）"
    )


class EnhancePromptResponse(BaseModel):
    """
    提示词增强响应。

    刻意**只回一段文本** —— 输入框辅助要的是「点一下就能替换进去」，不是一份分析报告。
    """
    draft: str = Field(description="原始输入，原样回传，便于前端做比对/撤销")
    enhanced: str = Field(description="增强后的提示词")
    degraded: bool = Field(
        default=False,
        description="LLM 不可用时为 True，此时 enhanced 为空字符串（绝不编造提示词）"
    )


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
# 静态素材批量生成（面板驱动）
# ============================================================

class AssetGenerationRequest(BaseModel):
    """静态素材批量出图请求（面板驱动，不做缺参追问）。"""
    product_name: str = Field(..., min_length=1, max_length=200, description="产品名称")
    image_types: List[str] = Field(
        default_factory=lambda: ["spu-main"],
        description="素材类型：spu-main/white-bg/scene/lifestyle/infographic/ad-main",
    )
    category: str = Field(default="general", description="产品类目")
    extra_description: str = Field(default="", description="补充描述（场景描述、卖点关键词等）")
    count_per_type: int = Field(default=1, ge=1, le=4, description="每种类型生成张数")
    size: str = Field(default="1024*1024", description="分辨率，必须用星号分隔（小写 x 会被拒）")
    source_image: Optional[str] = Field(
        default=None,
        description=(
            "产品原图（图生图底图）：公网 URL 或 base64 data URI 均可，"
            "万相 base_image_url 原生支持 base64、无需图床。"
            "留空则退回文生图。"
        ),
    )


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


# ============================================================
# 异步任务（长任务不阻塞 HTTP）
# ============================================================

class AigcJobSubmitRequest(BaseModel):
    """异步任务提交请求。

    设计：``kind`` + ``params`` 两段式，而不是「一种任务一个提交端点」。

    - ``params`` 的校验由路由层按 ``kind`` 找到对应的请求模型再 ``model_validate``，
      所以**校验强度与同步端点完全一致**（不是把 dict 原样塞进消息队列）。
    - 加一种新长任务只需：在 ``job_service.ALLOWED_KINDS`` 登记 +
      在 ``tasks._dispatch`` 加一个分支 + 在这里加一条映射，
      **不需要新增提交/查询端点**（否则每加一种任务就复制一遍轮询协议）。
    """

    kind: str = Field(
        ...,
        description="任务类型：asset_generate（静态素材批量出图）/ image_generate（单张产品图）",
    )
    params: Dict[str, Any] = Field(
        default_factory=dict, description="任务入参，结构由 kind 决定（见对应同步端点的请求体）"
    )

