"""AIGC 媒体生成 - 翻译与提示词辅助端点。

从 `router.py` 逐字搬来（第 363 轮拆包）。

★ 两个翻译端点的分工（别合并）：
  · `/content/translate`           SEO 友好翻译，面向**内容生产**（关键词位置/文化建议/多版本）
  · `/content/translate-selection` 划词翻译，面向**阅读辅助**（只回一个译文，首字更快）

★ 第 367 轮删掉了第三个端点 `/content/translate-image`（截屏翻译）—— 那条链路整套
  退场（前端浮层 /「粘贴图片」入口 + 后端 OCR + `vision_models.py` + `image_translate.py`）。
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from core.auth.dependencies import require_auth_if_enabled
from core.identity.models import User

from ..service import AIGCMediaService
from ..schemas import (
    AgentResponse,
    EnhancePromptRequest,
    SelectionTranslateRequest,
    TranslationRequest,
)

router = APIRouter()

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
