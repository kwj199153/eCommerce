"""
AIGC 媒体生成模块 → 主 Agent 工具注册表

把 AIGCMediaService 的 8 个**细粒度**能力包装成 langchain 工具，
供店秘书（主 Agent）通过 bind_tools 自主选择调用。

设计要点（照 listing_generator/tools.py 同范式）：
- 只包语义明确的细粒度方法，**不包** `chat` / `stream_chat`（粗粒度入口，
  内部 classify_intent 只返回引导文案，与主 Agent 判断冲突）。
- 工具函数用扁平参数 + 自构造 Pydantic request，LLM 通过 JSON Schema
  看到字段名与描述即可正确填参。
- 结果序列化为 JSON 字符串，工具层只做「调用 service + 序列化」，不碰 agent 本体。
"""

from langchain_core.tools import StructuredTool

from .service import (
    generate_product_image_service,
    analyze_main_image_service,
    generate_a_plus_content_service,
    generate_brand_story_service,
    translate_content_service,
    generate_infographic_service,
    check_compliance_service,
    generate_video_script_service,
)
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


async def _generate_product_image_tool(
    product_name: str,
    category: str,
    brand: str = "",
    target_market: str = "US",
    image_type: str = "main",
    style: str = "professional",
    color_scheme: str = "",
    keywords: list[str] | None = None,
    reference_description: str = "",
    dimensions: str = "2000x2000",
    material: str = "",
    shape: str = "",
    view_angle: str = "",
    need_logo: bool | None = None,
    product_detail: str = "",
    background_rule: str = "",
) -> str:
    """生成产品图片（含提示词、SEO 关键词、文案建议、风格指南）。

    注意：若关键信息（材质/造型/视角/是否需要 logo/产品细节/背景规则）缺失，
    本工具会返回 needs_clarification=true 和缺失字段清单。此时**不要**再用
    默认值重复调用本工具，应把缺失字段逐项向用户追问清楚后再调用。

    Args:
        product_name: 产品名称（必填）。
        category: 产品类目（必填）。
        brand: 品牌名称（可选）。
        target_market: 目标市场，如 US / EU / JP（默认 US）。
        image_type: 图片类型，main 主图 / lifestyle 场景图 / infographic 信息图等。
        style: 风格，如 professional / lifestyle（默认 professional）。
        color_scheme: 配色方案描述（可选）。
        keywords: 关键词列表（可选）。
        reference_description: 参考描述（可选）。
        dimensions: 尺寸，如 2000x2000（默认）。
        material: 产品材质（如不锈钢/玻璃/陶瓷），白底图建议提供。
        shape: 产品造型（如圆柱/方形/流线型）。
        view_angle: 拍摄视角（如正面/45度/俯视）。
        need_logo: 是否需要展示品牌 logo。
        product_detail: 需突出展示的产品细节。
        background_rule: 背景规则（如纯白底/是否允许阴影）。
    """
    req = ImageGenerationRequest(
        product_name=product_name,
        category=category,
        brand=brand,
        target_market=target_market,
        image_type=image_type,
        style=style,
        color_scheme=color_scheme,
        keywords=keywords or [],
        reference_description=reference_description,
        dimensions=dimensions,
        material=material,
        shape=shape,
        view_angle=view_angle,
        need_logo=need_logo,
        product_detail=product_detail,
        background_rule=background_rule,
    )
    resp = await generate_product_image_service(req)
    return _dump(resp)


async def _analyze_main_image_tool(
    image_url: str,
    product_category: str = "",
) -> str:
    """分析产品主图质量，返回整体评分、CTR 预测、视觉评分、合规检查与改进建议。

    Args:
        image_url: 图片 URL 或路径（必填）。
        product_category: 产品类目（可选）。
    """
    req = MainImageAnalysisRequest(image_url=image_url, product_category=product_category)
    resp = await analyze_main_image_service(req)
    return _dump(resp)


async def _generate_a_plus_content_tool(
    product_name: str,
    brand: str,
    features: list[str],
    specifications: dict[str, str] | None = None,
    target_audience: str = "",
) -> str:
    """生成 A+ 内容（EBC 增强品牌内容）各模块。

    Args:
        product_name: 产品名称（必填）。
        brand: 品牌名（必填）。
        features: 产品特性列表（必填）。
        specifications: 规格参数字典（可选）。
        target_audience: 目标受众描述（可选）。
    """
    req = APlusContentRequest(
        product_name=product_name,
        brand=brand,
        features=features,
        specifications=specifications,
        target_audience=target_audience,
    )
    resp = await generate_a_plus_content_service(req)
    return _dump(resp)


async def _generate_brand_story_tool(
    brand_name: str,
    industry: str,
    products: list[str],
    values: list[str] | None = None,
    founding_story: str = "",
) -> str:
    """生成品牌故事（定位、使命、价值观、起源、卖点、标语、叙事角度）。

    Args:
        brand_name: 品牌名称（必填）。
        industry: 所属行业（必填）。
        products: 主要产品线列表（必填）。
        values: 品牌价值观列表（可选）。
        founding_story: 创立背景故事（可选）。
    """
    req = BrandStoryRequest(
        brand_name=brand_name,
        industry=industry,
        products=products,
        values=values,
        founding_story=founding_story,
    )
    resp = await generate_brand_story_service(req)
    return _dump(resp)


