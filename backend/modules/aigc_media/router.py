"""
AIGC 媒体生成模块 - API 路由 (Router)
====================================
提供 12 个 RESTful API 端点
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from core.billing.usage_tracker import meter_agent_chat
from core.database import get_db
from core.observability.context import current_request_id
from core.tenant.middleware import get_current_shop_id
from typing import Optional, Dict, Any
import logging

from ai_infra.sse import sse_event_stream

from core.auth.dependencies import require_auth_if_enabled
from modules.user_subscription.models import User

from . import job_service

from .schemas import (
    AigcJobSubmitRequest,
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
    summary="静态素材批量生成（同步）",
    description=(
        "面板驱动：按素材类型（SPU 主图/白底副图/场景图/生活方式图/信息图解图/广告主图）"
        "并发出图，返回可长期访问的 /static 图片地址。\n"
        "- 与 /image/generate 的区别：那条是对话驱动、可先追问缺参；这条不做缺参拦截。\n"
        "- 任一类型失败不影响其余，失败原因逐项回传；**全部失败才返回 503**。\n"
        "- 当前为文生图（源图需公网可访问地址才能图生图，图床尚未接入）。\n"
        "\n"
        "⚠️ **本端点会同步阻塞整个出图过程**（最坏 720s：8 张 / 并发 2 × 单张超时 180s）。\n"
        "前端生产路径请改用异步端点 `POST /aigc/jobs`（kind=asset_generate），"
        "本端点保留给「能承受长连接」的调用方（脚本、调试、以及没有 worker 的环境）。\n"
        "两者共用同一个执行内核，出图口径不会分叉。"
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


# ============================================================
# 异步任务端点（长任务不阻塞 HTTP）
# ------------------------------------------------------------
# 为什么需要这一组：出图原本整段同步阻塞在 HTTP 请求里。
# 实测参数（代码常量）：单张 15-25s、内部并发 2（3 并发会被服务端 429）、
# 单次最多 8 张、`wait_for_images` 单张超时 180s
# ⇒ 最坏 8/2 × 180s = 720s。
# 而前端 axios 超时是 300s ⇒ **720 > 300**：极端情况下用户看到「超时失败」，
# 但后端仍在出图、DashScope 已按张计费（≈¥0.14/张）—— **钱花了，结果丢了**。
#
# 改成异步后：
#   - HTTP 连接只占一次提交（毫秒级），不再被长任务长期占用（uvicorn worker 得以释放）
#   - 即使前端轮询中断，任务仍在 worker 上跑完并落库，刷新后能查到
#   - 任务状态落 `aigc_jobs` 表（不依赖 Celery result backend，后者 1 小时就过期）
#
# ★ 与同步端点的分工（避免「同一件事两条路各写一遍」）：
#   两者**共用** `asset_gen.generate_assets` 这个执行内核，只是投递方式不同：
#     - `/aigc/asset/generate`（同步）：调用方能承受长连接时使用（脚本 / 调试 / 无 worker 环境）
#     - `/aigc/jobs`（异步）：**前端生产路径**
#   所以「执行口径」只有一套源，「投递方式」按调用方能力分两种。
# ============================================================

#: kind → 入参校验模型。★ 异步端点不是「把 dict 直接塞进队列」：
#: 这里复用同步端点同一套 Pydantic 模型，校验强度完全一致。
_JOB_PARAM_SCHEMAS = {
    "asset_generate": AssetGenerationRequest,
    "image_generate": ImageGenerationRequest,
}


def _job_owner(current_user: Optional[User]) -> tuple[str, bool]:
    """从当前用户推出 (user_id, is_admin)。

    认证开关关闭时（演示模式）current_user 为 None ⇒ user_id 为空串，
    此时任务按 shop_id 收敛（见 job_service._inflight_filter 的说明）。
    """
    if current_user is None:
        return "", False
    return current_user.id, current_user.role.value == "admin"


@router.post(
    "/jobs",
    status_code=202,
    summary="提交 AIGC 长任务（异步）",
    description=(
        "提交后立即返回 202 + job_id，出图在 Celery worker 上执行。\n"
        "- 用 `GET /aigc/jobs/{job_id}` 轮询状态，状态落 `aigc_jobs` 表（不依赖 Celery result backend）。\n"
        "- **同一入参的进行中任务会被去重**：连点两次不会重复出图（出图按张计费，重复提交=重复花钱），"
        "命中时返回同一条任务并带 `deduplicated=true`。\n"
        "- 单用户进行中任务上限 3 条，超出返回 429。\n"
        "- 异步执行器（Redis/Celery）不可用时返回 503 并把任务显式标成 failed —— "
        "**不会**留下一个永远停在 pending 的假排队任务。"
    ),
)
async def submit_aigc_job(
    request: AigcJobSubmitRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id),
    db: AsyncSession = Depends(get_db),
):
    """提交一个 AIGC 长任务，立即返回 job_id。"""
    schema = _JOB_PARAM_SCHEMAS.get(request.kind)
    if schema is None:
        raise HTTPException(
            status_code=400,
            detail=(
                f"未知任务类型：{request.kind}；"
                f"当前支持 {', '.join(sorted(_JOB_PARAM_SCHEMAS))}"
            ),
        )

    try:
        params = schema.model_validate(request.params).model_dump(mode="json")
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"任务入参不合法：{exc.errors()[:3]}",
        ) from exc

    user_id, is_admin = _job_owner(current_user)

    try:
        job, deduplicated = await job_service.submit_job(
            db,
            kind=request.kind,
            payload=params,
            user_id=user_id,
            shop_id=shop_id or "",
            request_id=current_request_id(),
        )
    except job_service.TooManyInflight as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    # ★ 必须先提交再投递：worker 拿到 job_id 后要回库读 payload，
    #   若先投递后提交，worker 可能读到一个尚未可见的行。
    await db.commit()

    if deduplicated:
        return {
            "success": True,
            "job": job_service.serialize_job(job),
            "deduplicated": True,
            "message": "已存在相同参数的进行中任务，本次未重复提交（不重复计费）",
        }

    # 投递到 Celery
    ctx = {
        "request_id": current_request_id(),
        "shop_id": shop_id or "",
        "user_id": user_id,
    }
    try:
        task_id = job_service.enqueue(job.id, ctx)
    except job_service.ExecutorUnavailable as exc:
        # ★ 显式失败：把刚建的 pending 任务标成 failed 再报 503。
        #   绝不能只报错不改状态 —— 用户会看到列表里多出一条永远「排队中」的任务。
        await job_service.mark_failed(db, job.id, str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                f"异步执行器不可用，任务未被执行：{exc}。"
                "请确认 Redis 与 Celery worker 已启动（docker compose up -d redis worker）"
            ),
        ) from exc

    if task_id:
        await job_service.set_celery_task_id(db, job.id, task_id)

    return {
        "success": True,
        "job": job_service.serialize_job(job),
        "deduplicated": False,
        "message": "任务已提交，请轮询 /api/v1/aigc/jobs/{job_id} 获取进度",
    }


@router.get(
    "/jobs/{job_id}",
    summary="查询 AIGC 任务状态",
    description=(
        "读取任务的权威状态（`aigc_jobs` 表）。\n"
        "- **按归属过滤**：只能查自己提交的任务，别人的 job_id 一律返回 404"
        "（返回 404 而非 403，避免泄露 job_id 是否存在）；admin 可查全部。\n"
        "- `status`：pending → running → succeeded / failed；`is_terminal=true` 表示已结束，不用再轮询。\n"
        "- 时间戳为 **UTC 且带 Z 后缀**，前端请用 `new Date(s).toLocaleString('zh-CN')` 折算本地时区。"
    ),
)
async def get_aigc_job(
    job_id: str,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """按 ID 查询任务状态（只能查自己的）。"""
    user_id, is_admin = _job_owner(current_user)
    job = await job_service.get_job(db, job_id, user_id=user_id, is_admin=is_admin)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"success": True, "job": job_service.serialize_job(job)}


@router.get(
    "/jobs",
    summary="我的 AIGC 任务列表",
    description=(
        "最近创建优先，默认 20 条（上限 100）。\n"
        "用途：前端轮询中断（刷新页面 / 关掉标签页）后仍能找回自己刚提交的任务 —— "
        "这是异步化相对同步阻塞最直接的收益：**任务不会因为前端断线而消失**。"
    ),
)
async def list_aigc_jobs(
    limit: int = Query(default=job_service.DEFAULT_LIST_LIMIT, ge=1, le=100),
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    db: AsyncSession = Depends(get_db),
):
    """列出当前用户的任务（不含 result 大字段，列表页用）。"""
    user_id, is_admin = _job_owner(current_user)
    jobs = await job_service.list_jobs(db, user_id=user_id, is_admin=is_admin, limit=limit)
    return {
        "success": True,
        "jobs": [job_service.serialize_job(j, include_result=False) for j in jobs],
        "total": len(jobs),
    }

