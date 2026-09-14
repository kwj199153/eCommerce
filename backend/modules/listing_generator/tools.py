"""
Listing 模块 → 主 Agent 工具注册表

把 ListingGeneratorService 的**细粒度**能力包装成 langchain 工具，
供店秘书（主 Agent）通过 bind_tools 自主选择调用。

设计要点（为什么这么做，见 docs/refactor-plan.md 与项目记忆）：
- 只包「语义明确」的细粒度方法，**不包** `chat` / `generate_complete_listing`
  / `optimize_listing` / `analyze_seo` 这类「交给 agent 内部 _classify_intent
  关键词表再判断一次」的粗粒度入口 —— 那会与主 Agent 的 LLM 判断冲突。
- 参数直接用 schemas 里已有的 Pydantic 请求模型，LLM 能通过 JSON Schema
  看到字段名与描述，从而正确填参。
- 工具层只做「调用 service + 序列化为 JSON 字符串」，不碰 agent 本体。
"""

from langchain_core.tools import StructuredTool

from .service import ListingGeneratorService
from .schemas import (
    GenerateListingRequest,
    OptimizeListingRequest,
    TitleOptimizationRequest,
    BulletPointsRequest,
    DescriptionRequest,
    SEOAnalysisRequest,
    ABTestRequest,
)

# 单例 service（与 router 同源）
_service = ListingGeneratorService()


async def _optimize_title_tool(
    current_title: str,
    product_name: str = "",
    main_keyword: str = "",
) -> str:
    """优化现有 Listing 的标题，返回 SEO 改进版本。

    Args:
        current_title: 当前的标题原文（必填）。
        product_name: 产品名称，用于辅助理解（可选）。
        main_keyword: 希望命中的主关键词（可选）。
    """
    req = TitleOptimizationRequest(
        current_title=current_title,
        product_name=product_name or None,
        main_keyword=main_keyword or None,
    )
    resp = await _service.optimize_title(req)
    return resp.model_dump_json()


async def _generate_bullet_points_tool(
    product_name: str,
    features: list[str] | None = None,
) -> str:
    """为产品生成五点描述（Key Product Features）。

    Args:
        product_name: 产品名称（必填）。
        features: 产品特性列表，用于提炼卖点（可选）。
    """
    req = BulletPointsRequest(
        product_name=product_name,
        features=features,
    )
    resp = await _service.generate_bullet_points(req)
    return resp.model_dump_json()


async def _generate_description_tool(
    product_name: str,
    features: list[str] | None = None,
    include_html: bool = True,
) -> str:
    """为产品生成详情描述（Product Description）。

    Args:
        product_name: 产品名称（必填）。
        features: 产品特性列表（可选）。
        include_html: 是否同时生成 HTML 富文本版本（默认 True）。
    """
    req = DescriptionRequest(
        product_name=product_name,
        features=features,
        include_html=include_html,
    )
    resp = await _service.generate_description(req)
    return resp.model_dump_json()


async def _generate_search_terms_tool(
    title: str,
    category: str = "",
) -> str:
    """基于标题生成后台搜索词（Search Terms）。

    Args:
        title: 已确定的产品标题（必填）。
        category: 产品类目，用于补充类目词（可选）。
    """
    resp = await _service.generate_search_terms(title, category)
    return resp.model_dump_json()


async def _generate_complete_listing_tool(
    product_name: str,
    brand: str = "",
    category: str = "",
    features: list[str] | None = None,
    price: float | None = None,
    generate_ab_variants: bool = False,
) -> str:
    """从零生成完整 Listing（标题 + 五点 + 描述 + 关键词 + SEO 评分）。

    Args:
        product_name: 产品名称（必填）。
        brand: 品牌名称（可选）。
        category: 产品类目（可选）。
        features: 产品特性列表（可选）。
        price: 产品售价，单位美元（可选）。
        generate_ab_variants: 是否同时生成 A/B 测试变体（默认 False）。
    """
    req = GenerateListingRequest(
        product_name=product_name,
        brand=brand or None,
        category=category or None,
        features=features,
        price=price,
        generate_ab_variants=generate_ab_variants,
    )
    resp = await _service.generate_complete_listing(req)
    return resp.model_dump_json()


