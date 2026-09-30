# -*- coding: utf-8 -*-
"""选品 Agent 的**路由与意图层**（P0-6 第三刀：从 `agent_product_research.py` 外移）。

## 这一层是什么

「**这句话该走哪条路**」的全部判定与执行：

    build_router            装配工具路由子层（BaseAgent + 全部 product_research 工具）
    parse_tool_output       工具返回的 JSON 文本 → 带 `type` 的 dict
    route_via_tools         LLM 自主选工具执行（非流式）
    route_gated_intent      有副作用意图的**非流式**审批入口
    stream_gated_intent     有副作用意图的**流式**审批入口（与上者逐字同源）
    classify_intent         意图分类（前置信号 → 关键词表）
    is_candidate_query      「候选存量清点」与门
    is_market_insight_query 「选品大盘读口」与门
    named_tokens            查询里用于点名商品的实词 token

原先是 `ProductResearchAgent` 上的 9 个私有方法 + 9 个类级常量。

## 为什么用显式传参（而不是 mixin / 继承）

与第一刀（`agent_helpers.py`，mixin）、第二刀（`agent_analyzers.py`，显式传参）同一条
方法论：**藏进基类只会让耦合从「可以数的参数」变成「看不见的继承链」**，
门禁再也数不出这个类实际依赖什么 —— 那是自欺。

于是本模块的函数签名**就是依赖清单**：

    router             工具路由子层实例（原 `self._router`）
    get_router         取路由层的回调（原 `self._get_router()`）——
                       **懒加载缓存仍住 Agent**，那是实例状态
    route_via_tools    非流式工具路由（原 `self._route_via_tools`）
    stream_via_tools   流式工具路由（原 `self._stream_via_tools`）
    detect_pending     中断检测（原 `self._detect_pending_approval`，住在 `agent_hitl`）
    compose_reply      结论压成人话（原 `self._compose_reply`，属流式/回复组装层）

★ 为什么 `route_via_tools` / `stream_via_tools` 是**传回调**而不是直接调本模块的同名函数：
  `tests/test_hitl_approval_flow.py` 用 `monkeypatch.setattr(agent, "_route_via_tools", …)`
  替换实例方法。裸名调用会**绕开**那次替换，把「测试以为换掉了」变成「其实没生效」。
  同 `agent_hitl.resume_approval` 传 `detect_pending=` 的理由。

## 什么**留在** Agent 本类（不是漏搬）

    `_get_router`              它**持有** `self._router` 懒加载缓存 —— 那是实例状态
    `_APPROVAL_GATED_INTENTS`  有副作用意图名单：消费方是入口层（`_invoke_impl` /
                               `_stream_chat_impl`），不是本层
    `_INTENT_ROUTES`           **重导出**（唯一实现在本模块）：`tests/test_product_research_intent_inventory.py`
                               按 `ProductResearchAgent._INTENT_ROUTES` 取表，那是既有契约
    `_APPROVAL_CHANNEL_DOWN_MSG` 同上（消费方是 `_stream_gated_intent` 的流式孪生与
                               `_stream_via_tools`）

## 纯静态逻辑取**模块级别名**，不重写

`_extract_multiple_asins` 等来自 `ResearchHelpersMixin`；本模块取模块级别名
（与 `agent_analyzers.py` 同款取法）⇒ 函数体与改前**只差一个 `self.` 前缀**，
让「外移是否真的逐字搬走」成为可机检的事（`probes/r338/ast_parity.py`）。
"""
import json
from typing import Any, AsyncIterable, Awaitable, Callable, List, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent
from ai_infra.intent import Route, first_match

from core.logger import get_logger

from .agent_helpers import ResearchHelpersMixin
from .agent_models import AgentResponse

logger = get_logger("product_research.routing")

# ★ 与 `agent_analyzers.py` 同款取法：纯静态逻辑取**模块级别名**，于是函数体
#   与改前只差一个 `self.` 前缀（可机检），也避免「外移顺手改写」。
_extract_multiple_asins = ResearchHelpersMixin._extract_multiple_asins


