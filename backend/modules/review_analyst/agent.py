"""运营复盘师 Agent（第 166 轮 · `#726` 第 2 条补齐）。

★ 为什么这个文件此前不存在、现在必须有
--------------------------------------
实测（AST / 运行时对账，不是读文档猜的）：

  · 8 个业务 Agent 里 7 个有 chat 端点，**只有 `review_analyst` 的 router 没有**
    （对账 `modules/*/router.py` 的 `@router.post("...chat...")`）；
  · `review_analyst_tools` 的 6 个工具全仓**零装配**（悬空），由
    `tests/test_tool_registry_guard.py::test_orphan_registry_ratchet` 钉着；
  · 前端 `useChatOrchestrator.ts` 里有一条 review-analyst **专用 mock 分支**，
★ 第 167 轮（#725）现状更新：本条所述 mock 分支**已不存在** —— `@/mock/reviewDashboard` 已删除，前端改调 `POST /review/chat`；右侧看板的图位也从内联常量换成了后端真源。
    而 `mock/reviewDashboard.ts` 的注释写着「真实上线替换为后端 review-analyst
    Agent 生成」；
  · `secretary` 的系统提示词已经把「复盘/周报/月报/经营大盘/业绩/报表」指向
    `review-analyst` 这个 handoff 目标 —— 目标背后却没有 Agent。

⇒ 缺的不是「一个文件」，而是一条**真通道**：前端在等、工具在悬空、handoff 目标空着。

★ 两件事必须做对，否则补了也是假的
-----------------------------------
1. **`store_id` 只能服务端注入**。6 个工具原来把 `store_id: str` 写在**对 LLM
   可见的入参**里 —— 那是「客户端可控」的同一个坑（LLM 会照着自己编一个，
   而它编出来的值恰好可能是别的店铺）。本文件用 ContextVar `_current_shop_id`
   在**入口处**写入已校验归属的值，`tools.py` 读回（范式同
   `product_research._current_shop_id`）。
2. **没有店铺就硬拒绝**。6 项能力都按 `store_id` 取数；缺它时 Mock 数据源对
   任意 store_id 都返回同一批数据 ⇒ 老板会拿到一份**看起来正常、其实不知属于谁**
   的报告。那是归因错误，比一句可行动的「请先选店铺」糟得多
   （`router.py` 的 docstring 已就同一问题选过 strict 守卫这一边）。

★ 本 Agent **不做计算**：数字一律来自 `service`（确定性汇总）。
  LLM 只负责「选对工具」+「把结果复述成人话」，见 `prompts.py` 的硬约束 1/2。
"""
from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any, Dict, Optional

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent
from ai_infra.budget import BUDGET_ROUTER
from ai_infra.context import CONTEXT_ROUTER
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
from core.logger import get_logger

from . import service
from .prompts import REVIEW_ANALYST_PROMPT
from .schemas import (
    InventoryHealthRequest,
    MonthlyReviewRequest,
    ProductPerformanceRequest,
    ProfitAuditRequest,
    ReviewChatResult,
    WeeklyReportRequest,
)

logger = get_logger(__name__)

#: 服务端注入的店铺归属（**不入 LLM 可见入参**）。只由本模块入口写入，工具侧读回。
_current_shop_id: ContextVar[Optional[str]] = ContextVar("review_current_shop_id", default=None)

#: 会话 ID（同上：工具入参由 LLM 生成，塞不进去）。
_current_context_id: ContextVar[Optional[str]] = ContextVar(
    "review_current_context_id", default=None
)

#: 复盘报告的会话结论卡类型（前端 `results/conversation/registry.ts` 按它查表）。
#:
#: ★ 为什么必须有这个名字：报告是**结构化**的（metrics / insights / actions），
#:   而 `display_type="text"` 会被前端当成普通文本 —— 结构化载荷照样下发、
#:   界面上却一点看不出来。这类"数据传到了但没人接"的形态本仓咬过多次
#:   （判据：新增结构化产物必须同时给出**消费点**）。
REVIEW_REPORT_DISPLAY_TYPE = "review_report"

#: 5 个工具名（= 前端 `toolDefinitions.ts` 里 review-analyst 的 5 张卡）
_TOOL_NAMES = (
    "weekly_report",
    "monthly_review",
    "product_performance",
    "inventory_health",
    "profit_audit",
)

