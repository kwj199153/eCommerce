"""
AIGC 媒体生成模块 - API 路由 (Router)
====================================
提供 12 个 RESTful API 端点
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from core.billing.usage_tracker import meter_agent_chat
from typing import Optional, Dict, Any
import logging

from ai_infra.sse import sse_event_stream

from core.auth.dependencies import require_auth_if_enabled
from modules.user_subscription.models import User

from .schemas import (
    ImageGenerationRequest,
    GeneratedImageResponse,
    MainImageAnalysisRequest,
    MainImageAnalysisResponse,
    APlusContentRequest,
    APlusContentResponse,
    BrandStoryRequest,
    BrandStoryResponse,
    TranslationRequest,
    SelectionTranslateRequest,
    EnhancePromptRequest,
    AssetGenerationRequest,
    TranslationResponse,
    InfographicRequest,
    InfographicSpecResponse,
    ComplianceCheckRequest,
    ComplianceReportResponse,
    VideoScriptRequest,
    VideoScriptResponse,
    ChatRequest,
    AgentResponse,
)
from .service import AIGCMediaService

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/aigc",
    tags=["AIGC 媒体生成 (Phase 7)"]
)


# ============================================================
# 图片生成端点
# ============================================================

@router.post(
    "/image/generate",
    response_model=AgentResponse,
    summary="AI 生成产品图片",
    description="根据产品信息生成专业的电商图片（主图/场景图/信息图等）"
)
async def generate_image(request: ImageGenerationRequest):
    """
    AI 产品图片生成

    支持的图片类型：
    - main: 专业主图（纯白背景）
    - lifestyle: 场景生活方式图
    - infographic: 营销信息图
    - comparison: 产品对比图
    - packaging: 包装展示图
    - size_chart: 尺寸参考图

    支持的风格：
    - professional: 专业商业摄影
    - lifestyle: 生活场景
    - minimalist: 极简主义
    - dramatic: 戏剧性风格
    """
    result = await AIGCMediaService.generate_product_image(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "图片生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="generate_image",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


@router.post(
    "/image/analyze",
    response_model=AgentResponse,
    summary="主图质量分析",
    description="分析主图的视觉吸引力、合规性、预估点击率，并提供优化建议和A/B测试变体"
)
async def analyze_image(request: MainImageAnalysisRequest):
    """
    主图分析功能

    分析维度：
    - 视觉吸引力评分（5个子维度）
    - Amazon 合规性检查
    - CTR 预测
    - A/B 测试变体建议
    """
    result = await AIGCMediaService.analyze_main_image(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "主图分析失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="analyze_main_image",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# A+ 内容端点
# ============================================================

@router.post(
    "/content/a-plus",
    response_model=AgentResponse,
    summary="生成 A+/EBC 内容",
    description="为 Amazon Listing 生成完整的 Enhanced Brand Content 模块化内容"
)
async def create_a_plus_content(request: APlusContentRequest):
    """
    A+ / EBC 内容生成

    生成的模块包括：
    - 品牌故事横幅
    - 产品特性对比表格
    - 核心特性展示（图文结合）
    - 规格参数表
    - 使用场景展示
    """
    result = await AIGCMediaService.generate_a_plus_content(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "A+内容生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="generate_a_plus",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 品牌故事端点
# ============================================================

@router.post(
    "/content/brand-story",
    response_model=AgentResponse,
    summary="生成品牌故事",
    description="生成完整的品牌故事文案，包括品牌定位、使命、起源故事、USP等"
)
async def create_brand_story(request: BrandStoryRequest):
    """
    品牌故事生成

    输出内容：
    - 品牌定位声明
    - 品牌使命
    - 核心价值观
    - 创始故事
    - 独特卖点 (USP)
    - Slogan 建议
    - 完整 About 描述（可用于 Amazon Store）
    - 多角度叙事版本
    """
    result = await AIGCMediaService.generate_brand_story(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "品牌故事生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="generate_brand_story",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 翻译端点
# ============================================================

@router.post(
    "/content/translate",
    response_model=AgentResponse,
    summary="SEO 友好翻译",
    description="将内容翻译为目标语言，同时保留 SEO 关键词，提供文化适配建议"
)
async def translate_content(request: TranslationRequest):
    """
    多语言翻译服务

    特性：
    - SEO 关键词保留与位置优化
    - 文化差异提示
    - 多版本输出（正式版/口语版）
    - 支持主流电商语言
    """
    result = await AIGCMediaService.translate_content(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "翻译失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="translate",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


@router.post(
    "/content/translate-selection",
    response_model=AgentResponse,
    summary="划词翻译",
    description=(
        "用户选中一段文字直接出译文，面向阅读辅助。"
        "与 /content/translate（SEO 友好翻译，面向内容生产）互补："
        "本端点只返回一个译文，不产出关键词位置、文化建议、多版本等结构，因此首字更快。"
    )
)
async def translate_selection(
    request: SelectionTranslateRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    划词翻译

    特性：
    - 目标语言 auto：含中文则译英，否则译中（看海外商品页的主场景是英译中）
    - 严格只输出译文，保留品牌/型号/规格
    - LLM 不可用时返回 degraded=true 且译文为空 —— **不编造译文**
    """
    result = await AIGCMediaService.translate_selection(request)
    if not result["success"]:
        # 503 而非 500：这是「依赖不可用」不是「请求有问题」
        raise HTTPException(status_code=503, detail=result.get("message", "翻译服务暂不可用"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="translate_selection",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


@router.post(
    "/prompt/enhance",
    response_model=AgentResponse,
    summary="提示词增强",
    description=(
        "把对话框里的一句口语化需求改写成更可执行的提示词（补齐任务目标 / 约束条件 / 期望的输出形式）。"
        "面向输入辅助，只回一段文本；**不会编造用户没给的业务事实**，缺失信息以「（请补充：…）」留白。"
    )
)
async def enhance_prompt(
    request: EnhancePromptRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    提示词增强

    特性：
    - 只回改写后的提示词，前端直接替换输入框内容
    - 严禁编造 ASIN / 店铺 / 数字等业务事实，缺什么就留白让用户自己填
    - LLM 不可用时返回 degraded=true 且内容为空 —— **不编造提示词**
    """
    result = await AIGCMediaService.enhance_prompt(request)
    if not result["success"]:
        # 503 而非 500：这是「依赖不可用」不是「请求有问题」
        raise HTTPException(status_code=503, detail=result.get("message", "提示词增强暂不可用"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="enhance_prompt",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 静态素材批量生成（面板驱动）
# ============================================================

@router.post(
    "/asset/generate",
    response_model=AgentResponse,
    summary="静态素材批量生成",
    description=(
        "面板驱动：按素材类型（SPU 主图/白底副图/场景图/生活方式图/信息图解图/广告主图）"
        "并发出图，返回可长期访问的 /static 图片地址。\n"
        "- 与 /image/generate 的区别：那条是对话驱动、可先追问缺参；这条不做缺参拦截。\n"
        "- 任一类型失败不影响其余，失败原因逐项回传；**全部失败才返回 503**。\n"
        "- 当前为文生图（源图需公网可访问地址才能图生图，图床尚未接入）。"
    ),
)
async def generate_assets(
    request: AssetGenerationRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """静态素材批量生成（面板驱动，不追问缺参）。"""
    result = await AIGCMediaService.generate_assets(request)
    if not result["success"]:
        raise HTTPException(status_code=503, detail=result.get("message", "素材生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="asset_generate",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 信息图端点
# ============================================================

@router.post(
    "/design/infographic",
    response_model=AgentResponse,
    summary="生成营销信息图规格",
    description="生成信息图的设计规格，包括布局、配色、文字内容等"
)
async def design_infographic(request: InfographicRequest):
    """
    信息图设计规格生成

    类型支持：
    - benefit: 优势展示型
    - comparison: 对比型
    - process: 流程步骤型
    - statistic: 数据统计型

    输出完整设计稿规格，可直接用于设计工具制作
    """
    result = await AIGCMediaService.generate_infographic(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "信息图生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="generate_infographic",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 合规检查端点
# ============================================================

@router.post(
    "/compliance/check",
    response_model=AgentResponse,
    summary="图片合规检查",
    description="检查图片是否符合目标平台（如 Amazon）的规范要求"
)
async def check_image_compliance(request: ComplianceCheckRequest):
    """
    图片合规性检查

    检查项目：
    - 主图规范（白背景、无水印、占比等）
    - 生活场景图规范
    - 通用版权/侵权规则
    - 类目特殊要求

    输出：通过/警告/不通过 + 具体问题 + 修改建议
    """
    result = await AIGCMediaService.check_compliance(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "合规检查失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="check_compliance",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 视频脚本端点
# ============================================================

@router.post(
    "/video/script",
    response_model=AgentResponse,
    summary="生成短视频脚本",
    description="为 TikTok/Reels/YouTube Shorts 等平台生成完整的视频脚本"
)
async def create_video_script(request: VideoScriptRequest):
    """
    短视频脚本生成

    输出内容：
    - 分镜头脚本（画面/字幕/配音/音乐/转场）
    - 黄金3秒钩子备选
    - CTA 引导建议
    - 话题标签推荐
    - 制作备注

    支持平台：TikTok, Instagram Reels, YouTube Shorts
    """
    result = await AIGCMediaService.generate_video_script(request)
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result.get("error", "视频脚本生成失败"))
    return AgentResponse(
        success=True,
        agent="aigc_media",
        intent="generate_video_script",
        response=result["data"],
        message=result["message"],
        timestamp=""
    )


# ============================================================
# 聊天路由端点
# ============================================================

@router.post(
    "/chat",
    response_model=AgentResponse,
    summary="AIGC 助手聊天",
    description="智能识别用户意图并分发到对应的功能模块"
)
async def aigc_chat(
    request: ChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """
    AIGC 媒体助手聊天接口

    自动识别用户意图：
    - 生成图片 → 引导至图片生成工具
    - 主图分析 → 引导至主图诊断
    - A+内容 → 引导至 A+ 生成
    - 品牌故事 → 引导至品牌故事工具
    - 翻译 → 引导至翻译工具
    - 信息图 → 引导至信息图设计
    - 合规检查 → 引导至合规检测
    - 视频脚本 → 引导至视频脚本工具
    """
    result = await AIGCMediaService.chat(
        message=request.message,
        context=request.context
    )
    return AgentResponse(
        success=result.get("success", True),
        agent="aigc_media",
        intent=result.get("intent", ""),
        response=None,
        message=result.get("message", ""),
        timestamp=result.get("timestamp", "")
    )


@router.post(
    "/chat/stream",
    summary="AIGC 助手聊天（SSE 流式）",
)
async def aigc_chat_stream(
    request: ChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """AIGC 助手聊天，SSE 流式返回（打字机效果）。"""
    import json as _json

    async def _wrapped():
        try:
            async for event in sse_event_stream(AIGCMediaService.stream_chat(request.message)):
                yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


# ============================================================
# 工具列表端点
# ============================================================

@router.get(
    "/tools",
    response_model=AgentResponse,
    summary="获取可用工具列表",
    description="返回 AIGC 媒体生成模块的所有可用工具及其描述"
)
async def get_tools():
    """返回工具列表"""
    tools = [
        {
            "id": "ai-image-gen",
            "name": "🎨 AI 生图",
            "description": "生成专业产品主图、场景图、信息图等",
            "endpoint": "/api/v1/aigc/image/generate",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "main-image-diagnosis",
            "name": "🔍 主图诊断",
            "description": "分析主图质量、合规性、预测 CTR",
            "endpoint": "/api/v1/aigc/image/analyze",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "a-plus-generator",
            "name": "📝 A+ 内容生成",
            "description": "生成 Amazon EBC/A+ 模块化内容",
            "endpoint": "/api/v1/aigc/content/a-plus",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "brand-story-writer",
            "name": "🏆 品牌故事",
            "description": "生成品牌定位、起源故事、About 文案",
            "endpoint": "/api/v1/aigc/content/brand-story",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "multi-lang-translator",
            "name": "🌍 多语言翻译",
            "description": "SEO 友好的多语言翻译服务",
            "endpoint": "/api/v1/aigc/content/translate",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "infographic-designer",
            "name": "📊 信息图设计",
            "description": "生成营销信息图设计规格",
            "endpoint": "/api/v1/aigc/design/infographic",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "compliance-checker",
            "name": "✅ 合规检查",
            "description": "检查图片是否符合平台规范",
            "endpoint": "/api/v1/aigc/compliance/check",
            "mode": "form",
            "status": "active"
        },
        {
            "id": "video-script-writer",
            "name": "🎬 视频脚本",
            "description": "TikTok/Reels 短视频脚本生成",
            "endpoint": "/api/v1/aigc/video/script",
            "mode": "form",
            "status": "active"
        }
    ]

    return AgentResponse(
        success=True,
        agent="aigc_media",
        response={"tools": tools, "total": len(tools)},
        message=f"AIGC 媒体生成模块就绪，共 {len(tools)} 个工具",
        timestamp=""
    )


# ============================================================
# 健康检查端点
# ============================================================

@router.get(
    "/health",
    summary="健康检查",
    description="检查 AIGC 媒体生成模块状态"
)
async def health_check():
    """健康检查"""
    from .agent_aigc import AIGCMediaAgent
    agent = AIGCMediaAgent()
    return {
        "status": "healthy",
        "agent": agent.agent_name,
        "version": agent.version,
        "tools_count": 8,
        "capabilities": [
            "image_generation",
            "main_image_analysis",
            "a_plus_content",
            "brand_story",
            "translation",
            "infographic",
            "compliance_check",
            "video_script"
        ]
    }