# ====== 意图标签（**唯一真源**）======

#: 「候选存量清点」意图标签。
#:
#: ★ 为什么单独命名而不是散落字面量：这个标签要在三处出现 —— 产出
#:   （`classify_intent`）、消费（`invoke` / `_stream_chat_impl`）、门禁（断言）。
#:   写三遍字面量 ⇒ 改一处漏两处；本仓既有教训正是
#:   「同一判定两份实现 ⇒ 至少一份永远测不到」。
QUERY_CANDIDATES_INTENT = "query_candidates"

#: 「选品大盘读口」意图标签（**唯一真源**，第 325 轮）。
#:
#: ★ 与 `QUERY_CANDIDATES_INTENT` 同款同因：这个标签要在三处出现 ——
#:   产出（`classify_intent`）、消费（`invoke` / `_stream_chat_impl`）、
#:   门禁（断言）。写三遍字面量 ⇒ 改一处漏两处。
#:
#: ★ 老板的原始投诉（第 324 轮截图）：「现在哪个品类蓝海分最高」→ Agent 答
#:   「未识别出具体类目，已按全类目高潜方向扫描，发现 8 个蓝海方向」+ 8 条候选
#:   商品 —— **它去挖蓝海了，压根没读大盘**（`market_snapshots` 里就存着蓝海评分）。
#:
#: ★ 为什么要一个标签而不是直接落 `general`：`general` 也能进工具路由（最终结果
#:   一样），但要的是**可观测** —— 老板问这句时，日志与进度文案里必须看得见
#:   「在读数」而不是「在挖矿」。标签是这条判定**唯一**的落点。
MARKET_INSIGHT_INTENT = "market_insight"


# ====== 工具路由子层的装配 ======

