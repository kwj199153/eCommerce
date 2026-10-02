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

import hashlib
import json
import re
import random
import math
from dataclasses import dataclass, field, asdict
from uuid import uuid4
from typing import List, Dict, Optional, Any, AsyncIterable
from datetime import datetime, timedelta
from enum import Enum

from core.logger import get_logger

logger = get_logger(__name__)


def _stable_pick(options: List[str], key: str) -> str:
    """从模板池里**确定性地**挑一条 —— 同一 key 永远得到同一条。

    ★ 为什么不用 ``random.choice``：本仓存在大量「随机挑一条写好的文案」的写法，
      它们产出的**不是编造数据**（模板本身是合法文案），真正的毛病是
      「同一输入两次调用结果不同」——既让回归测试没法断言（同一夹具两次结果不同），
      也被 ``tests/test_no_random_in_production.py`` 的 random 棘轮计入存量台账。
      改用 ``md5(key)`` 取模 ⇒ 不同商品/品牌仍拿到不同文案（观感上的多样性保留），
      但同一输入稳定复现 ⇒ 可测、可复现。

    Args:
        options: 候选文案池
        key: 定位用的业务键（如 ``f"{brand}::{product}"``）—— 决定选中哪一条

    Returns:
        选中的文案；``options`` 为空时返回空串
    """
    if not options:
        return ""
    digest = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()  # 非安全用途
    return options[int(digest[:8], 16) % len(options)]


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
    # 追问字段（子 Agent 接管后逐项追问补齐）
    material: str = ""
    shape: str = ""
    view_angle: str = ""
    need_logo: Optional[bool] = None
    product_detail: str = ""
    background_rule: str = ""


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

# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested

# 第 210 轮：思考过程（工具轨迹）的消化器。
from ai_infra.sse import StreamDigest
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.aigc_media import prompts as _prompts  # noqa: F401  —— 触发提示词注册


