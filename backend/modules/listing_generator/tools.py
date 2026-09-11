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
    TitleOptimizationRequest,
    BulletPointsRequest,
    DescriptionRequest,
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


# ====== 工具注册表 ======

listing_tools = [
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
