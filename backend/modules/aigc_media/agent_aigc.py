"""
AIGC 媒体生成 Agent (Phase 7)
============================
核心能力：
1. AI 产品图片生成 - 场景图、主图、变体图
2. 主图优化建议 - 点击率预测、视觉分析
3. A+ 内容生成 - EBC 模块化内容
4. 品牌故事文案 - 品牌定位、故事线
5. 多语言翻译 - SEO 友好翻译
6. 关键词视觉化 - 信息图、对比图
7. 图片合规检查 - 平台规则检测
8. 视频脚本生成 - 短视频、产品展示
"""

import re
import random
import math
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Any, AsyncIterable
from datetime import datetime, timedelta
from enum import Enum

from core.logger import get_logger

logger = get_logger(__name__)


# ============================================================
# 数据模型
# ============================================================

class ImageType(str, Enum):
    MAIN = "main"           # 主图
    LIFESTYLE = "lifestyle" # 场景图
    INFOGRAPHIC = "infographic"  # 信息图
    COMPARISON = "comparison"    # 对比图
    PACKAGING = "packaging"      # 包装图
    SIZE_CHART = "size_chart"    # 尺码表


class ContentType(str, Enum):
    BRAND_STORY = "brand_story"
    PRODUCT_DESCRIPTION = "product_description"
    A_PLUS_CONTENT = "a_plus_content"
    SOCIAL_MEDIA = "social_media"
    EMAIL_COPY = "email_copy"


class ComplianceLevel(str, Enum):
    PASS = "pass"           # 通过
    WARNING = "warning"     # 警告
    FAIL = "fail"           # 不通过


@dataclass
class ImageGenerationRequest:
    """图片生成请求"""
    product_name: str
    category: str
    brand: str = ""
    target_market: str = "US"
    image_type: str = "main"
    style: str = "professional"
    color_scheme: str = ""
    keywords: List[str] = field(default_factory=list)
    reference_description: str = ""
    dimensions: str = "2000x2000"


@dataclass
class GeneratedImage:
    """生成的图片信息"""
    image_id: str
    prompt: str
    image_type: str
    description: str
    suggested_captions: List[str]
    seo_keywords: List[str]
    usage_tips: List[str]
    variation_suggestions: List[str]


@dataclass
class MainImageAnalysis:
    """主图分析结果"""
    overall_score: float  # 0-100
    ctr_prediction: float  # 预估点击率
    visual_appeal: Dict[str, Any]
    compliance_check: Dict[str, Any]
    improvement_suggestions: List[str]
    ab_test_variants: List[Dict[str, Any]]


@dataclass
class APlusModule:
    """A+ 内容模块"""
    module_id: str
    module_type: str  # standard/comparison/image_banner/text_table
    title: str
    content: str
    images_needed: int
    character_count: int
    seo_score: float


@dataclass
class APlusContent:
    """完整 A+ 内容"""
    product_asin: str
    brand_name: str
    modules: List[APlusModule]
    total_modules: int
    estimated_read_time: int  # 秒
    optimization_tips: List[str]


@dataclass
class BrandStory:
    """品牌故事"""
    brand_name: str
    brand_positioning: str
    brand_mission: str
    brand_values: List[str]
    origin_story: str
    unique_selling_proposition: str
    tagline_options: List[str]
    about_brand_text: str  # 完整品牌描述（可用于 Amazon Store/Listing）
    storytelling_angles: List[Dict[str, str]]  # 不同叙事角度


@dataclass
class TranslationResult:
    """翻译结果"""
    original_text: str
    translated_text: str
    source_lang: str
    target_lang: str
    seo_optimized: bool
    keyword_inclusion: List[Dict[str, str]]  # [{keyword, position}]
    cultural_notes: List[str]
    alternative_versions: List[Dict[str, str]]  # [{version, text}]


@dataclass
class InfographicSpec:
    """信息图规格"""
    title: str
    type: str  # comparison/benefit/process/statistic
    dimensions: str
    sections: List[Dict[str, Any]]
    color_palette: List[str]
    text_content: Dict[str, str]
    call_to_action: str


@dataclass
class ComplianceIssue:
    """合规问题"""
    issue_type: str
    severity: str  # warning/critical
    description: str
    suggestion: str
    affected_area: str


@dataclass
class ComplianceReport:
    """合规检查报告"""
    overall_status: str
    score: float
    issues: List[ComplianceIssue]
    passed_checks: List[str]
    recommendations: List[str]


@dataclass
class VideoScene:
    """视频场景"""
    scene_number: int
    duration: int  # 秒
    visual_description: str
    text_overlay: str
    voiceover: str
    background_music: str
    transition: str


@dataclass
class VideoScript:
    """视频脚本"""
    title: str
    total_duration: int  # 秒
    format: str  # short_form/product_demo/testimonial
    target_platform: str  # tiktok/reels/youtube_shorts
    scenes: List[VideoScene]
    hook_lines: List[str]  # 黄金3秒钩子
    cta_suggestions: List[str]
    hashtag_recommendations: List[str]
    production_notes: List[str]


# ============================================================
# 核心 Agent 类
# ============================================================

# 导入 LLM 集成能力
try:
    from ai_infra.llm.integration import LLMEnabledAgent, LLMCallResult
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False
    class LLMEnabledAgent:
        ENABLE_LLM = False
        def __init__(self): pass