def build_router(
    *,
    agent_name: str,
    system_prompt: str,
    tools: List[Any],
    budget: Any,
    context_policy: Any,
    checkpointer: Any,
    checkpoint_ns: str,
) -> Any:
    """构建工具化路由层（BaseAgent 实例，注入 `product_research_tools` 全部工具）。

    原 `ProductResearchAgent._build_router`。

    ★ 为什么 `tools` / `checkpointer` / `budget` / `context_policy` / `checkpoint_ns`
      由调用方传而不是本模块自取：它们是**装配策略**（本 Agent 用哪张注册表、
      哪个 ns、哪档预算），属于「谁在用这层」的决定，不属于这层本身。
      `tests/test_agent_tool_wiring.py::test_router_sublayer_shape` 正是钉「`tools=`
      实参住在 `_build_router()` **体内**」——判据要的实证点是**装配点会被执行**，
      所以那一行必须留在 Agent 侧的薄壳里。

    ★ 为什么 `ENABLE_LLM` 总开关与「装配失败即降级」的 `try/except` **不住本模块**
      而住 Agent 侧薄壳：那是**本 Agent 的可用性策略**（开关关掉就整层不做、
      装配抛错就退化成无路由），不是「路由层怎么装配」。搬进来会多出一个
      恒为 True 的死参数，还会把 `logger.warning` 的归属从 `product_research`
      漂到 `product_research.routing`。
    """
    # ★ 2026-09-17：**子层也要绑 checkpointer** —— 主 Agent 传了
    #   session_id 也没有任何东西可被持久化（`interrupt()` 更是直接抛）。
    #   `checkpoint_ns` 把本 Agent 的会话与 secretary 隔开，避免同一个
    #   session_id 挤进同一段消息历史（见 BaseAgent.resolve_thread_id）。
    return BaseAgent(
        agent_name=f"{agent_name}_router",
        system_prompt=system_prompt,
        tools=tools,
        # ★ 第 145 轮 批 C5：裸数字 → 具名档位（同 listing 路由子层）。
        budget=budget,
        # ★ 第 147 轮 批 C4：上下文档位与预算档位**同档**（ROUTER）。
        #   路由子层「单次决策 + 一串工具调用、用完即答」⇒ 历史最短、裁得最狠
        #   （12k / 保底 2 轮），与 `checkpoint_ns="product_research"` 同一层。
        context_policy=context_policy,
        checkpointer=checkpointer,
        checkpoint_ns=checkpoint_ns,
        # ★★★ 第 131 轮：`save_candidate` 是全仓**唯一**「有外部副作用
        #   （真写 PG：`candidates/service.create_candidate`）+ 真被生产
        #   代码装配」的 agent 工具 ⇒ 它是 HITL 的首选、也是唯一目标。
        #   （全仓 8 个工具注册表里，写库的只有它 —— 其余全是只读；
        #    `create_ticket` 所在注册表的生产装配点数是 0（悬空）——
        #    ★ 第 143 轮 A4 起 `create_ticket` 已**真落库**（cs_tickets 表），
        #    所以它落选的理由是「注册表悬空」而**不是**「零副作用」，
        #    两者不要混为一谈。见 probe `out-r131-a2-toolmatrix.txt`。
        #    ★ 第 207 轮：原举例 `track_batch_asins` 已退役，改为不举例。）
        #   为什么必须有上面那两行：`interrupt()` 在**没有 checkpointer 的
        #   图上直接抛**，不是「降级为不审批」⇒ HITL 与 checkpointer 是
        #   **同一个前提**。`checkpoint_ns` 再把本 Agent 的会话与
        #   secretary 隔开（见 `BaseAgent.resolve_thread_id`）。
        #
        # ★★★ 第 145 轮 批 B2：**删掉了手写的 `hitl_tools=["save_candidate"]`**。
        #   审批名单从此由 `ai_infra.tools.side_effects` 的副作用策略
        #   自动推导（见 `BaseAgent._wrap_hitl_tools`）—— 本模块的
        #   职责是「装配哪张注册表」，不是「哪个工具危险」。
        #   行为不变：`product_research_tools` 里只有 `save_candidate`
        #   不在只读豁免名单内（第 325 轮新增的 `query_market_insight`
        #   声明的是 `READ_ONLY_METADATA`）⇒ 推导结果仍是
        #   `{"save_candidate"}`（由 `test_hitl_wiring.py` 钉住）。
        #   为什么必须删而不是留：留着就等于留了**第二份真源**，
        #   而两份真源迟早会漂移 —— 那时「策略表里是 A、Agent 里是 B」
        #   会让审批范围变成一个没人能说清的东西。
    )


# ====== 工具结果解析 ======

# 工具名 → display_type（对齐 `_process_query` 的 type 语义）
TOOL_TYPE_MAP = {
    "analyze_blue_ocean": "blue_ocean_analysis",
    "analyze_profit": "profit_analysis",
    "analyze_pain_points": "pain_point_analysis",
    "compare_competitors": "competitor_analysis",
    "save_candidate": "candidate_saved",
}


def parse_tool_output(tool_name: str, tool_result) -> Optional[dict]:
    """
    工具返回的 JSON 文本 → 带 `type` 的 dict（解析不出来返回 None）。

    抽出来给非流式（`route_via_tools`）与流式（`_stream_via_tools`）共用 ——
    两条路径对同一份工具输出必须给出同一种 type 语义。
    """
    if not tool_result:
        return None
    try:
        data = json.loads(tool_result)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    return {**data, "type": TOOL_TYPE_MAP.get(tool_name, "analysis")}


# ====== 有副作用意图的审批入口（非流式 / 流式，逐字同源）======

# 审批通道不可用时的统一拒绝文案（两个入口共用，避免「同一件事两种说法」）
APPROVAL_CHANNEL_DOWN_MSG = (
    "入库是写操作，需要人工确认后才能执行；但审批通道当前不可用，"
    "这次**没有写入**。请稍后重试。"
)

