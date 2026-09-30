"""
选品分析 Agent (Product Research Agent)

继承 BaseAgent 基类，实现跨境电商选品分析的核心能力。

功能模块：
1. 蓝海品类挖掘 - 发现高潜力低竞争的细分市场
2. 痛点机会识别 - 分析竞品评论提取用户痛点
3. SKU 利润计算 - FBA费用/定价策略/ROI分析
4. 竞品深度对比 - 多维度对比竞品优劣势
5. 季节性趋势 - 市场热度时间轴
6. 避坑指南 - 侵权风险/合规检查

设计来源：
- 推理循环：继承 ai_infra.base_agent.BaseAgent
- 工具调用：使用 platforms.amazon.AmazonAdapter 获取数据
- HITL 机制：关键操作（如导出报告）需人工审批

升级特性（Phase 8）：
- ✅ DashScope Qwen LLM 智能增强分析
- ✅ 自动降级到模拟响应
"""

import json
from typing import List, Dict, Any, Optional, AsyncIterable
from contextvars import ContextVar
from datetime import datetime

from pydantic import BaseModel, Field

from platforms import get_platform_adapter, PlatformType
from platforms.base import (
    ProductData,
    KeywordData,
    FeeStructure,
    ReviewData,
    CompetitorAnalysis,
)
from ai_infra.sse import ToolTrace, progress

from core.logger import get_logger

# ★ 本文件此前有 9 处 `logger.warning(...)`，但**从未定义 logger** ——
#   而它们全在 except 分支里，意味着「LLM/工具调用失败时本该降级」的路径
#   会自己抛 `NameError: name 'logger' is not defined`，把可恢复错误变成 500。
#   接上统一日志出口后，这些降级日志也会带上 request_id 落进日志文件。
logger = get_logger("product_research.agent")

# LLM 能力（可用性判据 / 降级 / RAG）已统一到唯一基类 BaseAgent：
# 继承它即同时获得「LangChain 图内核」与「DashScopeLLM 原语」两套 LLM 槽位。
from ai_infra.base_agent import BaseAgent
from ai_infra.budget import BUDGET_ROUTER
from ai_infra.context import CONTEXT_ROUTER
# ★ 第 145 轮批 C1：会话级状态的**容器机制**（脏追踪 + 有界缓存）——
#   它不认识数据库；落库那一半在 `modules/conversation`，两者在这里接起来。
from ai_infra.session_state import SessionStateRegistry
from ai_infra.intent import Route, first_match
from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE, is_skill_requested
# 业务提示词（原在 ai_infra/llm/dashscope_client.py）；import 即向基础设施层注册
from modules.product_research import prompts as _prompts  # noqa: F401
# 第 145 轮批 C1：会话级状态的**持久化出口** —— 走 conversation 门面
# （跨模块引用只允许 `from modules.B import <已声明出口>`，见
#   tests/test_module_facades.py）。
from modules.conversation import hydrate_state as _hydrate_session_state
from modules.conversation import persist_state as _persist_session_state

# P0-6 第二刀：**分析编排层**外移 —— 下方 `_analyze_*` 薄壳调用的 4 个 `analyze_*` 函数。
# 依赖（adapter / session / LLM 回调）由薄壳**显式传参**；逻辑体逐字搬走，改写处见
# `.workbuddy/probes/r336-p0-6b/ast_parity.py` 的 `ApplyPlan`（4 处，全部列明）。
from modules.product_research.agent_analyzers import (
    analyze_blue_ocean,
    analyze_competitors,
    analyze_pain_points,
    analyze_profit,
)
# P0-6 第一刀：领域纯逻辑层（类目映射 / 机会评分 / ASIN 解析 / 文案）外移。
# 主类继承 `ResearchHelpersMixin` 拿到这些方法 ⇒ `self._x` / `cls._x` 调用点零改动；
# 两个常量在此 re-export —— `tests/test_product_research_blue_ocean.py` 与
# `tests/test_product_research_intent_routing.py` 按**本模块路径**导入它们，
# 改测试的导入路径等于替第三方改契约，不做。
from modules.product_research.agent_helpers import (  # noqa: F401
    ResearchHelpersMixin,
    _ASIN_RE,
    _TRENDING_KEYWORDS,
)
# P0-6 第二刀：**数据结构层**外移。这 5 个名字在本模块继续可用（re-export）——
# 消费方是测试（`tests/test_hitl_approval_flow.py` 按本模块路径导入 `AgentResponse`）
# 与 `ResearchReport` 的字段标注；是**同一对象**，不是第二份定义。
from modules.product_research.agent_models import (  # noqa: F401
    AgentResponse,
    BlueOceanOpportunity,
    PainPointAnalysis,
    ProfitAnalysis,
    ResearchReport,
)


# 深层分层路由：子 Agent 的工具化路由层（bind_tools + LangGraph 图）。
# 深层分层路由：工具化路由层（bind_tools + LangGraph 图），以**组合**方式引入。
# 本类继承 BaseAgent 只为拿 LLM 原语；router 是本类内部一个独立的 BaseAgent 实例，
# 让「分析逻辑」与「工具编排」各归其位（而非让本类自己成为一张图）。
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
# ★ 第 131 轮 item2-B：resume 要把审批决策喂回被中断的图，必须用 `Command(resume=...)`
from langgraph.types import Command


# ====== 数据模型 ======
#
# 5 个模型（AgentResponse / BlueOceanOpportunity / ProfitAnalysis /
# PainPointAnalysis / ResearchReport）已外移到 `modules/product_research/agent_models.py`（P0-6 第二刀）。
# 它们是**跨层契约**，不该钉在 2375 行的 God Class 上；外移后 `agent_analyzers.py`
# 构造结果模型时不必反向 import 本文件（那会是个环）。
# 本模块仍能从这里取到全部 5 个名字 —— 见文件顶部的 re-export。


# ====== System Prompt ======
# ★ 第 283 轮：正文已归位到 `prompts.py`（注册表键 `"product_research_system"`）。
#   注意与 `"product_research"` 是**两份**：前者是 Agent 的固定人设，
#   后者带 `{market}` 变量，供具体子任务按需取用。


# 结构化意图 → 阶段进度文案（stream_chat 在耗时分析前发给前端，避免空转）
_INTENT_PROGRESS = {
    "blue_ocean": "正在挖掘蓝海品类数据…",
    "query_candidates": "正在清点候选库…",
    "profit": "正在测算利润空间…",
    "pain_points": "正在分析用户痛点…",
    "competitor": "正在对比竞品数据…",
    "save_candidate": "正在写入选品库…",
    "market_insight": "正在读取选品大盘…",
}

#: 「候选存量清点」意图标签（**唯一真源**）。
#:
#: ★ 为什么单独命名而不是散落字面量：这个标签要在三处出现 —— 产出
#:   （`_classify_intent`）、消费（`invoke` / `_stream_chat_impl`）、门禁（断言）。
#:   写三遍字面量 ⇒ 改一处漏两处；本仓既有教训正是
#:   「同一判定两份实现 ⇒ 至少一份永远测不到」。
QUERY_CANDIDATES_INTENT = "query_candidates"

#: 「选品大盘读口」意图标签（**唯一真源**，第 325 轮）。
#:
#: ★ 与 `QUERY_CANDIDATES_INTENT` 同款同因：这个标签要在三处出现 ——
#:   产出（`_classify_intent`）、消费（`invoke` / `_stream_chat_impl`）、
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

#: 命中即**短路**的意图（关键词层直接执行业务方法，LLM 不参与）。
#:
#: ★ 两个入口（`invoke` / `_stream_chat_impl`）**共用这一份名单**。
#:   改前 `invoke` 写的是 `if intent != "general"`、`_stream_chat_impl` 写的是
#:   一份显式元组 —— 同一规则两种表达，加一个新标签必然漂移
#:   （漂移后果：同一句话走流式开挖、走非流式清点，本仓 `_APPROVAL_GATED_INTENTS`
#:   的注释里记着同一类事故）。
#: ★ `save_candidate`（有副作用 ⇒ 必须经 HITL 审批）与 `query_candidates`
#:   （读库问题 ⇒ 必须交工具路由）**刻意不在其中**。
INTENT_SHORTCUTS = ("blue_ocean", "profit", "pain_points", "competitor")

#: 「**不短路**、但要给一句进度文案」的意图（两个入口共用，第 325 轮收拢）。
#:
#: ★ 与 `INTENT_SHORTCUTS` 同样只允许**一份表达**：改前 `_stream_chat_impl` 里
#:   写的是 `if intent == QUERY_CANDIDATES_INTENT:`（单个标签的散装判断），
#:   再加一个大盘标签就得复制第二行 —— 那正是「同一规则两份表达」的入口
#:   （漂移后果：同一句话走流式与大屏提示不同）。
#: ★ 这两个标签的共同点：**都是读库问题** ⇒ 不短路（交给工具路由的 LLM 决定
#:   调哪个工具、怎么筛），但都要先让老板看到「在读数」。
PROGRESS_ONLY_INTENTS = (QUERY_CANDIDATES_INTENT, MARKET_INSIGHT_INTENT)

# 当前会话 ID（ContextVar）。
#
# 用途：走 LLM 工具路由时，工具函数（tools.py）需要知道「这是哪个会话」——
# 工具的入参由 LLM 生成，塞不进 context_id，只能靠上下文传递。
# 不传的后果：工具里的 `_save_candidate` 落在 `_default` 会话，既看不到该会话的
# 蓝海结果（「把第 1 个入库」解析不出目标），也接不上待补槽位（多轮补齐断链）。
_current_context_id: ContextVar[Optional[str]] = ContextVar(
    "product_research_context_id", default=None
)

# 当前店铺 ID（ContextVar）。
#
# 用途：与 `_current_context_id` 同因 —— 走 LLM 工具路由时，工具函数的入参由
# LLM 生成，**塞不进 shop_id**，只能靠上下文传递。
#
# ★★★ 与旧写法的关键区别（P0 安全修复 2026-09-16）
#   修复前：写库路径直读 `core.tenant.middleware.tenant_context.shop_id`
#           （★ C4 2026-09-16：该符号已随账户侧收拢删除，此处仅为事故记录），
#           而那个值由 `TenantMiddleware` 用**未校验的原始 `X-Shop-ID` 头**
#           对每个请求写入 ⇒ 任何带有效 token 的用户改一下请求头，就能把候选
#           写进别人的选品库（探针 r84d 实测：落库 shop_id = 受害店铺，200）。
#   现在：本 ContextVar **只**由 `invoke` / `stream_chat` 写入，值来自 service
#           层显式传入的、**已过归属校验**的 shop_id（`get_current_shop_id*`）。
#           ⇒ 中间件不再碰业务上下文，注入通道被物理切断。
#
# ★ 并且 `_write_candidates` 在 shop_id 缺失时**硬拒绝写入**（不是写空分区），
#   所以"拿不到已校验的店铺"= 不落数据，而不是落到别人的分区。
_current_shop_id: ContextVar[Optional[str]] = ContextVar(
    "product_research_shop_id", default=None
)

# 当前**身份**（ContextVar）。
#
# 用途：会话级状态的**作用域**键里含 user_id（与 checkpointer 的 thread_id
# 同口径）。同一个 session_id 在两个身份下必须是两份状态 —— 否则「把第 1 个
# 加进选品库」可能拿别人的上一轮结果去解析指代。
#
# ★ 只由 `_bind_context()` 在入口写；**只读方**是 `_state_scope()`。
#   不接受「把 user_id 当参数传进来」的写法：两个真源必然分叉。
_current_user_id: ContextVar[Optional[str]] = ContextVar(
    "product_research_user_id", default=None
)

