"""
Listing 生成优化模块 - API 路由

提供 RESTful API 端点，供前端调用 Listing 生成优化功能。

端点列表：
POST /api/v1/listing/generate          - 生成完整 Listing
POST /api/v1/listing/optimize           - 优化现有 Listing
POST  /api/v1/listing/optimize/title    - 单独优化标题
POST /api/v1/listing/generate/bullets   - 生成五点描述
POST /api/v1/listing/generate/description - 生成产品描述
POST /api/v1/listing/generate/keywords  - 生成后台关键词
POST /api/v1/listing/analyze/seo        - SEO 分析诊断
POST /api/v1/listing/ab-test            - A/B 测试变体
POST /api/v1/listing/chat               - 自然语言对话
GET  /api/v1/listing/capabilities       - Agent 能力说明
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from core.billing.usage_tracker import meter_agent_chat
from typing import List

from ai_infra.sse import sse_event_stream

from .schemas import (
    GenerateListingRequest,
    OptimizeListingRequest,
    TitleOptimizationRequest,
    BulletPointsRequest,
    DescriptionRequest,
    SEOAnalysisRequest,
    ABTestRequest,
    ListingChatRequest,
    ApiResponse,
    ErrorResponse,
)
from .service import ListingGeneratorService

router = APIRouter(prefix="/api/v1/listing", tags=["Listing 生成优化"])

# 初始化服务
service = ListingGeneratorService()


@router.post("/generate", response_model=ApiResponse, summary="生成完整 Listing")
async def generate_listing(request: GenerateListingRequest):
    """
    从零生成完整的 Amazon Listing 内容，包括：

    - **标题**：SEO优化的产品标题（150-180字符）
    - **五点描述**：5条卖点（大写标题+详细说明）
    - **产品描述**：A+ Content 风格富文本
    - **后台关键词**：合规的 Search Terms（≤250字节）
    - **SEO评分**：多维度质量评估
    - **A/B变体**（可选）：多个测试版本

    示例请求：
    ```json
    {
        "product_name": "Portable Coffee Grinder Manual Ceramic",
        "brand": "BrewMaster",
        "category": "kitchen",
        "features": ["Ceramic burr", "Adjustable coarseness", "Compact design"],
        "price": 24.99
    }
    ```
    """
    try:
        result = await service.generate_complete_listing(request)
        return ApiResponse(data=result.dict(), message="Listing 生成成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize", response_model=ApiResponse, summary="优化现有 Listing")
async def optimize_listing(request: OptimizeListingRequest):
    """
    分析现有 Listing 并给出逐项优化建议。

    返回按优先级排序的改进建议，每项包含：
    - 当前值 vs 建议值
    - 优化原因
    - 预期提升效果
    """
    try:
        result = await service.optimize_listing(request)
        return ApiResponse(data=result.dict(), message="优化分析完成")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/optimize/title", response_model=ApiResponse, summary="优化标题")
async def optimize_title(request: TitleOptimizationRequest):
    """单独优化 Listing 标题，返回 SEO 改进版本"""
    try:
        result = await service.optimize_title(request)
        return ApiResponse(data=result.dict(), message="标题优化完成")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/bullets", response_model=ApiResponse, summary="生成五点描述")
async def generate_bullets(request: BulletPointsRequest):
    """
    生成专业的五点描述（Key Product Features）

    每条包含：
    - 大写卖点标题（如 PREMIUM QUALITY）
    - 详细说明文字
    - 情感触发设计
    """
    try:
        result = await service.generate_bullet_points(request)
        return ApiResponse(data=result.dict(), message="五点描述生成成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/description", response_model=ApiResponse, summary="生成产品描述")
async def generate_description(request: DescriptionRequest):
    """
    生成产品描述（Product Description）

    支持：
    - 纯文本格式
    - HTML 富文本格式（A+ Content 风格）
    - 多段落结构化内容
    """
    try:
        result = await service.generate_description(request)
        return ApiResponse(data=result.dict(), message="产品描述生成成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate/keywords", response_model=ApiResponse, summary="生成后台关键词")
async def generate_keywords(
    title: str,
    category: str = "",
):
    """
    基于标题自动生成后台搜索词（Search Terms）

    规则：
    - 总长度 ≤ 250 字节
    - 不重复标题已有词汇
    - 包含同义词、长尾词、拼写变体
    """
    try:
        result = await service.generate_search_terms(title, category)
        return ApiResponse(data=result.dict(), message="关键词生成成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze/seo", response_model=ApiResponse, summary="SEO 分析诊断")
async def analyze_seo(request: SEOAnalysisRequest):
    """
    对现有 Listing 进行全面的 SEO 诊断

    返回：
    - 综合评分（0-100）
    - 各维度得分（标题/五点/描述/关键词）
    - 通过/未通过检查项清单
    - 具体改进建议
    - 等级评定（A/B/C/D/F）
    """
    try:
        result = await service.analyze_seo(request)
        return ApiResponse(data=result.dict(), message="SEO 分析完成")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ab-test", response_model=ApiResponse, summary="生成 A/B 测试变体")
async def create_ab_test(request: ABTestRequest):
    """
    基于基础 Listing 生成多个 A/B 测试变体

    每个变体包含：
    - 变体标签（如 A - Value Focus）
    - 测试假设
    - 修改后的内容
    """
    try:
        result = await service.generate_ab_test_variants(request)
        return ApiResponse(data=result.dict(), message="A/B 变体生成成功")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat", response_model=ApiResponse, summary="自然语言对话")
async def chat_with_listing_agent(
    request: ListingChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """
    与 Listing 优化专家进行自然语言对话

    支持的功能：
    - 询问 Listing 最佳实践
    - 讨论特定产品的文案策略
    - 获取平台规则解读
    - 请求案例参考
    """
    try:
        result = await service.chat(request.message, request.context)
        return ApiResponse(data=result, message="OK")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream", summary="自然语言对话（SSE 流式）")
async def chat_with_listing_agent_stream(
    request: ListingChatRequest,
    _meter=Depends(meter_agent_chat),
):
    """
    与 Listing 优化专家对话，SSE 流式返回（打字机效果）。

    事件协议：
    - event: delta  → data: {"text": "..."}  增量文本
    - event: done   → data: {"text": "..."}  完整文本
    - event: error  → data: {"message": "..."}
    """
    import json as _json

    async def _wrapped():
        try:
            async for event in sse_event_stream(service.stream_chat(request.message)):
                yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


@router.get("/capabilities", summary="Agent 能力说明")
async def get_capabilities():
    """返回 Listing Agent 的能力描述和使用说明"""
    capabilities = {
        "agent_name": "ListingGenerator",
        "display_name": "Listing 生成优化专家",
        "version": "1.0.0",
        "description": "专业的电商 Listing 内容生成与优化 Agent，精通 Amazon 平台规则和 SEO 最佳实践",
        "capabilities": [
            {
                "name": "complete_generation",
                "display_name": "完整 Listing 生成",
                "description": "从产品信息一键生成标题、五点、描述、关键词",
                "endpoint": "POST /api/v1/listing/generate",
            },
            {
                "name": "title_optimization",
                "display_name": "标题优化",
                "description": "SEO 关键词布局、字符控制、可读性优化",
                "endpoint": "POST /api/v1/listing/optimize/title",
            },
            {
                "name": "bullet_points",
                "display_name": "五点描述生成",
                "description": "专业卖点的提炼与情感触发设计",
                "endpoint": "POST /api/v1/listing/generate/bullets",
            },
            {
                "name": "description_writing",
                "display_name": "产品描述撰写",
                "description": "A+ Content 风格的富文本描述生成",
                "endpoint": "POST /api/v1/listing/generate/description",
            },
            {
                "name": "keyword_research",
                "display_name": "后台关键词生成",
                "description": "合规的 Search Terms 生成（≤250字节）",
                "endpoint": "POST /api/v1/listing/generate/keywords",
            },
            {
                "name": "seo_audit",
                "display_name": "SEO 诊断评分",
                "description": "多维度 Listing 质量评估与改进建议",
                "endpoint": "POST /api/v1/listing/analyze/seo",
            },
            {
                "name": "ab_testing",
                "display_name": "A/B 测试支持",
                "description": "生成多个 Listing 变体用于对比测试",
                "endpoint": "POST /api/v1/listing/ab-test",
            },
        ],
        "supported_platforms": ["amazon"],
        "output_languages": ["en-US"],
        "tips": [
            "提供的产品信息越详细，生成的 Listing 质量越高",
            "可以先使用选品 Agent 分析竞品，再使用本 Agent 生成差异化 Listing",
            "建议在发布前使用 SEO 诊断功能检查合规性",
            "A/B 测试建议持续 2 周以上以获得统计显著性",
        ],
    }
    return capabilities