async def _translate_content_tool(
    content: str,
    target_lang: str,
    source_lang: str = "zh",
    context: str = "ecommerce",
    keywords: list[str] | None = None,
) -> str:
    """多语言内容翻译（含 SEO 优化与关键词保留）。

    Args:
        content: 待翻译内容（必填）。
        target_lang: 目标语言代码，如 en / de / ja（必填）。
        source_lang: 源语言代码（默认 zh）。
        context: 翻译上下文场景（默认 ecommerce）。
        keywords: 需保留的关键词列表（可选）。
    """
    req = TranslationRequest(
        content=content,
        source_lang=source_lang,
        target_lang=target_lang,
        context=context,
        keywords=keywords,
    )
    resp = await translate_content_service(req)
    return _dump(resp)


async def _generate_infographic_tool(
    topic: str,
    data_points: list[dict] | None = None,
    infographic_type: str = "benefit",
    brand_colors: list[str] | None = None,
) -> str:
    """生成营销信息图规格（分区、文案、配色、行动号召）。

    Args:
        topic: 信息图主题（必填）。
        data_points: 数据点列表（可选）。
        infographic_type: 信息图类型，如 benefit / comparison / how_to（默认 benefit）。
        brand_colors: 品牌色板列表（可选）。
    """
    req = InfographicRequest(
        topic=topic,
        data_points=data_points,
        infographic_type=infographic_type,
        brand_colors=brand_colors,
    )
    resp = await generate_infographic_service(req)
    return _dump(resp)


async def _check_compliance_tool(
    image_url: str,
    platform: str = "amazon",
    category: str = "",
) -> str:
    """检查图片合规性，返回状态、评分、问题清单与整改建议。

    Args:
        image_url: 图片 URL（必填）。
        platform: 目标平台，如 amazon（默认）。
        category: 产品类目（可选）。
    """
    req = ComplianceCheckRequest(image_url=image_url, platform=platform, category=category)
    resp = await check_compliance_service(req)
    return _dump(resp)


async def _generate_video_script_tool(
    product_name: str,
    product_category: str,
    key_features: list[str],
    target_platform: str = "tiktok",
    video_type: str = "product_demo",
    duration_target: int = 30,
) -> str:
    """生成短视频脚本（分镜、旁白、字幕、音乐、钩子、CTA、话题标签）。

    Args:
        product_name: 产品名称（必填）。
        product_category: 产品类目（必填）。
        key_features: 核心特性列表（必填）。
        target_platform: 目标平台，如 tiktok / reels（默认 tiktok）。
        video_type: 视频类型，如 product_demo（默认）。
        duration_target: 目标时长秒数，10-120（默认 30）。
    """
    req = VideoScriptRequest(
        product_name=product_name,
        product_category=product_category,
        key_features=key_features,
        target_platform=target_platform,
        video_type=video_type,
        duration_target=duration_target,
    )
    resp = await generate_video_script_service(req)
    return _dump(resp)


def _dump(resp) -> str:
    """统一序列化：优先 data，其次 message/error。"""
    import json

    if isinstance(resp, dict):
        return json.dumps(resp, ensure_ascii=False)
    return str(resp)


# ====== 工具注册表 ======

aigc_tools = [
    StructuredTool.from_function(
        coroutine=_generate_product_image_tool,
        name="generate_product_image",
        description="生成产品图片（含提示词、SEO 关键词、文案建议）。当用户想做图/生成产品图/主图时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_analyze_main_image_tool,
        name="analyze_main_image",
        description="分析产品主图质量（评分、CTR 预测、合规、改进建议）。当用户想诊断/优化主图时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_a_plus_content_tool,
        name="generate_a_plus_content",
        description="生成 A+ 内容（EBC 增强品牌内容）各模块。当用户想做 A+ / EBC / 详情页品牌内容时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_brand_story_tool,
        name="generate_brand_story",
        description="生成品牌故事（定位、使命、卖点、标语、叙事角度）。当用户想写品牌故事/品牌文案时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_translate_content_tool,
        name="translate_content",
        description="多语言内容翻译（含 SEO 优化与关键词保留）。当用户想翻译文案到其他语言时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_infographic_tool,
        name="generate_infographic",
        description="生成营销信息图规格（分区、文案、配色、CTA）。当用户想做信息图/营销图时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_check_compliance_tool,
        name="check_image_compliance",
        description="检查图片合规性（状态、评分、问题清单、整改建议）。当用户想检查图片是否合规时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_video_script_tool,
        name="generate_video_script",
        description="生成短视频脚本（分镜、旁白、字幕、钩子、CTA）。当用户想做短视频/视频脚本时使用。",
    ),
]