# 会话级状态的**默认作用域**（没有 context_id 时用它）。
#
# ★ 为什么这个字符串是常量而不是就地写的字面量：它同时出现在「取容器」
#   （`_session`）与「算落盘键」（`_state_key`）两处。两处各写一份字面量，
#   改名时漏一处就会让「有会话」与「无会话」两条路径撞进同一个容器 ——
#   而那种错误只在单会话场景下不显形。
_DEFAULT_STATE_SCOPE = "_default"


# 全类目高潜关键词 `_TRENDING_KEYWORDS` 与 ASIN 正则 `_ASIN_RE`
# 已随 P0-6 第一刀外移到 `modules/product_research/agent_helpers.py`；
# 本模块顶部 re-export 它们，既有的按路径导入继续可用。


# ====== 选品 Agent 实现 ======

# ★ P0-6 第一刀：纯解析 / 评分 / 文案层住 `ResearchHelpersMixin`
#   （`modules/product_research/agent_helpers.py`）。继承而不是复制：那 11 个
#   方法体里一个 `self` 都没有，本就不需要 Agent 实例。
class ProductResearchAgent(ResearchHelpersMixin, BaseAgent):
    """
    选品分析 Agent

    Phase 2: 独立实现核心功能（不依赖 BaseAgent 的 LLM 调用）
    Phase 3: 集成 BaseAgent 实现完整的 LangGraph 推理循环
    Phase 8: 接入 DashScope Qwen LLM 实现智能增强

    使用示例：
        agent = ProductResearchAgent()

        # 蓝海挖掘
        result = await agent.invoke("帮我找厨房用品类的蓝海机会")

        # 利润计算
        result = await agent.invoke("分析便携式咖啡研磨器的利润空间")
    """

    # LLM 配置
    DEFAULT_MODEL = "qwen-max"       # 分析任务用最强模型
    ENABLE_LLM = True
    FALLBACK_TO_MOCK = True

    def __init__(self, platform: str = "amazon"):
        """
        初始化选品 Agent

        Args:
            platform: 目标平台（默认 amazon）
        """
        # 初始化 LLM 基类
        super().__init__()

        self.platform = platform
        self.adapter = get_platform_adapter(platform)
        self.agent_name = "ProductResearcher"
        self.system_prompt = self.get_prompt_template("product_research_system")

        # 深层分层路由：工具化路由层（懒加载，避免 tools→service→agent 循环导入）
        self._router = None

        # 会话级状态（key = context_id），见下方 `_session()`：
        #   last_blue_ocean —— 最近一次蓝海结果，供「第 1 个」「这个品」这类指代解析
        #   pending_save    —— 入库槽位填充进行中（必填项没补齐）时，记录待补内容
        #
        # ⚠️ 必须按会话隔离。service 层持有的是**全局单例** Agent，早先把状态直接
        # 挂在实例上（`self._last_blue_ocean`）→ A 会话挖完蓝海，B 会话说
        # 「把第 1 个加进选品库」会存进 A 的商品，**跨会话串数据**。
        #
        # ★ 第 145 轮批 C1：从一个普通 dict 换成**有界 + 脏追踪**的注册表。
        #   前者有两个洞：键只增不减（长跑进程持续吃内存）、且完全活在进程里
        #   （多 worker 不可见、重启即丢）。现在这里当**内存视图**，持久层是
        #   `agent_session_state` 表 —— 见 `_session()` / `_hydrate_state()`
        #   / `_flush_state()` 三段注释。
        self._session_states = SessionStateRegistry()

    # ====== 会话级状态（第 145 轮批 C1：进程内存 → PG）======
    #
    # 迁移前的形态是一个挂在单例上的普通 dict：
    #     self._session_state: dict = {}                     # 进程内存
    #     return self._session_state.setdefault(context_id or "_default", {})
    #
    # 两个洞（r141 §2.4 实测）：
    #   · 键只增不减 —— 长跑进程持续吃内存；
    #   · 完全活在进程里 —— 进程数 > 1 时跨 worker 不可见；重启即丢。
    #     后者的表现最迷惑：「聊天记录还在（消息在 PG 里），但 AI 忘了我在补什么」。
    #
    # 现在的形状：`self._session_states`（有界缓存 + 脏追踪）当**内存视图**，
    # `agent_session_state` 表当**持久层**；异步只出现在入口 hydrate / 出口 flush。
    #
    # ★ 为什么读接口仍是**同步**的：8 个消费点里有一半在同步私有方法里
    #   （`_ask_for_save` / `_last_products` / `_resolve_named_product`），
    #   把它们全掀成 async 只为迁就一处 IO，收益为零、风险不小。

    def _state_scope(self, context_id: Optional[str] = None) -> str:
        """
        当前请求的**状态作用域** —— 唯一一份口径，`_session()` 与
        `_hydrate_state()` / `_flush_state()` 三方共用它。

        · 有会话 + 有身份 ⇒ `resolve_thread_id()`（= checkpointer 的 thread_id）
        · 只有会话（单测 / 未登录）⇒ 会话 ID 本身，**纯内存、不落库**
        · 无会话 ⇒ `_default`，同样不落库

        ★★ 为什么不自己拼一份键：状态与 checkpoint 描述的是"同一个会话"。
           两处各拼一份必然漂移，而漂移的表现是「历史还在、槽位没了」——
           两边都不报错。第 138 轮的 `X-Shop-ID` 事故正是"同一概念两套 ID 空间"。

        ★ 只读 ContextVar（由 `_bind_context` 写入），不接受 user_id 入参：
           入参与 ContextVar 是**两个真源**，测试把 `_bind_context` 换掉之后
           两者就会分叉（hydrate 读 A、业务写 B），而那种错不报错、只丢状态。
        """
        if not context_id:
            return _DEFAULT_STATE_SCOPE
        user_id = _current_user_id.get()
        if user_id:
            return self.resolve_thread_id(context_id, user_id)
        return context_id

    def _state_key(self, context_id: Optional[str] = None) -> tuple:
        """
        返回 `(内存作用域, 落盘键)`；落盘键为 `None` ⇒ 本次不落库。

        ★ 把「作用域」与「要不要落库」放在**同一个函数**里算：它们必须同源。
          分两处判断迟早出现「hydrate 用 A 键、flush 用 B 键」—— 同样不报错。
        """
        scope = self._state_scope(context_id)
        persistable = bool(context_id and _current_user_id.get())
        return scope, (scope if persistable else None)

    def _session(self, context_id: Optional[str] = None):
        """
        取（必要时创建）该会话的状态容器（`ai_infra.session_state.SessionState`）。

        没有 context_id 时退化为 `_default` —— 单会话场景（含既有测试）仍可用；
        多会话并发下**必须由调用方传 context_id**，否则还是会串。

        ★ 作用域里带上身份：同一个 session_id 在不同身份下必须是两份状态。
          只按 context_id 分片，在"会话归谁"这件事上就完全依赖上游校验 ——
          而这条路径上没有第二道防线。
        """
        return self._session_states.scope(self._state_scope(context_id))

    async def _hydrate_state(self, context_id: Optional[str] = None) -> None:
        """
        入口：把该会话的状态从 PG 读回内存（无身份 / 无会话 ⇒ 空操作，零 DB 往返）。

        ★ 先补写、再读：上一轮可能**没写成功**（落盘失败，或流式生成器被客户端
          中断而 finally 里的 await 被取消）。那笔改动仍在内存容器里且标记为脏，
          而 `hydrate_state()` 对脏容器是"不覆盖"的 ⇒ 若不在入口先补写，
          这次请求就一直拿着内存那份，库里那份（更早的）永远回不来，
          而这笔改动也永远不出门。补写把两个方向都堵上。
        """
        scope, thread_id = self._state_key(context_id)
        state = self._session_states.scope(scope)
        if thread_id is not None and state.is_dirty:
            await self._flush_state(context_id)
        await _hydrate_session_state(
            state, owner_id=_current_user_id.get(), thread_id=thread_id
        )

    async def _flush_state(self, context_id: Optional[str] = None) -> None:
        """
        出口：把内存里未落盘的改动写回 PG（无改动 ⇒ 空操作）。

        ★ 这里再包一层 try/except：`persist_state()` 自己已经吞掉了 DB 异常，
          但**生成器被关闭**（客户端断流 / `aclose()`）时，`finally` 里的 await
          还可能抛 `RuntimeError`（事件循环正在关）。那种异常不该从 finally 里
          冒出来，把一次已经生成完的回答变成错误页 —— 状态没写上是小损失，
          把回答炸掉是大的。
        """
        scope, thread_id = self._state_key(context_id)
        if thread_id is None:
            return
        try:
            await _persist_session_state(
                self._session_states.scope(scope),
                owner_id=_current_user_id.get(),
                thread_id=thread_id,
                session_id=context_id,
            )
        except Exception as e:  # noqa: BLE001 —— 见 docstring
            logger.warning(f"[product_research] 会话状态落盘跳过：{e}")

    def _last_products(self, context_id: Optional[str] = None) -> List[dict]:
        """该会话上一轮蓝海产出的候选商品（没有则空列表）。"""
        cached = self._session(context_id).get("last_blue_ocean") or {}
        return cached.get("products") or []

    @property
    def _last_blue_ocean(self) -> Optional[dict]:
        """
        默认会话的蓝海结果（**兼容旧引用的只读别名**；新代码请用 `_last_products(context_id)`）。

        保留它是因为既有测试与 `_session_context_block` 按「单会话」语义书写。
        """
        return self._session(None).get("last_blue_ocean")

    @staticmethod
    def _bind_context(
        context_id: Optional[str],
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> None:
        """
        把会话 ID、**已校验的**店铺 ID 与**身份**绑定到 ContextVar。

        三个值都由**服务端**在入口写入，用途各不相同：
          · `context_id` —— tools.py 靠它找到本会话的状态（`_session()`）；
          · `shop_id`    —— `_write_candidates` 的写入归属，必须是已校验的值；
          · `user_id`    —— 会话状态的**作用域**键（`_state_scope()`）。
            漏传的后果不是「少记一点」，而是状态落到另一个作用域下 ——
            表现为「刚补的槽位下一轮又不见了」，且没有任何报错。

        `shop_id` 绝不能是原始请求头 —— 详见 `_current_shop_id` 的注释。

        **有意不 reset**：每个请求是独立的 asyncio Task，ContextVar 天然按 Task 隔离，
        且下一次调用会覆盖 —— 这样可省掉「用 try/finally 缩进整个 async 生成器体」。
        """
        _current_context_id.set(context_id)
        _current_shop_id.set(shop_id)
        _current_user_id.set(user_id)

    async def invoke(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        同步调用 Agent（简单任务）—— **外层入口**。

        ★ 第 145 轮批 C1：本方法现在只做四件事 ——
          绑上下文 → 入口 hydrate → 委托实现体 → 出口 flush。
          真正的决策路径在 `_invoke_impl()` 里。

        为什么必须包一层、而不是在实现体首尾各加一行：
          · hydrate / flush 都要 `user_id`，而它是本方法的入参；
          · flush 必须落在实现体的**每一条** return 上。实现体里有 5 个 return，
            逐个补等于给自己留一个"以后新增 return 就忘了 flush"的坑；
            `try/finally` 是这里唯一能覆盖全部出口的形状。
        """
        self._bind_context(context_id, shop_id, user_id)
        await self._hydrate_state(context_id)
        try:
            return await self._invoke_impl(query, context_id, shop_id, user_id)
        finally:
            await self._flush_state(context_id)

    async def _invoke_impl(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        同步调用 Agent（简单任务）的**实现体**；入口见 `invoke()`。

        Args:
            query: 用户查询
            context_id: 会话上下文 ID（可选）
            shop_id: **已校验归属**的店铺 ID（可选）。入库类意图必须传，
                     否则 `_write_candidates` 会硬拒绝写入。

        Returns:
            AgentResponse 包含结果和展示数据

        决策路径（与 `stream_chat` **完全一致** —— 流式与否只是输出形式，不是两套智能）：
          1. 有 pending 入库槽位 → 优先续填
          2. 关键词表命中结构化意图 → 直接执行（省一次 LLM 往返）
          3. 未命中（general）→ LLM 工具路由兜底（router 自主选工具）
          4. 路由不可用 → 关键词表的 general 分支
        """
        # 0. 会话 ID / 店铺归属 / 身份 三者已在**外层 `invoke()`** 里绑好，那里
        #    还负责入口 hydrate 与出口 flush。这里不再绑 —— 重复绑定一旦少传一个
        #    参数，就会把 ContextVar 覆盖成 None（作用域随之漂移）。
        #
        # 1. 入库槽位续填优先（上一轮追问过「还差什么」，本轮回答直接当槽位填充）
        if self._session(context_id).get("pending_save"):
            resumed = await self._resume_pending_save(query, context_id, shop_id)
            if resumed is not None:
                return AgentResponse(
                    content=self._compose_reply(resumed),
                    data=resumed,
                    display_type=resumed.get("type", "general"),
                )

        # 2. 关键词表优先
        # ★★ 点名技能 ⇒ **禁用关键词短路**（第 246 轮）：下面两条短路
        #   （`_APPROVAL_GATED_INTENTS` / `INTENT_SHORTCUTS`）都不构造
        #   system prompt，而技能正文 / 目录 / `load_skill` 工具全住在 system
        #   prompt 里（`BaseAgent` 的图注入）⇒ 短路 = 用户点的技能一次都
        #   渲染不到。让路给第 3 步的工具路由（那条路真的构造 prompt）。
        #   ★ `general` 三条短路都不命中（门禁钉住这个前提）⇒ 等于「不短路」；
        #     未点名时行为逐字不变。
        intent = "general" if is_skill_requested() else await self._classify_intent(query)
        # ★★★ 第 131 轮：**有副作用的意图必须走带 HITL 审批的工具路径**，
        #   不能由关键词表直写 —— 否则「说一句入库」是零审批直写，
        #   而「LLM 判为入库」要审批（同一操作两套规矩）。详见
        #   `_route_gated_intent` 的 docstring。
        if intent in self._APPROVAL_GATED_INTENTS:
            return await self._route_gated_intent(query, context_id, user_id, shop_id)
        # ★★ 第 223 轮：判据由 `!= "general"` 换成**共用名单** `INTENT_SHORTCUTS`。
        #   改前两条入口各写一份（这里 `!= "general"`、`_stream_chat_impl` 一份
        #   显式元组）⇒ 新加一个标签必然漂移：同一句话走流式开挖、走非流式清点。
        #   现在 `query_candidates`（清点）与 `general` 一样**落到第 3 步的工具
        #   路由**（LLM 调 `list_candidates`），而不是被送进 `_process_query` 做
        #   业务短路。
        if intent in INTENT_SHORTCUTS:
            return await self._process_query(query, context_id, intent, shop_id)

        # 3. 未命中 → 工具路由兜底（关键词表从「唯一门」降为「加速器」）
        router = self._get_router()
        if router is not None:
            result = await self._route_via_tools(query, context_id, user_id)
            if result is not None:
                return result

        # 4. 最后兜底
        #   ★ 点名技能、但技能通道（工具环路）不可用 ⇒ 如实说，**不回关键词表
        #     兜底**：那会拿一份"别的东西"顶替用户点的技能，而界面上看不出来。
        if is_skill_requested():
            return AgentResponse(content=SKILL_CHANNEL_UNAVAILABLE, display_type="text")
        return await self._process_query(query, context_id, "general")

    def _get_router(self):
        """懒加载工具化路由层，返回 None 表示不可用（回退关键词表）。"""
        if self._router is None:
            self._router = self._build_router()
        return self._router

    def _build_router(self):
        """构建工具化路由层（BaseAgent 实例，注入 `product_research_tools` 全部工具）。"""
        if not (self.ENABLE_LLM):
            return None
        try:
            from .tools import product_research_tools

            from core.checkpoint import get_checkpointer

            # ★ 2026-09-17：**子层也要绑 checkpointer** —— 主 Agent 传了
            #   session_id 也没有任何东西可被持久化（`interrupt()` 更是直接抛）。
            #   `checkpoint_ns` 把本 Agent 的会话与 secretary 隔开，避免同一个
            #   session_id 挤进同一段消息历史（见 BaseAgent.resolve_thread_id）。
            return BaseAgent(
                agent_name=f"{self.agent_name}_router",
                system_prompt=self.system_prompt,
                tools=product_research_tools,
                # ★ 第 145 轮 批 C5：裸数字 → 具名档位（同 listing 路由子层）。
                budget=BUDGET_ROUTER,
                # ★ 第 147 轮 批 C4：上下文档位与预算档位**同档**（ROUTER）。
                #   路由子层「单次决策 + 一串工具调用、用完即答」⇒ 历史最短、裁得最狠
                #   （12k / 保底 2 轮），与 `checkpoint_ns="product_research"` 同一层。
                context_policy=CONTEXT_ROUTER,
                checkpointer=get_checkpointer(),
                checkpoint_ns="product_research",
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
                #   自动推导（见 `BaseAgent._wrap_hitl_tools`）—— 本文件的
                #   职责是「装配哪张注册表」，不是「哪个工具危险」。
                #   行为不变：`product_research_tools` 里只有 `save_candidate`
                #   不在只读豁免名单内（第 325 轮新增的 `query_market_insight`
                #   声明的是 `READ_ONLY_METADATA`）⇒ 推导结果仍是
                #   `{"save_candidate"}`（由 `test_hitl_wiring.py` 钉住）。
                #   为什么必须删而不是留：留着就等于留了**第二份真源**，
                #   而两份真源迟早会漂移 —— 那时「策略表里是 A、Agent 里是 B」
                #   会让审批范围变成一个没人能说清的东西。
            )
        except Exception as e:
            logger.warning(f"[product_research] router build failed: {e}")
            return None

    # ====== HITL 人工审批（第 131 轮 item2-B）======

    # ★★★ 有副作用的意图名单：**只能**经带 HITL 审批的工具路径执行。
    #
    # 为什么必须收在**一处**：`invoke()` 与 `stream_chat()` 是两条独立入口，
    # 各自维护一份名单必然漂移 —— 而这里漂移的后果是「同一句话走流式不审批、
    # 走非流式审批」这种**按请求形式决定要不要审批**的荒谬结果。
    #
    # 为什么「入库」会上这个名单：它真的写 PG（`candidates/service.create_candidate`），
    # 而 `_classify_intent()` 的 `save_keywords` 里含「选品库 / 入库」等高频词 ——
    # 修之前，说一句「加进选品库」就是**零审批直写**。
    _APPROVAL_GATED_INTENTS = frozenset({"save_candidate"})

    # 审批通道不可用时的统一拒绝文案（两个入口共用，避免「同一件事两种说法」）
    _APPROVAL_CHANNEL_DOWN_MSG = (
        "入库是写操作，需要人工确认后才能执行；但审批通道当前不可用，"
        "这次**没有写入**。请稍后重试。"
    )

    async def _route_gated_intent(
        self,
        query: str,
        context_id: Optional[str],
        user_id: Optional[str],
        shop_id: Optional[str] = None,
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
                content=(
                    "入库需要有目标店铺，但当前没有选择店铺，这次**没有写入**。"
                    "请先在界面左上角选一个店铺，再说一次「把……加进选品库」。"
                ),
                data={
                    "type": "candidate_save_failed",
                    "error": "no_shop_selected",
                },
                display_type="text",
            )

        if self._get_router() is not None:
            result = await self._route_via_tools(query, context_id, user_id)
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
            content=self._APPROVAL_CHANNEL_DOWN_MSG,
            data={
                "type": "candidate_save_failed",
                "error": "approval_channel_unavailable",
            },
            display_type="text",
        )

    async def _stream_gated_intent(
        self,
        query: str,
        context_id: Optional[str],
        user_id: Optional[str],
        shop_id: Optional[str] = None,
    ) -> AsyncIterable:
        """有副作用意图的**流式**入口：同 `_route_gated_intent`，理由见其 docstring。"""
        if not (shop_id or "").strip():
            # 与非流式 `_route_gated_intent` 的文案**逐字相同**：两条路径说同一件事
            yield (
                "入库需要有目标店铺，但当前没有选择店铺，这次**没有写入**。"
                "请先在界面左上角选一个店铺，再说一次「把……加进选品库」。"
            )
            return
        if self._get_router() is None:
            yield self._APPROVAL_CHANNEL_DOWN_MSG
            return
        async for chunk in self._stream_via_tools(
            query, context_id, user_id, gated=True
        ):
            yield chunk


    async def _detect_pending_approval(
        self, context_id: Optional[str], user_id: Optional[str] = None
    ) -> Optional[AgentResponse]:
        """
        判断「这张图此刻是不是停在一次人工审批上」；是则渲染成 `pending_approval`。

        ★ 为什么走 `aget_state()` 而不是读 `ainvoke` 的返回值：
          流式与非流式都要判同一件事。非流式的 state 里有 `__interrupt__` 可读，
          但**流式没有**（`astream_events` 只给事件、不给最终 state）。
          两边各写一份判定，就会长出「非流式弹卡、流式静默吞掉」的不一致。
          `aget_state()` 对两条路径**语义完全相同**，是这里唯一正确的口径。

        ★ 为什么必须先确认 `context_id and user_id`：两者缺任一时
          `graph_for_session()` 返回的是**不带 checkpointer 的图**，
          对它调 `aget_state()` 会直接抛（连接层报 checkpointer 未设置）。
        """
        if not (context_id and user_id):
            return None

        router = self._get_router()
        if router is None or router.checkpointer is None:
            return None

        try:
            graph, cfg = router.graph_for_session(context_id, user_id)
            snapshot = await graph.aget_state(cfg)
        except Exception as e:  # noqa: BLE001 —— 探测失败不该让整轮对话崩
            logger.warning(f"[product_research] pending-approval probe failed: {e}")
            return None

        for task in (getattr(snapshot, "tasks", None) or []):
            for it in (getattr(task, "interrupts", None) or []):
                return self._pending_approval_from_interrupt(it, context_id)
        return None

    @staticmethod
    def _pending_approval_from_interrupt(
        interrupt_obj, context_id: Optional[str]
    ) -> AgentResponse:
        """
        把 LangGraph 的 `Interrupt` 渲染成前端可直接展示的审批请求。

        ★ 刻意**不回传 `thread_id`**：前端只要把同一个 `session_id` 交回来，
          服务端会按**与首轮完全相同的口径**重算 thread_id
          （`resolve_thread_id`）。把 thread_id 交给客户端，等于把
          「这条待审批操作归谁」交给请求方 —— 而 thread_id 里就含 user_id。
        """
        req = getattr(interrupt_obj, "value", None) or {}
        action = (req.get("action_request") or {}) if isinstance(req, dict) else {}
        tool_name = action.get("action") or "未知操作"
        return AgentResponse(
            content=(
                f"这一步需要你确认：准备执行「{tool_name}」，"
                "在批准之前它不会被真正执行。请选择「批准」或「拒绝」。"
            ),
            data={
                "type": "pending_approval",
                "approval": {
                    "interrupt_id": getattr(interrupt_obj, "id", None),
                    "action": tool_name,
                    "args": action.get("args") or {},
                    "require_reason": bool(action.get("require_reason")),
                    "timeout_seconds": action.get("timeout"),
                    "description": req.get("description") or "",
                },
                "session_id": context_id,
            },
            display_type="pending_approval",
        )

    @staticmethod
    def _build_resume_payload(
        decision: str,
        *,
        reason: Optional[str] = None,
        args: Optional[dict] = None,
        feedback: Optional[str] = None,
    ) -> dict:
        """
        把外部的「决策」翻译成 `hitl_decorator.call_tool_with_hitl` 认得的载荷。

        ★ 契约在包装器那一侧（`response.get("type")` /
          `response.get("args", {}).get(...)`）。两边结构必须逐字段对齐 ——
          结构对不上的表现是「点了批准但什么都没发生」（`type` 认不出 ⇒
          落到 else 分支抛 `不支持的 HITL 响应类型`），而不是任何显式报错。
        """
        d = (decision or "").strip().lower()
        if d == "accept":
            return {"type": "accept", "args": {}}
        if d == "reject":
            return {"type": "reject", "args": {"reason": reason or "未提供原因"}}
        if d == "edit":
            if not isinstance(args, dict) or not args:
                raise ValueError("decision=edit 时必须提供非空的 args（改写后的工具入参）")
            return {"type": "edit", "args": {"args": args}}
        if d == "response":
            return {"type": "response", "args": feedback or ""}
        raise ValueError(
            f"不支持的审批决策: {decision!r}（可选 accept / reject / edit / response）"
        )

    @staticmethod
    def _unwrap_hitl_tool_output(raw: str) -> Optional[dict]:
        """
        从 HITL 包装器的返回文案里取回**内层工具的原始结构化结果**。

        包装器的返回形如：

            ✅ 操作已执行 [save_candidate]
            结果: {"type": "candidate_saved", ...}

        ★ 为什么值得做这层解包：审批通过后的结果应该与「没走审批」时
          **长得一模一样**（同一个结果卡、同一套字段）。否则前端要为
          「审批后」单独写一套渲染 —— 两边字段一旦漂移，就又回到
          「同一件事两种表现」的老问题。
        ★ 解包失败一律返回 `None`（调用方降级为展示原始文案），
          不让「文案改了」升级成「审批流程报错」。
        """
        if not raw:
            return None
        marker = "结果: "
        idx = raw.find(marker)
        if idx < 0:
            return None
        try:
            parsed = json.loads(raw[idx + len(marker):])
        except Exception:  # noqa: BLE001
            return None
        return parsed if isinstance(parsed, dict) else None

    async def resume_approval(
        self,
        context_id: str,
        decision: str,
        *,
        user_id: Optional[str] = None,
        shop_id: Optional[str] = None,
        reason: Optional[str] = None,
        args: Optional[dict] = None,
        feedback: Optional[str] = None,
    ) -> AgentResponse:
        """
        把审批决策回传给**被中断的那张图**，让它续跑到结束。

        ★ 为什么必须重新 `_bind_context()`：续跑时被中断的工具会**重新执行**，
          而它靠 ContextVar 拿会话与店铺归属（见 `tools.py::_save_candidate_tool`）。
          不重新绑定 ⇒ `shop_id` 拿不到 ⇒ `_write_candidates` **硬拒绝写入** ——
          用户「批准了」却收到「请先选一个店铺」，是这条链路上最迷惑的表现。
        """
        router = self._get_router()
        if router is None:
            return AgentResponse(
                content="审批通道暂时不可用（工具路由层未就绪），请稍后重试。",
                data={"type": "approval_failed", "error": "router_unavailable"},
                display_type="text",
            )
        if not (context_id and user_id):
            return AgentResponse(
                content="审批必须带上会话与登录身份，否则定位不到你那条待审批的操作。",
                data={"type": "approval_failed", "error": "missing_session_or_identity"},
                display_type="text",
            )
        if router.checkpointer is None:
            return AgentResponse(
                content="审批通道暂时不可用（会话存储未就绪），请稍后重试。",
                data={"type": "approval_failed", "error": "checkpointer_unavailable"},
                display_type="text",
            )

        try:
            payload = self._build_resume_payload(
                decision, reason=reason, args=args, feedback=feedback
            )
        except ValueError as e:
            return AgentResponse(
                content=str(e),
                data={"type": "approval_failed", "error": "bad_decision"},
                display_type="text",
            )

        # 续跑前重新绑定上下文（被中断的工具会重新执行，需要会话 + 归属 + 身份）
        # ★ 第 145 轮批 C1：身份也要绑 —— 会话状态的作用域键含 user_id，漏传会让
        #   被中断的工具在**另一个作用域**里找会话状态（`_save_candidate` 要靠它
        #   把「第 1 个」解析成具体商品）。
        # ★ 为什么这里只 hydrate 不 flush：本次调用能触达的写路径（`_save_candidate`
        #   → `_write_candidates`）**不改会话状态**（不写也不删任何键）。若将来它
        #   改了，入口 hydrate 的"先补写"仍会把它写出去，不会永久滞留。
        self._bind_context(context_id, shop_id, user_id)
        await self._hydrate_state(context_id)

        graph, cfg = router.graph_for_session(context_id, user_id)
        try:
            state = await graph.ainvoke(Command(resume=payload), config=cfg)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[product_research] resume failed: {e}")
            return AgentResponse(
                content="审批回传失败，请重试；若反复失败请重新发起这次操作。",
                data={
                    "type": "approval_failed",
                    "error": "resume_failed",
                    "detail": str(e)[:200],
                },
                display_type="text",
            )

        # 多步审批：续跑后可能又停在**下一个**中断上，别把它当成功
        again = await self._detect_pending_approval(context_id, user_id)
        if again is not None:
            return again

        messages = state.get("messages", []) if isinstance(state, dict) else []
        tool_content = ""
        reply = ""
        for m in messages:
            if m.__class__.__name__ == "ToolMessage":
                tool_content = str(m.content)
            elif m.__class__.__name__ == "AIMessage":
                c = getattr(m, "content", "")
                if isinstance(c, str) and c.strip():
                    reply = c

        unwrapped = self._unwrap_hitl_tool_output(tool_content)
        if unwrapped is not None:
            return AgentResponse(
                content=reply or self._compose_reply(unwrapped),
                data={**unwrapped, "approval_decision": decision},
                display_type=unwrapped.get("type", "text"),
            )
        return AgentResponse(
            content=tool_content or reply or "已记录你的审批决定。",
            data={"type": "approval_resolved", "decision": decision},
            display_type="text",
        )

    # 工具名 → display_type（对齐 _process_query 的 type 语义）
    _TOOL_TYPE_MAP = {
        "analyze_blue_ocean": "blue_ocean_analysis",
        "analyze_profit": "profit_analysis",
        "analyze_pain_points": "pain_point_analysis",
        "compare_competitors": "competitor_analysis",
        "save_candidate": "candidate_saved",
    }

    def _parse_tool_output(self, tool_name: str, tool_result) -> Optional[dict]:
        """
        工具返回的 JSON 文本 → 带 `type` 的 dict（解析不出来返回 None）。

        抽出来给非流式（`_route_via_tools`）与流式（`_stream_via_tools`）共用 ——
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
        return {**data, "type": self._TOOL_TYPE_MAP.get(tool_name, "analysis")}

    async def _route_via_tools(
        self,
        query: str,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[AgentResponse]:
        """工具化路由：LLM 自主选工具执行，把工具结果包装回 AgentResponse。

        返回 None 表示路由失败，调用方继续兜底。
        """
        try:
            # ★ 2026-09-17：改走统一入口。旧键 `...-{context_id or id(self)}`
            #   的 `id(self)` 是**对象内存地址** ⇒ 没有 context_id 时换个进程
            #   就换 thread_id，永远命中不到上一轮的 checkpoint。
            state = await self._router.run_session(
                {"messages": [HumanMessage(content=query)]},
                session_id=context_id,
                user_id=user_id,
            )

            # ★★★ 第 131 轮 item2-B：有副作用工具的 HITL 中断必须**立刻回传**，
            #   而不是继续按「这轮没调到工具」往下解析 —— 图此刻停在 tool_node 上，
            #   消息里**根本没有 ToolMessage**，继续走会一路落到 `return None`
            #   ⇒ 调用方退化到闲聊兜底 ⇒ 用户收到一句无关的回复，
            #   **完全不知道有个操作正卡在等他审批**（审批卡永远出不来）。
            pending = await self._detect_pending_approval(context_id, user_id)
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

            data = self._parse_tool_output(tool_name, tool_result)
            if data is not None:
                return AgentResponse(
                    # 同样不裸吐 JSON：优先 LLM 归纳的 final_reply，
                    # 否则用 summary / error 压成人话（见 _compose_reply）
                    content=final_reply or self._compose_reply(data),
                    data=data,
                    display_type=data.get("type", "analysis"),
                )

            if final_reply:
                return AgentResponse(content=final_reply, data=None, display_type="text")

            return None
        except Exception as e:
            logger.warning(f"[product_research] tool routing failed: {e}")
            return None

    async def _stream_via_tools(
        self,
        query: str,
        context_id: Optional[str] = None,
        user_id: Optional[str] = None,
        gated: bool = False,
    ) -> AsyncIterable:
        """
        LLM 工具路由（**流式版**）。

        与 `_route_via_tools` 是**同一条决策路径**（router 的 LLM 自主选工具），
        差别只在输出形式：文本逐 token 下发，而不是攒完一次性返回。
        这正是「流式与非流式只是输出形式」的落地 —— 先前流式路径只走关键词表，
        表漏一个词就掉进 general 闲聊，同一句话在两条路径上表现不一致（实测踩坑）。

        兜底链：router 不可用 / 异常 / 无输出 → 带会话语境的 LLM 闲聊。
        保证**永远有输出**，不会给老板一个空白回复。
        """
        router = self._get_router()
        tool_name = ""
        tool_output = None
        replied = False
        #: 工具事件 → 步骤事件的有状态翻译器（见 `ai_infra.sse.ToolTrace`）。
        #: 一次 `_stream_via_tools` 调用 = 一条轨迹，故建在函数内而非 self 上。
        # ★ 工具人话标题走**注入**：真源在业务侧
        #   （`modules/skills/tools_catalog.py::tool_title`，全仓唯一查询口），
        #   而 `ai_infra` 不许依赖业务（分层硬红线）⇒ 只能把查询口传进去。
        #   惰性 import：Agent 的**模块导入期**无需把 `modules.skills` 拉进依赖图，
        #   只有真跑流式工具环路时才需要它。
        # 走**包门面**（本仓条款 1：跨模块引用不得伸手进包内部）。
        from modules.skills import tool_title

        trace = ToolTrace(title_resolver=tool_title)

        if router is not None:
            try:
                # 与非流式走**同一个** thread_id 口径（同一会话两条路径互通）
                async for ev in router.stream_session(
                    {"messages": [HumanMessage(content=query)]},
                    session_id=context_id,
                    user_id=user_id,
                ):
                    et = ev.get("event")
                    if et == "on_chat_model_stream":
                        chunk = ev.get("data", {}).get("chunk")
                        text = getattr(chunk, "content", "") or ""
                        if text:
                            replied = True
                            yield text
                    elif et == "on_tool_start":
                        tool_name = ev.get("name") or tool_name
                    elif et == "on_tool_end":
                        tool_output = ev.get("data", {}).get("output")

                    # ★ 第 210 轮：把工具轨迹**实时**下发（「思考过程」的原料）。
                    #   此前的流式路径**已经在消费** on_tool_start / on_tool_end，
                    #   但只用来解析最终结果 —— 拿到手的过程信息被整段丢掉，
                    #   前端于是只看到一个转圈。
                    #   ★ 这一句刻意放在 if/elif 链**之外**：`feed()` 是**有状态**的
                    #     （start 记时刻、end 算耗时），同一事件只能喂一次。
                    #     塞进某个分支里，下次想在另一分支复用就会变成两次喂、
                    #     耗时被算成 0。
                    trace_step = trace.feed(ev)
                    if trace_step is not None:
                        yield trace_step
            except Exception as e:
                logger.warning(f"[product_research] stream tool routing failed: {e}")

        # ★★★ 第 131 轮 item2-B：流式路径的中断检测**必须与非流式同源**。
        #   两边各写一份判定，就必然长出「非流式弹审批卡、流式静默吞掉」这种
        #   「同一句话在两条路径上表现不一致」的经典缺陷（本项目此前踩过，
        #   见 `_stream_via_tools` 的 docstring：流式与非流式必须是同一条决策路径）。
        #   所以两者都调同一个 `_detect_pending_approval()`（它走 `aget_state`，
        #   对流式同样适用 —— `astream_events` 只给事件、不给最终 state）。
        pending = await self._detect_pending_approval(context_id, user_id)
        if pending is not None:
            if not replied:
                yield pending.content
            yield {
                "event": "meta",
                "data": {"display_type": pending.display_type, "data": pending.data},
            }
            return

        data = self._parse_tool_output(tool_name, tool_output)
        if data is not None:
            # LLM 没自己总结过工具结果 → 由我们把结论压成人话补上
            if not replied:
                yield self._compose_reply(data)
            yield {
                "event": "meta",
                "data": {"display_type": data.get("type", "analysis"), "data": data},
            }
            return

        if replied:
            # ★ `gated`（有副作用意图）：LLM 自己写了文本、却**没调工具** ⇒
            #   这一步压根没到审批闸门前。把它当答案返回，用户会以为入库已完成
            #   （实测文案是一段泛泛闲聊），而操作从未发生。
            if gated:
                yield self._APPROVAL_CHANNEL_DOWN_MSG
            return

        # 既没调到工具、也没吐出文本 → 闲聊兜底（带会话语境，别让它编通用知识）。
        # ★ `gated` 意图**不**走闲聊兜底：闸门的语义是「要么走审批、要么明说
        #   没执行」，掉进闲聊等于把一次写操作伪装成一次普通对话。
        if gated:
            yield self._APPROVAL_CHANNEL_DOWN_MSG
            return
        async for chunk in self._general_stream(query, context_id):
            yield chunk

    async def _general_stream(
        self, query: str, context_id: Optional[str] = None
    ) -> AsyncIterable[str]:
        """闲聊流式（带本轮会话语境；LLM 不可用时退化为能力引导文案）。"""
        if not (self.ENABLE_LLM and self.llm_client):
            result = await self._general_chat(query)
            yield result.get("response", "")
            return

        try:
            async for chunk in self.llm_stream(
                query,
                # 角色提示词 + **本轮会话语境**：不带上文时 LLM 手里没有真实数据，
                # 只能照提示词骨架编通用知识（实测编出 Google Trends / CE 认证 / 物流风险）。
                system_prompt=self.get_prompt_template("product_research", market="全球")
                + self._session_context_block(context_id),
                model=self.DEFAULT_MODEL,
                temperature=0.7,
                max_tokens=1024,
            ):
                yield chunk
        except Exception as e:
            logger.warning(f"[product_research] general stream failed: {e}")
            result = await self._general_chat(query)
            yield result.get("response", "")

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
    _INTENT_ROUTES = (
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

    async def _classify_intent(self, query: str) -> str:
        """分类用户意图（兜底 `general`；控制流见 `ai_infra.intent.first_match`）。

        Returns:
            blue_ocean / profit / pain_points / competitor / save_candidate /
            query_candidates / general
        """
        # ★ 非关键词的**前置信号**：「≥2 个 ASIN」比关键词可靠，优先判定。
        #   它不属于「关键词路由」这一机制，因此留在业务侧、在机制**之前**执行。
        if len(self._extract_multiple_asins(query)) >= 2:
            return "competitor"
        # ★ 第二条前置信号：候选存量清点（与上一条同款形态 —— 都不是关键词命中，
        #   而是**看句子形态**就能定的判定）。排在 `first_match` **之前**是关键：
        #   收进 `_INTENT_ROUTES` 会排在 `save_candidate` 之后而永远轮不到
        #   （「选品库里现在有多少条」里含「选品库」）。
        # ★ 第三条前置信号：选品大盘问句（第 325 轮 —— 老板「现在哪个品类蓝海分
        #   最高」被「品类」吞去挖蓝海了）。与上两条同款形态：看句子里的
        #   **量纲 + 诉求**就能定，不靠关键词命中。排在 `first_match` **之前**是关键：
        #   「品类」在 `blue_ocean` 组里，排到后面就永远轮不到它。
        if self._is_market_insight_query(query):
            return MARKET_INSIGHT_INTENT
        if self._is_candidate_query(query):
            return QUERY_CANDIDATES_INTENT
        return first_match(query, self._INTENT_ROUTES, "general")

    #: 「候选存量清点」前置判定的**左门**：指向「候选选品库这个对象」的词。
    #: ★ 只收**对象词**，不收指向挖掘方向的词（品类 / 趋势 / 热门…）——
    #:   后者是真蓝海问句的载体（「有什么冷门品类」「比较火的品类有哪些」）。
    _CANDIDATE_QUERY_DOMAIN = ("选品", "候选")

    #: 「候选存量清点」前置判定的**右门**：表达「清点 / 列举」诉求的词。
    _CANDIDATE_QUERY_COUNT = ("多少", "几个", "几条", "几件", "几款",
                              "有哪些", "列表", "列一下", "列下", "列出来", "列出",
                              "看看", "看下", "查看", "都有啥", "都有什么",
                              "统计", "盘点", "清点", "总共", "一共")

    def _is_candidate_query(self, query: str) -> bool:
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
        domain_hit = any(w in q for w in self._CANDIDATE_QUERY_DOMAIN)
        count_hit = any(w in q for w in self._CANDIDATE_QUERY_COUNT)
        return domain_hit and count_hit

    #: 选品大盘前置判定的**左门**：大盘**量纲词**（= 面板上真有数据的那些列）。
    #: ★ 只收「类目级大盘才有的量纲」。**不**试图区分「这个产品的搜索量」这种
    #:   同词不同对象的问法 —— 那不是本判定的职责（LLM 会判），而且误判的代价
    #:   只是换个标签：`MARKET_INSIGHT_INTENT` **不在** `INTENT_SHORTCUTS` 里，
    #:   两个入口都落到同一条工具路由（唯一可观察差异是流式多一句进度文案）。
    _MARKET_INSIGHT_METRICS = (
        "蓝海评分", "蓝海分", "蓝海得分",
        "搜索量", "搜索热度", "搜索增长",
        "价格带", "价格中位数", "价格趋势",
        "卖家数", "新卖家数", "竞争度",
    )

    #: 右门：**排行 / 清点诉求**词。左边给量纲、右边给动作，缺一不可
    #: （同 `_CANDIDATE_QUERY_*` 的与门形态与理由）。
    _MARKET_INSIGHT_RANK = (
        "最高", "最低", "最多", "最少", "最大", "最小", "最强",
        "排名", "排行", "前几", "top",
        "哪个", "哪些", "有没有", "是什么",
        "多少", "几个", "几条",
    )

    def _is_market_insight_query(self, query: str) -> bool:
        """是不是「读选品大盘」问句（**与门**：量纲词 AND 排行/清点诉求词）。

        ★ 这条判定**不是**「识别大盘问句」（那是 LLM 的活），它只干一件事：
          **不让关键词短路把大盘问句吞掉**。因此它可以写得很窄 —— 没被它拦下的
          大盘问句落 `general` ⇒ **仍然**进工具路由 ⇒ LLM 照样能调
          `query_market_insight`（第 325 轮新增）。
          代价不对称因此成立：漏判 = 与现状相同；误判 = 也只是换个标签。
        ★ 与 `_CANDIDATE_QUERY_*` 同款：这两组词**不进** `BARE_WORD_VERDICTS`
          —— 它们不是「关键词路由」，而是**与门的一半**，单独一个词永不命中
          （裸词处置表管的是「一个词就能把问句抢走」的那一类）。
        """
        q = (query or "").lower()
        metric_hit = any(w in q for w in self._MARKET_INSIGHT_METRICS)
        rank_hit = any(w in q for w in self._MARKET_INSIGHT_RANK)
        return metric_hit and rank_hit

    # ====== 核心分析方法（P0-6 第二刀：逻辑已外移到 `agent_analyzers.py`）======
    #
    # ★ 这里只留**薄壳**：把依赖显式传进去，然后委托。
    #   为什么不删掉方法、直接在调用点改成模块级调用 ——
    #   `tests/test_product_research_blue_ocean.py` / `..._candidate_flow.py` /
    #   `..._intent_routing.py` 共 13 处按 `agent._analyze_*(...)` 调用，
    #   那是本仓既有的测试契约（改测试的调用形态等于替第三方改契约）。
    # ★ 为什么不重施第一刀的 mixin：这 4 个方法**必须**用 adapter 与会话状态，
    #   藏进基类只会让耦合从「可以数的参数」变成「看不见的继承链」。
    #   依赖清单就写在 `agent_analyzers.py` 的函数签名里。

    async def _analyze_blue_ocean(self, query: str, context_id: Optional[str] = None) -> dict:
        """蓝海品类挖掘（薄壳；领域逻辑见 `agent_analyzers.analyze_blue_ocean`）。"""
        return await analyze_blue_ocean(
            self.adapter,
            query,
            context_id,
            session=self._session(context_id),
            structured_llm=self.llm_structured if self.ENABLE_LLM else None,
            system_prompt=(
                self.get_prompt_template("product_research", market="全球")
                if self.ENABLE_LLM else ""
            ),
        )

    async def _analyze_profit(self, query: str) -> dict:
        """SKU 利润分析（薄壳；领域逻辑见 `agent_analyzers.analyze_profit`）。"""
        return await analyze_profit(self.adapter, query)

    async def _analyze_pain_points(self, query: str) -> dict:
        """痛点机会识别（薄壳；领域逻辑见 `agent_analyzers.analyze_pain_points`）。"""
        return await analyze_pain_points(self.adapter, query)

    async def _analyze_competitors(self, query: str) -> dict:
        """竞品对比分析（薄壳；领域逻辑见 `agent_analyzers.analyze_competitors`）。"""
        return await analyze_competitors(self.adapter, query)

    def _session_context_block(self, context_id: Optional[str] = None) -> str:
        """
        给「对话类」LLM 回复注入**本轮会话语境**。

        为什么必须注入：general 分支原先把 query 裸丢给 LLM —— 只给了角色提示词，
        既没有上下文也没有工具。LLM 手里没有任何真实数据，只能照着 system prompt 里
        「数据驱动 / 趋势洞察 / 风险意识」的骨架**编通用知识**：实测编出了
        「Google Trends 搜索热度较高」「CE、FCC 认证」「液体容器国际运输限制」
        这类放之四海皆准的套话，读起来像通用聊天机器人而不是选品助手。

        注意这跟「有没有接 LLM」无关 —— LLM 接了，但没给它干活的条件。
        把真实候选商品摆到它面前，它才答得出「你要入库的是不是这个」。
        """
        lines: List[str] = []
        products = self._last_products(context_id)

        if products:
            lines.append("")
            lines.append("【本轮会话上下文】")
            lines.append("上一轮蓝海挖掘产出的候选商品（用户说「这个 / 那个 / 第 N 个」时指的是这些）：")
            for i, p in enumerate(products[:10], 1):
                lines.append(
                    f"  {i}. {p.get('title') or '未命名'}（{p.get('asin') or '无 ASIN'}）"
                    f" 售价 ${float(p.get('price') or 0):.2f}"
                    f" ｜ 预估 ROI {p.get('roi') or 0}%"
                )

        lines.append("")
        lines.append("【输出约束】")
        lines.append(
            "1. 只依据上面的真实数据和用户原话回答；"
            "**严禁编造**搜索趋势、销量、专利、认证、物流限制等外部数据。"
            "拿不到的数据就说拿不到，并告诉用户该走哪个分析动作。"
        )
        lines.append(
            "2. 你**没有执行任何写操作**。若用户想入库但目标商品不在上面、也没给 ASIN，"
            "直接追问要入库哪一个（让他给 ASIN 或商品标题），不要替他猜、也不要假装已完成。"
        )
        return "\n".join(lines)

    async def _general_chat(self, query: str) -> dict:
        """通用对话（降级路径：LLM 不可用时返回能力引导文案）"""
        return {
            "type": "general_response",
            "query": query,
            "response": f"收到您的关于「{query}」的问题。作为选品分析师，我可以帮您：\n\n"
                       f"1. 🔍 挖掘蓝海品类机会\n"
                       f"2. 💰 计算 SKU 利润空间\n"
                       f"3. 📊 分析竞品用户痛点\n"
                       f"4. ⚔️ 对比多个竞品\n"
                       f"5. 📥 把看中的商品加进选品库（说「把第 1 个加进选品库」即可）\n\n"
                       f"请告诉我您想了解哪个方面？",
        }

    def _named_tokens(self, query: str) -> List[str]:
        """
        查询里用于「点名商品」的实词 token。

        `tokenize` 以非字母数字切分 → 中文（「帮我加进选品库」「这个品」「第 2 个」）
        自然落空，只剩英文实词；再滤掉英文动作词（add / candidate / library …）。
        因此返回非空 == 用户**点名了某个商品**，空 == 纯指代或纯中文指令。
        """
        from platforms.amazon.client import tokenize

        return [t for t in tokenize(query) if t not in self._SAVE_ACTION_WORDS]

    async def _resolve_named_product(
        self, query: str, context_id: Optional[str] = None
    ) -> Optional[dict]:
        """
        查询里点名了商品标题 → 在商品池里按词边界匹配 Top 1；找不到返回 None。

        为什么必须有这一步：原先的解析只有「ASIN / 序数 / 否则 Top1」三条路，
        用户把**整条商品标题**贴进来时既没 ASIN 也没序数 → 直接落到「上一轮 Top1」。
        实测踩坑：上一轮蓝海 Top1 是瑜伽垫，这轮点名
        「Automatic Pet Feeder, Smart Food Dispenser…」→ 又把瑜伽垫存了一遍（存了 3 条重复）。
        """
        tokens = self._named_tokens(query)
        if not tokens:
            return None

        try:
            hits = await self.adapter.match_products(" ".join(tokens), limit=1)
        except Exception as e:  # noqa: BLE001 —— 匹配失败按「没找到」处理，别阻断入库
            logger.warning(f"[product_research] resolve named product failed: {e}")
            return None
        if not hits:
            return None

        hit = hits[0]
        # 上一轮蓝海结果里已有同一商品时优先用它（自带来源机会词等市场层上下文）
        asin = (hit.get("asin") or hit.get("product_id") or "").upper()
        if asin:
            for p in self._last_products(context_id):
                if (p.get("asin") or "").upper() == asin:
                    return p
        return hit

    # ====== 入库：面板流程的「对话免填版」 ======

    def _candidate_payload_from_product(self, p: dict) -> dict:
        """
        商品记录 → 候选 payload。

        字段语义**对齐前端面板**（`BlueOceanResult.vue` 的 `mapToCandidate()`）：
        sku / margin / tags / notes 全部自动生成，用户什么都不用填。
        可选字段这里「有数据就带上」，缺省由 `candidates/service.build_candidate_record`
        补默认值 —— 两处默认值不再各写一份。
        """
        price = float(p.get("price") or 0)
        roi = float(p.get("roi") or p.get("roi_estimated") or 0)
        margin = (
            round((price - price / (1 + roi / 100)) / price * 100)
            if price > 0 and roi > 0 else 0
        )
        raw_category = p.get("category") or ""
        asin = (p.get("asin") or "").strip()
        score = int(p.get("keyword_opportunity_score") or p.get("blue_ocean_score") or 0)
        source_keyword = p.get("source_keyword") or ""
        sales = int(p.get("estimated_monthly_sales") or 0)

        return {
            "asin": asin,
            "sku": f"SKU-CAND-{asin[2:] if asin.upper().startswith('B0') else (asin or 'MANUAL')}",
            # 注意：这里**不兜底**「未命名候选」—— 必填校验要能看见「标题是空的」，
            # 兜底交给 build_candidate_record（那是「写入时」的职责，不是「校验时」的）。
            "title": (p.get("title") or "").strip(),
            "brand": p.get("brand") or "",
            "category": (raw_category.split(" > ")[0] or "other") if raw_category else "other",
            "sub_category": raw_category.split(" > ")[-1] if raw_category else "",
            "price": price,
            "currency": "USD",
            "site": p.get("marketplace") or "Amazon US",
            "estimated_monthly_sales": sales,
            "review_count": int(p.get("review_count") or 0),
            "rating": float(p.get("rating") or 0),
            "bsr": p.get("bsr_rank"),
            "bsr_category": raw_category,
            "roi_estimated": roi,
            "margin": margin,
            "blue_ocean_score": score,
            "main_image": p.get("main_image") or p.get("image_url") or "",
            "source": "blue_ocean",
            "keywords": [source_keyword] if source_keyword else [],
            "tags": ["蓝海挖掘", f"评分:{score}", f"ROI:{roi}%"],
            "notes": (
                f"来源：蓝海挖掘 | 评分：{score} | 预估月销：{sales} | ROI：{roi}%"
                + (f" | 来源机会词：{source_keyword}" if source_keyword else "")
                + "（由选品分析师从对话写入）"
            ),
            # 分组是面板里唯一的人工交互（可选项）—— 对话入库由后台兜底，不为它打断用户
            "groups": [],
        }

    def _ask_for_save(
        self,
        context_id: Optional[str],
        draft: dict,
        missing: List[str],
        hint: str = "",
    ) -> dict:
        """
        记下待补槽位并追问。

        **有状态**才是关键：下一轮用户回「B0KLMN3456」时不再重新做意图分类，
        而是直接当答案填进来（见 `_resume_pending_save`）。
        没有这个状态，「多轮补齐」根本进行不下去 —— 用户回一句
        「就那个加湿器」会被判成 general 直接跑偏（实测）。
        """
        from modules.candidates import describe_missing_fields

        self._session(context_id)["pending_save"] = {
            "draft": draft,
            "awaiting": list(missing),
            "hint": hint,
        }
        return {
            "type": "candidate_save_failed",
            # soft_error：这是**追问**（对话的正常一步），不是失败 ——
            # 让 `_compose_reply` 别给它套上「这次没跑通」。
            "soft_error": True,
            "awaiting": list(missing),
            "error": f"还缺 {describe_missing_fields(missing)}，补齐我就直接入库。{hint}",
        }

    _SAVE_CANCEL_WORDS = ("算了", "取消", "不用了", "不弄了", "不要了", "先不放", "放弃")

    async def _resume_pending_save(
        self,
        query: str,
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> Optional[dict]:
        """
        入库槽位续填：把这一轮消息当作「上一轮追问的答案」处理。

        返回 None 表示「用户显然在说别的事」→ 调用方清掉 pending 回到常规流程。
        `shop_id` 一路带到 `_write_candidates`（槽位补齐的**终点就是一次写库**，
        漏传会让"多轮补齐"在最后一步被拒）。
        """
        from modules.candidates import missing_required_fields

        session = self._session(context_id)
        pending = session.get("pending_save") or {}
        q = (query or "").strip()
        draft = dict(pending.get("draft") or {})

        # ① 明确放弃
        if any(w in q for w in self._SAVE_CANCEL_WORDS):
            session.pop("pending_save", None)
            return {
                "type": "candidate_save_failed",
                "soft_error": True,
                "error": "好，这次不入库了。想存的时候说一声「把这个品加进选品库」就行。",
            }

        # ② 用户在说别的事（含其他结构化意图）→ 放弃 pending，回到常规分类
        # ★★ 点名技能同样算「在说别的事」（第 246 轮）：不拦的话，用户点了卡
        #   片之后恰好被追问过入库槽位时，这句话会被**当成槽位答案吃掉** ——
        #   点名通道根本没机会跑。判定复用机制层唯一真源（自带短路 ⇒ 点名时
        #   连分类都不必做）。
        if is_skill_requested() or await self._classify_intent(q) != "general":
            session.pop("pending_save", None)
            return None

        asins = self._extract_multiple_asins(q)
        if asins and not draft.get("asin"):
            asin = asins[0]
            draft["asin"] = asin
            # 顺手把标题补上：先看本会话蓝海结果，再查商品详情
            hit = next(
                (p for p in self._last_products(context_id)
                 if (p.get("asin") or "").upper() == asin),
                None,
            )
            if hit:
                draft["product"] = hit
                draft["title"] = draft.get("title") or (hit.get("title") or "").strip()
            else:
                try:
                    detail = await self.adapter.get_product_detail(asin)
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"[product_research] pending save detail failed: {e}")
                    detail = None
                if detail:
                    draft["title"] = draft.get("title") or (detail.title or "").strip()

        elif not draft.get("title"):
            # 没给 ASIN → 当作「补商品名 / 标题」
            named = await self._resolve_named_product(q, context_id)
            if named:
                draft["product"] = named
                draft.setdefault("asin", (named.get("asin") or "").strip())
                draft["title"] = (named.get("title") or "").strip()
            else:
                # 拿用户原话当标题（去掉首尾标点与动作词残留）
                text = q.strip(" \t\r\n「」\"'。,.，")
                if text:
                    draft["title"] = text

        missing = missing_required_fields(draft)
        if missing:
            return self._ask_for_save(context_id, draft, missing, pending.get("hint") or "")

        session.pop("pending_save", None)
        product = dict(draft.get("product") or {})
        product["asin"] = product.get("asin") or draft.get("asin") or ""
        product["title"] = product.get("title") or draft.get("title") or ""
        return await self._write_candidates([product], context_id, shop_id)

    async def _write_candidates(
        self,
        targets: List[dict],
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> dict:
        """
        真正写库：批量 + **把判重交给写入口**。

        与面板走**同一个写入口**（`candidates/service.create_candidate`），
        所以字段默认值与前端按钮完全一致 —— 判重也走同一个入口
        （`on_duplicate="skip"`），本层**不再自己查一遍**。

        ★ 第 216 轮：此前判重是**在本层手写**的（`candidate_exists` 先查、再
          `create_candidate`），而自称「唯一写入口」的 `create_candidate` 内部
          不判重、REST `POST /api/v1/candidates` 完全无判重
          ⇒ 判重成了**孤儿**：只有对话这条路在判，前端手动录入那条路继续
          累积重复行（实测库里 `B0CXXXX009` 三条）。这是「同一判定两份实现」
          的反面 —— **一份实现挂错了地方**。现在收口在写入口。

        ★★★ `shop_id` 必须**显式传入**（P0 安全修复 2026-09-16，BOLA）
            修复前这里直读 `core.tenant.middleware.tenant_context.shop_id`
            （★ C4 2026-09-16：该符号已随账户侧收拢删除，此处仅为事故记录），
            而那个值由 `TenantMiddleware` 用**未校验的原始 `X-Shop-ID` 头**写入
            ⇒ 「带自己的 token + 改一下请求头」就能把候选写进别人的选品库
              （探针 r84d 实测三段对照：有校验的端点 403，本路径 200 且落库
                 shop_id = 受害店铺）。
            为什么旧写法特别隐蔽：读的是"看起来很干净"的 request-scoped 缓存，
            脏数据在上游写进去，本处完全看不出问题。

        ★ 无店铺上下文 ⇒ **硬拒绝**（可读失败 + 零数据库往返）。
          不用"写空分区"兜底：`shop_id` 为空会撞 `fk_*_shop_id_stores_store`
          外键 → 500 且把 SQLAlchemy 报错与约束名吐给客户端（见 shop_id 空值
          守卫那段修复），而且归因文案会变成"数据库不可用"，误导排查方向。
        """
        from modules.candidates import create_candidate

        shop_id = (shop_id or "").strip() or None
        if shop_id is None:
            return {
                "type": "candidate_save_failed",
                "error": (
                    "还没选择店铺，我这边没法入库。请先在界面左上角选一个店铺，"
                    "再说一次「把……加进选品库」。"
                ),
            }

        saved: List[dict] = []
        skipped: List[str] = []
        failed: List[str] = []
        for p in targets:
            payload = self._candidate_payload_from_product(p)
            # 判重**不在这一层做了**（第 216 轮收口进写入口）：
            # `on_duplicate="skip"` ⇒ 同店同 ASIN 已存在则不插入、
            # 返回值里 `deduped=True`，本层据此把它归到 skipped。
            # 否则「Agent 判重、REST 不判重」= 同一判定一份实现挂在错地方。
            #
            # ★ 判重查询失败**不再吞掉**（改前那份 try/except 是静默退化）：
            #   判重坏掉以后重复行会悄悄重新长出来，且没有任何可观测信号。
            #   现在失败会被下面的 `except` 归到 `failed` —— 老板看得见。
            try:
                created = await create_candidate(
                    payload, shop_id=shop_id, on_duplicate="skip"
                )
            except Exception as e:
                logger.warning(f"[product_research] save_candidate failed for {payload['asin']}: {e}")
                failed.append(payload["asin"] or "未知 ASIN")
                continue
            if created.get("deduped"):
                # 已存在 ⇒ 回的是库里那条（不是本次 payload），只报「未重复写入」
                skipped.append(
                    f"{(payload['title'] or '未命名')[:28]}（{payload['asin'] or '—'}）"
                )
            else:
                saved.append(created)

        if not saved and not skipped:
            return {
                "type": "candidate_save_failed",
                "error": "写入选品库失败（数据库不可用），请稍后重试。",
            }

        parts: List[str] = []
        if saved:
            names = "、".join(
                f"{(s.get('title') or '未命名')[:28]}（{s.get('asin') or '—'}）" for s in saved
            )
            parts.append(f"已加入选品库（待评审）：{names}")
        if skipped:
            parts.append(f"已在选品库中、未重复写入：{'、'.join(skipped)}")
        if failed:
            parts.append(f"{len(failed)} 个写入失败（{', '.join(failed)}）")

        return {
            "type": "candidate_saved",
            "saved": saved,
            "skipped": skipped,
            "failed": failed,
            "summary": "；".join(parts),
        }

    async def _save_candidate(
        self,
        query: str,
        context_id: Optional[str] = None,
        shop_id: Optional[str] = None,
    ) -> dict:
        """
        把商品写入选品库（对话直达）。

        `shop_id` 是**已校验归属**的店铺 ID（来自 `get_current_shop_id*` 依赖）。
        不传 = 拿不到归属 = `_write_candidates` 拒绝写入，绝不"猜一个"。

        这是前端「蓝海结果卡 → 勾选 → 选分组 → 保存」那条**面板流程的免填版**：
        字段契约与面板一致（必填 ASIN / 商品标题，单点定义在 `modules/candidates/service.py`），
        差别只在交互方式：
          - 必填缺失 → **多轮追问补齐**（`_ask_for_save` 记 pending，`_resume_pending_save` 续填）
          - 可选缺失 → 后台按默认值自动补，**不打扰用户**（含面板里那个人工交互「选分组」）

        目标商品解析优先级：
          1. 查询里显式写了 ASIN → 用提到的（支持多个）
          2. 查询里写了序数（第一个 / 第2个 / top1）→ 取本会话上一次蓝海结果的对应位
             （越界则**追问**并告知实际条数，绝不静默折回 Top1）
          3. 查询里**点名了商品**（如整条标题）→ 去商品池按词边界匹配 Top1
          4. 纯指代（「这个品」「刚才那个」）→ 本会话上一次蓝海结果的 Top 1
        解析不到 / 必填凑不齐 → 追问，**绝不写半成品或空壳**。

        另有**同店铺同 ASIN 判重**：已收口在**写入口**
        `candidates/service.create_candidate`（`on_duplicate="skip"`）——
        本层不再自己查一遍，否则「对话这条路判重、REST 那条不判重」
        就是同一判定一份实现挂在错地方。已在库中则不重复写入。
        """
        last_products: List[dict] = self._last_products(context_id)

        targets: List[dict] = []
        asins = self._extract_multiple_asins(query)
        if asins:
            for a in asins:
                hit = next(
                    (p for p in last_products if (p.get("asin") or "").upper() == a),
                    None,
                )
                if hit is None:
                    detail = await self.adapter.get_product_detail(a)
                    if detail:
                        hit = {**detail.model_dump(), "asin": detail.product_id,
                               "main_image": detail.image_url}
                if hit:
                    targets.append(hit)
                else:
                    # 给了 ASIN，但本会话蓝海结果与商品库里都没有它 → 标题就是缺的。
                    # 面板里标题是必填项，所以这里追问补齐，而不是拿 ASIN 当标题硬写。
                    return self._ask_for_save(
                        context_id,
                        draft={"asin": a},
                        missing=["title"],
                        hint=f"商品 {a} 不在商品库里，把它的标题发我就能入库。",
                    )
        else:
            idx = self._extract_ordinal(query)
            if idx is not None:
                # 序数越界**不能静默折回 Top1**：「把第 9 个加进去」存成第 1 个
                # 属于「答非所问地写库」，比不写更糟（用户会以为存对了）。
                if not last_products:
                    return {
                        "type": "candidate_save_failed",
                        "error": f"还没有可选的商品清单。先让我挖一轮蓝海，"
                                 f"再说「把第 {idx + 1} 个加进选品库」。",
                    }
                if not (0 <= idx < len(last_products)):
                    return {
                        "type": "candidate_save_failed",
                        "error": f"上一轮只有 {len(last_products)} 个商品，没有第 {idx + 1} 个。"
                                 f"可以说「把第 1~{len(last_products)} 个加进选品库」。",
                    }
                targets.append(last_products[idx])
            else:
                # 查询里若**点名了商品**（如整条标题），必须去商品池核对；
                # 否则一旦落到「上一轮 Top1」，就会出现「点名宠物喂食器、存进瑜伽垫」。
                named = await self._resolve_named_product(query, context_id)
                if named:
                    targets.append(named)
                elif self._named_tokens(query):
                    # 点名了但池里匹配不到 → 不能改存别的商品充数（实测会存成上一轮 Top1），
                    # 转成「缺 ASIN」的待补项：用户给了 ASIN 就能入库。
                    hint = " ".join(self._named_tokens(query))[:60]
                    return self._ask_for_save(
                        context_id,
                        draft={"title": hint},
                        missing=["asin"],
                        hint=f"商品库里没找到「{hint}」，给我 ASIN（如 B0KLMN3456）就能入库。",
                    )
                elif last_products:
                    # 纯指代（「这个品」「刚才那个」）——才允许取上一轮 Top1
                    targets.append(last_products[0])

        if not targets:
            # 完全没说清要入哪个：记 pending 追问，用户下一句回答会被当槽位填充
            return self._ask_for_save(
                context_id,
                draft={},
                missing=["asin", "title"],
                hint="可以直接给我 ASIN（如 B0KLMN3456），或把商品标题贴给我。",
            )

        # 目标解析完成 → 写库（与前端面板同一个写入口）
        return await self._write_candidates(targets, context_id, shop_id)

    async def stream_chat(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterable[str]:
        """
        流式对话 —— **外层入口**：绑上下文 → 入口 hydrate → 委托实现体 → 出口 flush。

        ★ `finally` 里的 flush 是**尽力而为**：消费者中途断开（客户端断流）时
          生成器被 `aclose()`，`finally` 仍会跑，但那时任务往往已被取消，
          里面的 await 会立刻抛 `CancelledError` ⇒ 这次落盘跳过。
          可接受：未落盘的内存态还在容器里，而 `_hydrate_state()` 会在下一个请求
          的入口先把它补写出去（见其 docstring），状态不会丢。
        ★ 实现体是 `_stream_chat_impl()` —— 决策路径一个字都没变。
        """
        self._bind_context(context_id, shop_id, user_id)
        await self._hydrate_state(context_id)
        try:
            async for chunk in self._stream_chat_impl(
                query, context_id, shop_id, user_id
            ):
                yield chunk
        finally:
            await self._flush_state(context_id)

    async def _stream_chat_impl(
        self,
        query: str,
        context_id: str = None,
        shop_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> AsyncIterable[str]:
        """
        流式对话（逐 token 返回 LLM 文本）的**实现体**；入口见 `stream_chat()`。

        **决策路径与 `invoke` 完全一致** —— 流式只是输出形式，不是另一套智能：
          1. pending 入库槽位 → 续填
          2. 关键词表命中结构化意图 → 执行；结论仍一次性下发（它本就是结构化清单，
             不是逐字生成的），并补 `meta` 让前端出卡
          3. 未命中 → **LLM 工具路由（流式版 `_stream_via_tools`）**，与非流式同路径
          4. 路由不可用 → 带会话语境的 LLM 闲聊流式

        先前「流式只走关键词表」的分叉，会让表里没有的说法在两条路径上表现不一致：
        实测「…帮我入库」在流式下被判成 general，丢掉商品名去编通用市场分析。

        Yields:
            文本片段 / progress / meta 事件（供 ai_infra.sse.sse_event_stream 包装成 SSE）
        """
        # 0. 会话 ID / 店铺归属 / 身份 已在外层 `stream_chat()` 里绑好（连同入口
        #    hydrate）。这里不再绑 —— 重复绑定一旦少传参数就会把 ContextVar
        #    覆盖成 None，作用域随之漂移。
        #
        # 1. 入库槽位续填优先：上一轮追问过「还差什么」，本轮回答直接当槽位填充。
        #    少了这一步，「多轮补齐」就无从进行 —— 用户回「就那个加湿器」会被判成 general。
        if self._session(context_id).get("pending_save"):
            resumed = await self._resume_pending_save(query, context_id, shop_id)
            if resumed is not None:
                yield self._compose_reply(resumed)
                return

        # 2. 关键词表命中结构化意图 → 直接执行
        # ★★ 点名技能 ⇒ **禁用关键词短路**（第 246 轮，与非流式**同一判据**）：
        #   短路分支不构造 system prompt，技能正文一次都渲染不到。
        #   ★ `general` 不命中 `_APPROVAL_GATED_INTENTS` / `INTENT_SHORTCUTS` /
        #     `QUERY_CANDIDATES_INTENT` ⇒ 与「清点类」一样一路落到尾部工具路由。
        intent = "general" if is_skill_requested() else await self._classify_intent(query)
        # ★★★ 第 131 轮：`save_candidate` **故意**从下面这个元组里拿掉 ——
        #   它是有副作用的写操作，必须经带 HITL 审批的工具路径执行。
        #   留在这里就等于「流式下说『入库』零审批直写」（旁路），
        #   而同一句话走非流式却要审批。详见 `_stream_gated_intent` 的 docstring。
        if intent in self._APPROVAL_GATED_INTENTS:
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析…"))
            async for chunk in self._stream_gated_intent(
                query, context_id, user_id, shop_id
            ):
                yield chunk
            return
        # ★ 这批意图**不短路**：一路落到函数尾部的工具路由（与 `general` 同一条
        #   路），这里只补一句进度文案 —— 让老板知道「在读数」而不是「在挖矿」。
        #   （改前「现在有多少选品了」被判成 blue_ocean，于是先报
        #   「正在挖掘蓝海品类数据…」再直接开挖 —— 截图里那条；
        #   第 325 轮的「现在哪个品类蓝海分最高」是同一条病 ⇒ 共用一份名单。）
        if intent in PROGRESS_ONLY_INTENTS:
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析…"))
        # ★ 与 `invoke` 共用 `INTENT_SHORTCUTS`（同一规则只允许一份表达）。
        if intent in INTENT_SHORTCUTS:
            yield progress(_INTENT_PROGRESS.get(intent, "正在分析…"))
            result = await self._process_query(query, context_id, intent, shop_id)
            yield result.content
            # 结构化载荷随流下发：前端据此在**同一列**（对话消息内）渲染「结论卡」，
            # 并写入「最近结果」槽（清空会话后仍可找回）。
            # 注意：content 已自带完整结论清单，即便前端不认 display_type 也能读懂；
            # meta 只是把同一份结论的**结构化形态**补上，属于增强而非依赖。
            # 追问/报错类结果（含 error 键）不出卡——那不是结论，弹卡反而制造噪音。
            # 入库类结果同样不出卡：它是「动作回执」不是「分析结论」，
            # 出卡会污染「最近结果」槽（把刚存进库的商品卡顶掉）。
            _META_SKIP_TYPES = {"candidate_saved", "candidate_save_failed", "general_response"}
            is_conclusive = (
                isinstance(result.data, dict)
                and not result.data.get("error")
                and result.data.get("type") not in _META_SKIP_TYPES
            )
            if result.data and is_conclusive:
                yield {
                    "event": "meta",
                    "data": {
                        "display_type": result.display_type or "general",
                        "data": result.data,
                    },
                }
            return

        # 3/4. 未命中关键词表 → 与非流式同一条 LLM 工具路由（内部已含闲聊兜底）
        produced_text = False
        async for chunk in self._stream_via_tools(query, context_id, user_id):
            if isinstance(chunk, str) and chunk.strip():
                produced_text = True
            yield chunk
        # ★ 点名技能、但技能通道没产出任何正文 ⇒ 如实说（不让关键词表顶上）。
        #   ★ 未点名时这一句不生效 ⇒ 上面那圈只是多记一个布尔，行为不变。
        if is_skill_requested() and not produced_text:
            yield SKILL_CHANNEL_UNAVAILABLE

    # ====== 内部辅助方法（纯解析 / 评分层已外移） ======
    #
    # P0-6 第一刀把下面这批**不依赖实例状态**的方法搬到了
    # `agent_helpers.py::ResearchHelpersMixin`（本类继承它，调用点零改动）：
    #   _extract_category      _generate_search_keywords  _calculate_opportunity_score
    #   _generate_reason       _estimate_price_range     _estimate_margin
    #   _generate_improvement_suggestions
    #   _extract_product_info  _extract_asin             _extract_multiple_asins
    #   _extract_ordinal
    #
    # 判据是形态不是口味：这 11 个函数体里一个 `self` 都没有 ⇒ 它们不需要 Agent 实例，
    # 留在类里只会让「类目映射表」「机会评分公式」必须造实例才能测。
    #
    # 下面这个常量**留在本类**：消费方是 `_named_tokens`（实例方法，未外移）。

    # 英文「动作/指令」词：出现它们**不代表**用户点名了商品。
    # 若不过滤，「add this to candidate library」会被判成「点名了商品但池里没匹配上」→ 误追问。
    _SAVE_ACTION_WORDS = {
        "add", "save", "insert", "put", "into", "to", "my", "this", "that", "it",
        "please", "candidate", "candidates", "library", "pool", "list", "collection",
        "item", "items", "product", "products", "cart", "wishlist", "new",
    }

    async def _process_query(
        self,
        query: str,
        context_id: str = None,
        intent: str = None,
        shop_id: Optional[str] = None,
    ) -> AgentResponse:
        """处理查询（内部方法）。

        `intent` 由调用方传入时跳过重复分类 —— `invoke`/`stream_chat` 已经判过一次，
        再判一次纯属浪费；而且两条路径必须落在**同一个** intent 上。

        ★ `query_candidates`（候选存量清点）**不进**这张表：清点是一个读库问题，
          由工具路由交给 LLM 调 `list_candidates` 作答。这里加一个 query 分支
          等于把「怎么答」也钉死在关键词层（本轮 bug 的病根正是「答法被钉死」）。
          真被传进来时它落到 `else` 的闲聊分支 —— 属于调用方错误，非正常路径。
        """
        if intent is None:
            intent = await self._classify_intent(query)

        if intent == "blue_ocean":
            result = await self._analyze_blue_ocean(query, context_id)
        elif intent == "profit":
            result = await self._analyze_profit(query)
        elif intent == "pain_points":
            result = await self._analyze_pain_points(query)
        elif intent == "competitor":
            result = await self._analyze_competitors(query)
        elif intent == "save_candidate":
            result = await self._save_candidate(query, context_id, shop_id)
        else:
            result = await self._general_chat(query)

        return AgentResponse(
            content=self._compose_reply(result),
            data=result,
            display_type=result.get("type", "general"),
        )

    # 趋势英文标识 → 中文（面向老板的文案不出现 rising/stable）
    _TREND_CN = {"rising": "上升", "up": "上升", "stable": "平稳", "flat": "平稳", "declining": "下滑", "falling": "下滑", "down": "下滑"}

    @classmethod
    def _format_blue_ocean_reply(cls, result: dict) -> str:
        """
        蓝海结果 → **自带清单**的正文。

        `summary` 只报汇总数，答不了老板真正问的「有哪些」，所以正文必须逐条列出。

        主列表列的是**商品**而不是关键词：
          - 商品有 ASIN / 售价 / 月销 / ROI，能直接对比、直接入库；
          - 关键词只是中间产物（「往哪个方向找」），且**无法入库**
            （候选库以 asin 为核心标识）。
        词没有消失，而是降级为商品的**来源标注**（连同该词的市场层指标）。
        商品池无匹配时才降级回词清单。
        """
        products = result.get("products") or []
        opportunities = result.get("opportunities") or []
        summary = result.get("summary") or ""

        # 去掉「（已列出高潜 Top N）」这类空承诺——下面真的会列出来
        overview = summary.split("（已列出")[0].rstrip("，,。 ") + "："

        if products:
            lines = [overview, ""]
            for idx, p in enumerate(products, 1):
                trend = cls._TREND_CN.get(
                    (p.get("keyword_trend") or "").lower(), p.get("keyword_trend") or "—"
                )
                competition = p.get("keyword_competition")
                competition_text = (
                    f"{competition:.0%}" if isinstance(competition, (int, float)) else "—"
                )
                roi = p.get("roi") or p.get("roi_estimated") or 0
                lines.append(
                    f"{idx}. **{p.get('title') or '未命名商品'}**（{p.get('asin') or '—'}）"
                )
                lines.append(
                    f"   - 售价 ${float(p.get('price') or 0):.2f}"
                    f" ｜ 月销 {int(p.get('estimated_monthly_sales') or 0):,}"
                    f" ｜ 评论 {int(p.get('review_count') or 0):,}"
                    f" ｜ 预估 ROI {roi}%"
                )
                lines.append(
                    f"   - 来源机会词：{p.get('source_keyword') or '—'}"
                    f"（月搜索 {int(p.get('keyword_search_volume') or 0):,}"
                    f" ｜ 竞争度 {competition_text} ｜ 趋势 {trend}）"
                )
            lines += ["", "要入库直接说「把第 1 个加进选品库」；换类目说「找厨房用品的蓝海机会」。"]
            return "\n".join(lines)

        if not opportunities:
            return summary or "这次没跑出达标的蓝海机会，建议换个类目或放宽筛选条件。"

        # ===== 降级：商品池无匹配，只能给词方向 =====
        lines = [overview, ""]
        for idx, opp in enumerate(opportunities, 1):
            name = opp.get("category") or "未命名"
            score = opp.get("opportunity_score") or 0
            volume = opp.get("search_volume") or 0
            competition = opp.get("competition")
            trend = cls._TREND_CN.get((opp.get("trend") or "").lower(), opp.get("trend") or "—")
            competition_text = f"{competition:.0%}" if isinstance(competition, (int, float)) else "—"

            lines.append(
                f"{idx}. **{name}** ｜ 机会分 {score:.0f} ｜ 月搜索 {volume:,} "
                f"｜ 竞争度 {competition_text} ｜ 趋势 {trend}"
            )
            if opp.get("reason"):
                lines.append(f"   - 理由：{opp['reason']}")
            if not opp.get("matched_count"):
                lines.append("   - 商品池暂无匹配商品，可先用这个词去找货源")

        lines += ["", "想看某个类目的更多细节，可以直接说「找厨房用品的蓝海机会」。"]
        return "\n".join(lines)

    @classmethod
    def _compose_reply(cls, result: dict) -> str:
        """
        把分析结果压成给老板看的一段话。

        **绝不用 `json.dumps(result)` 当正文**——那会把内部结构原样丢给用户，
        实测出现过 `{"error":"请提供至少 2 个产品 ASIN 进行对比"}` 这种裸 JSON。
        """
        if result.get("type") == "blue_ocean_analysis":
            # 蓝海类结论「说有几个」不够，必须「列出有哪些」
            return cls._format_blue_ocean_reply(result)
        if result.get("summary"):
            return result["summary"]
        if result.get("response"):
            # _general_chat 的正文（能力引导文案）
            return result["response"]
        if result.get("error"):
            # soft_error 标记的是「追问 / 用户主动取消」这类**对话的正常步骤**，
            # 文案本身已是人话；套上「这次没跑通」会把一次正常交互说成事故。
            if result.get("soft_error"):
                return result["error"]
            return f"这次没跑通：{result['error']}"
        return "分析已完成。"
