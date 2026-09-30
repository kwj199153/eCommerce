"""
选品分析模块 - API 路由

提供 RESTful API 接口供前端调用。

端点列表（共 9 个 —— 与路由表**逐条对应**，由 `tests/test_product_research_capabilities.py` 钉住不许漂移）：
- POST /api/v1/product-research/blue-ocean     - 蓝海品类分析
- POST /api/v1/product-research/profit          - SKU 利润分析
- POST /api/v1/product-research/pain-points      - 痛点机会识别
- POST /api/v1/product-research/competitors      - 竞品对比分析
- POST  /api/v1/product-research/chat            - 自然语言对话（主入口）
- POST  /api/v1/product-research/approval/resume - 人工审批决策回传（HITL 闭环）
- POST  /api/v1/product-research/chat/stream     - 对话流式返回（SSE）
- GET  /api/v1/product-research/market-insight/treemap - 选品市场洞察大盘云图
- GET  /api/v1/product-research/capabilities     - 查询 Agent 能力说明

★★★ 多租户边界（P0 安全修复 2026-09-16，OWASP API Security #1 BOLA）
所有端点都会 `Depends(require_auth_if_enabled)`（认证）。但**认证 ≠ 授权**：
只有 `chat` / `chat/stream` 需要租户上下文（它们能落业务数据 —— 候选选品），
所以只有这两个挂店铺依赖；另外 5 个端点只读不写、且数据来自公共 mock 商品池，
不接触任何租户数据，因此**有意不挂**（挂了反而会让"未选店铺"的用户连
蓝海分析都用不了，属无收益的体验损伤）。

为什么是两个不同依赖名，而不是照抄别的模块的严格版（`get_current_shop_id`）：
  该严格版对**所有写方法**（含 POST）强制要求 `X-Shop-ID`，缺失即 400。
  对话入口不能这样 —— 用户还没选店铺时，「帮我找蓝海机会」这类只读意图
  是完全合法的；一律 400 等于把功能改坏。
  于是取 `get_current_shop_id_optional`：**带店铺头时校验归属**（伪造头 403），
  不带时返回 None → 对话照常，但入库被 `_write_candidates` 硬拒绝。
  即：**门禁放在"写"这一层，而不是"入口"这一层。**
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from core.metering.usage_tracker import meter_agent_chat
from typing import List, Optional

from ai_infra.sse import sse_event_stream
from ai_infra.context_target import bind_context_target, context_target_payload
from ai_infra.skills import bind_requested_skill

# ★ 读口（「本次请求的作用对象」注入段）的**注册不需要在本文件里触发**：
#   第 257 轮起注册点已上提到 `modules/context_target_section.py`，
#   由 `modules/__init__.py` 在包初始化时 import ⇒ 任何业务模块被导入都覆盖到。
#   本文件**故意不再 import 它** —— 注册与某个具体 Agent 的 router 解耦，
#   是那一轮的核心目的（此前「机制属于选品」是一条从未被声明的约定）。
#   判据：`tests/test_context_target_gate.py::test_reader_section_is_imported_at_module_level`
#   钉住"谁负责 import 它"仍是**可查的一行**（现在是 `modules/__init__.py`）。

from core.auth.dependencies import require_auth_if_enabled
from core.identity.models import User
from core.tenant.middleware import get_current_shop_id_optional

from modules.product_research.schemas import (
    BlueOceanRequest,
    ProfitAnalysisRequest,
    PainPointRequest,
    CompetitorCompareRequest,
    ChatRequest,
    ChatResponse,
    ApprovalResumeRequest,
    ApiResponse,
)
from modules.product_research.service import product_research_service, get_market_insight_treemap as _get_market_insight_treemap


# 创建路由器
router = APIRouter(
    prefix="/product-research",
    tags=["选品分析"],
)

# 复用 service 层的**唯一**单例（与 tools.py 同源）——
# 否则 router 与 tools 各持一个 Agent 实例，会话状态互不可见。
service = product_research_service


@router.get("/market-insight/treemap")
async def get_market_insight_treemap(
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """
    选品市场洞察大盘云图（第 305 轮 · 蓝海挖掘大盘云图）

    返回站点 × 类目 的市场洞察快照，供前端 ECharts Treemap 渲染「品类分布、
    价格带、竞争密度、搜索热度、卖家分布、趋势」六维度大盘。

    ★ 为什么是 GET + `get_current_shop_id_optional`：
      · 大盘云图是**只读**展示，走 GET（不是写端点，缺 `X-Shop-ID` 不会 400，
        而是返回空 —— 与「未选店铺看空列表」的既有体验一致）。
      · 用 `optional` 而非严格版：用户还没选店铺时，看大盘是合法只读意图；
        隔离由 `MARKET_SNAPSHOT_SPEC` 上内核的 `scoped()` 承担
        （第 325 轮后不再是 service 里手写的那一句）
        （`shop_id=None` ⇒ 查不到任何行 ⇒ 空态 fail-closed），
        门禁在「读」这一层，与 `/chat` 的「门禁放在写层」同理。

    ★ 真源诚实：演示账号返回 mock 快照且 `degraded=True`（前端如实标注）；
      真实账号返回空 + `degraded=False` + 引导文案，不编假大盘。
    """
    result = await _get_market_insight_treemap(shop_id)
    return ApiResponse(
        success=True,
        message="市场洞察大盘已就绪",
        data=result,
    )


@router.post("/blue-ocean", response_model=ApiResponse)
async def analyze_blue_ocean(
    request: BlueOceanRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    蓝海品类挖掘（MVP 完整版）

    发现高需求、低竞争的蓝海商品机会。

    **筛选参数**：
    - marketplace: 目标站点（默认 amazon_us）
    - category: 类目路径（多级选择）
    - price_min / price_max: 价格区间
    - max_reviews: 评论数上限（控制低竞争）
    - min_monthly_sales: 最小月销量（保证需求）
    - min_roi: 最低目标 ROI (%)
    - exclude_seasonal / exclude_brand_dominant / exclude_high_risk: 高级排除选项

    **返回**：
    - 候选商品列表（含蓝海评分 0-100）
    - 各等级统计（优质蓝海 / 一般潜力 / 高竞争）
    - 完整分析报告摘要
    """
    result = await service.analyze_blue_ocean(request)
    return ApiResponse(
        success=True,
        message="蓝海挖掘完成",
        data=result,
    )