class AIGCMediaAgent(LLMEnabledAgent if LLM_AVAILABLE else object):
    """
    AIGC 媒体生成 Agent

    负责所有与内容创作、图片生成、多媒体相关的 AI 能力。

    升级特性（Phase 8）：
    - ✅ DashScope Qwen LLM 文案生成（标题/描述/品牌故事等）
    - ✅ 自动降级到模板引擎

    后续可接入：
    - Stable Diffusion / DALL-E (图片生成)
    - Amazon Builder Tools (A+ 内容)
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-plus"       # 文本生成用均衡模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    def __init__(self):
        # 初始化 LLM 基类
        if LLM_AVAILABLE:
            super().__init__()

        self.agent_name = "AIGC 媒体生成器"
        self.version = "2.0.0"  # 升级版本号

    async def _llm_generate_text(self, prompt: str, system_prompt: str = None, max_tokens: int = 1500) -> Optional[str]:
        """
        LLM 增强：生成真实文案内容。

        LLM 不可用或失败时返回 None，由调用方降级到模板/规则生成。
        """
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
            return None
        try:
            result = await self.llm_chat(
                user_message=prompt,
                system_prompt=system_prompt or self.get_prompt_template("aigc_media"),
                model=self.DEFAULT_MODEL,
                temperature=0.8,
                max_tokens=max_tokens,
            )
            if result.success and not result.fallback and result.content:
                return result.content.strip()
        except Exception as e:
            logger.warning(f"[aigc_media] LLM generate failed: {e}")
        return None

        # 图片风格库
        self.image_styles = {
            "professional": {
                "description": "专业商业摄影风格",
                "lighting": "柔和均匀光",
                "background": "纯白或渐变灰",
                "mood": "高端大气",
                "color_temp": "5500K"
            },
            "lifestyle": {
                "description": "生活场景风格",
                "lighting": "自然光",
                "background": "真实使用场景",
                "mood": "亲切自然",
                "color_temp": "暖色调"
            },
            "minimalist": {
                "description": "极简主义风格",
                "lighting": "高调光",
                "background": "大量留白",
                "mood": "简洁现代",
                "color_temp": "中性"
            },
            "dramatic": {
                "description": "戏剧性风格",
                "lighting": "侧光/轮廓光",
                "background": "深色背景",
                "mood": "强烈冲击",
                "color_temp": "冷色调"
            }
        }

        # 平台合规规则
        self.compliance_rules = {
            "amazon": {
                "main_image": [
                    ("纯白背景", "pass", "主图必须使用纯白背景 (RGB 255,255,255)"),
                    ("产品占画面85%以上", "warning", "产品应占据画面85%以上空间"),
                    ("无文字水印", "critical", "主图不能包含任何文字或水印"),
                    ("无配件展示", "warning", "主图不应包含配件，除非是套装"),
                    ("真实照片", "pass", "必须是实拍图，不能是渲染图")
                ],
                "lifestyle": [
                    ("生活场景", "pass", "应展示产品在真实场景中的使用"),
                    ("无误导信息", "critical", "不能有夸大或误导性的视觉效果"),
                    ("分辨率要求", "warning", "建议最低 1000x1000 像素启用缩放")
                ],
                "general": [
                    ("版权清晰", "critical", "确保所有素材拥有使用权"),
                    ("不侵权", "critical", "不得包含其他品牌的商标或logo"),
                    ("符合类目规范", "warning", "不同类目可能有特殊要求")
                ]
            }
        }

        # 多语言 SEO 关键词映射
        self.seo_keyword_maps = {
            "en-de": {  # English to German
                "high quality": "hohe Qualität",
                "premium": "Premium",
                "durable": "robust",
                "eco-friendly": "umweltfreundlich",
                "waterproof": "wasserdicht"
            },
            "en-jp": {  # English to Japanese
                "high quality": "高品質",
                "premium": "プレミアム",
                "durable": "耐久性",
                "eco-friendly": "エコフレンドリー",
                "waterproof": "防水"
            },
            "en-es": {  # English to Spanish
                "high calidad": "alta calidad",
                "premium": "premium",
                "duradero": "duradero",
                "eco-friendly": "ecológico",
                "waterproof": "impermeable"
            }
        }

    async def generate_product_image(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """
        生成产品图片

        Args:
            request: 图片生成请求

        Returns:
            生成的图片信息和提示词
        """
        image_type = request.image_type
        style_config = self.image_styles.get(request.style, self.image_styles["professional"])

        # 构建详细提示词
        prompt = self._build_image_prompt(request, style_config)

        # 生成图片元信息
        image_id = f"IMG_{datetime.now().strftime('%Y%m%d%H%M%S')}_{random.randint(1000,9999)}"

        # 根据图片类型生成不同的说明
        type_specific_content = self._get_type_specific_content(image_type, request)

        return {
            "success": True,
            "image_id": image_id,
            "prompt": prompt,
            "image_type": image_type,
            "style": request.style,
            "dimensions": request.dimensions,
            "description": f"{request.product_name} 的{self._get_image_type_name(image_type)}",
            "suggested_captions": type_specific_content["captions"],
            "seo_keywords": type_specific_content["keywords"],
            "usage_tips": type_specific_content["tips"],
            "variation_suggestions": self._generate_variation_suggestions(request),
            "style_guide": {
                "lighting": style_config["lighting"],
                "background": style_config["background"],
                "mood": style_config["mood"],
                "color_temperature": style_config["color_temp"]
            },
            "generation_params": {
                "model": "stable-diffusion-xl",
                "steps": 50,
                "cfg_scale": 7.5,
                "seed": random.randint(1, 99999)
            },
            "note": "当前为模拟模式，接入真实图片生成服务后返回实际图片URL"
        }

    def _build_image_prompt(self, request: ImageGenerationRequest, style_config: Dict) -> str:
        """构建详细的图片生成提示词"""
        base_prompt = f"Professional product photography of {request.product_name}"

        if request.brand:
            base_prompt += f", brand: {request.brand}"

        base_prompt += f", category: {request.category}"
        base_prompt += f", style: {style_config['description']}"
        base_prompt += f", lighting: {style_config['lighting']}"
        base_prompt += f", background: {style_config['background']}"

        if request.color_scheme:
            base_prompt += f", color scheme: {request.color_scheme}"

        if request.keywords:
            base_prompt += f", keywords: {', '.join(request.keywords[:5])}"

        if request.reference_description:
            base_prompt += f", additional details: {request.reference_description}"

        # 添加图片类型特定指令
        type_instructions = {
            "main": ", pure white background, product occupies 85% of frame, studio lighting, high detail, commercial photography",
            "lifestyle": ", in natural use environment, lifestyle setting, contextual, authentic atmosphere",
            "infographic": ", clean layout with text space, modern design, information visualization ready",
            "comparison": ", side by side comparison layout, before after or versus format, clear visual hierarchy",
            "packaging": ", product packaging showcase, branded unboxing experience, premium presentation",
            "size_chart": ", size reference with measurements, clear scale indicators, technical illustration style"
        }

        base_prompt += type_instructions.get(request.image_type, "")

        # 质量增强词
        base_prompt += ", 8k resolution, highly detailed, professional grade, commercial use"

        return base_prompt

    def _get_image_type_name(self, image_type: str) -> str:
        names = {
            "main": "专业主图",
            "lifestyle": "场景生活方式图",
            "infographic": "营销信息图",
            "comparison": "产品对比图",
            "packaging": "包装展示图",
            "size_chart": "尺寸参考图"
        }
        return names.get(image_type, "产品图片")

    def _get_type_specific_content(self, image_type: str, request: ImageGenerationRequest) -> Dict:
        """根据图片类型生成特定的内容建议"""
        product = request.product_name

        if image_type == "main":
            return {
                "captions": [
                    f"{product} - Premium Quality | Free Shipping",
                    f"{product} - {request.brand or 'Top Rated'} | Shop Now",
                    f"{product} - Best Seller | Limited Time Offer"
                ],
                "keywords": [product.lower(), "premium quality", "best seller", "free shipping", request.category],
                "tips": [
                    "确保产品占画面85%以上空间",
                    "使用纯白背景 (RGB 255,255,255)",
                    "分辨率至少 2000x2000 像素",
                    "展示产品的最佳角度",
                    "避免阴影过重"
                ]
            }
        elif image_type == "lifestyle":
            return {
                "captions": [
                    f"{product} in action - Experience the difference",
                    f"How {product} fits your lifestyle perfectly",
                    f"Real customers love {product} - Join them"
                ],
                "keywords": ["lifestyle", "real world", "experience", "everyday use", product.lower()],
                "tips": [
                    "展示产品在真实使用场景中",
                    "模特/使用者表情自然",
                    "环境光线充足且自然",
                    "构图引导视线到产品",
                    "传达情感和使用体验"
                ]
            }
        elif image_type == "infographic":
            return {
                "captions": [
                    f"{product} - Key Features at a Glance",
                    f"Why Choose {product}? See the facts",
                    f"{product} vs Competitors - The numbers don't lie"
                ],
                "keywords": ["features", "specifications", "comparison", "guide", "infographic"],
                "tips": [
                    "保持设计简洁易读",
                    "使用图标代替大段文字",
                    "突出3-5个核心卖点",
                    "配色与品牌一致",
                    "适合移动端浏览"
                ]
            }
        else:
            return {
                "captions": [f"Discover {product}", f"{product} - See the difference"],
                "keywords": [product.lower(), "quality", "value", request.category],
                "tips": ["保持高质量输出", "符合平台规范"]
            }

    def _generate_variation_suggestions(self, request: ImageGenerationRequest) -> List[Dict]:
        """生成变体建议"""
        variations = []
        styles = list(self.image_styles.keys())
        types = ["main", "lifestyle", "infographic"]

        # 风格变体
        for style in styles[:3]:
            if style != request.style:
                variations.append({
                    "type": "style_variation",
                    "suggestion": f"尝试 {style} 风格",
                    "reason": self.image_styles[style]["description"],
                    "expected_ctr_change": round(random.uniform(-5, 15), 1)
                })

        # 类型变体
        for t in types[:2]:
            if t != request.image_type:
                variations.append({
                    "type": "type_variation",
                    "suggestion": f"添加{self._get_image_type_name(t)}",
                    "reason": "丰富Listing图片组合",
                    "expected_ctr_change": round(random.uniform(3, 12), 1)
                })

        return variations[:4]

    async def analyze_main_image(self, image_url: str, product_category: str = "") -> MainImageAnalysis:
        """
        分析主图质量

        Args:
            image_url: 图片 URL 或路径
            product_category: 产品类目

        Returns:
            主图分析结果
        """
        # 模拟视觉分析结果
        scores = {
            "visual_appeal": round(random.uniform(60, 95), 1),
            "clarity": round(random.uniform(65, 98), 1),
            "color_quality": round(random.uniform(55, 92), 1),
            "composition": round(random.uniform(50, 90), 1),
            "brand_presence": round(random.uniform(40, 85), 1)
        }

        overall = sum(scores.values()) / len(scores)

        # CTR 预测（基于历史数据模拟）
        ctr_base = 0.35  # 行业平均
        ctr_adjustment = (overall - 70) * 0.005
        ctr_prediction = max(0.1, min(0.8, ctr_base + ctr_adjustment + random.uniform(-0.05, 0.05)))

        # 合规检查
        compliance_issues = []
        passed_checks = []

        checks = [
            ("white_background", "纯白背景", random.choice([True, True, True, False])),
            ("no_watermark", "无水印文字", random.choice([True, True, False])),
            ("product_dominant", "产品占比>85%", random.choice([True, True, True, False])),
            ("high_resolution", "高分辨率", random.choice([True, True, True, True, False])),
            ("no_accessories", "无多余配件", random.choice([True, True, False]))
        ]

        for check_id, check_name, passed in checks:
            if passed:
                passed_checks.append(check_name)
            else:
                severity = "critical" if check_id in ["white_background", "no_watermark"] else "warning"
                compliance_issues.append({
                    "check": check_name,
                    "severity": severity,
                    "suggestion": f"建议：{check_name}需要优化"
                })

        # 改进建议
        suggestions = []
        if scores["composition"] < 70:
            suggestions.append("📐 优化构图：尝试三分法则，将产品放在黄金分割点")
        if scores["color_quality"] < 70:
            suggestions.append("🎨 提升色彩：调整饱和度和对比度，使产品更突出")
        if scores["clarity"] < 80:
            suggestions.append("🔍 提高清晰度：使用更高分辨率的原图")
        if not any(c["check"] == "纯白背景" for c in compliance_issues):
            suggestions.append("⚪ 确保背景为纯白色 (RGB 255,255,255)")
        if ctr_prediction < 0.35:
            suggestions.append("👀 提升点击率：增加产品细节特写或使用场景元素")

        # A/B 测试变体
        ab_variants = [
            {
                "variant": "A (当前)",
                "description": "原始图片",
                "predicted_ctr": round(ctr_prediction, 3)
            },
            {
                "variant": "B (角度变化)",
                "description": "45度角拍摄，展示更多产品维度",
                "predicted_ctr": round(ctr_prediction * random.uniform(1.05, 1.2), 3)
            },
            {
                "variant": "C (情境加入)",
                "description": "添加微妙的场景暗示（如桌面/手持）",
                "predicted_ctr": round(ctr_prediction * random.uniform(1.08, 1.18), 3)
            }
        ]

        return MainImageAnalysis(
            overall_score=round(overall, 1),
            ctr_prediction=round(ctr_prediction, 3),
            visual_appeal=scores,
            compliance_check={
                "score": len(passed_checks) / len(checks) * 100,
                "passed": passed_checks,
                "issues": compliance_issues
            },
            improvement_suggestions=suggestions,
            ab_test_variants=ab_variants
        )

    async def generate_a_plus_content(
        self,
        product_name: str,
        brand: str,
        features: List[str],
        specifications: Optional[Dict[str, str]] = None,
        target_audience: str = ""
    ) -> APlusContent:
        """
        生成 A+ / EBC 内容

        Args:
            product_name: 产品名称
            brand: 品牌名
            features: 产品特性列表
            specifications: 规格参数
            target_audience: 目标受众

        Returns:
            A+ 内容模块集合
        """
        modules = []

        # 模块1：品牌故事横幅
        modules.append(APlusModule(
            module_id="M001",
            module_type="image_banner",
            title=f"关于 {brand}",
            content=self._generate_brand_intro(brand, product_name),
            images_needed=1,
            character_count=200,
            seo_score=85.0
        ))

        # 模块2：产品特性对比表格
        modules.append(APlusModule(
            module_id="M002",
            module_type="comparison_table",
            title=f"{product_name} vs 普通产品",
            content=self._generate_comparison_table(features),
            images_needed=0,
            character_count=500,
            seo_score=92.0
        ))

        # 模块3：核心特性展示（图文结合）
        for i, feature in enumerate(features[:4]):
            modules.append(APlusModule(
                module_id=f"M{str(i+3).zfill(3)}",
                module_type="standard",
                title=feature.split("：")[0] if "：" in feature else feature[:30],
                content=self._expand_feature(feature, product_name),
                images_needed=1,
                character_count=300,
                seo_score=round(random.uniform(78, 95), 1)
            ))

        # 模块4：规格参数表
        if specifications:
            modules.append(APlusModule(
                module_id=M006,
                module_type="text_table",
                title="产品规格",
                content=self._format_specifications(specifications),
                images_needed=0,
                character_count=len(specifications) * 40,
                seo_score=88.0
            ))

        # 模块5：使用场景
        modules.append(APlusModule(
            module_id="M007",
            module_type="image_banner",
            title="使用场景",
            content=self._generate_usage_scenarios(product_name, target_audience),
            images_needed=3,
            character_count=250,
            seo_score=82.0
        ))

        total_chars = sum(m.character_count for m in modules)
        avg_read_speed = 3  # 字符/秒（中文约3字/秒，英文更快）

        return APlusContent(
            product_asin=f"B0{random.randint(10000000, 99999999)}",
            brand_name=brand,
            modules=modules,
            total_modules=len(modules),
            estimated_read_time=max(30, total_chars // avg_read_speed),
            optimization_tips=[
                "每个模块保持焦点单一，避免信息过载",
                "使用高质量图片（最低1600x1600）",
                "融入目标关键词但保持自然",
                "定期更新内容以保持新鲜度",
                "利用模块顺序讲述品牌故事"
            ]
        )

    def _generate_brand_intro(self, brand: str, product: str) -> str:
        """生成品牌介绍"""
        templates = [
            f"{brand} 致力于打造高品质的 {product} 产品。我们相信，卓越的品质源于对每一个细节的执着追求。",
            f"从概念到成品，{brand} 始终坚持创新与品质并重。这款 {product} 是我们对完美的最新诠释。",
            f"{brand} —— 您值得信赖的选择。这款 {product} 凝聚了我们多年的行业经验和技术积累。"
        ]
        return random.choice(templates)

    def _generate_comparison_table(self, features: List[str]) -> str:
        """生成对比表格内容"""
        lines = ["| 特性 | 普通产品 | {brand} {product} |"]
        lines.append("|------|---------|---------------|")

        for feat in features[:5]:
            short_feat = feat[:40] + "..." if len(feat) > 40 else feat
            lines.append(f"| {short_feat} | ⚠️ 基础 | ✅ {feat} |")

        return "\n".join(lines)

    def _expand_feature(self, feature: str, product: str) -> str:
        """展开特性描述"""
        expansions = {
            "quality": f"这款 {product} 采用顶级材料和精密工艺制造，确保每一件产品都达到最高品质标准。经过严格的质量控制流程，为您提供持久可靠的使用体验。",
            "durable": f"耐用性是我们设计的核心理念。这款 {product} 经过强化处理，能够承受日常使用的磨损，延长产品使用寿命，为您创造更大价值。",
            "easy": f"简单易用是我们的承诺。无论是安装还是操作，这款 {product} 都经过人性化设计，让您轻松上手，享受便捷体验。",
            "default": f"{feature}。这一特性让 {product} 在同类产品中脱颖而出，为用户带来卓越的使用体验和价值。"
        }

        feat_lower = feature.lower()
        for key, template in expansions.items():
            if key in feat_lower or key == "default":
                return template.replace("{product}", product)

        return expansions["default"]

    def _format_specifications(self, specs: Dict[str, str]) -> str:
        """格式化规格参数"""
        lines = ["### 产品规格参数\n"]
        for key, value in specs.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def _generate_usage_scenarios(self, product: str, audience: str) -> str:
        """生成使用场景描述"""
        scenarios = [
            f"无论您是在家中还是户外，{product} 都能完美适配您的需求。",
            f"适合{audience or '各类用户'}的多种使用场景，{product} 是您日常生活的好伙伴。",
            f"从早晨到夜晚，{product} 陪伴您的每一刻。"
        ]
        return random.choice(scenarios)

    async def generate_brand_story(
        self,
        brand_name: str,
        industry: str,
        products: List[str],
        values: Optional[List[str]] = None,
        founding_story: str = ""
    ) -> BrandStory:
        """
        生成品牌故事

        Args:
            brand_name: 品牌名称
            industry: 所属行业
            products: 主要产品线
            values: 品牌价值观
            founding_story: 创立背景（可选）

        Returns:
            完整品牌故事
        """
        # 品牌定位
        positioning_options = [
            f"{industry}领域的创新引领者",
            f"专注于高品质{industry}产品的专家品牌",
            f"为现代生活打造的{industry}解决方案提供商",
            f"将传统工艺与现代科技完美融合的{industry}品牌"
        ]

        # 品牌使命
        mission_templates = [
            f"让每一位用户都能享受到优质的{industry}产品与服务",
            f"通过持续创新，重新定义{industry}的产品标准",
            f"以匠心精神，打造值得信赖的{industry}品牌",
            f"致力于为全球用户提供卓越的{industry}体验"
        ]

        # 品牌价值观
        default_values = values or [
            "品质至上",
            "用户第一",
            "持续创新",
            "诚信经营",
            "社会责任"
        ]

        # 起源故事
        if not founding_story:
            founding_story = (
                f"{brand_name} 诞生于对更好{industry}产品的追求。"
                f"我们的创始人发现市场上的产品无法满足用户对品质和创新的期待，"
                f"于是决定创立{brand_name}，致力于改变这一现状。"
                f"从最初的小团队到如今的服务全球用户，我们始终不忘初心。"
            )

        # USP（独特卖点）
        usp_options = [
            f"将{industry}的专业级品质带入日常生活",
            f"以合理的价格提供超越期待的{industry}产品",
            f"融合前沿科技与传统工艺的{industry}创新者",
            f"全方位考虑用户需求的{industry}解决方案"
        ]

        # Slogan 建议
        tagline_options = [
            f"{brand_name} — {industry}的新标杆",
            f"品质生活，从{brand_name}开始",
            f"{brand_name}，重新定义{industry}",
            f"选择{brand_name}，选择更好的每一天"
        ]

        # 完整品牌描述（用于 Amazon About）
        about_text = f"""{brand_name} 是一家专注于{industry}的创新型企业。自成立以来，我们始终坚持以用户需求为核心，以产品品质为生命线。