# 缺目标店铺时的统一拒绝文案。★ 非流式与流式入口**必须逐字同源** ——
# 同一句话在两条路径上说不同的话，是本仓反复踩过的那类缺陷。
NO_SHOP_SELECTED_MSG = (
    "入库需要有目标店铺，但当前没有选择店铺，这次**没有写入**。"
    "请先在界面左上角选一个店铺，再说一次「把……加进选品库」。"
)


async def route_gated_intent(
    query: str,
    context_id: Optional[str],
    user_id: Optional[str],
    shop_id: Optional[str] = None,
    *,
    get_router: Callable[[], Any],
    route_via_tools: Callable[..., Awaitable[Optional[AgentResponse]]],
) -> AgentResponse:
    """
    把「有副作用」的意图送进**带 HITL 审批的**工具路径（非流式入口）。

    ★ 为什么不让关键词命中的入库直接 `_save_candidate()`：
      那样「说一句『加进选品库』」= 零审批直写；而同一件事若由 LLM 判定
      入库 = 要审批 ⇒ **同一个操作两套规矩**，且被绕过的那条恰好是最高频的
      表达（`save_keywords` 里就含「入库」）。审批闸门等于形同虚设。
    ★ 为什么审批通道不可用时**拒绝写入**、而不是降级直写：
      与 `core.auth.accounts.filter_accessible_stores` 同一条原则 ——
      「没有身份 ⇒ 没有数据」。这里是「**没有审批通道 ⇒ 不执行有副作用的
      操作**」。降级直写意味着「基础设施一抖，审批就自动失效」，
      比拒绝危险得多。
    """
    # ★★ 缺店铺 ⇒ **立刻**给可读原因、零 DB 往返。
    #   为什么提前到入口，而不是复用 `_write_candidates` 的硬拒绝：
    #   此处意图**已确定为写**，不存在「只读意图被误伤」的顾虑
    #   （`chat` 之所以用豁免版依赖，正是为了不误伤只读意图）；
    #   而等到审批走完再报「没选店铺」，等于让用户白点一次批准，
    #   失败还被推迟到看不见的地方。与写路径同一条原则，只是提前。
    #   ★ 两条路径必须**逐字同源**：同一句话在流式/非流式上要说同一件事。
    if not (shop_id or "").strip():
        return AgentResponse(
            content=NO_SHOP_SELECTED_MSG,
            data={
                "type": "candidate_save_failed",
                "error": "no_shop_selected",
            },
            display_type="text",
        )

    if get_router() is not None:
        result = await route_via_tools(query, context_id, user_id)
        # ★★★ 「走了审批闸门」的判据是**拿到结构化结果**：
        #   中断态 pending 带 `data.type == "pending_approval"`，
        #   工具结果带自己的 type。两者都非 None。
        #   纯文本（`data is None`）意味着**目标工具根本没被调用** ——
        #   LLM 没选它、或 LLM 不可用 —— 这一步压根没到闸门前。
        #   把它当答案返回，用户会以为入库已完成，实际什么都没发生
        #   （实测：LLM 离线时回一句泛泛闲聊，入库静默消失）。
        #   fail-closed：说不清有没有执行，就明确说「这次没有写入」。
        if result is not None and result.data is not None:
            return result
    return AgentResponse(
        content=APPROVAL_CHANNEL_DOWN_MSG,
        data={
            "type": "candidate_save_failed",
            "error": "approval_channel_unavailable",
        },
        display_type="text",
    )


async def stream_gated_intent(
    query: str,
    context_id: Optional[str],
    user_id: Optional[str],
    shop_id: Optional[str] = None,
    *,
    get_router: Callable[[], Any],
    stream_via_tools: Callable[..., AsyncIterable],
) -> AsyncIterable:
    """有副作用意图的**流式**入口：同 `route_gated_intent`，理由见其 docstring。"""
    if not (shop_id or "").strip():
        # 与非流式 `route_gated_intent` 的文案**逐字相同**：两条路径说同一件事
        yield NO_SHOP_SELECTED_MSG
        return
    if get_router() is None:
        yield APPROVAL_CHANNEL_DOWN_MSG
        return
    async for chunk in stream_via_tools(
        query, context_id, user_id, gated=True
    ):
        yield chunk


