"""AIGC 媒体生成 - 内容类端点（图片 / A+ / 品牌故事 / 信息图 / 合规 / 视频脚本）。

从 `router.py` 逐字搬来（第 363 轮拆包）。本文件只负责 HTTP 面：
入参校验靠 `schemas`，业务逻辑全在 `AIGCMediaService`。

★ 这一组端点**不带**鉴权依赖 —— 与 translate / assets 组不同。
  这是拆分前的既有形态（`router.py` 里这一组本来就没有 `Depends(require_auth_if_enabled)`），
  本次拆分**刻意原样保留**：拆分只应搬动代码，不应顺带改动鉴权面。
  若要给它们加鉴权，请单独做一轮并说明理由。
"""

from fastapi import APIRouter, HTTPException

from ..schemas import (
    AgentResponse,
    APlusContentRequest,
    BrandStoryRequest,
    ComplianceCheckRequest,
    ImageGenerationRequest,
    InfographicRequest,
    MainImageAnalysisRequest,
    VideoScriptRequest,
)
from ..service import AIGCMediaService

router = APIRouter()

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
    summary="主图质量分析（含模拟值声明）",
    description=(
        "分析主图的视觉吸引力、预估点击率，并提供优化建议和A/B测试变体。"
        "注意：视觉评分与 CTR 当前为模拟值；合规项未接入自动判定，返回待人工核查清单。"
    )
)
async def analyze_image(request: MainImageAnalysisRequest):
    """
    主图分析功能

    分析维度：
    - 视觉吸引力评分（5个子维度，⚠️ 当前为模拟值）
    - Amazon 合规核查清单（⚠️ 未接入自动判定，不产出通过/不通过结论）
    - CTR 预测（⚠️ 当前为模拟值）
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
    summary="图片合规核查清单（不产出自动判定结论）",
    description=(
        "整理目标平台（如 Amazon）的合规核查清单供人工逐项确认。"
        "本接口未接入自动判定能力，overall_status 恒为 manual_review_required，"
        "不产出「通过/警告/不通过」结论。"
    )
)
async def check_image_compliance(request: ComplianceCheckRequest):
    """
    图片合规核查清单

    覆盖范围（按平台规则整理）：
    - 主图规范（白背景、无水印、占比等）
    - 生活场景图规范
    - 通用版权/侵权规则
    - 类目特殊要求

    输出：overall_status = "manual_review_required" + 人工核查清单。
    **不产出通过/警告/不通过结论**（未接入图片合规自动判定能力，禁止编造结论）。
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