我们的产品线涵盖{', '.join(products[:3])}等领域，每一款产品都经过精心设计和严格测试，确保为用户提供卓越的使用体验。

在{brand_name}，我们相信：好的产品不仅要满足功能需求，更要提升生活品质。这就是为什么我们在材料选择、工艺打磨、用户体验等每一个环节都精益求精。

展望未来，{brand_name} 将继续秉承\"{'、'.join(default_values[:3])}\"的品牌理念，为全球用户创造更多价值。"""

        # ====== LLM 增强：品牌描述 ======
        llm_about = await self._llm_generate_text(
            prompt=f"""请为品牌「{brand_name}」撰写一段用于 Amazon 品牌旗舰店 About 板块的品牌介绍（200字左右，中文）。
行业：{industry}
产品线：{', '.join(products[:3])}
品牌价值观：{'、'.join(default_values[:3])}
要求：专业、有感染力、突出差异化卖点，符合电商品牌调性。""",
            max_tokens=800,
        )
        if llm_about:
            about_text = llm_about

        # 故事叙述角度
        storytelling_angles = [
            {"angle": "创始人视角", "narrative": f"从一个想法到{industry}知名品牌，{brand_name}的创业之旅"},
            {"angle": "用户视角", "narrative": f"因为不满意市面上的选择，所以有了{brand_name}"},
            {"angle": "创新视角", "narrative": f"用技术革新推动{industry}进步的{brand_name}"},
            {"angle": "愿景视角", "narrative": f"打造世界级{industry}品牌——{brand_name}的使命"}
        ]

        return BrandStory(
            brand_name=brand_name,
            brand_positioning=random.choice(positioning_options),
            brand_mission=random.choice(mission_templates),
            brand_values=default_values,
            origin_story=founding_story,
            unique_selling_proposition=random.choice(usp_options),
            tagline_options=tagline_options,
            about_brand_text=about_text,
            storytelling_angles=storytelling_angles
        )

    async def translate_content(
        self,
        content: str,
        source_lang: str,
        target_lang: str,
        context: str = "ecommerce",
        keywords: Optional[List[str]] = None
    ) -> TranslationResult:
        """
        翻译内容（SEO 友好）

        Args:
            content: 待翻译内容
            source_lang: 源语言代码
            target_lang: 目标语言代码
            context: 翻译上下文
            keywords: 需要保留/优化的关键词

        Returns:
            翻译结果
        """
        # 模拟翻译（实际应调用 LLM API）
        lang_names = {
            "de": "德语", "ja": "日语", "es": "西班牙语",
            "fr": "法语", "it": "意大利语", "pt": "葡萄牙语",
            "ar": "阿拉伯语", "ko": "韩语", "nl": "荷兰语"
        }

        target_name = lang_names.get(target_lang, target_lang)

        # 基础翻译标记（作为 LLM 降级兜底）
        translated = f"[{target_name}翻译] {content}"

        # ====== LLM 增强：真实翻译 ======
        kw_hint = f"\n需保留的关键词（自然融入）：{', '.join(keywords[:5])}" if keywords else ""
        llm_translated = await self._llm_generate_text(
            prompt=f"""请将以下电商内容从{source_lang}翻译成{target_name}（{target_lang}）。
上下文：{context}
要求：翻译自然地道、符合{target_name}电商表达习惯，保留原意不增删信息。{kw_hint}

待翻译内容：
{content}""",
            max_tokens=1200,
        )
        if llm_translated:
            translated = llm_translated

        # 关键词 inclusion
        keyword_inclusion = []
        if keywords:
            for kw in keywords[:5]:
                keyword_inclusion.append({
                    "keyword": kw,
                    "position": "title" if random.random() > 0.3 else "body"
                })

        # 文化注意事项
        cultural_notes = []
        if target_lang == "de":
            cultural_notes.append("德语语法严谨，注意名词首字母大写")
            cultural_notes.append("德国消费者重视产品参数和认证信息")
        elif target_lang == "ja":
            cultural_notes.append("日语需要根据产品调性选择敬语程度")
            cultural_notes.append("日本市场偏好简洁、含蓄的表达方式")
        elif target_lang == "es":
            cultural_notes.append("注意区分拉丁美洲西班牙语和欧洲西班牙语差异")
            cultural_notes.append("西班牙语表达相对热情，可适当使用感叹号")

        # 替代版本
        alternatives = [
            {"version": "正式版", "text": f"[{target_name}正式] {content}"},
            {"version": "口语版", "text": f"[{target_name}口语] {content}"}
        ]

        return TranslationResult(
            original_text=content,
            translated_text=translated,
            source_lang=source_lang,
            target_lang=target_lang,
            seo_optimized=True,
            keyword_inclusion=keyword_inclusion,
            cultural_notes=cultural_notes,
            alternative_versions=alternatives
        )

    async def generate_infographic(
        self,
        topic: str,
        data_points: Optional[List[Dict]] = None,
        infographic_type: str = "benefit",
        brand_colors: Optional[List[str]] = None
    ) -> InfographicSpec:
        """
        生成信息图规格

        Args:
            topic: 主题
            data_points: 数据点
            infographic_type: 类型 (benefit/comparison/process/statistic)
            brand_colors: 品牌色板

        Returns:
            信息图规格
        """
        default_colors = brand_colors or ["#1890ff", "#52c41a", "#faad14", "#f5222d", "#722ed1"]

        type_configs = {
            "benefit": {
                "title": f"{topic} - 核心优势",
                "dimensions": "1080x1920",
                "sections": [
                    {"type": "header", "content": topic, "icon": "star"},
                    {"type": "benefit_list", "items": ["优势1", "优势2", "优势3", "优势4"]},
                    {"type": "cta", "text": "立即了解详情"}
                ],
                "call_to_action": "Shop Now"
            },
            "comparison": {
                "title": f"{topic} 对比",
                "dimensions": "1200x900",
                "sections": [
                    {"type": "header", "content": "横向对比", "icon": "scale"},
                    {"type": "comparison_table", "rows": 4},
                    {"type": "winner_highlight", "content": "推荐选择"}
                ],
                "call_to_action": "See the Difference"
            },
            "process": {
                "title": f"{topic} 使用指南",
                "dimensions": "1080x2160",
                "sections": [
                    {"type": "header", "content": "简单四步", "icon": "number"},
                    {"type": "step", "number": 1, "text": "步骤一"},
                    {"type": "step", "number": 2, "text": "步骤二"},
                    {"type": "step", "number": 3, "text": "步骤三"},
                    {"type": "step", "number": 4, "text": "步骤四"}
                ],
                "call_to_action": "Get Started"
            },
            "statistic": {
                "title": f"{topic} 数据说话",
                "dimensions": "1080x1080",
                "sections": [
                    {"type": "big_number", "value": "99%", "label": "满意度"},
                    {"type": "big_number", "value": "1M+", "label": "用户选择"},
                    {"type": "big_number", "value": "4.9", "label": "平均评分"}
                ],
                "call_to_action": "Join Them"
            }
        }

        config = type_configs.get(infographic_type, type_configs["benefit"])

        return InfographicSpec(
            title=config["title"],
            type=infographic_type,
            dimensions=config["dimensions"],
            sections=config["sections"],
            color_palette=default_colors,
            text_content={
                "headline": topic,
                "subheadline": f"为什么选择 {topic}",
                "footer": f"© {datetime.now().year} All Rights Reserved"
            },
            call_to_action=config["call_to_action"]
        )

    async def check_compliance(
        self,
        image_url: str,
        platform: str = "amazon",
        category: str = ""
    ) -> ComplianceReport:
        """
        检查图片合规性

        Args:
            image_url: 图片 URL
            platform: 目标平台
            category: 产品类目

        Returns:
            合规报告
        """
        rules = self.compliance_rules.get(platform, self.compliance_rules["amazon"])
        all_issues = []
        all_passed = []

        # 检查各类规则
        for rule_type, rule_list in rules.items():
            for rule_name, severity, description in rule_list:
                # 模拟检查结果（随机通过/失败）
                pass_rate = 0.85 if severity == "pass" else (0.6 if severity == "warning" else 0.75)
                passed = random.random() < pass_rate

                if passed:
                    all_passed.append(f"[{rule_type}] {rule_name}")
                else:
                    all_issues.append(ComplianceIssue(
                        issue_type=rule_type,
                        severity=severity,
                        description=description,
                        suggestion=f"请确保：{description}",
                        affected_area=rule_name
                    ))

        # 计算总分
        total_checks = len(all_passed) + len(all_issues)
        score = (len(all_passed) / total_checks) * 100 if total_checks > 0 else 0

        # 总体状态
        critical_count = sum(1 for i in all_issues if i.severity == "critical")
        if critical_count > 0:
            status = "fail"
        elif len(all_issues) > 2:
            status = "warning"
        else:
            status = "pass"

        # 优化建议
        recommendations = [
            "定期更新合规知识，关注平台政策变化",
            "建立内部审核清单，发布前逐项检查",
            "保存所有素材的版权授权文件",
            "关注竞品违规案例，引以为戒"
        ]

        if category.lower() in ["supplement", "beauty", "medical"]:
            recommendations.append("特别注意：该类目有额外的合规要求，请查阅具体规定")

        return ComplianceReport(
            overall_status=status,
            score=round(score, 1),
            issues=all_issues,
            passed=all_passed,
            recommendations=recommendations
        )

    async def generate_video_script(
        self,
        product_name: str,
        product_category: str,
        key_features: List[str],
        target_platform: str = "tiktok",
        video_type: str = "product_demo",
        duration_target: int = 30
    ) -> VideoScript:
        """
        生成视频脚本

        Args:
            product_name: 产品名称
            product_category: 产品类目
            key_features: 核心特性
            target_platform: 目标平台
            video_type: 视频类型
            duration_target: 目标时长（秒）

        Returns:
            完整视频脚本
        """
        platform_configs = {
            "tiktok": {"max_duration": 60, "style": "快节奏、强视觉冲击"},
            "reels": {"max_duration": 90, "style": "美学导向、转场流畅"},
            "youtube_shorts": {"max_duration": 60, "style": "信息密度高、价值驱动"}
        }

        config = platform_configs.get(target_platform, platform_configs["tiktok"])
        actual_duration = min(duration_target, config["max_duration"])

        # 生成场景
        scenes = []
        scene_templates = self._get_scene_templates(video_type)

        # 开场钩子（黄金3秒）
        hook_text = self._generate_hook(product_name, key_features)
        hook_voiceover = self._generate_hook_voiceover(product_name)

        # ====== LLM 增强：开场钩子 ======
        llm_hook = await self._llm_generate_text(
            prompt=f"""请为「{product_name}」({product_category}) 生成一条 TikTok 短视频开场钩子文案和配音文案。
核心卖点：{'、'.join(key_features[:3])}
要求：
1. 钩子文字（text_overlay）：短促有力，10字以内，抓眼球
2. 配音文案（voiceover）：一句话，口语化，制造好奇
请用 JSON 格式返回：{{"text_overlay": "...", "voiceover": "..."}}""",
            max_tokens=400,
        )
        if llm_hook:
            try:
                import json as _json
                # 尝试解析 JSON（可能有 markdown 包裹）
                hook_text_raw = llm_hook.strip()
                if hook_text_raw.startswith("```"):
                    hook_text_raw = hook_text_raw.split("\n", 1)[1].rsplit("```", 1)[0]
                hook_data = _json.loads(hook_text_raw)
                if isinstance(hook_data, dict):
                    hook_text = hook_data.get("text_overlay", hook_text)
                    hook_voiceover = hook_data.get("voiceover", hook_voiceover)
            except Exception:
                # 解析失败，保留规则生成
                pass

        scenes.append(VideoScene(
            scene_number=1,
            duration=3,
            visual_description="产品特写镜头，配合动态效果",
            text_overlay=hook_text,
            voiceover=hook_voiceover,
            background_music="轻快节奏音乐起",
            transition="快速切入"
        ))

        # 中间内容场景
        remaining_time = actual_duration - 6  # 减去开头和结尾
        scene_duration = max(5, remaining_time // (len(key_features) + 1))

        for i, feature in enumerate(key_features[:4]):
            template = scene_templates[i % len(scene_templates)]
            scenes.append(VideoScene(
                scene_number=i + 2,
                duration=scene_duration,
                visual_description=template["visual"].format(
                    product=product_name,
                    feature=feature
                ),
                text_overlay=template["text"].format(
                    feature=feature
                ),
                voiceover=template["voiceover"].format(
                    product=product_name,
                    feature=feature
                ),
                background_music=template["music"],
                transition=template["transition"]
            ))

        # 结尾 CTA
        scenes.append(VideoScene(
            scene_number=len(scenes) + 1,
            duration=3,
            visual_description="产品全景 + 品牌 Logo",
            text_overlay="立即购买 / 点击链接",
            voiceover=f"点击下方链接，把 {product_name} 带回家！关注我们获取更多好物推荐。",
            background_music="音乐高潮收尾",
            transition="淡出"
        ))

        # 钩子备选
        hook_lines = [
            f"等等！在你划走之前，看看这个{product_category}神器！",
            f"花了XX元买的{product_category}，后悔没早点遇到它...",
            f"这个{product_name}彻底改变了我的生活！",
            f"99%的人都不知道的{product_category}秘密..."
        ]

        # CTA 建议
        cta_suggestions = [
            "点击黄色购物车按钮享受限时优惠",
            "关注我不迷路，每天分享好物",
            "评论区告诉我你最想看哪个功能详解",
            "点赞本视频，下期抽奖送同款"
        ]

        # 话题标签
        hashtags = [
            f"#{product_name.replace(' ', '')}",
            f"#{product_category}",
            "#好物推荐",
            "#亚马逊好物",
            "#购物分享",
            "#测评"
        ]

        # 制作备注
        production_notes = [
            f"目标平台：{target_platform}，建议时长：{actual_duration}秒",
            f"风格基调：{config['style']}",
            "拍摄建议：使用稳定器保证画面流畅",
            "光线：自然光为主，必要时补光",
            "后期：添加字幕和音效提升完播率"
        ]

        return VideoScript(
            title=f"{product_name} - 产品展示视频",
            total_duration=sum(s.duration for s in scenes),
            format=video_type,
            target_platform=target_platform,
            scenes=scenes,
            hook_lines=hook_lines,
            cta_suggestions=cta_suggestions,
            hashtag_recommendations=hashtags,
            production_notes=production_notes
        )

    def _get_scene_templates(self, video_type: str) -> List[Dict]:
        """获取场景模板"""
        if video_type == "product_demo":
            return [
                {
                    "visual": "{product} 全景展示，360度旋转",
                    "text": "✨ {feature}",
                    "voiceover": "首先来看看 {product} 的 {feature}...",
                    "music": "节奏明快",
                    "transition": "滑动切换"
                },
                {
                    "visual": "{feature} 特写镜头，细节放大",
                    "text": "🔍 细节见真章",
                    "voiceover": "这个 {feature} 是我们最自豪的设计...",
                    "music": "节奏明快",
                    "transition": "缩放过渡"
                },
                {
                    "visual": "实际使用场景演示",
                    "text": "💡 真实体验",
                    "voiceover": "在实际使用中，{feature} 让一切变得简单...",
                    "music": "轻快愉悦",
                    "transition": "场景切换"
                },
                {
                    "visual": "用户好评/反馈展示",
                    "text": "⭐ 用户说好才是真的好",
                    "voiceover": "用户们都在夸赞 {feature}...",
                    "music": "温馨感人",
                    "transition": "淡入淡出"
                }
            ]
        else:  # testimonial
            return [
                {
                    "visual": "真人出镜，面对镜头",
                    "text": "让我告诉你我的真实感受",
                    "voiceover": "说实话，一开始我也怀疑...",
                    "music": "轻松自然",
                    "transition": "直接切换"
                }
            ] * 4

    def _generate_hook(self, product: str, features: List[str]) -> str:
        """生成开场钩子文字"""
        hooks = [
            f"⚡ {features[0] if features else '惊艳'}！",
            f"🔥 这个 {product} 太强了！",
            f"😱 不敢相信...这效果！",
            f"💰 花小钱办大事！"
        ]
        return random.choice(hooks)

    def _generate_hook_voiceover(self, product: str) -> str:
        """生成开场配音"""
        voiceovers = [
            f"停！如果你正在找好用的 {product}，这条视频一定要看完！",
            f"今天要给大家安利一个我最近发现的宝藏——{product}",
            f"用了这么多产品，终于找到一个真正好用的 {product}！"
        ]
        return random.choice(voiceovers)

    # ============================================================
    # Intent 分类（用于聊天路由）
    # ============================================================

    async def stream_chat(self, query: str) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）。

        对话类意图走 LLM 流式；具体工具类意图（生图/翻译等）退化为引导文本。

        Yields:
            文本片段（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        intent = self.classify_intent(query)

        # 具体工具意图：返回引导文本（一次性）
        if intent != "general":
            guide = (
                f"检测到您想做「{intent}」，请使用对应的顶部工具填写详细信息。\n"
                f"我也可以直接帮您生成文案，例如说「帮我写一段品牌故事」或「翻译这段文案」。"
            )
            yield guide
            return

        # 对话类：走 LLM 流式
        if not (LLM_AVAILABLE and self.ENABLE_LLM and self.llm_client):
            yield (
                "我是 AIGC 媒体生成助手，可以帮您：\n"
                "- 🎨 AI 产品图片生成\n- 📝 A+/EBC 内容生成\n"
                "- 🏆 品牌故事文案\n- 🌍 多语言 SEO 翻译\n"
                "- 🎬 短视频脚本生成"
            )
            return

        try:
            async for chunk in self.llm_stream(
                query,
                system_prompt=self.get_prompt_template("aigc_media"),
                model=self.DEFAULT_MODEL,
                temperature=0.8,
                max_tokens=1200,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[aigc_media] stream_chat failed: {e}")
            yield "（流式生成中断，请重试或改用顶部工具）"

    def classify_intent(self, user_input: str) -> str:
        """
        分类用户意图

        Returns:
            intent 类型
        """
        input_lower = user_input.lower()

        # 图片生成相关
        img_gen_keywords = ["生成图片", "生成主图", "ai图片", "产品图片", "生成场景图", "product image", "generate image"]
        if any(kw in input_lower for kw in img_gen_keywords):
            return "generate_image"

        # 主图优化
        main_img_keywords = ["主图分析", "主图优化", "图片质量", "点击率", "main image", "ctr"]
        if any(kw in input_lower for kw in main_img_keywords):
            return "analyze_main_image"

        # A+ 内容
        aplus_keywords = ["a+", "ebc", "enhanced", "图文版", "详情页", "a plus content"]
        if any(kw in input_lower for kw in aplus_keywords):
            return "generate_a_plus"

        # 品牌故事
        brand_keywords = ["品牌故事", "品牌介绍", "about us", "brand story", "品牌文案"]
        if any(kw in input_lower for kw in brand_keywords):
            return "generate_brand_story"

        # 翻译
        trans_keywords = ["翻译", "translate", "多语言", "本地化", "localization", "english", "德语", "日语"]
        if any(kw in input_lower for kw in trans_keywords):
            return "translate"

        # 信息图
        info_keywords = ["信息图", "infographic", "对比图", "宣传图", "海报"]
        if any(kw in input_lower for kw in info_keywords):
            return "generate_infographic"

        # 合规检查
        compliance_keywords = ["合规", "违规", "compliance", "审核", "图片规则"]
        if any(kw in input_lower for kw in compliance_keywords):
            return "check_compliance"

        # 视频脚本
        video_keywords = ["视频", "短视频", "脚本", "video", "tiktok", "reels", "抖音"]
        if any(kw in input_lower for kw in video_keywords):
            return "generate_video_script"

        return "general"
