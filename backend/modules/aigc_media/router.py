"""
AIGC 媒体生成模块 - API 路由 (Router)
====================================
提供 12 个 RESTful API 端点
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, Dict, Any
import logging

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
from .service import (
    generate_product_image_service,
    analyze_main_image_service,
    generate_a_plus_content_service,
    generate_brand_story_service,
    translate_content_service,
    generate_infographic_service,
    check_compliance_service,
    generate_video_script_service,
    chat_service,
)

logger = logging.getLogger(__name__)

# 创建路由器
router = APIRouter(
    prefix="/api/v1/aigc",
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
    result = await generate_product_image_service(request)
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
    result = await analyze_main_image_service(request)
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
    result = await generate_a_plus_content_service(request)
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
    result = await generate_brand_story_service(request)
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
    result = await translate_content_service(request)
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
    result = await generate_infographic_service(request)
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
    result = await check_compliance_service(request)
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
    result = await generate_video_script_service(request)
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
async def aigc_chat(request: ChatRequest):
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
    result = await chat_service(
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
