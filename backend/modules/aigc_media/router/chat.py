"""AIGC 媒体生成 - 对话端点与模块元信息（tools / health）。

从 `router.py` 逐字搬来（第 363 轮拆包）。

★ 两条对话链路（`/chat` 与 `/chat/stream`）都必须把「点名技能」与「作用对象」
  在同**一个作用域**里入栈；流式那条的写入点必须在**生成器体内**
  —— 包在返回 StreamingResponse 的外层，`async with` 会在生成器被第一次迭代
  之前就退出 ⇒ 等于没设。原文的注释一并保留在下面各自的位置。
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from core.metering.usage_tracker import meter_agent_chat

from ai_infra.context_target import bind_context_target, context_target_payload
from ai_infra.skills import bind_requested_skill
from ai_infra.sse import sse_event_stream

from ..service import AIGCMediaService
from ..schemas import AgentResponse, ChatRequest

router = APIRouter()

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
    - 合规检查 → 引导至合规核查清单
    - 视频脚本 → 引导至视频脚本工具
    """
        # ★ 点名通道（第 188 轮）：本次对话若指定了技能名，把它置进
        #   调用链上下文，由 `skills_selected` 段落把该技能正文注入
        #   system prompt（与 `load_skill` 共用同一个解析实现）。
        # ★ 「作用对象」与它**同一个作用域**（第 257 轮）：两条通道一起
        #   入栈、一起出栈，避免出现「技能读到了、对象没读到」的半态。
        #   ★ 本 Agent **只注入、不拒答**，理由见 `.schemas.ChatRequest` 的字段注释。
    async with (
        bind_requested_skill(request.skill),
        bind_context_target(context_target_payload(request)),
    ):
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
            # ★ 写入点必须在**生成器体内**：包在返回 StreamingResponse
            #   的外层，`async with` 会在生成器被第一次迭代之前就退出 ⇒ 等于没设。
            # ★ 作用对象同域入栈（第 257 轮），理由见 `/chat` 那处注释。
            async with (
                bind_requested_skill(request.skill),
                bind_context_target(context_target_payload(request)),
            ):
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
            "description": "分析主图质量、预测 CTR（模拟值）；合规项只出核查清单，不产出通过/不通过结论",
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
            "name": "✅ 合规核查清单",
            "description": "整理平台合规核查清单供人工确认（未接入自动判定，不产出通过/不通过结论）",
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
    from ..agent_aigc import AIGCMediaAgent
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
