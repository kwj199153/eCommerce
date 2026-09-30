"""
智能客服模块 - API 路由 (Router)

提供客服相关的 RESTful API 端点
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from core.metering.usage_tracker import meter_agent_chat
from core.tenant.middleware import (
    MissingShopContext,
    get_current_shop_id,
    get_current_shop_id_optional,
)
from typing import Optional

from ai_infra.sse import sse_event_stream
from ai_infra.context_target import bind_context_target, context_target_payload
from ai_infra.skills import bind_requested_skill

from .schemas import (
    ChatRequest, ChatResponse,
    FAQSearchRequest, FAQSearchResponse,
    TicketCreateRequest, TicketResponse,
    OrderTrackRequest, OrderTrackResponse,
    SentimentAnalysisRequest, SentimentResponse,
    ApiResponse, ErrorResponse,
    CapabilityResponse
)
from .service import CustomerServiceService, get_cs_agent


# 创建路由器（带前缀）
router = APIRouter(
    prefix="/customer-service",
    tags=["智能客服"]
)


# ====== 对话接口 ======

@router.post("/chat", response_model=ApiResponse, summary="客服对话")
async def chat_endpoint(
    request: ChatRequest,
    # ★ 第 286 轮：话术是租户隔离数据（`knowledge_faqs.shop_id`），读话术
    #   必须有店铺归属。用 **optional** 而非 strict（与 `/chat/stream`
    #   同口径）：没选店铺的用户不该被整个挡在门外，只是拿不到本店话术，
    #   回复里会**如实说明**是哪种缺失。
    #   会落数据吗？不会（对话本身只读话术）；写路径（create_ticket）
    #   另有 strict 守卫。豁免形态见
    #   `tests/test_shop_id_guard.py::ALLOWED_OPTIONAL`。
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
    _meter=Depends(meter_agent_chat),
):
    """
    智能客服对话主入口

    支持多轮对话、FAQ 匹配、情感分析、意图识别
    """
    # ★ 点名通道（第 188 轮）：本次对话若指定了技能名，把它置进
    #   调用链上下文，由 `skills_selected` 段落把该技能正文注入
    #   system prompt（与 `load_skill` 共用同一个解析实现）。
    # ★ 「作用对象」与它**同一个作用域**（第 298 轮）：两条通道一起
    #   入栈、一起出栈，避免出现「技能读到了、对象没读到」的半态。
    #   ★ 本 Agent **只注入、不拒答**，理由见 `.schemas.ChatRequest` 的字段注释。
    async with (
        bind_requested_skill(request.skill),
        bind_context_target(context_target_payload(request)),
    ):
        response = await CustomerServiceService.chat(request, store_id)
    return ApiResponse(
        data={
            "reply": response.reply,
            "conversation_id": response.conversation_id,
            "intent": response.intent,
            "sentiment": response.sentiment,
            "display_type": response.display_type,
            "data": response.data,
            "suggested_actions": response.suggested_actions,
            "should_escalate": response.should_escalate
        },
        message="对话处理完成"
    )


@router.post("/chat/stream", summary="客服对话（SSE 流式）")
async def chat_stream(
    request: ChatRequest,
    # ★ 第 204 轮：这里是 **optional** 而非 strict —— 归属门禁放在「写」那一层。
    #   它是客服的**主对话入口**（前端 `replies/customerService.ts` 的 SSE 分支），
    #   同时服务只读意图（FAQ 搜索 / 情感分析 / 对话摘要）。用 strict 会把
    #   「还没选店铺」的用户整个挡在门外（400）—— 零收益的体验损伤。
    #   它会落数据吗？会（LLM 可能在这个环路里调 `create_ticket`）。但写路径
    #   硬拒绝：`tools._shop_id()` 取不到 ⇒ `service.create_ticket` 抛
    #   `MissingShopContext` ⇒ 零数据库往返（豁免形态 ②，真源 =
    #   `tests/test_shop_id_guard.py::ALLOWED_OPTIONAL`）。
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
    _meter=Depends(meter_agent_chat),
):
    """智能客服对话，SSE 流式返回（打字机效果）。

    ★ 第 204 轮：`store_id` 只为工具环路注入归属（`create_ticket` 落库必须带
      租户维度）。它是 optional 的 —— 缺店铺时对话照常，只有写工具会被拒。
    """
    import json as _json

    async def _wrapped():
        try:
            # ★ 写入点必须在**生成器体内**：包在返回 StreamingResponse
            #   的外层，`async with` 会在生成器被第一次迭代之前就退出 ⇒ 等于没设。
            # ★ 作用对象同域入栈（第 298 轮），理由见 `/chat` 那处注释。
            async with (
                bind_requested_skill(request.skill),
                bind_context_target(context_target_payload(request)),
            ):
                async for event in sse_event_stream(
                    CustomerServiceService.stream_chat(request.message, store_id)
                ):
                    yield event
        except Exception as e:
            yield f"event: error\ndata: {_json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


@router.post("/quick-reply", response_model=ApiResponse, summary="快速回复")
async def quick_reply_endpoint(
    request: ChatRequest,
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """简化版对话接口，用于快捷入口（店铺归属同 `/chat`）"""
    result = await CustomerServiceService.quick_reply(request.message, store_id)
    return ApiResponse(data=result, message="OK")


# ====== FAQ 接口 ======

@router.post("/faq/search", response_model=FAQSearchResponse, summary="搜索知识库")
async def search_faq_endpoint(
    request: FAQSearchRequest,
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """
    在 FAQ 知识库中搜索相关问题（**检索源：`knowledge_faqs` 表**）

    ★ 第 286 轮之前它搜的是内存里 12 条硬编码 FAQ，与库里真话术无关。
    ★ 话术按店铺隔离 ⇒ 缺 `X-Shop-ID` 返回 400；话术库读不出来返回 503
      （**不返回空列表** —— 空列表会把故障伪装成「没有相关话术」）。
    """
    try:
        return await CustomerServiceService.search_faq(request, store_id)
    except PermissionError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=f"话术库暂不可用：{e}")


@router.get("/faq/categories", response_model=ApiResponse, summary="获取 FAQ 分类")
async def get_faq_categories(
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """获取**当前店铺**的 FAQ 分类（读 `knowledge_faqs`）

    ★ 第 286 轮：此前它读 Agent 单例里那批内存话术 —— 而单例在没有店铺
      上下文时列表为空 ⇒ 分类恒为空数组。现在按店铺实时统计。
    ★ `faq_error` 非空表示**话术库读不出来**（与「还没配话术」不同），
      端点把它放进 message，界面上才不会把故障显示成「暂无分类」。
    """
    payload = await CustomerServiceService.list_faq_categories(store_id)
    categories = [
        {"name": c["name"], "count": c["count"], "icon": _get_category_icon(c["name"])}
        for c in payload["categories"]
    ]
    err = payload.get("faq_error") or ""
    return ApiResponse(
        data=categories,
        message=("话术库暂不可用：" + err) if err else "OK",
    )


def _get_category_icon(category: str) -> str:
    """获取分类图标"""
    icons = {
        "物流": "🚚",
        "退换货": "🔄",
        "订单": "📦",
        "售后": "🔧",
        "支付": "💳",
        "其他": "❓"
    }
    return icons.get(category, "📋")


# ====== 工单接口 ======

@router.post("/ticket/create", response_model=TicketResponse, summary="创建工单")
async def create_ticket_endpoint(
    request: TicketCreateRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    创建客户服务工单（**落库到 `cs_tickets`**）

    自动计算优先级和 SLA。

    ★ 归属由 `X-Shop-ID` 请求头注入（strict 版）：缺/空 ⇒ 400；
      带真 token ⇒ 强制校验该店铺 ∈ 当前用户可见账户（不符 403）。
      请求体里**没有** store_id 字段 —— 归属只能是服务端注入的。
    """
    try:
        return await CustomerServiceService.create_ticket(request, store_id)
    except MissingShopContext as e:
        # 映射成 400（请求形状问题）而不是 500（服务端故障）——
        # 混进 500 会让人去查日志找一个根本不存在的异常。
        raise HTTPException(status_code=400, detail=str(e))


