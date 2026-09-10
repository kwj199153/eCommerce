"""
AIGC 媒体生成模块 - 业务服务层 (Service)
=======================================
处理业务逻辑，调用 Agent 能力
"""

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from .agent_aigc import AIGCMediaAgent
from .schemas import (
    ImageGenerationRequest,
    MainImageAnalysisRequest,
    APlusContentRequest,
    BrandStoryRequest,
    TranslationRequest,
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
    """生成产品图片"""
    try:
        result = await agent.generate_product_image(request)
        return {
            "success": True,
            "data": result,
            "message": "图片生成请求已提交"
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
            "passed_checks": result.passed,
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