# ====== 非流式工具路由 ======

async def route_via_tools(
    query: str,
    context_id: Optional[str] = None,
    user_id: Optional[str] = None,
    *,
    router: Any,
    detect_pending: Callable[..., Awaitable[Optional[AgentResponse]]],
    compose_reply: Callable[[dict], str],
) -> Optional[AgentResponse]:
    """工具化路由：LLM 自主选工具执行，把工具结果包装回 AgentResponse。

    返回 None 表示路由失败，调用方继续兜底。
    """
    try:
        # ★ 2026-09-17：改走统一入口。旧键 `...-{context_id or id(self)}`
        #   的 `id(self)` 是**对象内存地址** ⇒ 没有 context_id 时换个进程
        #   就换 thread_id，永远命中不到上一轮的 checkpoint。
        state = await router.run_session(
            {"messages": [HumanMessage(content=query)]},
            session_id=context_id,
            user_id=user_id,
        )

        # ★★★ 第 131 轮 item2-B：有副作用工具的 HITL 中断必须**立刻回传**，
        #   而不是继续按「这轮没调到工具」往下解析 —— 图此刻停在 tool_node 上，
        #   消息里**根本没有 ToolMessage**，继续走会一路落到 `return None`
        #   ⇒ 调用方退化到闲聊兜底 ⇒ 用户收到一句无关的回复，
        #   **完全不知道有个操作正卡在等他审批**（审批卡永远出不来）。
        pending = await detect_pending(context_id, user_id)
        if pending is not None:
            return pending

        # ★ 第 159 轮 批 D1：**优先读结构化摘要**（由 `_respond_node` 产出），
        #   不再一上来就扫整段 `messages`。此前这段解析让父层对**历史形态**
        #   （消息顺序 / 类型 / 条数）产生硬依赖 —— 换个图或改一次裁剪就静默错位。
        activity = (state.get("structured_response") or {}).get("activity") or {}
        if activity:
            tool_name = (activity.get("tool_calls") or [""])[-1]
            tool_result = activity.get("tool_result")
            final_reply = activity.get("reply") or ""
        else:
            # 回退：摘要缺失时（自定义图 / 旧 checkpoint 恢复）仍按老路径扫历史。
            # **安全失败方向**：宁可多扫一次，也不要让工具名静默变空。
            messages = state.get("messages", [])
            tool_result = None
            tool_name = ""
            final_reply = ""
            for m in messages:
                if isinstance(m, AIMessage):
                    if getattr(m, "tool_calls", None):
                        for tc in m.tool_calls:
                            if tc.get("name"):
                                tool_name = tc["name"]
                    if m.content:
                        final_reply = m.content
                elif isinstance(m, ToolMessage):
                    tool_result = m.content

        data = parse_tool_output(tool_name, tool_result)
        if data is not None:
            return AgentResponse(
                # 同样不裸吐 JSON：优先 LLM 归纳的 final_reply，
                # 否则用 summary / error 压成人话（见 _compose_reply）
                content=final_reply or compose_reply(data),
                data=data,
                display_type=data.get("type", "analysis"),
            )

        if final_reply:
            return AgentResponse(content=final_reply, data=None, display_type="text")

        return None
    except Exception as e:
        logger.warning(f"[product_research] tool routing failed: {e}")
        return None


# ====== 意图分类 ======