#: 第一级：**显式报表类型名** —— 用户明确点名「要看哪一份报表」时走的层。
#:
#: ★ 为什么必须与下一级分开 —— 第 265 轮实测的缺陷：
#:   原表把「周报」与「利润 / 广告 / 库存 / sku」等**正文里的业务指标词**混在
#:   **同一条链**里按固定顺序判，而 `weekly_report` 排在**末位** ⇒ 正文只要出现
#:   任一指组词，点名的「周报」就永远轮不到。实测 `周报里利润是多少` 判成了
#:   `profit_audit` ⇒ 老板收到的是一份「利润审计」（点归档也按 profit_audit 落库）。
#:
#: ★ 两级的语义不是「谁更重要」，而是「**产物名** vs **正文里散落的业务对象词**」：
#:   前者是对「要哪张表」的显式指定，后者只是他在描述「关心什么」。显式指定先被看见。
#:
#: ★ 本级的每个词都**包含原表已有、且指向同一组的业务词**（如「利润审计」⊃「利润」），
#:   所以逐条看判定结果与原表**完全一致** —— 变的只有「与别组业务词共存时谁胜」。
_EXPLICIT_TYPE_ROUTES = (
    Route("monthly_review", ("月报", "月度复盘")),
    Route("product_performance", ("商品表现",)),
    Route("inventory_health", ("库存健康",)),
    Route("profit_audit", ("利润审计",)),
    Route("weekly_report", ("周报", "经营大盘", "业绩概览")),
)

#: 第二级：**正文里的业务指标词**（没点名报表，只在描述关心什么）。
#: 顺序即优先级。关键词**原样比较**（`first_match` 只小写化查询）⇒ 英文词必须小写。
#: ★ 第一级已拿走「周报 / 月报 / 商品表现」等类型名，这里只剩业务词 —— 组的顺序与
#:   余下的关键词**逐字保持原样**，所以「没点名类型名」的查询行为与改造前一致。
_INTENT_ROUTES = (
    Route("monthly_review", ("月度", "本月", "monthly")),
    Route(
        "product_performance",
        ("sku", "哪个品", "卖得好", "滞销", "爆款", "排名", "bsr"),
    ),
    Route("inventory_health", ("库存", "断货", "补货", "周转", "积压")),
    Route("profit_audit", ("利润", "净利润", "毛利", "成本结构", "赚了多少", "赚钱")),
    Route("weekly_report", ("本周", "概览", "复盘")),
)

#: 意图标签 → (service 函数, 请求模型, 默认周期天数)
_SERVICE_CALLS: Dict[str, tuple] = {
    "weekly_report": (service.weekly_report, WeeklyReportRequest, 7),
    "monthly_review": (service.monthly_review, MonthlyReviewRequest, 30),
    "product_performance": (service.product_performance, ProductPerformanceRequest, 7),
    "inventory_health": (service.inventory_health, InventoryHealthRequest, 7),
    "profit_audit": (service.profit_audit, ProfitAuditRequest, 30),
}

#: 缺店铺归属时的拒绝文案（**必须可行动**：说清「怎么办」，而不是说一句实现细节）。
_MISSING_SHOP_REPLY = (
    "复盘需要有店铺归属：请先在界面左上角选一个店铺，再说一次。\n\n"
    "（5 项复盘能力都按店铺取数；缺归属时数据源对任意店铺都返回同一批数据，"
    "那会给你一份看起来正常、其实不知属于谁的报表 —— 所以这里直接拒绝，"
    "而不是拿它凑一份出来。）"
)

#: 关键词没命中、也没有可用工具路由时的引导语。
#: ★ 不说「我正在为您分析」——那会让老板以为后台真在跑（本仓第 166 轮 `#732`
#:   刚把「静默空壳」清过一遍，这类无信息的占位文案是同一个病）。
_GUIDE_REPLY = (
    "可以，不过我需要知道你这次想看哪一项。可选：\n"
    "1. 经营概览（周报）2. 月度复盘 3. 商品表现 4. 库存健康 5. 利润审计\n"
    "（直接说「本周周报」「库存健康怎么样」「哪些品滞销」这样就行。）"
)