# ====== 订单追踪接口 ======

@router.post("/order/track", response_model=OrderTrackResponse, summary="订单追踪")
async def track_order_endpoint(
    request: OrderTrackRequest,
    # ★ 第 285 轮：订单是**租户隔离**数据，查自有订单库必须有店铺归属。
    #   用 optional 而非 strict：缺店铺时**仍能**退回平台适配层（与
    #   `/chat/stream` 同口径 —— 读路径不把没选店铺的用户挡在门外），
    #   只是查不到自有库，响应里会如实写明。
    store_id: Optional[str] = Depends(get_current_shop_id_optional),
):
    """
    查询订单状态与物流信息。

    ★ 取数顺序（第 285 轮）：**自有订单库 → 平台适配层**。
      自有库（`orders` / `shipments`）是真源，信息更全（有运单号 / 承运商 /
      物流轨迹 / 迟到天数）；平台适配层只在自有库查不到时兜底。

    ★ fail-closed：只支持按订单号查。仅给邮箱 / 手机号时不再用 `hash(email)`
      编一个订单号去查，而是直接回 `found=false` + 原因；两个源都查不到时
      同样如实回原因，**绝不返回编造的订单内容**。
    """
    return await CustomerServiceService.track_order(request, store_id)


# ====== 情感分析接口 ======

@router.post("/analyze/sentiment", response_model=SentimentResponse, summary="情感分析")
async def analyze_sentiment_endpoint(request: SentimentAnalysisRequest):
    """
    分析文本的情感倾向

    用于实时监控客户情绪
    """
    return await CustomerServiceService.analyze_sentiment(request)


# ====== 对话管理接口 ======

@router.get("/conversation/{conversation_id}", response_model=ApiResponse, summary="对话摘要")
async def get_conversation_endpoint(conversation_id: str):
    """
    获取指定会话的摘要信息
    """
    summary = await CustomerServiceService.get_conversation_summary(conversation_id)

    if not summary:
        raise HTTPException(status_code=404, detail="会话不存在")

    return ApiResponse(data=summary.model_dump())


# ====== 能力描述 ======

@router.get("/capabilities", response_model=CapabilityResponse, summary="Agent 能力")
async def capabilities_endpoint():
    """
    获取智能客服 Agent 的能力描述
    """
    return CustomerServiceService.get_capabilities()


# ====== 健康检查 ======

@router.get("/health", summary="健康检查")
async def health_check():
    """服务健康检查"""
    agent = get_cs_agent()
    return {
        "status": "healthy",
        "agent_name": agent.agent_name,
        "faq_count": len(agent.faq_database),
        "active_conversations": len(agent.conversations)
    }