#: 意图路由表（**策略数据**留业务模块；控制流见 `ai_infra.intent.first_match`）。
#: ★ 顺序即优先级，而**顺序本身承载一条实测教训**：`save_candidate` 必须排在
#:   `blue_ocean` 之前 —— 「选品库」里含「选品」，而「选品」是 `blue_ocean` 的
#:   关键词；顺序一换，「帮我进入选品库」会被判成 blue_ocean、把挖掘重跑一遍。
#: ★ 「入库」这类**口语说法**必须留在关键词里：漏它 = 最高频的表达判成 general，
#:   商品名于是被裸丢给 LLM 闲聊（实测编出一大段套话）。
#: ★ 第 223 轮**裸词体检**：63 个词逐个过了一遍，动了 4 处，逐条记明理由 ——
#:   ① 删 `blue_ocean` 的裸「选品」= **本轮 bug 的病根**。「选品」在本产品里
#:      的领域义是**候选选品这个存量对象**（「有多少选品」「列一下我的选品」），
#:      却排在 `blue_ocean` 里；`save_candidate` 组一个裸「选品」都没有
#:      ⇒ 清点问句在第一组零命中、被第二组吞掉，直接开挖（老板看到的是
#:      8 个蓝海候选 + 「要入库直接说把第 1 个加进选品库」）。
#:   ② 删 `blue_ocean` 的裸「机会」—— 泛名词（「我这个品还有机会吗」）。
#:      代价不对称：删掉后「有什么机会」落**工具路由**、由 LLM 调
#:      `analyze_blue_ocean` 仍答对；留着则同类误判**没有任何补救路径**
#:      （短路发生在 LLM 被调用之前）。
#:   ③ 删 `pain_points` 的裸「问题」—— 全表最宽的万能名词（实测
#:      「我的店铺有什么问题」被判成痛点分析 ⇒ 反问要 ASIN）。本组
#:      「痛点 / 差评 / 不满意 / 抱怨」四个区分性词已足够。
#:   ④ `"FBA"` / `"ROI"` → 小写。**这是一处有意的行为变更**，不是顺手改：
#:      查询串在 `first_match` 里被 `lower()` ⇒ 含大写的关键词**永不命中**
#:      （实测「fba 费用怎么算」判成 general）。收敛期刻意原样保留过，本轮
#:      体检把它定性为**声明承诺型假门禁**（写了词、从不生效）⇒ 修。
#:      受影响面**仅一种**：含 fba / roi 的问句由 general 变 profit。
#:   ★ 未动的裸词（品类 / 评论 / 入库 / 利润 / 对比…）逐条登记在
#:     `tests/test_product_research_intent_inventory.py` 的处置表里 ——
#:     新增裸词必须在表里同步登记，否则门禁报红。
INTENT_ROUTES = (
    Route("save_candidate", ("选品库", "候选库", "候选池", "入库",
                             "加入候选", "加入选品", "添加到选品", "加到选品",
                             "保存到选品", "存入选品", "加进选品", "存进选品")),
    Route("blue_ocean", ("蓝海", "挖掘", "品类", "趋势", "什么好卖",
                         "好卖", "好销", "热销", "热门", "爆款", "比较火", "很火",
                         "火爆", "有市场", "值得做", "潜力", "好做", "能做吗",
                         "有前途", "冷门")),
    Route("profit", ("利润", "费用", "fba", "成本", "roi", "售价", "定价", "赚钱")),
    Route("pain_points", ("痛点", "差评", "评论", "不满意", "抱怨")),
    # ★ 绝不能收裸 "比较"：中文里 "比较" 绝大多数是**副词**（比较好卖 / 比较火），
    #   只有带被比较对象时才是「对比」语义。收裸 "比较" 会让
    #   「现在有哪些比较火的产品」被判成竞品对比（实测 bug）。
    Route("competitor", ("对比", "竞品", "竞争对手", "比较一下", "比较下", "比较两",
                         "比较这", "哪个更好", "哪个好", "哪款好", "买哪个",
                         "选哪个", "vs", "versus", "analysis")),
)