class AIGCMediaAgent(BaseAgent):
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
        super().__init__()

        self.agent_name = "AIGC 媒体生成器"
        self.version = "2.0.0"  # 升级版本号
        # ★ 第 204 轮：工具化路由子层（懒加载）。**不能**在 __init__ 里构建 ——
        #   那会触发 `tools → service → agent_aigc` 循环导入。
        self._router: Optional[Any] = None

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

    # ==================== 工具化路由（第 204 轮）====================
    #
    # 本 Agent 此前是**范式 B**：`invoke()` / `stream_chat()` → `_classify_intent()`
    # （关键词表）→ `_handle_*` 规则引擎；LLM 只出现在写文案的辅助方法里。
    # 于是 `aigc_tools`（9 个）**零装配** —— 注册了、却没有任何 Agent
    # 绑定它（全仓 `from .tools import aigc_tools` 零命中）。
    #
    # 现在接到**范式 A**（LLM 自主 bind_tools），做法与
    # `competitor_intel` / `listing_generator` / `product_research` 的
    # `_build_router()` 逐字同构。

    def _get_router(self):
        """懒加载工具化路由层，返回 None 表示不可用（回退关键词路由）。"""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def _build_router(self):
        """构建工具化路由层（BaseAgent 实例，注入 9 个AIGC工具）。

        ★★★ 为什么必须**组合一个 BaseAgent**，而不能只在 `super().__init__()`
          里多写一个 `tools=`：
            工具只在 `BaseAgent._llm_with_tools()` 里被 `bind_tools`，而它
            只被图节点 `_llm_call_node` 调用。本 Agent 自己的 `invoke()` /
            `stream_chat()` **从不驱动那张图** ⇒ 只加 `tools=` 是**装饰性接线**：
            注册表不再「悬空」、门禁变绿，而模型手里依旧没有工具 ——
            比不接更糟（把缺口藏起来）。
        """
        if not self.ENABLE_LLM:
            return None
        try:
            from .tools import aigc_tools

            from ai_infra.base_agent import BaseAgent
            from ai_infra.budget import BUDGET_ROUTER
            from ai_infra.context import CONTEXT_ROUTER
            from core.checkpoint import get_checkpointer

            return BaseAgent(
                # ★ 子层名字带 `_router` 后缀（同 competitor / listing / PR），
                #   技能注入边界由 `modules.skills.agents.business_agent_name()` 归一回业务名。
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.get_prompt_template("aigc_media"),
                tools=aigc_tools,
                # 路由子层是「单次决策 + 一串工具调用、用完即答」⇒ 用 ROUTER 档。
                budget=BUDGET_ROUTER,
                context_policy=CONTEXT_ROUTER,
                checkpointer=get_checkpointer(),
                checkpoint_ns="aigc_media",
            )
        except Exception as e:  # noqa: BLE001 —— 路由层不可用时回退，不影响主流程
            logger.warning(f"[aigc_media] router build failed: {e}")
            return None

    async def _stream_via_tools(self, query: str,
                                context: Optional[Dict[str, Any]] = None) -> AsyncIterable:
        """流式工具路由：**实时**下发思考过程（step），答复文本仍一次性给出。

        ★ 与 `_route_via_tools` 是**同一条决策路径**（router 的 LLM 自主选工具），
          差别只在「过程能不能边跑边看」：
          · `run_session` 一次性返回 state ⇒ 轨迹**事后**才拿得到，而调用方
            只取最后一条 AIMessage ⇒ 轨迹被整段丢掉，前端只看到一个转圈
            （这正是第 210 轮老板的原始诉求）；
          · 这里改走 `stream_session` + `StreamDigest`：工具事件**逐条**转成
            step 事件下发，答复按原时序**攒齐一次吐出** ——
            即「只做加法、正文行为零变化」。

        Yields:
            step 事件（dict）/ 整段答复文本（str）；**没有产出就什么都没 yield**，
            由调用方按空结果回退关键词路由（与 `_route_via_tools` 返回 None 同义）。
        """
        router = self._get_router()
        if router is None:
            return

        # 注：本 Agent 的工具均无租户归属 ⇒ 不需要 `_current_shop_id`
        #     （与非流式路径 `_route_via_tools` 的注释一致）。

        prompt = query
        if context:
            try:
                ctx_json = json.dumps(context, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                ctx_json = str(list(context.keys()))
            prompt = f"{query}\n\n[上下文数据] {ctx_json[:2000]}"

        from langchain_core.messages import HumanMessage

        # ★ 工具人话标题走**注入**：真源在业务侧
        #   （`modules/skills/tools_catalog.py::tool_title`，全仓唯一查询口），
        #   而 `ai_infra` 不许依赖业务（分层硬红线）⇒ 只能把查询口传进去。
        #   惰性 import：Agent 的**模块导入期**无需把 `modules.skills` 拉进依赖图，
        #   只有真跑流式工具环路时才需要它。
        # 走**包门面**（本仓条款 1：跨模块引用不得伸手进包内部）。
        from modules.skills import tool_title

        digest = StreamDigest(title_resolver=tool_title)
        try:
            async for ev in router.stream_session(
                {"messages": [HumanMessage(content=prompt)]},
            ):
                s = digest.feed(ev)
                if s is not None:
                    yield s
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[aigc_media] stream tool routing failed: {e}")
            return

        if digest.reply:
            yield digest.reply

    async def _route_via_tools(self, query: str,
                               context: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """工具化路由：LLM 自主选工具执行，返回可读回复文本。

        返回 None 表示不可用或失败，调用方回退关键词路由（`_classify_intent`）。
        """
        router = self._get_router()
        if router is None:
            return None

        prompt = query
        if context:
            try:
                ctx_json = json.dumps(context, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                ctx_json = str(list(context.keys()))
            prompt = f"{query}\n\n[上下文数据] {ctx_json[:2000]}"

        from langchain_core.messages import AIMessage, HumanMessage

        try:
            state = await router.run_session(
                {"messages": [HumanMessage(content=prompt)]},
            )
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[aigc_media] tool routing failed: {e}")
            return None

        reply = ""
        for m in state.get("messages") or []:
            if isinstance(m, AIMessage) and m.content:
                reply = m.content if isinstance(m.content, str) else str(m.content)
        return reply.strip() or None

    async def _llm_generate_text(
        self,
        prompt: str,
        system_prompt: str = None,
        max_tokens: int = 1500,
        temperature: float = 0.8,
    ) -> Optional[str]:
        """
        LLM 增强：生成真实文案内容。

        LLM 不可用或失败时返回 None，由调用方降级到模板/规则生成。

        temperature 默认 0.8（文案创作需要发挥）；**翻译类调用要显式压低**（如 0.2），
        否则同一个词每次译法都不一样。
        """
        if not (self.ENABLE_LLM and self.llm_client):
            return None
        try:
            result = await self.llm_chat(
                user_message=prompt,
                system_prompt=system_prompt or self.get_prompt_template("aigc_media"),
                model=self.DEFAULT_MODEL,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            if result.success and not result.fallback and result.content:
                return result.content.strip()
        except Exception as e:
            logger.warning(f"[aigc_media] LLM generate failed: {e}")
        return None

    # 语言代码 → 中文名（翻译类调用共用，避免各处再抄一份）
    _LANG_NAMES = {
        "zh": "简体中文", "en": "英文", "ja": "日语", "ko": "韩语",
        "de": "德语", "es": "西班牙语", "fr": "法语", "it": "意大利语",
        "pt": "葡萄牙语", "ar": "阿拉伯语", "nl": "荷兰语",
    }

    # SELECTION_TRANSLATE_SYSTEM 的正文已归位到 `prompts.py`（注册表键 `"aigc_selection_translate"`）
    # ★ 第 283 轮：提示词带版本与指纹后才可对账。

    @classmethod
    def _detect_lang(cls, text: str) -> str:
        """粗判语言：含中日韩字符即视为 zh（划词场景两种方向足够，不做完整语种识别）。"""
        for ch in text:
            if "\u3400" <= ch <= "\u9fff":
                return "zh"
        return "en"

    @staticmethod
    def _clean_translation(raw: str) -> str:
        """兜底清洗：模型偶尔仍会包 ``` 或加「译文：」前缀。"""
        s = (raw or "").strip()
        s = re.sub(r"^```[a-zA-Z]*\s*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
        s = re.sub(r"^(译文|翻译|Translation)\s*[:：]\s*", "", s, flags=re.IGNORECASE)
        s = re.sub(r'^["\'「『]', "", s)
        s = re.sub(r'["\'」』]$', "", s)
        return s.strip()

    async def translate_selection(
        self,
        text: str,
        target_lang: str = "auto",
        context: str = "ecommerce",
    ) -> Dict[str, Any]:
        """
        划词翻译：用户选中一段文字，只要一个能直接读的译文。

        与 `translate_content`（SEO 友好翻译）的分工，不是重复造轮子：
          - `translate_content` 面向**内容生产**：长文本、关键词位置优化、文化适配、多版本输出；
          - 本方法面向**阅读辅助**：短文本、1-2 秒内出结果、只要一个译文，
            故不产出 keyword/cultural/alternative 这些内容生产用的结构。
        两者共用同一套 LLM 基建（`_llm_generate_text`），不重复初始化、不重复维护 prompt 骨架。

        Returns:
            {"success", "data", "message"}；LLM 不可用时 success=False 且 translation 为空
            （**不编造译文** —— 宁可让前端提示「暂不可用」，也不要给一个假译文）
        """
        text = (text or "").strip()
        if not text:
            return {"success": False, "message": "没有取到文字", "data": {
                "original_text": "", "translation": "", "source_lang": "", "target_lang": "", "degraded": True,
            }}

        source_lang = self._detect_lang(text)
        if target_lang in (None, "", "auto"):
            target_lang = "en" if source_lang == "zh" else "zh"

        target_name = self._LANG_NAMES.get(target_lang, target_lang)

        translated = await self._llm_generate_text(
            prompt=(
                f"目标语言：{target_name}\n"
                f"上下文：{context}\n\n"
                f"原文：\n{text}"
            ),
            system_prompt=self.get_prompt_template("aigc_selection_translate"),
            max_tokens=800,
            temperature=0.2,
        )

        if not translated:
            # 降级：空白而非假译文（空状态优于虚构默认）
            return {
                "success": False,
                "message": "翻译服务暂不可用",
                "data": {
                    "original_text": text,
                    "translation": "",
                    "source_lang": source_lang,
                    "target_lang": target_lang,
                    "degraded": True,
                },
            }

        return {
            "success": True,
            "message": f"翻译完成 ({source_lang} -> {target_lang})",
            "data": {
                "original_text": text,
                "translation": self._clean_translation(translated),
                "source_lang": source_lang,
                "target_lang": target_lang,
                "degraded": False,
            },
        }

    # ENHANCE_PROMPT_SYSTEM 的正文已归位到 `prompts.py`（注册表键 `"aigc_enhance_prompt"`）
    # ★ 第 283 轮：提示词带版本与指纹后才可对账。

    # 增强结果常见的「前缀」写法（兜底剥掉；`_clean_translation` 只认译文类前缀）
    _ENHANCE_PREFIXES = (
        "改写后：", "改写：", "改写后的提示词：",
        "增强后：", "增强：", "优化后：", "优化：",
    )

    async def enhance_prompt(self, draft: str, context: str = "ecommerce") -> Dict[str, Any]:
        """
        提示词增强：把一句口语化的需求改写成更可执行的提示词。

        与 `translate_selection` 并列（都是「输入辅助、只回一段文本、共用 `_llm_generate_text`」），
        区别是它**不改语言，改的是需求的完备度**：补齐任务目标 / 约束条件 / 输出形式。

        temperature 压到 0.4：这不是创作，是「如实扩写」。放开会导致同一句话每次补出的
        维度都不一样，用户会以为功能不稳定。

        Returns:
            {"success", "data", "message"}；LLM 不可用时 success=False 且 enhanced 为空
            （**不编造提示词** —— 空状态优于虚构默认）
        """
        draft = (draft or "").strip()
        if not draft:
            return {
                "success": False,
                "message": "没有取到输入内容",
                "data": {"draft": "", "enhanced": "", "degraded": True},
            }

        enhanced = await self._llm_generate_text(
            prompt=f"""业务上下文：{context}

用户原始输入：
{draft}""",
            system_prompt=self.get_prompt_template("aigc_enhance_prompt"),
            max_tokens=800,
            temperature=0.4,
        )

        if not enhanced:
            # 降级：空白而非假提示词（空状态优于虚构默认）
            return {
                "success": False,
                "message": "提示词增强暂不可用",
                "data": {"draft": draft, "enhanced": "", "degraded": True},
            }

        # 复用翻译的清洗（去 ``` 围栏、去包裹引号），再剥增强场景特有的前缀
        cleaned = self._clean_translation(enhanced)
        for prefix in self._ENHANCE_PREFIXES:
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip()
                break

        return {
            "success": True,
            "message": "已增强",
            "data": {"draft": draft, "enhanced": cleaned, "degraded": False},
        }

    async def generate_product_image(self, request: ImageGenerationRequest) -> Dict[str, Any]:
        """
        生成产品图片

        Args:
            request: 图片生成请求

        Returns:
            生成的图片信息和提示词；若关键信息不足，返回 needs_clarification + 缺失字段清单
        """
        # —— 缺参校验：关键追问字段缺失时，不硬凑结果，返回追问标记 ——
        clarify_fields = self._collect_missing_clarification_fields(request)
        if clarify_fields:
            return {
                "success": False,
                "needs_clarification": True,
                "missing_fields": clarify_fields,
                "message": "信息不足，需补充以下信息后才能生成高质量图片",
                "note": "主 Agent 应将本标记透传给用户，逐项追问补齐后再调用本工具",
            }

        image_type = request.image_type
        style_config = self.image_styles.get(request.style, self.image_styles["professional"])

        # 构建详细提示词
        prompt = self._build_image_prompt(request, style_config)

        # 生成图片元信息
        image_id = f"IMG_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid4().hex[:6]}"

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
                "seed": uuid4().int % 99999 + 1
            },
            "note": "当前为模拟模式，接入真实图片生成服务后返回实际图片URL"
        }

    def _collect_missing_clarification_fields(self, request) -> List[str]:
        """收集生图所需的追问字段中，哪些尚未提供。

        白底主图/场景图要出高质量结果，关键字段包括材质、造型、视角、
        是否需要 logo、产品细节、背景规则。缺哪些列哪些，全缺即整张清单。
        """
        missing: List[str] = []
        checks = [
            ("material", "材质", getattr(request, "material", "")),
            ("shape", "造型", getattr(request, "shape", "")),
            ("view_angle", "视角", getattr(request, "view_angle", "")),
            ("need_logo", "是否需要 logo", getattr(request, "need_logo", None)),
            ("product_detail", "产品细节", getattr(request, "product_detail", "")),
            ("background_rule", "背景规则（如纯白底/允许阴影）", getattr(request, "background_rule", "")),
        ]
        for _key, label, value in checks:
            # need_logo 是布尔，None 视为未提供；其余字符串空视为未提供
            if value is None or (isinstance(value, str) and not value.strip()):
                missing.append(label)
        return missing

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

        # 追问字段（补齐后融入提示词）
        if getattr(request, "material", ""):
            base_prompt += f", material: {request.material}"
        if getattr(request, "shape", ""):
            base_prompt += f", shape: {request.shape}"
        if getattr(request, "view_angle", ""):
            base_prompt += f", camera angle: {request.view_angle}"
        if getattr(request, "need_logo", None) is not None:
            base_prompt += ", with brand logo" if request.need_logo else ", no logo"
        if getattr(request, "product_detail", ""):
            base_prompt += f", highlight detail: {request.product_detail}"
        if getattr(request, "background_rule", ""):
            base_prompt += f", background rule: {request.background_rule}"

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

        ⚠️ 本方法当前是**模拟实现**：视觉评分（5 个子维度）与 CTR 预测均为随机生成，
        不代表对 image_url 的真实测量；A/B 变体的 CTR 也由随机系数放大而来。
        其中**合规子块**已单独收紧为「待人工核查」——不再随机产出通过/不通过结论。

        Args:
            image_url: 图片 URL 或路径
            product_category: 产品类目

        Returns:
            主图分析结果
        """
        # 模拟视觉分析结果（⚠️ 见 docstring：mock，不是对 image_url 的真实测量）
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

        # 合规子块 —— ⚠️ 未接入自动判定能力，**不产出通过/不通过结论**
        # （与 check_compliance() 同一口径；这里只列出「人工要核查什么」，
        #   不再用 random.choice 掷骰子决定某条规则过没过）
        checks = [
            ("white_background", "纯白背景", "critical", "主图必须使用纯白背景 (RGB 255,255,255)"),
            ("no_watermark", "无水印文字", "critical", "主图不能包含任何文字或水印"),
            ("product_dominant", "产品占比>85%", "warning", "产品应占据画面85%以上空间"),
            ("high_resolution", "高分辨率", "warning", "建议最低 1000x1000 像素以启用缩放"),
            ("no_accessories", "无多余配件", "warning", "主图不应包含配件，除非是套装"),
        ]
        compliance_issues: List[Dict[str, Any]] = []   # 未做自动判定 ⇒ 不产出「发现问题」
        passed_checks: List[str] = []                  # 未做自动判定 ⇒ 不产出「已通过结论」
        compliance_check = {
            "status": "manual_review_required",
            "score": 0.0,                              # 占位，不代表 0 分
            "passed": passed_checks,
            "issues": compliance_issues,
            "checklist": [
                f"[{cid}] {name}｜{sev}｜{criterion}"
                for cid, name, sev, criterion in checks
            ],
        }

        # 改进建议
        suggestions = []
        if scores["composition"] < 70:
            suggestions.append("📐 优化构图：尝试三分法则，将产品放在黄金分割点")
        if scores["color_quality"] < 70:
            suggestions.append("🎨 提升色彩：调整饱和度和对比度，使产品更突出")
        if scores["clarity"] < 80:
            suggestions.append("🔍 提高清晰度：使用更高分辨率的原图")
        # 合规项未做判定 ⇒ 白底始终作为待人工确认项提示（而非「没发现问题才提示」）
        suggestions.append("⚪ 待人工确认：背景是否为纯白色 (RGB 255,255,255)")
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
            compliance_check=compliance_check,
            improvement_suggestions=suggestions,
            ab_test_variants=ab_variants
        )

    async def generate_a_plus_content(
        self,
        product_name: str,
        brand: str,
        features: List[str],
        specifications: Optional[Dict[str, str]] = None,
        target_audience: str = "",
        product_asin: str = ""
    ) -> APlusContent:
        """
        生成 A+ / EBC 内容

        Args:
            product_name: 产品名称
            brand: 品牌名
            features: 产品特性列表
            specifications: 规格参数
            target_audience: 目标受众
            product_asin: 产品 ASIN（可选；留空则响应里 product_asin 为空串 —— 服务端不再编造 ASIN）

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
                # ★ 修复：同族模块都用字符串（"M001"/"M002"/"M007"），
                #   且 APlusModule.module_id 声明为 str ⇒ 裸 M006 是 NameError。
                module_id="M006",
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
            product_asin=product_asin,
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
        return _stable_pick(templates, f"{brand}::{product}")

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
        return _stable_pick(scenarios, f"{product}::{audience or ''}")

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
            brand_positioning=_stable_pick(positioning_options, brand_name),
            brand_mission=_stable_pick(mission_templates, brand_name),
            brand_values=default_values,
            origin_story=founding_story,
            unique_selling_proposition=_stable_pick(usp_options, brand_name),
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
        # ★ 修复：此前 position 用 random.random() 掷骰子（与译文内容完全无关，
        #   且同一输入每次结果不同）。改为**真检测**：在译文里找关键词的实际落点，
        #   前三行视为标题区；译文里根本没有该关键词时如实返回 "absent"，
        #   不再假装它出现在某个位置。（前端目前不消费本字段，加值是安全的。）
        keyword_inclusion = []
        if keywords:
            haystack = (translated or "").lower()
            head = "\n".join(haystack.split("\n")[:3])
            for kw in keywords[:5]:
                needle = kw.lower()
                if needle not in haystack:
                    position = "absent"
                elif needle in head:
                    position = "title"
                else:
                    position = "body"
                keyword_inclusion.append({
                    "keyword": kw,
                    "position": position
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
        图片合规检查 —— 输出**待人工核查清单**

        ⚠️ 本模块**没有接入任何图片合规自动判定能力**（收得到 image_url 却从不读图），
        因此本方法**不产出「通过 / 警告 / 不通过」结论**，而是显式返回待人工核查状态：

        - overall_status = "manual_review_required"
        - issues = [] / passed_checks = []  —— 一项也没检查过，**不是「全部通过」**
        - score = 0.0 —— **纯占位，不代表 0 分**；判断状态请只认 overall_status
        - recommendations —— 该平台该逐条走一遍的核查清单（来自 self.compliance_rules，
          含每条规则的严重级别与判定口径），人工核查据此逐项确认

        历史实现（已删除）用 random.random() < pass_rate 为每条规则随机掷骰子，
        同一张图每次调用结论都不同 —— 那是**编造一份看起来很专业的合规报告**，
        比「没有这个功能」危险得多（用户会据此直接把素材发上架）。
        回归判据见 backend/tests/test_aigc_compliance_failclosed.py。

        Args:
            image_url: 图片 URL（本方法不读取它，仅记入日志以便追溯）
            platform: 目标平台
            category: 产品类目

        Returns:
            合规报告（overall_status == "manual_review_required"）
        """
        rules = self.compliance_rules.get(platform, self.compliance_rules["amazon"])

        checklist = []
        for rule_type, rule_list in rules.items():
            for rule_name, severity, description in rule_list:
                checklist.append(f"[{rule_type}] {rule_name}｜{severity}｜{description}")

        logger.warning(
            "合规检查未接入自动判定能力，返回待人工核查（不产出通过/不通过结论）"
            f" image_url={image_url} platform={platform} category={category or '-'}"
        )

        recommendations = [
            "⚠️ 本次未做自动合规判定（该能力未接入）：以下为人工核查清单，请逐项确认后再发布",
            *[f"待核查 {item}" for item in checklist],
            "定期更新合规知识，关注平台政策变化",
            "建立内部审核清单，发布前逐项检查",
            "保存所有素材的版权授权文件",
        ]

        if category.lower() in ["supplement", "beauty", "medical"]:
            recommendations.append("特别注意：该类目有额外的合规要求，请查阅具体规定")

        return ComplianceReport(
            overall_status="manual_review_required",
            score=0.0,
            issues=[],
            passed_checks=[],
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
        return _stable_pick(hooks, product)

    def _generate_hook_voiceover(self, product: str) -> str:
        """生成开场配音"""
        voiceovers = [
            f"停！如果你正在找好用的 {product}，这条视频一定要看完！",
            f"今天要给大家安利一个我最近发现的宝藏——{product}",
            f"用了这么多产品，终于找到一个真正好用的 {product}！"
        ]
        return _stable_pick(voiceovers, product)

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
        # ★ 第 204 轮：工具环路优先（LLM 用 bind_tools 自主选那 9 个 AIGC 工具）。
        #   不可用 / 失败 ⇒ 回退下面的引导文本 / LLM 流式。
        #   注：9 个 AIGC 工具均无租户归属（service 只收 request），
        #   故本 Agent 不需要 `_current_shop_id`。
        # ★ 第 210 轮：改走**流式版**工具环路 —— 思考过程（step）实时下发，
        #   答复文本仍按原来的时序**攒齐一次吐出**（正文行为零变化）。
        #   `tool_chunks` 为空 = 工具路没产出任何文本 ⇒ 与原来返回 None 一样
        #   落到下面的关键词回退链（降级链一行没动）。
        tool_chunks: list = []
        async for chunk in self._stream_via_tools(query):
            if isinstance(chunk, dict):
                yield chunk
            else:
                tool_chunks.append(chunk)
        if tool_chunks:
            yield "".join(tool_chunks)
            return

        # ★ 点名技能、但技能通道（工具环路）没产出 ⇒ **如实说，不落下面的
        #   关键词短路**（第 246 轮）：那条短路不构造 system prompt，拿它的
        #   结果顶替用户点的技能，界面上完全看不出来（静默退化）。
        #   ★ 未点名时这一句不生效 ⇒ 下面整条降级链**一行没动**。
        if is_skill_requested():
            yield SKILL_CHANNEL_UNAVAILABLE
            return

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
        if not (self.ENABLE_LLM and self.llm_client):
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

    #: 意图路由表（**策略数据**留业务模块；控制流见 `ai_infra.intent.first_match`）。
    #: 顺序即优先级，逐项保持收敛前的原序。
    _INTENT_ROUTES = (
        Route("generate_image", ("生成图片", "生成主图", "ai图片", "产品图片",
                                 "生成场景图", "product image", "generate image")),
        Route("analyze_main_image", ("主图分析", "主图优化", "图片质量", "点击率",
                                     "main image", "ctr")),
        Route("generate_a_plus", ("a+", "ebc", "enhanced", "图文版", "详情页",
                                  "a plus content")),
        Route("generate_brand_story", ("品牌故事", "品牌介绍", "about us",
                                       "brand story", "品牌文案")),
        Route("translate", ("翻译", "translate", "多语言", "本地化", "localization",
                            "english", "德语", "日语")),
        Route("generate_infographic", ("信息图", "infographic", "对比图", "宣传图", "海报")),
        Route("check_compliance", ("合规", "违规", "compliance", "审核", "图片规则")),
        Route("generate_video_script", ("视频", "短视频", "脚本", "video", "tiktok",
                                        "reels", "抖音")),
    )

    def classify_intent(self, user_input: str) -> str:
        """分类用户意图（控制流与兜底见 `ai_infra.intent.first_match`）。

        ★ 方法名**保持公开且不改名**：`modules/aigc_media/service.py`
          仍按 `agent.classify_intent(...)` 调用它。
        """
        return first_match(user_input, self._INTENT_ROUTES, "general")
