"""店秘书（主 Agent）路由 —— 轻量编排端点"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ai_infra.sse import sse_event_stream
from core.metering.usage_tracker import meter_agent_chat
# ★ 用 `_optional` 变体而不是 `get_current_shop_id`：本端点是 **POST 但属对话入口**，
#   不是业务数据写入口。用严格版会让「刚注册、还没有店铺」的用户一进来就被 400
#   挡住 —— 而这时候他恰恰只能靠店秘书去创建第一家店铺。
#   详见 `get_current_shop_id_optional` 的 docstring 使用边界。
from core.auth.dependencies import require_auth_if_enabled
from core.identity.models import User
from core.tenant.middleware import get_current_shop_id_optional
from modules.secretary.agent import current_plan, route, route_stream
from modules.secretary.shop_context import build_shop_context

router = APIRouter(prefix="/api/v1/orchestrator", tags=["店秘书"])


class HistoryMessage(BaseModel):
    role: str = Field(..., description="消息角色：user / assistant")
    content: str = Field(..., description="消息内容")


class OrchestratorRequest(BaseModel):
    message: str = Field(..., description="用户一句话", min_length=1)
    history: list[HistoryMessage] = Field(
        default=[],
        description="本会话历史消息（不含当前 message），用于多轮上下文连贯",
    )
    session_id: Optional[str] = Field(
        None,
        description="会话 ID（跨会话记忆）。非空时后端从 DB 读取历史 + 用 checkpoint 持久化",
    )


class OrchestratorResponse(BaseModel):
    reply: str = Field(..., description="面向用户的回复")
    actions: list = Field(default=[], description="有序动作列表，前端按顺序执行")
    action: dict | None = Field(
        None,
        description=(
            "动作（向后兼容，= actions 最后一个）："
            "{action: switch_agent, agentId} 或 {action: navigate, view} "
            "或 {action: select_product, product:{id,title,asin}}"
        ),
    )
    tool_calls: list = Field(default=[], description="本次实际调用的工具名列表")
    route_mode: str = Field(
        "llm",
        description="决策路径：shortcut=关键词短路（未调 LLM）/ llm=LLM 兜底",
    )
    session_id: Optional[str] = Field(
        None, description="会话 ID（回显，未传时后端新建并返回，供前端持久化）"
    )
    plan: dict | None = Field(
        None,
        description=(
            "本会话的子任务计划（第 148 轮 批 C3）："
            "{total, completed, by_status, items:[{id, content, status, note}]}。"
            "仅在店秘书建立了计划时出现 —— 恒返回空计划会让调用方分不清"
            "「该 Agent 没开启规划」与「开启了但这一轮还没规划」。"
            "计划存在图状态（随 checkpointer 落 PG），**不在消息历史里**，"
            "因此不会因为对话变长被上下文裁剪而丢失。"
        ),
    )
    truncated: bool = Field(
        False,
        description=(
            "本轮是否因预算限制被截断（第 159 轮 批 D3）。"
            "`true` 时 `reply` **已经带上提示前缀** —— 所以即使前端不渲染这个字段，"
            "用户也看得到「结果可能不完整」。它同时是图状态 `structured_response` "
            "的第一个真消费者：此前 `_respond_node` 写进去的 `status` 全仓无人读。"
            "短路路径（关键词命中、不跑图）恒为 False。"
        ),
    )


class PlanResponse(BaseModel):
    """`GET /plan` 的响应：**只含一个字段**，且刻意不区分"没有计划"与"读不到"。"""

    plan: dict | None = Field(
        default=None,
        description=(
            "会话当前的子任务计划，形状与 `POST /chat` 的 `plan` 字段**完全相同**"
            "（`{total, completed, by_status, items:[{id, content, status, note}]}`）。"
            "`null` 表示：还没有计划 / 没有可用会话 / 未登录 —— **三者同一个响应**。"
            "★ 刻意不区分原因：一旦区分，这个端点就成了「这个 session_id 存不存在」"
            "的探针，可被用来枚举别人的会话。"
        ),
    )


async def _resolve_session(
    request: "OrchestratorRequest", current_user: Optional[User]
) -> tuple[str, list]:
    """解析本次对话要用的**会话与历史** —— `POST /chat` 与 `/chat/stream` 的唯一实现。

    ★ 为什么要收成一处：这是**授权判定**（"这个 session_id 是不是你的"），
      不是普通取数。两份实现里只要有一份写漏，症状就是**别人的对话被读到、
      还被当作上下文喂给 LLM**，而且不报任何错 —— 本仓对这类形态的态度是
      「同一判定两份实现 ⇒ 至少一份永远测不到」。

    归属（★★★ P0-1，2026-09-18）
    ---------------------------
    `session_id` 由**客户端**提供 ⇒ 必须先过归属校验。修复前这里只问
    「会话存在吗」（`conversation_exists`），不问「是你的吗」⇒ 拿别人的
    session_id 就能：
      ① 读到别人的完整对话（`get_history` 直读）；
      ② 那段历史被当作上下文**喂给 LLM**；
      ③ 本轮两条消息被 `append_message` 写进**别人的**会话。
    实测（生产模式）：B 持有效 token 传 A 的 session_id → 200 + A 的历史全文。

    现在换成 `get_owned_conversation`：**不存在与无权返回同一个 None**，
    本函数据此只做一件事 —— 当作"没有可用会话"，走新建。
    ★ 绝不把别人的 session_id 回显给调用方，否则等于确认"这个 ID 是真的"。

    ★ 取门面出口（第 140 轮）：原先是 `from modules.conversation.service import ...`
      —— 门禁上线后属「伸手进包内部」。改成取包门面，service 内部重构不再
      影响调用方。
    """
    # ★ 第 140 轮：原先抓的是**子模块** `conversation.service`（门禁上线后
    #   属「伸手进包内部」）。改为取门面出口的 4 个动作 —— 契约可见，
    #   service 内部重构不再影响本文件。
    from modules.conversation import (
        create_conversation,
        get_owned_conversation,
        history_of,
    )

    session_id = request.session_id
    conv = None
    if session_id:
        conv = await get_owned_conversation(current_user, session_id)

    history = [h.model_dump() for h in request.history]
    if conv is not None:
        # DB 历史为准（跨会话恢复场景）
        db_history = await history_of(conv, limit=20)
        if db_history:
            history = db_history
    else:
        # 没带 session_id / 会话不存在 / 不属于当前用户（换账号、换环境、伪造）
        # ⇒ 一律新建。owner_id **只能**来自服务端身份，不接受任何自报。
        session_id = await create_conversation(
            agent_id="secretary",
            owner_id=current_user.id if current_user else None,
        )

    return session_id, history


async def _persist_turn(
    current_user: Optional[User],
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """把本轮 user + assistant 消息写入会话（异步持久化，**失败不阻断响应**）。

    ★ 为什么失败只记日志：写历史是**副产品**，它挂掉（如 DB 未就绪）不该把
      已经产出的回复变成 500。这与「禁止静默假装成功」不矛盾 —— 那条针对的是
      **业务结论**；这里丢的只是"以后翻历史少一轮"。

    ★ 此刻 `session_id` 必然是「当前用户自己的会话」或「刚为他新建的会话」，
      所以这里不会再碰到别人的会话（`append_message` 内部仍会判一次，冗余但无害）。

    ★ 顺带修掉一个旧 bug：修复前 `session_id` 被置 None 后仍会走到这里，
      于是落一条 `conversation_id=None` 的孤儿消息（该列**无外键**，
      所以它不会报错、只会静默堆积）。现在 `session_id` 恒非空。
    """
    from modules.conversation import append_message

    try:
        await append_message(current_user, session_id, "user", user_text)
        await append_message(current_user, session_id, "assistant", assistant_text)
    except Exception as e:
        # 写历史失败不影响主流程（如 DB 未就绪）
        logging.getLogger(__name__).warning(f"会话消息持久化失败: {e}")


@router.post("/chat", response_model=OrchestratorResponse, summary="店秘书对话（意图路由）")
async def secretary_chat(
    request: OrchestratorRequest,
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    _meter=Depends(meter_agent_chat),
):
    """
    店秘书全局入口：识别用户意图，调用业务工具或返回导航/选择动作。

    决策层 B（跨会话记忆）+ C（checkpointer）：
    - 请求带 session_id 且**它属于当前用户** → 从 DB 读历史注入 + checkpoint 持久化
    - 其余情况（没带 / 不存在 / 不属于你）→ 新建会话，返回新 session_id 供前端持久化

    ★ P0-1（2026-09-18）：`session_id` 是**客户端提供的**，所以必须先判归属。
      不属于当前用户时**当作没有会话**（新建），且**不回显**传入的 ID ——
      回显等于确认"这个 ID 是真实的"，可供枚举。
      实测修复前：B 持有效 token 传 A 的 session_id → 200 + A 的历史全文
      （读到后还被当作上下文喂给 LLM），本轮消息也会写进 A 的会话。

    返回：
    - reply：面向用户的回复文本
    - actions：有序动作列表（选产品 → 切 Agent 等），前端按顺序 dispatchAppAction
    - action：向后兼容字段（= actions 最后一个）
    - tool_calls：本次调用的工具名（调试/埋点用）
    - session_id：会话 ID（前端持久化，后续请求带回）
    """
    # ★ 归属解析与落库都收进**唯一实现**（`_resolve_session` / `_persist_turn`）：
    #   流式孪生端点 `/chat/stream` 走的是同一份 —— 「同一判定两份实现，
    #   至少一份永远测不到」是本仓反复踩过的形态（详见那两个函数的 docstring；
    #   这里的归属判定是**授权**，不是取数，抄一份漏一份的代价是数据泄露）。
    session_id, history = await _resolve_session(request, current_user)

    # ★ 第 242 轮：本轮「当前店铺」权威事实（服务端查库渲染，见
    #   `modules/secretary/shop_context.py`）。
    #   为什么不放在 `route()` 里取：它是**同步签名**，拿不到 DB 会话。
    #   实测事故：切到「亚马逊1」后模型仍写「当前店铺（虾皮1）」——
    #   那句话在修复前只能从对话历史里取。
    #   ★ 取的是**包裹**（事实 + 历史去污染名单）：只注入事实不够 ——
    #     实测模型会照抄历史里那条现成的错误自称（见 shop_context 头注释）。
    shop_context = await build_shop_context(shop_id)

    result = await route(
        request.message,
        shop_id=shop_id,
        # 与 `shop_id` **同源**、由服务端构造：模型据此自称当前店铺，
        # 同时用它把历史里的**其它**店铺名抹掉。
        shop_context=shop_context,
        history=history,
        session_id=session_id,
        # ★ 身份只从服务端上下文取（`current_user` 由鉴权依赖注入），
        #   绝不接受 body 里的任何自报字段。
        user_id=current_user.id if current_user else None,
    )

    # 决策层 B：把本轮 user + assistant 消息写入会话（失败不阻断响应）
    await _persist_turn(
        current_user, session_id, request.message, result.get("reply", "")
    )

    return OrchestratorResponse(
        reply=result.get("reply", "处理完成"),
        actions=result.get("actions", []),
        action=result.get("action"),
        tool_calls=result.get("tool_calls", []),
        route_mode=result.get("route_mode", "llm"),
        session_id=session_id,
        # ★ 第 148 轮 批 C3：把子任务计划一并回传（短路路径没有 plan ⇒ None）。
        plan=result.get("plan"),
        # ★ 第 159 轮 批 D3：截断标记（短路路径不跑图 ⇒ False）。
        truncated=result.get("truncated", False),
    )


@router.post("/chat/stream", summary="店秘书对话（SSE 流式）")
async def secretary_chat_stream(
    request: OrchestratorRequest,
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    current_user: Optional[User] = Depends(require_auth_if_enabled),
    _meter=Depends(meter_agent_chat),
):
    """店秘书对话，SSE 流式返回：**过程实时可见**，正文与结构化字段与 `/chat` 同源。

    ★ 为什么需要这条通道（第 212 轮）
    --------------------------------
    `/chat` 是**一次性 JSON**：整张图（含工具调用）跑完才吐响应，中途
    **一个事件都不发**。而店秘书恰恰是 `AGENT_LIST[0]` —— 打开应用默认就
    选中它 ⇒ 老板的第一印象必然是「转圈几秒 → 直接出结果（过程看不见）」。
    接上这条 SSE 通道之后，「思考过程」在**所有对话**里都能看到。

    ★ 原 `/chat` **保留不动**：非流式调用方（脚本 / 测试 / 前端降级链）依赖
      它的稳定契约。两条路共用 `_resolve_session` / `_persist_turn` 与
      `modules/secretary/agent.py::_digest_graph_state`
      ⇒ **归属判定与正文取法都只有一份实现**。

    事件协议（与其余 5 家流式 Agent **完全一致**，见 `ai_infra/sse.py`）：
      · `progress` —— 阶段提示（会被覆盖，非正文）
      · `step`     —— 工具轨迹，逐条追加（**这就是「思考过程」**）
      · `preview`  —— 模型 token 的**预览**增量（第 238 轮；随时被替换，非正文）
      · `delta`    —— 正文增量（**权威正文**，与 `done` / 落库同一份）
      · `meta`     —— 结构化字段：`actions` / `plan` / `session_id` /
                      `tool_calls` / `route_mode` / `truncated`
      · `done`     —— 收尾（带完整正文）

    ★ 豁免写守卫的形态与 `/chat` **完全同构**（真源见
      `tests/test_shop_id_guard.py::ALLOWED_OPTIONAL`）：它是对话入口而非业务
      写入口 —— 用严格版会把「一家店铺都还没有」的新用户一开口就 400 挡住，
      而那时他恰恰只能靠店秘书去创建第一家店铺（自救路径被自己堵死）。
    """
    async def _wrapped():
        try:
            session_id, history = await _resolve_session(request, current_user)

            # ★ 第 242 轮：与 `/chat` **同一处**取事实 —— 非流式与流式两条路
            #   不许各算一份，否则同一句话在两条链上的「当前店铺」会漂移
            #   （本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到）。
            shop_context = await build_shop_context(shop_id)

            # ★ 落库正文取自 `event: meta` 的 `reply` 字段 —— **唯一真源**。
            #
            # 改前是"把所有 `str` chunk 拼起来"。那条口径的正确性依赖一个
            # **隐式前提**：「route_stream 只会 yield 一段 str」。它今天成立，
            # 但没有任何门禁钉住它 —— 谁哪天多 yield 一段（比如把预览也写成
            # `str`），库里立刻多出一截，而且**零报错**（表现只是"历史里那段话
            # 变长了"）。第 238 轮加 `preview` 通道时正好撞上这个前提。
            # 现在取的 `meta["reply"]` 就是 `_digest_graph_state` 的产物本身，
            # 与非流式 `/chat` 落库的是**同一个字段** ⇒ 两条通道不可能漂移。
            persisted_reply = ""

            async def _chunks():
                nonlocal persisted_reply
                async for chunk in route_stream(
                    request.message,
                    shop_id=shop_id,
                    # 同 `/chat`：服务端构造的权威上下文（事实 + 去污染名单）。
                    shop_context=shop_context,
                    history=history,
                    session_id=session_id,
                    user_id=current_user.id if current_user else None,
                ):
                    # `meta` 恒在正文之后、`done` 之前发出（见 `route_stream`）
                    # ⇒ 循环正常跑完时它必定已经拿到。
                    if isinstance(chunk, dict) and chunk.get("event") == "meta":
                        reply_text = (chunk.get("data") or {}).get("reply")
                        if reply_text:
                            persisted_reply = str(reply_text)
                    yield chunk

            async for event in sse_event_stream(_chunks()):
                yield event

            await _persist_turn(
                current_user, session_id, request.message, persisted_reply
            )
        except Exception as e:
            # ★ 与其余 5 家一致：流已经开始就不能再改 HTTP 状态码，
            #   错误只能作为一条 `error` 事件下发（`/chat` 那边是 500 ——
            #   它还没开始写响应体，所以能体面地报错）。
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(_wrapped(), media_type="text/event-stream")


@router.get("/plan", response_model=PlanResponse, summary="读会话当前子任务计划")
async def secretary_plan(
    session_id: str = Query(
        ...,
        min_length=1,
        description="会话 ID（前端持久化后带回；与 `POST /chat` 用的是同一个）",
    ),
    shop_id: Optional[str] = Depends(get_current_shop_id_optional),
    current_user: Optional[User] = Depends(require_auth_if_enabled),
):
    """
    读当前会话的**子任务计划**（只读：不推进图、不调 LLM、零副作用）。

    为什么端点要单独存在
    --------------------
    `POST /chat` 已经把 `plan` 带在响应里了，但那是**对话的副产品**：
    老板刷新页面后，前端手上没有"最近一次响应"，计划条就会空着 —— 直到他
    再随便说一句话。而计划是**跨轮持续的状态**（后端刻意把它放在图状态而非
    消息序列里，正是为了让它不随上下文裁剪消失），所以它也该有个不依赖
    「刚好聊过一句」的读取方式。

    ★ 查询参数而不是请求体：`session_id` 是裸标量，按本仓口径**走 query**。
      写成 body 会踩到那个已修过一次的坑（`refresh_token` 按 query 解析 ⇒
      前端发 body 稳定 422 ⇒ 功能"看起来做了"但从未生效）。

    归属与枚举防护
    --------------
    - `user_id` 只从**服务端身份**取（`current_user`），不接受任何自报字段；
      `thread_id = ns:user_id:session_id` ⇒ 别人拿你的 session_id 来读，
      算出的是**他自己**的键，物理上读不到你的计划。
    - 未登录 / 没有会话 / 没有计划 / 读失败 ⇒ **一律 `plan: null`**，
      不区分原因（区分即成为会话存在性探针）。

    ★ 为什么一个只读端点也在配额门禁之下（第 155 轮实测记录）
    -----------------------------------------------------------
    `main.py` 给本 router 挂了 `BUSINESS_AUTH` + `CHAT_QUOTA` 两个**路由级**
    依赖，因此 `/plan` 会自动继承它们（实测：`/plan` 顶层依赖 4 条，与
    `/chat` 的差集只有 `meter_agent_chat` 一条）。这不是负担，两条都恰当：
      · `BUSINESS_AUTH`（`require_auth_if_enabled`）—— optional 语义，
        演示模式返回 None，与本端点"没身份就没有计划"的设计一致；
      · `CHAT_QUOTA`（`check_agent_chat_quota`）—— 它的 docstring 写得很清楚：
        **「仅检查额度（不计量、不扣减）」**。所以刷新页面读计划**不会消耗**
        任何对话次数；额度用尽时它 429，而那时读计划本来也没有意义。
    ★ 真正**计费**的 `meter_agent_chat` 只在 `/chat` 上，本端点**刻意不挂**
      —— 读一次状态不该产生费用。
    """
    plan = await current_plan(
        session_id=session_id,
        # ★ 归属只能来自服务端上下文。
        user_id=current_user.id if current_user else None,
        shop_id=shop_id,
    )
    return PlanResponse(plan=plan)