async def classify_intent(query: str) -> str:
    """分类用户意图（兜底 `general`；控制流见 `ai_infra.intent.first_match`）。

    Returns:
        blue_ocean / profit / pain_points / competitor / save_candidate /
        query_candidates / general
    """
    # ★ 非关键词的**前置信号**：「≥2 个 ASIN」比关键词可靠，优先判定。
    #   它不属于「关键词路由」这一机制，因此留在业务侧、在机制**之前**执行。
    if len(_extract_multiple_asins(query)) >= 2:
        return "competitor"
    # ★ 第二条前置信号：候选存量清点（与上一条同款形态 —— 都不是关键词命中，
    #   而是**看句子形态**就能定的判定）。排在 `first_match` **之前**是关键：
    #   收进 `INTENT_ROUTES` 会排在 `save_candidate` 之后而永远轮不到
    #   （「选品库里现在有多少条」里含「选品库」）。
    # ★ 第三条前置信号：选品大盘问句（第 325 轮 —— 老板「现在哪个品类蓝海分
    #   最高」被「品类」吞去挖蓝海了）。与上两条同款形态：看句子里的
    #   **量纲 + 诉求**就能定，不靠关键词命中。排在 `first_match` **之前**是关键：
    #   「品类」在 `blue_ocean` 组里，排到后面就永远轮不到它。
    if is_market_insight_query(query):
        return MARKET_INSIGHT_INTENT
    if is_candidate_query(query):
        return QUERY_CANDIDATES_INTENT
    return first_match(query, INTENT_ROUTES, "general")


#: 「候选存量清点」前置判定的**左门**：指向「候选选品库这个对象」的词。
#: ★ 只收**对象词**，不收指向挖掘方向的词（品类 / 趋势 / 热门…）——
#:   后者是真蓝海问句的载体（「有什么冷门品类」「比较火的品类有哪些」）。
CANDIDATE_QUERY_DOMAIN = ("选品", "候选")

#: 「候选存量清点」前置判定的**右门**：表达「清点 / 列举」诉求的词。
CANDIDATE_QUERY_COUNT = ("多少", "几个", "几条", "几件", "几款",
                         "有哪些", "列表", "列一下", "列下", "列出来", "列出",
                         "看看", "看下", "查看", "都有啥", "都有什么",
                         "统计", "盘点", "清点", "总共", "一共")


def is_candidate_query(query: str) -> bool:
    """是不是「候选存量清点」问句（**与门**：域对象词 AND 清点诉求词）。

    ★ 为什么必须**两条同时成立**：只按「选品 / 候选」判，会把
      「帮我选个男装品类的机会」也吞掉（既有门禁
      `test_pure_discovery_still_routes_to_blue_ocean` 钉死了它应为 blue_ocean）；
      只按「多少 / 有哪些」判，会把「现在有哪些比较火的产品」吞掉
      （`test_adverb_bijiao_is_not_competitor` 的用例）。
    ★ 为什么命中后**不短路**：这不是一个独立的业务分析动作，而是一个
      **读库问题** —— 交工具路由由 LLM 调 `list_candidates` 作答
      （能答「按评审状态筛」「销量前 3」这类关键词表答不了的问法）。
      关键词表在这里只承担「别把它送进 `_process_query`」这一个作用。
    ★ 为什么**不新增第二份读库实现**：`list_candidates` 已是跨 Agent 共用的
      唯一实现（`modules/library/tools.py` → `modules.candidates.service`），
      且已返回**真实** `total` ⇒ 本判定只做路由，不碰数据。
    """
    q = (query or "").lower()
    domain_hit = any(w in q for w in CANDIDATE_QUERY_DOMAIN)
    count_hit = any(w in q for w in CANDIDATE_QUERY_COUNT)
    return domain_hit and count_hit


#: 选品大盘前置判定的**左门**：大盘**量纲词**（= 面板上真有数据的那些列）。
#: ★ 只收「类目级大盘才有的量纲」。**不**试图区分「这个产品的搜索量」这种
#:   同词不同对象的问法 —— 那不是本判定的职责（LLM 会判），而且误判的代价
#:   只是换个标签：`MARKET_INSIGHT_INTENT` **不在** `INTENT_SHORTCUTS` 里，
#:   两个入口都落到同一条工具路由（唯一可观察差异是流式多一句进度文案）。
MARKET_INSIGHT_METRICS = (
    "蓝海评分", "蓝海分", "蓝海得分",
    "搜索量", "搜索热度", "搜索增长",
    "价格带", "价格中位数", "价格趋势",
    "卖家数", "新卖家数", "竞争度",
)

