"""
AIGC 媒体生成模块 - 业务服务层 (Service)
=======================================
处理业务逻辑，调用 Agent 能力
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from .agent_aigc import AIGCMediaAgent
from . import asset_gen
from .schemas import (
    ImageGenerationRequest,
    MainImageAnalysisRequest,
    APlusContentRequest,
    BrandStoryRequest,
    TranslationRequest,
    SelectionTranslateRequest,
    EnhancePromptRequest,
    AssetGenerationRequest,
    InfographicRequest,
    ComplianceCheckRequest,
    VideoScriptRequest,
)

logger = logging.getLogger(__name__)

# 初始化 Agent
agent = AIGCMediaAgent()


# ============================================================
# 图片生成服务
# ============================================================

async def generate_product_image_service(request: ImageGenerationRequest) -> Dict[str, Any]:
    """产出产品图片提示词包（**不返回图片文件**；真出图走 generate_assets_service）。"""
    try:
        result = await agent.generate_product_image(request)
        # 缺参追问：透出 needs_clarification 标记，让主 Agent 逐项追问而非硬凑
        if isinstance(result, dict) and result.get("needs_clarification"):
            return {
                "success": False,
                "needs_clarification": True,
                "missing_fields": result.get("missing_fields", []),
                "message": result.get("message", "信息不足，需补充后生成"),
            }
        return {
            "success": True,
            "data": result,
            "message": "已产出图片提示词包（本能力不返回图片文件；需要真出图请调用 generate_assets）"
        }
    except Exception as e:
        logger.error(f"图片生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "图片生成失败"
        }


# ============================================================
# 主图分析服务
# ============================================================

async def analyze_main_image_service(request: MainImageAnalysisRequest) -> Dict[str, Any]:
    """分析主图质量"""
    try:
        result = await agent.analyze_main_image(
            image_url=request.image_url,
            product_category=request.product_category
        )
        result_dict = {
            "overall_score": result.overall_score,
            "ctr_prediction": result.ctr_prediction,
            "visual_appeal": result.visual_appeal,
            "compliance_check": result.compliance_check,
            "improvement_suggestions": result.improvement_suggestions,
            "ab_test_variants": result.ab_test_variants
        }
        return {
            "success": True,
            "data": result_dict,
            "message": "主图分析完成"
        }
    except Exception as e:
        logger.error(f"主图分析失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "主图分析失败"
        }


# ============================================================
# A+ 内容生成服务
# ============================================================

async def generate_a_plus_content_service(request: APlusContentRequest) -> Dict[str, Any]:
    """生成 A+ 内容"""
    try:
        result = await agent.generate_a_plus_content(
            product_name=request.product_name,
            brand=request.brand,
            features=request.features,
            specifications=request.specifications,
            target_audience=request.target_audience
        )
        result_dict = {
            "product_asin": result.product_asin,
            "brand_name": result.brand_name,
            "modules": [
                {
                    "module_id": m.module_id,
                    "module_type": m.module_type,
                    "title": m.title,
                    "content": m.content,
                    "images_needed": m.images_needed,
                    "character_count": m.character_count,
                    "seo_score": m.seo_score
                } for m in result.modules
            ],
            "total_modules": result.total_modules,
            "estimated_read_time": result.estimated_read_time,
            "optimization_tips": result.optimization_tips
        }
        return {
            "success": True,
            "data": result_dict,
            "message": f"A+ 内容生成完成，共 {result.total_modules} 个模块"
        }
    except Exception as e:
        logger.error(f"A+内容生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "A+内容生成失败"
        }


# ============================================================
# 品牌故事服务
# ============================================================

async def generate_brand_story_service(request: BrandStoryRequest) -> Dict[str, Any]:
    """生成品牌故事"""
    try:
        result = await agent.generate_brand_story(
            brand_name=request.brand_name,
            industry=request.industry,
            products=request.products,
            values=request.values,
            founding_story=request.founding_story
        )
        result_dict = {
            "brand_name": result.brand_name,
            "brand_positioning": result.brand_positioning,
            "brand_mission": result.brand_mission,
            "brand_values": result.brand_values,
            "origin_story": result.origin_story,
            "unique_selling_proposition": result.unique_selling_proposition,
            "tagline_options": result.tagline_options,
            "about_brand_text": result.about_brand_text,
            "storytelling_angles": result.storytelling_angles
        }
        return {
            "success": True,
            "data": result_dict,
            "message": "品牌故事生成完成"
        }
    except Exception as e:
        logger.error(f"品牌故事生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "品牌故事生成失败"
        }


# ============================================================
# 翻译服务
# ============================================================

async def translate_content_service(request: TranslationRequest) -> Dict[str, Any]:
    """翻译内容"""
    try:
        result = await agent.translate_content(
            content=request.content,
            source_lang=request.source_lang,
            target_lang=request.target_lang,
            context=request.context,
            keywords=request.keywords
        )
        result_dict = {
            "original_text": result.original_text,
            "translated_text": result.translated_text,
            "source_lang": result.source_lang,
            "target_lang": result.target_lang,
            "seo_optimized": result.seo_optimized,
            "keyword_inclusion": result.keyword_inclusion,
            "cultural_notes": result.cultural_notes,
            "alternative_versions": result.alternative_versions
        }
        return {
            "success": True,
            "data": result_dict,
            "message": f"翻译完成 ({request.source_lang} -> {request.target_lang})"
        }
    except Exception as e:
        logger.error(f"翻译失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "翻译失败"
        }


async def translate_selection_service(request: SelectionTranslateRequest) -> Dict[str, Any]:
    """
    划词翻译（轻量）。

    与 `translate_content_service` 的区别只在产出结构：这边只要一个译文，
    不返回 SEO/文化/多版本字段 —— 划词要的是快，不是全。
    """
    try:
        return await agent.translate_selection(
            text=request.text,
            target_lang=request.target_lang,
            context=request.context,
        )
    except Exception as e:
        logger.error(f"划词翻译失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "翻译服务暂不可用",
            "data": {
                "original_text": request.text,
                "translation": "",
                "source_lang": "",
                "target_lang": request.target_lang,
                "degraded": True,
            },
        }


async def enhance_prompt_service(request: EnhancePromptRequest) -> Dict[str, Any]:
    """
    提示词增强（输入框辅助）。

    与 `translate_selection_service` 并列：都是「轻量 LLM 辅助」，都只回一段文本。
    区别是这边改的不是语言，是需求的完备度。
    """
    try:
        return await agent.enhance_prompt(
            draft=request.draft,
            context=request.context,
        )
    except Exception as e:
        logger.error(f"提示词增强失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "提示词增强暂不可用",
            "data": {"draft": request.draft, "enhanced": "", "degraded": True},
        }


async def generate_assets_service(request: AssetGenerationRequest) -> Dict[str, Any]:
    """静态素材批量出图（面板驱动）。

    与 `generate_product_image_service` 的区别：那条是**对话驱动**、可以先追问缺参；
    这条是**面板驱动** —— 老板在表单里点「开始生成素材」就该出图，不做缺参拦截
    （否则表单没有的字段会让面板永远出不了图）。

    失败语义：整批全失败才 success=False；部分失败仍 success=True，把逐项原因
    放进 data.failed（长任务最怕一张挂掉就全灭）。
    """
    try:
        data = await asset_gen.generate_assets(
            product_name=request.product_name,
            image_types=request.image_types,
            category=request.category,
            extra_description=request.extra_description,
            count_per_type=request.count_per_type,
            size=request.size,
            source_image=request.source_image or "",
        )
        if data.get("degraded") and not data.get("assets"):
            reason = data.get("degraded_reason") or "素材生成失败"
            return {"success": False, "error": reason, "message": reason, "data": data}
        return {
            "success": True,
            "data": data,
            "message": f"已生成 {len(data.get('assets', []))} 张素材",
        }
    except Exception as e:
        logger.error(f"静态素材生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "素材生成失败",
            "data": {"assets": [], "failed": [], "degraded": True, "degraded_reason": str(e)},
        }


# ============================================================
# 信息图生成服务
# ============================================================

async def generate_infographic_service(request: InfographicRequest) -> Dict[str, Any]:
    """生成信息图规格"""
    try:
        result = await agent.generate_infographic(
            topic=request.topic,
            data_points=request.data_points,
            infographic_type=request.infographic_type,
            brand_colors=request.brand_colors
        )
        result_dict = {
            "title": result.title,
            "type": result.type,
            "dimensions": result.dimensions,
            "sections": result.sections,
            "color_palette": result.color_palette,
            "text_content": result.text_content,
            "call_to_action": result.call_to_action
        }
        return {
            "success": True,
            "data": result_dict,
            "message": "信息图规格生成完成"
        }
    except Exception as e:
        logger.error(f"信息图生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "信息图生成失败"
        }


# ============================================================
# 合规检查服务
# ============================================================

async def check_compliance_service(request: ComplianceCheckRequest) -> Dict[str, Any]:
    """检查合规性"""
    try:
        result = await agent.check_compliance(
            image_url=request.image_url,
            platform=request.platform,
            category=request.category
        )
        result_dict = {
            "overall_status": result.overall_status,
            "score": result.score,
            "issues": [
                {
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "description": i.description,
                    "suggestion": i.suggestion,
                    "affected_area": i.affected_area
                } for i in result.issues
            ],
            "passed_checks": result.passed_checks,
            "recommendations": result.recommendations
        }
        return {
            "success": True,
            "data": result_dict,
            "message": f"合规检查完成 - 状态: {result.overall_status}"
        }
    except Exception as e:
        logger.error(f"合规检查失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "合规检查失败"
        }


# ============================================================
# 视频脚本生成服务
# ============================================================

async def generate_video_script_service(request: VideoScriptRequest) -> Dict[str, Any]:
    """生成视频脚本"""
    try:
        result = await agent.generate_video_script(
            product_name=request.product_name,
            product_category=request.product_category,
            key_features=request.key_features,
            target_platform=request.target_platform,
            video_type=request.video_type,
            duration_target=request.duration_target
        )
        result_dict = {
            "title": result.title,
            "total_duration": result.total_duration,
            "format": result.format,
            "target_platform": result.target_platform,
            "scenes": [
                {
                    "scene_number": s.scene_number,
                    "duration": s.duration,
                    "visual_description": s.visual_description,
                    "text_overlay": s.text_overlay,
                    "voiceover": s.voiceover,
                    "background_music": s.background_music,
                    "transition": s.transition
                } for s in result.scenes
            ],
            "hook_lines": result.hook_lines,
            "cta_suggestions": result.cta_suggestions,
            "hashtag_recommendations": result.hashtag_recommendations,
            "production_notes": result.production_notes
        }
        return {
            "success": True,
            "data": result_dict,
            "message": f"视频脚本生成完成，共 {len(result.scenes)} 个场景，总时长 {result.total_duration} 秒"
        }
    except Exception as e:
        logger.error(f"视频脚本生成失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "视频脚本生成失败"
        }


# ============================================================
# 聊天路由服务
# ============================================================

async def chat_service(message: str, context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    聊天消息路由

    根据用户意图分发到对应的处理函数
    """
    try:
        intent = agent.classify_intent(message)

        response = {
            "intent": intent,
            "agent": "aigc_media",
            "timestamp": datetime.now().isoformat(),
            "message": ""
        }

        # 根据意图返回不同的提示信息
        intent_messages = {
            "generate_image": "检测到您想生成产品图片，请使用「AI生图」工具填写详细信息。",
            "analyze_main_image": "检测到您想分析主图，请上传图片URL并使用「主图诊断」功能。",
            "generate_a_plus": "检测到您想生成 A+ 内容，请使用「A+内容生成」工具。",
            "generate_brand_story": "检测到您想生成品牌故事，请使用「品牌故事」工具。",
            "translate": "检测到您需要翻译服务，请使用「多语言翻译」工具。",
            "generate_infographic": "检测到您想制作信息图，请使用「信息图设计」工具。",
            "check_compliance": "检测到您想检查图片合规性，请使用「合规检查」工具。",
            "generate_video_script": "检测到您想生成视频脚本，请使用「视频脚本」工具。",
            "general": "我是 AIGC 媒体生成助手，可以帮您：\n- 🎨 AI 产品图片生成\n- 📊 主图优化分析\n- 📝 A+/EBC 内容生成\n- 🏆 品牌故事文案\n- 🌍 多语言 SEO 翻译\n- 📈 营销信息图设计\n- ✅ 图片合规检查\n- 🎬 短视频脚本生成"
        }

        response["message"] = intent_messages.get(intent, intent_messages["general"])
        response["success"] = True

        return response

    except Exception as e:
        logger.error(f"AIGC聊天处理失败: {e}")
        return {
            "success": False,
            "error": str(e),
            "message": "处理失败"
        }


async def stream_chat(message: str):
    """流式对话入口（返回逐 token 异步迭代器）"""
    async for chunk in agent.stream_chat(message):
        yield chunk


# ============================================================
# Service 类（统一入口，收敛函数式风格）
# ============================================================

class AIGCMediaService:
    """AIGC 媒体生成服务（统一命名空间，便于与其他模块风格对齐）"""

    agent = agent

    generate_product_image = staticmethod(generate_product_image_service)
    generate_assets = staticmethod(generate_assets_service)
    analyze_main_image = staticmethod(analyze_main_image_service)
    generate_a_plus_content = staticmethod(generate_a_plus_content_service)
    generate_brand_story = staticmethod(generate_brand_story_service)
    translate_content = staticmethod(translate_content_service)
    translate_selection = staticmethod(translate_selection_service)
    enhance_prompt = staticmethod(enhance_prompt_service)
    generate_infographic = staticmethod(generate_infographic_service)
    check_compliance = staticmethod(check_compliance_service)
    generate_video_script = staticmethod(generate_video_script_service)
    chat = staticmethod(chat_service)
    stream_chat = staticmethod(stream_chat)