class ReviewAnalystAgent(BaseAgent):
    """运营复盘师 Agent（工具路由 + 确定性复盘汇总）。"""

    DEFAULT_MODEL = "qwen-plus"
    ENABLE_LLM = True

    def __init__(self) -> None:
        # ★ 刻意**不**在这里装配 6 个工具：装配点是 `_build_router()`。
        #   理由是 `interrupt()` 的前提（checkpointer）与工具装配必须同处一行
        #   才算显式（见 `tests/test_hitl_policy.py::test_assembly_surface_three_counts_agree`
        #   的三数联判）。范式同 `listing_generator` / `product_research`。
        super().__init__(agent_name="review_analyst", system_prompt=REVIEW_ANALYST_PROMPT)
        self._router: Optional[BaseAgent] = None

    # ====== 入口 ======

    async def invoke(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> ReviewChatResult:
        """处理一次复盘对话。

        Args:
            query: 用户提问。
            context: 附加上下文（如右侧看板的 `days` / `asins`）。
            session_id: 会话 ID；非空时透传给路由子层当 checkpointer 的 thread_id
                ⇒ 同一会话的第二轮能看见第一轮。为空则**不留记忆**
                （不拿默认值兜底，避免跨用户串记忆）。
            user_id: 身份（透传）。
            shop_id: **已校验归属**的店铺 ID。必须由调用方（router 的 strict
                守卫）注入；为空 ⇒ 直接拒绝，不发起任何取数。

        Returns:
            `ReviewChatResult`。失败/降级一律带 `degraded=True` + `degraded_reason`。
        """
        shop = (shop_id or "").strip()
        if not shop:
            logger.warning("[review_analyst] 缺店铺归属 ⇒ 拒绝（fail-closed）")
            return ReviewChatResult(
                reply=_MISSING_SHOP_REPLY,
                degraded=True,
                degraded_reason="missing_shop_context",
            )

        tok_shop = _current_shop_id.set(shop)
        tok_ctx = _current_context_id.set(session_id or "")
        try:
            # ★★ 点名技能 ⇒ **禁用关键词短路**（第 246 轮 P0-a）：
            #   下面的 `_run_one` 直连 service，**不构造 system prompt**；
            #   而技能正文 / 技能目录 / `load_skill` 工具**全住在 system prompt
            #   里**（由 `BaseAgent` 的图构造）⇒ 一旦短路，用户点的技能一次都
            #   渲染不到，他会收到一份"别的报表"。让路给下面的工具路由 ——
            #   那条路真的构造 prompt。
            #   ★ 归一到 `general` 而不是提前 return：`general` 在下面那个
            #     `if` 里不命中 ⇒ 与「没点名且没命中关键词」走**同一条**路，
            #     短路分支一行没动（未点名时行为逐字不变）。
            intent = "general" if is_skill_requested() else await self._classify_intent(query)

            # ★★ 第 250 轮（遗留项 A）：**上一轮是追问 ⇒ 这一轮是「答案」，不是新任务**。
            #   工具环路的 LLM 信息不足时会反问（「你想基于哪一期？」），而老板的
            #   答案**必然带着追问里的关键词**（答「基于月报」就含「月报」）——
            #   这正是关键词短路的结构性死角：任何纯关键词判定都躲不开。
            #   ⇒ 先问一句「上一轮是不是追问」，是则**让路给工具环路**
            #     （它带着上一轮的问句，才判得准）。
            #   ⚠️ 必须拿**真正跑图的实例**来问：会话状态寄存在路由子层上，
            #      本实例自己没绑 checkpointer ⇒ 对它调恒得 False。
            #   ⚠️ 读不到（无会话 / 无身份 / 未绑 / 读失败）一律 False ⇒ 走原路，
            #      行为与改造前**逐字等价**（让路是新增行为，拿不到证据不引入）。
            router = None
            defer_to_tools = False
            if intent != "general" and session_id and user_id:
                router = self._get_router()
                if router is not None:
                    defer_to_tools = await router.last_turn_was_clarification(
                        session_id, user_id
                    )

            # 1. 关键词命中、且**不是在回答追问** ⇒ 直接跑那一项
            #    （省一次 LLM 往返，且结果确定）
            if intent != "general" and not defer_to_tools:
                direct = await self._run_one(intent, context)
                if direct is not None:
                    return direct

            # 2. 工具路由（未命中 / 点名 / **回答追问**）
            if router is None:
                router = self._get_router()
            if router is not None:
                routed = await self._route_via_tools(query, context, session_id, user_id)
                if routed is not None:
                    return routed

            # 2b. ★ 回答追问、但工具环路没接住 ⇒ **退回原关键词直连**。
            #     「不许比改造前更差」：改造前这条路本来就是直连，所以退回直连
            #     至少与改造前等价 —— 而不是把老板的答案变成一句引导语。
            if intent != "general" and defer_to_tools:
                direct = await self._run_one(intent, context)
                if direct is not None:
                    return direct

            # 3. 都不可用 ⇒ 引导（**不假装在分析**）
            #   ★ 点名技能时给的是「技能通道不可用」，而不是「请告诉我你想看
            #     哪一项」—— 后者会让点了卡的老板以为系统没收到他的选择。
            if is_skill_requested():
                return ReviewChatResult(
                    reply=SKILL_CHANNEL_UNAVAILABLE,
                    degraded=True,
                    degraded_reason="skill_channel_unavailable",
                )
            return ReviewChatResult(reply=_GUIDE_REPLY)
        finally:
            # ContextVar 是模块级共享：用完必须还原，否则污染同进程的其它调用
            _current_shop_id.reset(tok_shop)
            _current_context_id.reset(tok_ctx)

    # ====== 意图 ======

    async def _classify_intent(self, query: str) -> str:
        """分类意图：**两级判定** —— 先认显式报表类型名，未命中再认业务指标词。

        ★ 第 265 轮修复：单链里「周报」排在最末，正文一出现「利润」就永远轮不到它
          （实测 `周报里利润是多少` → `profit_audit`）。两级后显式点名先被看见；
          没点名时第二级的组顺序与关键词逐字不变 ⇒ 既有行为不变。
        ★ 兜底仍是 `general`（控制流见 `ai_infra.intent.first_match`）。
        ★ 保留 `async`：与其余 6 个业务 Agent 的分类器签名一致，
          调用方（含测试）统一 `await`。
        """
        explicit = first_match(query, _EXPLICIT_TYPE_ROUTES, "")
        if explicit:
            return explicit
        return first_match(query, _INTENT_ROUTES, "general")

    # ====== 工具路由子层 ======

    def _get_router(self):
        """懒加载工具化路由层，返回 None 表示不可用（回退到直连/引导）。"""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def _build_router(self):
        """构建工具化路由层（`BaseAgent` 实例，注入 5 个复盘工具）。

        LLM 不可用时返回 None，由调用方回退到关键词直连。
        """
        if not self.ENABLE_LLM:
            return None
        try:
            from core.checkpoint import get_checkpointer

            from .tools import review_analyst_tools

            # ★ 组合一个 `BaseAgent` 作为路由层，复用其 bind_tools + LangGraph 图。
            #   子层也必须绑 checkpointer：主层传了 session_id 也无处可持久化。
            #   `checkpoint_ns="review_analyst"` 与 secretary / listing / 选品隔离。
            return BaseAgent(
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.system_prompt,
                tools=review_analyst_tools,
                budget=BUDGET_ROUTER,
                context_policy=CONTEXT_ROUTER,
                checkpointer=get_checkpointer(),
                checkpoint_ns="review_analyst",
            )
        except Exception as e:  # pragma: no cover - 装配失败必须可观测，不静默
            logger.warning(f"[review_analyst] router build failed: {e}")
            return None

    async def _route_via_tools(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[ReviewChatResult]:
        """工具化路由：LLM 自主选工具执行，把工具结果包装回 `ReviewChatResult`。

        返回 None 表示路由失败，调用方回退。
        """
        try:
            prompt = query
            if context:
                try:
                    ctx_json = json.dumps(context, ensure_ascii=False)
                    if len(ctx_json) > 2000:
                        ctx_json = ctx_json[:2000] + "..."
                    prompt = f"{query}\n\n[上下文数据] {ctx_json}"
                except (TypeError, ValueError):
                    prompt = f"{query}\n\n[上下文键] {list(context.keys())}"

            state = await self._router.run_session(
                {"messages": [HumanMessage(content=prompt)]},
                session_id=session_id,
                user_id=user_id,
            )

            # ★ 优先读结构化摘要（由 `_respond_node` 产出）；缺失时才回退扫历史。
            #   安全失败方向：宁可多扫一次，也不要让工具名静默变空。
            activity = (state.get("structured_response") or {}).get("activity") or {}
            if activity:
                tool_name = (activity.get("tool_calls") or [""])[-1]
                tool_result = activity.get("tool_result")
                final_reply = activity.get("reply") or ""
            else:
                messages = state.get("messages", [])
                tool_result = None
                tool_name = ""
                final_reply = ""
                for m in messages:
                    if isinstance(m, AIMessage):
                        for tc in getattr(m, "tool_calls", None) or []:
                            if tc.get("name"):
                                tool_name = tc["name"]
                        if m.content:
                            final_reply = m.content
                    elif isinstance(m, ToolMessage):
                        tool_result = m.content

            if tool_result:
                try:
                    data = json.loads(tool_result)
                except (json.JSONDecodeError, TypeError):
                    data = None
                if isinstance(data, dict):
                    return self._wrap(tool_name, data, fallback_reply=final_reply)

            # 无工具结果但有最终回复 ⇒ 纯文本（模型可能只是在追问/澄清）
            if final_reply:
                return ReviewChatResult(reply=final_reply, display_type="text")

            return None
        except Exception as e:
            logger.warning(f"[review_analyst] tool routing failed: {e}")
            return None

    # ====== 直连（关键词命中）======

    async def _run_one(
        self, intent: str, context: Optional[Dict[str, Any]] = None
    ) -> Optional[ReviewChatResult]:
        """按意图直接调 service（不经过 LLM）。失败返回 None 交给路由兜底。"""
        entry = _SERVICE_CALLS.get(intent)
        if entry is None:
            return None
        fn, req_cls, default_days = entry
        kwargs: Dict[str, Any] = {}
        ctx = context or {}
        days = ctx.get("days")
        if isinstance(days, int):
            kwargs["days"] = max(1, min(90, days))
        else:
            kwargs["days"] = default_days
        if req_cls is ProductPerformanceRequest:
            asins = ctx.get("asins")
            if isinstance(asins, list) and asins:
                kwargs["asins"] = [str(a) for a in asins][:50]

        try:
            data = await fn(req_cls(**kwargs), _current_shop_id.get())
        except service.MissingShopContext as e:
            # 归属在入口已判过一次；这里兜的是「ContextVar 在异步边界被清掉」这类
            # 意外 —— 一样要说真因，不许换成「系统繁忙」。
            logger.warning(f"[review_analyst] service 拒了店铺归属: {e}")
            return ReviewChatResult(
                reply=_MISSING_SHOP_REPLY, degraded=True, degraded_reason="missing_shop_context"
            )
        except Exception as e:
            logger.warning(f"[review_analyst] {intent} 直连失败: {e}")
            return None
        return self._wrap(intent, data)

    # ====== 统一包装 ======

    def _wrap(
        self,
        tool_name: str,
        data: Any,
        fallback_reply: str = "",
    ) -> ReviewChatResult:
        """把复盘报告包装成对话结果。

        ★ 失败/降级**必须回写界面状态**（`degraded` + `degraded_reason`）：
          否则「拿不到数据」和「数据就是很差」在前端长得一模一样 ——
          本仓第 166 轮 `#732` 的核心教训。
        """
        label = tool_name if tool_name in _TOOL_NAMES else "review"
        if not isinstance(data, dict):
            return ReviewChatResult(
                reply="复盘已返回，但结果不是可解析的结构化数据。请稍后重试。",
                display_type="text",
                degraded=True,
                degraded_reason="unparsable_report",
            )
        if data.get("error"):
            return ReviewChatResult(
                reply=f"这一项复盘没跑出来：{data['error']}",
                display_type="text",
                data=data,
                degraded=True,
                degraded_reason="report_error",
            )
        summary = data.get("summary") or ""
        reply = fallback_reply or summary or "复盘已生成，明细见右侧看板。"
        # ★★ P2（第 246 轮）：**具名** display_type。
        #   改前这里恒为 `"text"` ⇒ 前端 `resolveConversationResult('text')`
        #   返回 null ⇒ 报告只能按纯文本渲染，`data` 里的 metrics / insights /
        #   actions **没有卡片承托**（结构化载荷白白下发）。
        #   ★ 只有成功档改名：上面两档降级（`report_error` / `unparsable_report`）
        #     没有可渲染的报告 —— 给它们挂卡等于把"没跑出来"画成一张结论卡。
        return ReviewChatResult(reply=reply, display_type=REVIEW_REPORT_DISPLAY_TYPE, data=data)


#: 模块级单例（无会话状态；会话状态在 checkpointer 里，不在实例上）
_agent: Optional[ReviewAnalystAgent] = None


def get_review_analyst_agent() -> ReviewAnalystAgent:
    """获取运营复盘师实例（进程内单例，构造很轻）。"""
    global _agent
    if _agent is None:
        _agent = ReviewAnalystAgent()
    return _agent