#: 右门：**排行 / 清点诉求**词。左边给量纲、右边给动作，缺一不可
#: （同 `CANDIDATE_QUERY_*` 的与门形态与理由）。
MARKET_INSIGHT_RANK = (
    "最高", "最低", "最多", "最少", "最大", "最小", "最强",
    "排名", "排行", "前几", "top",
    "哪个", "哪些", "有没有", "是什么",
    "多少", "几个", "几条",
)


def is_market_insight_query(query: str) -> bool:
    """是不是「读选品大盘」问句（**与门**：量纲词 AND 排行/清点诉求词）。

    ★ 这条判定**不是**「识别大盘问句」（那是 LLM 的活），它只干一件事：
      **不让关键词短路把大盘问句吞掉**。因此它可以写得很窄 —— 没被它拦下的
      大盘问句落 `general` ⇒ **仍然**进工具路由 ⇒ LLM 照样能调
      `query_market_insight`（第 325 轮新增）。
      代价不对称因此成立：漏判 = 与现状相同；误判 = 也只是换个标签。
    ★ 与 `CANDIDATE_QUERY_*` 同款：这两组词**不进** `BARE_WORD_VERDICTS`
      —— 它们不是「关键词路由」，而是**与门的一半**，单独一个词永不命中
      （裸词处置表管的是「一个词就能把问句抢走」的那一类）。
    """
    q = (query or "").lower()
    metric_hit = any(w in q for w in MARKET_INSIGHT_METRICS)
    rank_hit = any(w in q for w in MARKET_INSIGHT_RANK)
    return metric_hit and rank_hit


# ====== 点名商品的实词 token ======

# 英文「动作/指令」词：出现它们**不代表**用户点名了商品。
# 若不过滤，「add this to candidate library」会被判成「点名了商品但池里没匹配上」→ 误追问。
SAVE_ACTION_WORDS = {
    "add", "save", "insert", "put", "into", "to", "my", "this", "that", "it",
    "please", "candidate", "candidates", "library", "pool", "list", "collection",
    "item", "items", "product", "products", "cart", "wishlist", "new",
}


def named_tokens(query: str) -> List[str]:
    """
    查询里用于「点名商品」的实词 token。

    `tokenize` 以非字母数字切分 → 中文（「帮我加进选品库」「这个品」「第 2 个」）
    自然落空，只剩英文实词；再滤掉英文动作词（add / candidate / library …）。
    因此返回非空 == 用户**点名了某个商品**，空 == 纯指代或纯中文指令。
    """
    from platforms.amazon.client import tokenize

    return [t for t in tokenize(query) if t not in SAVE_ACTION_WORDS]


# ★ 保留给 __all__ 的显式清单：本模块是**门面**，外部（含门禁）按名字取。
__all__ = [
    "APPROVAL_CHANNEL_DOWN_MSG",
    "CANDIDATE_QUERY_COUNT",
    "CANDIDATE_QUERY_DOMAIN",
    "INTENT_ROUTES",
    "MARKET_INSIGHT_INTENT",
    "MARKET_INSIGHT_METRICS",
    "MARKET_INSIGHT_RANK",
    "NO_SHOP_SELECTED_MSG",
    "QUERY_CANDIDATES_INTENT",
    "SAVE_ACTION_WORDS",
    "TOOL_TYPE_MAP",
    "build_router",
    "classify_intent",
    "is_candidate_query",
    "is_market_insight_query",
    "named_tokens",
    "parse_tool_output",
    "route_gated_intent",
    "route_via_tools",
    "stream_gated_intent",
]