@router.post("/profit", response_model=ApiResponse)
async def analyze_profit(
    request: ProfitAnalysisRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    SKU 利润计算

    精确计算 FBA 费用、广告成本、净利润和 ROI。

    - **selling_price**: 售价 (USD)
    - **cost_price**: 采购成本 (USD)
    - **weight_lbs**: 产品重量 (磅)
    - **dimensions**: 尺寸 (长x宽高 英寸)

    返回：
    - 费用明细（佣金、FBA配送费、仓储费、广告费）
    - 净利润、ROI、盈亏平衡点
    """
    result = await service.analyze_profit(request)
    return ApiResponse(
        success=True,
        message="利润分析完成",
        data=result,
    )


@router.post("/pain-points", response_model=ApiResponse)
async def analyze_pain_points(
    request: PainPointRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    痛点机会识别

    分析竞品评论，提取用户痛点和未满足需求。

    - **asin**: 产品 ASIN（必填）
    - **analyze_positive**: 是否同时分析好评

    返回：
    - 高频痛点列表及出现频率
    - 改进建议和市场空白度评分
    """
    result = await service.analyze_pain_points(request)
    return ApiResponse(
        success=True,
        message="痛点分析完成",
        data=result,
    )


@router.post("/competitors", response_model=ApiResponse)
async def compare_competitors(
    request: CompetitorCompareRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    竞品深度对比

    多维度对比多个竞品的优劣势。

    - **asins**: 竞品 ASIN 列表（2-5 个）
    - **include_reviews**: 是否包含评论分析

    返回：
    - 各竞品的 Listing 质量评分
    - 优势/劣势对比
    - 定位策略建议
    """
    result = await service.compare_competitors(request)
    return ApiResponse(
        success=True,
        message="竞品对比完成",
        data=result,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    _meter=Depends(meter_agent_chat),
):
    """
    选品助手对话（主入口）

    自然语言交互，自动识别用户意图并调用对应的分析能力。

    支持的查询类型：
    - "帮我找厨房用品类的蓝海机会" → 蓝海分析
    - "分析 B0CGLKP2R1 的利润空间" → 利润计算
    - "这个产品有什么用户痛点" → 痛点识别
    - "对比这两个竞品" → 竞品对比

    返回：
    - AI 回复文本
    - 结构化数据（用于右侧展示区渲染）
    - 后续操作建议
    """
    # ★ 点名通道（第 188 轮）：本次对话若指定了技能名，把它置进
    #   调用链上下文，由 `skills_selected` 段落把该技能正文注入
    #   system prompt（与 `load_skill` 共用同一个解析实现）。
    # ★ 「作用对象」与它**同一个作用域**（第 251 轮）：两条通道一起
    #   入栈、一起出栈，避免出现「技能读到了、对象没读到」的半态。
    async with (
        bind_requested_skill(request.skill),
        bind_context_target(context_target_payload(request)),
    ):
        result = await service.chat(
            message=request.message,
            context_id=request.context_id,
            shop_id=shop_id,
            user_id=current_user.id if current_user else None,
        )
    return result


@router.post("/approval/resume", response_model=ChatResponse)
async def resume_approval(
    request: ApprovalResumeRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """
    回传人工审批决策，恢复被 `interrupt()` 冻结的会话（HITL 闭环的收敛点）。

    为什么要单独一个端点、而不是复用 `/chat`：
      被挂起的图停在 `tool_node` 上等一个 `Command(resume=...)`。
      用户在界面上点「批准」**不是在说话**，所以走 `/chat` 只会开一轮全新对话，
      那个待审批的操作仍会永久挂着（且没有任何报错）。

    归属与隔离：
      · `thread_id` 由服务端按 `(命名空间, 用户, 会话)` 重算（见
        `BaseAgent.resolve_thread_id`），**不接受**客户端传入；
      · `session_id` 属于别人时，算出来的 thread_id 与对方不同 ⇒
        找不到那条中断 ⇒ 天然无法替别人批准（`user_id` 是键的一部分）。
    """
    try:
        result = await service.resume_approval(
            request.context_id,
            request.decision,
            shop_id=shop_id,
            user_id=current_user.id if current_user else None,
            reason=request.reason,
            args=request.args,
            feedback=request.feedback,
        )
    except ValueError as e:
        # 决策载荷本身不合法（如 edit 缺 args）⇒ 422，不是服务端故障
        raise HTTPException(status_code=422, detail=str(e)) from e

    # 与 `/chat` 同一个响应契约：前端用同一套结果卡渲染
    return ChatResponse(
        reply=result.content,
        display_type=result.display_type,
        data=result.data,
        suggestions=None,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    _meter=Depends(meter_agent_chat),
):
    """选品助手对话，SSE 流式返回（打字机效果）。"""
    import json as _json

    async def _wrapped():
        try:
            # context_id 必须传下去：入库待补槽位与「上一轮蓝海结果」都按会话隔离
            # ★ 写入点必须在**生成器体内**：包在返回 StreamingResponse
            #   的外层，`async with` 会在生成器被第一次迭代之前就退出 ⇒ 等于没设。
            # ★ 作用对象同域入栈（第 251 轮），理由见 `/chat` 那处注释。
            async with (
                bind_requested_skill(request.skill),
                bind_context_target(context_target_payload(request)),
            ):
                async for event in sse_event_stream(
                    service.stream_chat(
                        request.message,
                        context_id=request.context_id,
                        shop_id=shop_id,
                        user_id=current_user.id if current_user else None,
                    )
                ):
                    yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


@router.get("/capabilities", response_model=ApiResponse)
async def get_capabilities(
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    查询选品 Agent 能力说明

    返回该 Agent 支持的功能列表和使用示例。
    """
    capabilities = {
        "agent_name": "选品分析师 (Product Researcher)",
        "version": "1.0.0",
        "platform": "Amazon US",
        "description": "专业的跨境电商选品分析助手，帮助发现蓝海机会、评估利润空间、分析竞品优劣势。",
        "features": [
            {
                "name": "蓝海品类挖掘",
                "endpoint": "/product-research/blue-ocean",
                "description": "发现高潜力低竞争的细分市场",
                "example": {"category": "kitchen"},
            },
            {
                "name": "SKU 利润计算",
                "endpoint": "/product-research/profit",
                "description": "精确计算 FBA 费用和 ROI",
                "example": {"selling_price": 29.99, "cost_price": 8.50},
            },
            {
                "name": "痛点机会识别",
                "endpoint": "/product-research/pain-points",
                "description": "从竞品评论中提取用户痛点",
                "example": {"asin": "B0CGLKP2R1"},
            },
            {
                "name": "竞品深度对比",
                "endpoint": "/product-research/competitors",
                "description": "多维度对比多个竞品",
                "example": {"asins": ["B0CGLKP2R1", "B0DXYZ1234"]},
            },
            {
                "name": "自然语言对话",
                "endpoint": "/product-research/chat",
                "description": "用对话方式驱动所有分析功能",
                "example": {"message": "帮我找蓝海机会"},
            },
            {
                "name": "对话流式返回",
                "endpoint": "/product-research/chat/stream",
                "description": "同上，SSE 逐段返回（打字机效果）",
                "example": {"message": "帮我找蓝海机会"},
            },
            {
                "name": "人工审批决策",
                "endpoint": "/product-research/approval/resume",
                "description": "回传 accept / reject / edit / response，恢复被挂起的写操作",
                "example": {"context_id": "ctx-1", "decision": "accept"},
            },
            {
                "name": "选品市场洞察大盘云图",
                "endpoint": "/product-research/market-insight/treemap",
                "description": "品类分布/价格带/竞争密度/搜索热度/卖家分布/趋势六维度大盘 Treemap",
                "example": {},
            },
            {
                "name": "能力说明",
                "endpoint": "/product-research/capabilities",
                "description": "本接口：返回功能清单与示例（静态说明，不探测运行期状态）",
                "example": {},
            },
        ],
        "supported_categories": [
            "kitchen (厨房)", "electronics (电子)", "home (家居)",
            "outdoor (户外)", "sports (运动)", "pet (宠物)",
            "beauty (美妆)", "office (办公)", "baby (母婴)",
        ],
    }

    return ApiResponse(
        success=True,
        message="查询成功",
        data=capabilities,
    )