async def _optimize_listing_tool(
    current_title: str = "",
    current_bullets: list[str] | None = None,
    current_description: str = "",
    current_search_terms: str = "",
) -> str:
    """优化现有 Listing，返回逐项优化建议（按优先级排序）。

    Args:
        current_title: 当前标题原文（可选）。
        current_bullets: 当前五点描述列表（可选）。
        current_description: 当前产品描述（可选）。
        current_search_terms: 当前后台搜索词（可选）。
    """
    current_listing = {
        "title": current_title,
        "bullets": current_bullets or [],
        "description": current_description,
        "search_terms": current_search_terms,
    }
    req = OptimizeListingRequest(current_listing=current_listing)
    resp = await _service.optimize_listing(req)
    return resp.model_dump_json()


async def _analyze_seo_tool(
    title: str,
    bullets: list[str],
    description: str,
    search_terms: str = "",
    main_keyword: str = "",
) -> str:
    """对现有 Listing 做 SEO 诊断评分（标题/五点/描述/关键词多维打分 + 等级）。

    Args:
        title: 当前标题（必填）。
        bullets: 当前五点描述列表（必填）。
        description: 当前产品描述（必填）。
        search_terms: 当前后台搜索词（可选）。
        main_keyword: 主关键词（可选）。
    """
    req = SEOAnalysisRequest(
        title=title,
        bullets=bullets,
        description=description,
        search_terms=search_terms,
        main_keyword=main_keyword or None,
    )
    resp = await _service.analyze_seo(req)
    return resp.model_dump_json()


async def _ab_test_tool(
    base_title: str,
    base_bullets: list[str] | None = None,
    base_description: str = "",
) -> str:
    """基于基础 Listing 生成多个 A/B 测试变体。

    Args:
        base_title: 基础标题（必填）。
        base_bullets: 基础五点描述列表（可选）。
        base_description: 基础产品描述（可选）。
    """
    base_listing = {
        "title": base_title,
        "bullets": base_bullets or [],
        "description": base_description,
    }
    req = ABTestRequest(base_listing=base_listing)
    resp = await _service.generate_ab_test_variants(req)
    return resp.model_dump_json()


# ====== 工具注册表 ======

# 细粒度工具（原有 4 个）
_fine_grained_tools = [
    StructuredTool.from_function(
        coroutine=_optimize_title_tool,
        name="optimize_listing_title",
        description="优化 Listing 标题，返回 SEO 改进版本、字符数与 SEO 评分。当用户想改/润色/优化标题时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_bullet_points_tool,
        name="generate_bullet_points",
        description="为产品生成五点描述（卖点）。当用户想写/生成五点、卖点时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_description_tool,
        name="generate_product_description",
        description="为产品生成详情描述（可含 HTML 富文本）。当用户想写/生成产品描述时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_generate_search_terms_tool,
        name="generate_search_terms",
        description="基于标题生成后台搜索词（Search Terms）。当用户想生成/补充关键词时使用。",
    ),
]

# 粗粒度工具（本次补齐 4 个，供子 Agent 内部自主路由）
_coarse_grained_tools = [
    StructuredTool.from_function(
        coroutine=_generate_complete_listing_tool,
        name="generate_complete_listing",
        description="从零生成一套完整 Listing（标题+五点+描述+关键词+SEO评分）。当用户要「生成/写一套完整 listing」且没有指定只做标题/五点等单一部件时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_optimize_listing_tool,
        name="optimize_listing",
        description="分析现有 Listing 并给出逐项优化建议。当用户要「优化/改进现有 listing」而非只改标题时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_analyze_seo_tool,
        name="analyze_listing_seo",
        description="对现有 Listing 做 SEO 诊断评分。当用户要「诊断/评分/检查 SEO」时使用。",
    ),
    StructuredTool.from_function(
        coroutine=_ab_test_tool,
        name="generate_ab_test_variants",
        description="生成多个 A/B 测试变体。当用户要「A/B 测试/变体/多个版本」时使用。",
    ),
]

listing_tools = _fine_grained_tools + _coarse_grained_tools
