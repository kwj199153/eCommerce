"""
BaseAgent 基类 - **所有业务 Agent 的唯一基类**

设计思路（融合两个参考项目）：
- 推理循环：参考项目2 (A2A LangGraph-a2a/common/base_agent.py)
  • StateGraph 构建: LLM Call → Tool Call → Respond
  • 路由逻辑: should_continue() 决定下一步
- HITL 机制：参考项目1 (ReActAgentHIL/infrastructure/tools.py)
  • interrupt() 包装器实现人工审批
  • 支持 accept/reject/edit/response 四种响应
- 记忆管理：PostgreSQL Checkpoint 持久化
- Token 统计 & 成本控制

★ 本类同时提供「两套 LLM 槽位」，二者**不可互相替代**（实测方法集合交集为空）：

    self.llm         → LangChain ``BaseChatModel``（ChatOpenAI 指向 DashScope 兼容端点）
                       • 能力: bind_tools() / ainvoke() / astream_events()
                       • 用途: LangGraph 图内核 —— 工具路由、多轮 ReAct
                       • 产出: AIMessage.tool_calls

    self.llm_client  → 自研 ``DashScopeLLM``（原生 httpx）
                       • 能力: chat() / structured_chat() / chat_stream()
                       • 用途: RAG 检索问答、纯文本/结构化生成
                       • 产出: LLMCallResult

历史背景：这两套能力原先分裂在两个互不继承的类里——
``base_agent.BaseAgent``（图编排）与 ``llm.integration.LLMEnabledAgent``（LLM 原语），
业务 Agent 只继承后者，于是拿不到工具循环与 HITL；而后者内部又有一份
对 LangChain 侧无用的转发壳。本文件把它们收敛为**单一基类**，
业务 Agent 继承本类即同时获得两种能力，按需使用。

使用方式：
    from ai_infra.base_agent import BaseAgent

    class MyAgent(BaseAgent):
        DEFAULT_MODEL = "qwen-max"

        def __init__(self):
            super().__init__(                 # 全部参数均有默认值
                agent_name="MyAgent",
                system_prompt=MY_SYSTEM_PROMPT,
                tools=[my_tool_a, my_tool_b, ...],
                hitl_tools=["export_report"],  # 需要人工审批的工具
            )

        # ★ 基类**不提供** invoke/stream —— 入口契约由各业务模块自定义
        async def invoke(self, query: str):
            # 用 LLM 原语（走 DashScopeLLM）
            r = await self.llm_chat(query, system_prompt=self.system_prompt)
            ...

★ 本文件与业务无关：`ai_infra` 不 import `modules.*`；业务提示词、业务知识语料、
  业务维度（如 shop_id）都归业务模块。分层门禁见 `tests/test_infra_layering.py`。
"""

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterable, Dict, List, Optional, Union

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from ai_infra.budget import (
    DEFAULT_BUDGET,
    AgentBudget,
    BudgetExceeded,
    BudgetVerdict,
    check_budget,
)
from ai_infra.context import (
    DEFAULT_CONTEXT_POLICY,
    ContextPolicy,
    trim_history,
)
from ai_infra.plan import (
    PLANNING_GUIDE,
    TODOS_STATE_KEY,
    normalize_todos,
    plan_summary,
    planner_tools,
    render_plan_block,
)
from ai_infra.prompt_sections import (
    PromptContext,
    collect_prompt_sections,
)
from core.config import config
from core.logger import get_logger
from core.observability.context import current_user_id

logger = get_logger(__name__)


# ====== LLM 调用结果 ======
@dataclass
class LLMCallResult:
    """LLM 调用结果。

    原定义在 ``ai_infra.llm.integration``（随该壳一起并入本模块）。
    """
    success: bool
    content: Union[str, Dict, List] = ""
    raw_text: str = ""
    tokens_used: int = 0
    cost: float = 0.0
    latency_ms: float = 0.0
    fallback: bool = False       # 是否使用了降级响应
    error: Optional[str] = None
    # RAG 来源（原实现以 `_sources=` 传入，但 dataclass 无此字段 →
    # 成功路径必抛 TypeError 并被 except 吞掉，症状是「RAG 问答永远降级成普通 LLM」）
    sources: List[Dict] = field(default_factory=list)
    # RAG 综合置信度（RAGResponse.confidence 早已算好 = sources 平均分，但旧
    # `llm_rag_answer` 从不往外传 ⇒ 消费端 `getattr(r,'confidence',0)` 恒为 0，
    # 前端看到的 RAG 置信度永远是 0。★ 与 sources 同源：生产者不传=消费者静默 0）
    confidence: float = 0.0


# ====== Agent 状态定义 ======
class AgentState(MessagesState):
    """Agent 状态 Schema"""
    # 结构化响应（用于返回标准化结果）
    structured_response: Optional[dict] = None
    # ★ 第 159 轮（批 D3）：这里原先有一个 `metadata: dict = {}` —— 已删除。
    #   它是**只写不读的死重量**：唯一出口是 `default_metadata` → 本字段，
    #   而全仓 0 处读 `state["metadata"]`；写进去的只有「角色标记」
    #   （`metadata={"role": "sub_agent_router"}`），而那些标记也从未被读过。
    #   ★ 旧的护航门禁只钉「是不是自由字典」（形式），所以它合规地死了下去 ——
    #     判据必须钉**有没有人读**（性质）。见 `DETAILS/架构与横切收敛.md`。

    #: 预算耗用与超限结论（第 145 轮 · 批 C5）。
    #:
    #: ★ 生产者 `_llm_call_node`，消费者 `_respond_node`（以及直接读
    #:   `graph.ainvoke()` 返回 state 的业务调用方）。它存在的意义是把
    #:   「这次是被预算截断的」变成**调用方读得到**的状态 —— 此前只有一条
    #:   WARNING 日志，图返回的 state 与「模型自己答完了」完全一样。
    #:
    #: 键：`spent_tokens` / `iterations`（本轮耗用）、`truncated`（超限维度，
    #:     仅**真截断**时写）、`limit` / `used` / `message`（超限结论）、
    #:     `context`（本次请求的**上下文裁剪**结论，见 `ai_infra.context.TrimReport`；
    #:     第 147 轮 · 批 C4）。
    #:
    #: ★ `context` 与 `truncated` **不是**同一件事，别合并看待：
    #:   裁剪是长会话的**常态**（会话继续跑下去），截断是预算耗尽的**终局**
    #:   （本轮到此为止）。前者不该让 status 变红，后者必须让它变红 ——
    #:   把两者合成一个字段，就会要么「长会话每次都被报成失败」，
    #:   要么「真截断了却没人知道」。
    budget: dict = {}

    #: 子任务清单（第 148 轮 · 批 C3）。生产者 = `ai_infra.plan` 的两个工具
    #: （`plan_tasks` / `update_task`），消费者 = `_llm_call_node`（每轮渲染进
    #: system prompt）、`_respond_node`（进 `structured_response.plan`），
    #: 以及直接读图返回 state 的业务调用方与前端。
    #:
    #: ★ 它**不在 `messages` 里**，这是设计要点而非偶然：`ai_infra.context` 的
    #:   历史裁剪只作用于消息序列，计划放在这里就**结构上不可能被裁掉**。
    #:   此前若把计划写在回复正文里，第 147 轮批 C4 加的历史裁剪会把它当旧历史
    #:   一起裁掉 —— 裁完模型就"忘了还要做什么"。
    #:
    #: ★ 为什么用默认的「覆盖」更新语义、不自定义 reducer：两个规划工具**总是
    #:   返回完整的新列表**，覆盖即正确语义。自定义 reducer（把两份列表合并）
    #:   反而引入歧义 —— 重规划本该整体替换，合并会让旧步骤赖着不走。
    todos: list = []


class BaseAgent:
    """
    所有业务 Agent 的**唯一**基类

    提供通用能力：
    1. LangGraph 推理循环（LLM → Tool → LLM → ... → Respond）
    2. HITL 人工审批机制（可选工具级别）
    3. PostgreSQL Checkpoint 持久化
    4. Token 用量统计 & 成本估算（含请求级计费上报）
    5. 错误处理 & 重试机制
    6. **LLM 可用性判据 / 降级 / RAG**（原 LLMEnabledAgent 的能力）
       —— 见 `llm_client` / `rag_engine` / `llm_chat` / `_mock_result`
    """

    # ====== LLM 配置（子类可覆盖）======
    DEFAULT_MODEL: str = "qwen-plus"     # 默认模型（均衡性能）
    ANALYSIS_MODEL: str = "qwen-max"     # 复杂分析任务模型
    ENABLE_LLM: bool = True              # 总开关（关闭则全部走降级）
    ENABLE_RAG: bool = False             # 是否启用 RAG（通用检索增强，业务按需开启）
    FALLBACK_TO_MOCK: bool = True        # LLM 失败时是否降级
    #: 是否启用**自主规划器**（第 148 轮 · 批 C3）。开启后基类自动装配
    #: `plan_tasks` / `update_task` 两个工具，并在每轮把当前计划渲染进 system prompt。
    #: 默认关 —— 「先规划后执行」对多步骤任务有价值，对单轮问答只是多余开销。
    ENABLE_PLANNING: bool = False
    #: checkpointer 的线程命名空间（`thread_id` 前缀）。
    #: 空串 ⇒ `thread_id` 就是裸 `session_id`（`secretary` 的历史口径，勿改）；
    #: 非空 ⇒ `f"{ns}:{session_id}"`，用于隔离不同 Agent 的会话记忆。
    CHECKPOINT_NAMESPACE: str = ""

    #: 「无会话」的**显式原因**——随 `config["metadata"]` 传给图与工具
    #: （第 145 轮 批 B4）。
    #:
    #: ★ 为什么要显式化：此前「缺会话」只表现为 `config == {}` —— 下游
    #:   （尤其 HITL 审批闸门）只能看到「没有 thread_id」这个**症状**，
    #:   看不到「为什么没有」。于是拒绝文案只能含糊地说「缺少会话上下文」，
    #:   用户分不清是「没登录」还是「前端没带 session_id」。
    #:   更根本的问题是：「无会话 ⇒ 所有需审批操作被拒」这条**语义从未被声明**，
    #:   它只是三处代码（`graph_for_session` 的分支、`_memoryless_graph()`、
    #:   `hitl_decorator` 的守卫）互相作用后**涌现**出来的结果 ——
    #:   改任何一处都可能悄悄改变它。现在它是一个具名常量、随 config 传播，
    #:   执行层可以原样引用它来解释拒绝原因。
    MEMORYLESS_REASON: str = (
        "本次调用没有可持久化的会话上下文（缺少 session_id 或 user_id）——"
        "按「没有身份 ⇒ 没有数据；没有会话 ⇒ 不留记忆」的原则，本次对话不会"
        "留下任何记忆，且所有**需要人工审批**的操作都会被执行层拒绝"
        "（审批状态无处落盘，无法追溯）。"
    )

    @property
    def max_iterations(self) -> int:
        """迭代上限 —— **只读视图**，真源是 `self.budget`。

        ★ 保留这个名字，是因为既有调用点与回归用例
          （`test_secretary_agent.py::test_max_iterations_strips_orphan_tool_calls`、
          `_should_continue` 的日志文案）都在读它。但它是**派生值**，
          不是独立配置 —— 要改迭代上限请改 `self.budget`（构造期用
          `budget=` 具名档位，或 `max_iterations=` 兼容形参）。

        ★ 为什么不让形参与预算并存：那就是两份真源。
          「档位说 4、形参说 10」时没人说得清哪个生效，而不生效的那份
          会在下一次「改了这里怎么没反应」时被重新发现一遍。
        """
        return self.budget.max_iterations

    def __init__(
        self,
        agent_name: Optional[str] = None,
        system_prompt: str = "",
        tools: Optional[list[BaseTool]] = None,
        llm: Optional[BaseChatModel] = None,
        hitl_tools: Optional[list[str]] = None,
        budget: Optional[AgentBudget] = None,
        context_policy: Optional[ContextPolicy] = None,
        enable_planning: Optional[bool] = None,
        max_iterations: Optional[int] = None,
        checkpointer: Optional[AsyncPostgresSaver] = None,
        checkpoint_ns: Optional[str] = None,
    ):
        """
        初始化 Agent

        ★ 所有参数都有默认值，因此子类可以 `super().__init__()` 无参调用
          （业务 Agent 自己设置 agent_name / system_prompt 并覆盖类配置）。

        Args:
            agent_name: Agent 名称（用于日志和标识），缺省取类名
            system_prompt: 系统 Prompt（业务专属，由子类定义）
            tools: 工具列表（业务专属，由子类定义）
            llm: LangChain 模型实例（默认懒加载 DashScope Qwen 兼容端点）
            hitl_tools: 需要 HITL 审批的工具名列表
            budget: 运行预算（迭代 / token / 墙钟，见 `ai_infra.budget`）。
                缺省 `DEFAULT_BUDGET`。★ 业务 Agent 应传一个**具名档位**
                （`BUDGET_ROUTER` / `BUDGET_INTERACTIVE`），而不是自己写数字。
            context_policy: 上下文窗口策略（历史裁剪 + 旧工具结果折叠，
                见 `ai_infra.context`）。缺省 `DEFAULT_CONTEXT_POLICY`。
                ★ 业务 Agent 应传一个**具名档位**（`CONTEXT_ROUTER` /
                `CONTEXT_INTERACTIVE`），而不是自己写数字。
                ★ 它与 `budget` 是**两件事**：预算管「跑多久 / 一共花多少」，
                上下文管「这一次发出去多大」。多轮会话必然需要裁剪，
                而裁剪不是失败。
            enable_planning: 是否启用**自主规划器**（`ai_infra.plan`）。
                缺省取类属性 `ENABLE_PLANNING`。开启后：① 自动装配
                `plan_tasks` / `update_task` 两个工具；② 每轮把当前计划渲染进
                system prompt —— 于是计划**不随历史裁剪而丢失**。
                ★ 与 `budget` / `context_policy` 的分工：后两者分别管「跑多久」
                与「一次发多大」，本项管「有没有一张跨轮存活的计划」。
                三者是三个维度，不是同一件事的三个开关。
            max_iterations: 【兼容形参，建议改用 `budget`】只改写预算里的
                迭代上限。★ 它**不构成第二份真源**：内部被折进 `budget`，
                此后一切判定只读预算（见同名 property）。
            checkpointer: LangGraph checkpointer（PostgreSQL 持久化，None 则内存态）
            checkpoint_ns: checkpointer 的线程命名空间（`thread_id` 前缀）。
                缺省取类属性 `CHECKPOINT_NAMESPACE`；空串 ⇒ 直接用 `session_id`
                （`secretary` 的历史口径，勿改）。
        """
        self.agent_name = agent_name or self.__class__.__name__
        self.system_prompt = system_prompt
        # ---- 运行预算：**唯一真源**（第 145 轮 批 C5）----
        # ★ `max_iterations=` 兼容形参在这里被**折进**预算，而不是与它并存：
        #   `AgentBudget` 是 frozen 的，`with_max_iterations` 返回新实例 ——
        #   于是「形参覆盖」也只是一个预算法，判定路径永远只有一条。
        self.budget = budget if budget is not None else DEFAULT_BUDGET
        if max_iterations is not None:
            self.budget = self.budget.with_max_iterations(max_iterations)
        # ---- 上下文窗口：历史裁剪的口径（第 147 轮 · 批 C4）----
        # ★ 与预算**分开**是真源划分，不是重复：若把「单次输入上限」塞进
        #   `AgentBudget`，`max_tokens` 这一个名字就同时指两件事
        #   （本轮累计耗用 vs 这一次的输入），而「一个名字两种含义」
        #   正是两份实现的开端（同族判据：同一概念两套 ID 空间）。
        self.context_policy = (
            context_policy if context_policy is not None else DEFAULT_CONTEXT_POLICY
        )

        # ---- 自主规划器开关（第 148 轮 · 批 C3）----
        # ★ 解析结果必须落成 **bool**：`None` 是「未指定」的哨兵（取类属性），
        #   若把 None 原样留着，下游 `if self.enable_planning:` 与
        #   `self.enable_planning is False` 两处判定会分叉 —— 一个当假、
        #   一个当"没说过"。同一个值有两种解释正是两份实现的开端。
        self.enable_planning = (
            bool(enable_planning)
            if enable_planning is not None
            else bool(self.ENABLE_PLANNING)
        )
        # ★ 可变默认参数的经典坑：`def f(x=[])` 的默认对象在**函数定义时创建一次**，
        #   所有调用者共享同一个 list/dict。原写法 `hitl_tools=[]` / `metadata={}`
        #   意味着任意 Agent 实例对它们的改动会传染给后续所有实例 ——
        #   在「一个进程内建多个 Agent」的场景下会串数据。
        #   改用 None 哨兵 + 进函数体后新建，彻底切断共享。
        hitl_tools = list(hitl_tools) if hitl_tools else []
        self.hitl_tool_names = set(hitl_tools)
        self.checkpointer = checkpointer
        # ★ 线程命名空间：见 `resolve_thread_id()`。子类可用类属性声明，
        #   组合式（router 子层）用构造参数传。
        self.checkpoint_namespace = (
            checkpoint_ns if checkpoint_ns is not None else self.CHECKPOINT_NAMESPACE
        )

        # ---- LLM 槽位 ①：LangChain 模型（图内核）----
        # ★ 懒解析，不在 __init__ 立即创建。原因（实测）：
        #   缺 DASHSCOPE_API_KEY 时 ChatOpenAI(...) **构造即抛 OpenAIError**，
        #   原实现 `self.llm = llm or self._get_default_llm()` 会让「走图路径的
        #   Agent」在实例化阶段就崩；而不用图的业务 Agent 却要白白付这个风险。
        #   改为首次访问才解析 + 失败返回 None（由 _llm_with_tools 显式报错）。
        self._llm_override = llm
        self._llm_default: Optional[BaseChatModel] = None
        self._llm_resolved = False

        # ---- LLM 槽位 ②：DashScopeLLM（RAG / 纯文本）+ RAG 引擎（懒加载）----
        self._llm_client = None
        self._rag_engine = None
        self._llm_stats = {
            "total_calls": 0,
            "llm_calls": 0,
            "mock_calls": 0,
            "errors": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }

        # 处理 HITL 工具包装
        #
        # ★ 第 148 轮 批 C3：开启规划时由**基类自己**追加两个规划工具。
        #   为什么不让各业务 Agent 手写进 `tools=`：规划是基类能力
        #   （`AgentState.todos` 与 system prompt 注入都在基类），业务侧漏写一处
        #   的症状是「模型调不到 plan_tasks」—— 而模型**不会报错**，它只是不规划，
        #   界面上看不出任何异常。由基类无条件装配，业务侧只剩一个布尔开关。
        #
        # ★ `planner_tools` 是模块级共享对象：工具本身**无状态**（计划存在图的
        #   state 里，不在工具实例上），多个 Agent 复用同一批实例不会串数据；
        #   而 `_wrap_hitl_tools` 只在最外层建新 list、不改动元素。
        # ★ 它们声明为 `LOCAL_STATE_METADATA`（只写本地 state）⇒ 免 HITL 审批，
        #   所以「追加进去」不会给用户多出一步「请批准规划」的确认。
        _planner = list(planner_tools) if self.enable_planning else []
        self.tools = self._wrap_hitl_tools((list(tools) if tools else []) + _planner)
        if _planner:
            logger.info(
                f"🧭 [{self.agent_name}] 已启用自主规划器 "
                f"{[t.name for t in _planner]}（计划存于 state['{TODOS_STATE_KEY}']，"
                f"不随历史裁剪丢失）"
            )

        # ---- LangGraph 图懒构建 ----
        # ★ 不在 __init__ 建图：业务 Agent 只用 LLM 原语、不成为一张图，
        #   没有理由为它们付 ToolNode/StateGraph 的构建成本。
        #   需要图的一方（secretary、router 层）首次访问 `self.graph` 时构建。
        self._graph: Optional[Any] = None
        # 不带 checkpointer 的图（"无会话 ⇒ 不留记忆"用它；懒构建 + 缓存）
        self._graph_memoryless: Optional[Any] = None

        # 前向兼容：当前 MRO 的下一环是 object（无副作用）；保留此调用可确保
        # 未来若引入 mixin，基类初始化链不会断在中间。
        super().__init__()

        logger.info(
            f"✅ Agent 初始化完成: {self.agent_name} | "
            f"工具数: {len(self.tools)} | "
            f"HITL工具: {sorted(self.hitl_tool_names)}"
        )

    # ====== LLM 槽位 ①：LangChain 模型（图内核） ======

    def _get_default_llm(self) -> BaseChatModel:
        """获取默认 LLM（DashScope Qwen 兼容端点）"""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.llm_default_model,
            openai_api_key=config.dashscope_api_key,
            openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            timeout=config.llm_timeout_seconds,
        )

    @property
    def llm(self) -> Optional[BaseChatModel]:
        """LangChain 模型（懒加载，图内核专用）。

        返回 None 表示不可用（未启用 LLM / 缺 key / 初始化失败）——
        由 `_llm_with_tools` 在真正需要时给出显式错误，而不是在构造期抛异常。
        """
        if self._llm_override is not None:
            return self._llm_override
        if not self._llm_resolved:
            self._llm_resolved = True
            if not self.ENABLE_LLM:
                self._llm_default = None
            else:
                try:
                    self._llm_default = self._get_default_llm()
                except Exception as e:
                    logger.warning(
                        f"[{self.agent_name}] LangChain LLM 初始化失败，图路径不可用: {e}"
                    )
                    self._llm_default = None
        return self._llm_default

    # ====== LLM 槽位 ②：DashScopeLLM（原 LLMEnabledAgent 能力） ======

    @property
    def llm_client(self):
        """懒加载 DashScopeLLM 客户端（RAG / 纯文本场景）。"""
        if self._llm_client is None and self.ENABLE_LLM:
            try:
                from ai_infra.llm import get_llm

                self._llm_client = get_llm(model=self.DEFAULT_MODEL)
            except Exception as e:
                logger.warning(f"[{self.agent_name}] LLM init failed: {e}")
        return self._llm_client

    @property
    def rag_engine(self):
        """懒加载 RAG 引擎（仅当 ENABLE_RAG=True 时）。"""
        if self._rag_engine is None and self.ENABLE_RAG:
            try:
                from ai_infra.rag import HybridRAGEngine

                domain = (self.agent_name or "default").replace(" ", "_")
                self._rag_engine = HybridRAGEngine(domain=domain)

                # 若事件循环未在运行，顺手同步初始化；在运行时由调用方 await。
                import asyncio

                try:
                    loop = asyncio.get_event_loop()
                    if not loop.is_running():
                        loop.run_until_complete(self._rag_engine.initialize())
                except RuntimeError:
                    pass  # 事件循环未运行，稍后初始化
            except Exception as e:
                logger.warning(f"[{self.agent_name}] RAG init failed: {e}")
        return self._rag_engine

    async def initialize_rag(self, faq_items: List[Dict] = None):
        """初始化 RAG 引擎，并（可选）载入**调用方提供的**知识条目。

        ★ 基类只做两件事：把检索能力准备好 + 把**传入的**知识灌进去；
          **不预置任何业务语料**。

        原先这里还有一个 `else` 分支去调
        `KnowledgeBaseBuilder.build_customer_service_kb(...)` —— 基类因此认识
        「客服」这个业务域，而且该分支**不可达**：唯一调用点
        `modules/customer_service/agent_cs.py` 永远传 `faq_items`。
        业务知识库现归属 `modules/customer_service/knowledge.py`。

        Args:
            faq_items: FAQ 列表 [{"question": "...", "answer": "...", "category": "..."}]；
                       None 表示只初始化引擎、不载入知识。
        """
        if not self.ENABLE_RAG or not self.rag_engine:
            return

        try:
            await self.rag_engine.initialize()

            if faq_items:
                count = await self.rag_engine.add_faq_knowledge_base(faq_items)
                logger.info(f"[{self.agent_name}] RAG loaded {count} FAQ entries")
        except Exception as e:
            logger.error(f"[{self.agent_name}] RAG init error: {e}")

    # ---- 核心 LLM 调用方法 ----

    async def llm_chat(
        self,
        user_message: str,
        system_prompt: str = None,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        **kwargs,
    ) -> LLMCallResult:
        """标准 LLM 对话调用。

        Returns:
            LLMCallResult (success/content/fallback/error)
        """
        start_time = time.time()
        self._llm_stats["total_calls"] += 1

        if not self.ENABLE_LLM or not self.llm_client:
            return self._mock_result(user_message, "LLM disabled")

        try:
            response = await self.llm_client.chat(
                user_message,
                system_prompt=system_prompt,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )

            latency = (time.time() - start_time) * 1000
            self._update_llm_stats(response.total_tokens, response.cost, latency)

            return LLMCallResult(
                success=True,
                content=response.content,
                raw_text=response.content,
                tokens_used=response.total_tokens,
                cost=response.cost,
                latency_ms=latency,
                fallback=False,
            )

        except Exception as e:
            logger.error(f"[{self.agent_name}] LLM call error: {e}")
            self._llm_stats["errors"] += 1

            if self.FALLBACK_TO_MOCK:
                return self._mock_result(user_message, str(e))
            return LLMCallResult(
                success=False,
                error=str(e),
                latency_ms=(time.time() - start_time) * 1000,
            )

    async def llm_structured(
        self,
        user_message: str,
        system_prompt: str,
        output_format: str = "json",
        model: str = None,
        **kwargs,
    ) -> LLMCallResult:
        """结构化输出调用（JSON/表格/列表）。

        Returns:
            LLMCallResult (content 是解析后的 dict/list)
        """
        if not self.ENABLE_LLM or not self.llm_client:
            return self._mock_result(user_message, "LLM disabled", structured=True)

        try:
            result = await self.llm_client.structured_chat(
                user_message=user_message,
                system_prompt=system_prompt,
                output_format=output_format,
                model=model or self.ANALYSIS_MODEL,
                **kwargs,
            )

            return LLMCallResult(
                success=True,
                content=result,
                raw_text=(
                    json.dumps(result, ensure_ascii=False)
                    if isinstance(result, (dict, list))
                    else str(result)
                ),
                fallback=False,
            )

        except Exception as e:
            logger.error(f"[{self.agent_name}] Structured LLM error: {e}")
            self._llm_stats["errors"] += 1

            if self.FALLBACK_TO_MOCK:
                return self._mock_result(user_message, str(e), structured=True)
            return LLMCallResult(success=False, error=str(e))

    async def llm_rag_answer(
        self,
        query: str,
        system_prompt: str = None,
        top_k: int = 3,
    ) -> LLMCallResult:
        """RAG 增强回答（先检索再生成）。

        仅在 ENABLE_RAG=True 且 RAG 引擎已初始化时生效，否则退化为普通 LLM 调用。
        """
        start_time = time.time()
        self._llm_stats["total_calls"] += 1

        if not self.ENABLE_RAG or not self.rag_engine:
            return await self.llm_chat(query, system_prompt=system_prompt)

        try:
            rag_response = await self.rag_engine.answer(
                query=query,
                llm_client=self.llm_client,
                system_prompt=system_prompt,
                top_k=top_k,
            )

            latency = (time.time() - start_time) * 1000

            return LLMCallResult(
                success=True,
                content=rag_response.answer,
                raw_text=rag_response.answer,
                fallback=rag_response.fallback,
                latency_ms=latency,
                confidence=rag_response.confidence,
                sources=[
                    {"doc_id": s.document.doc_id, "score": s.score, "source": s.source}
                    for s in rag_response.sources
                ],
            )

        except Exception as e:
            logger.error(f"[{self.agent_name}] RAG answer error: {e}")
            # 降级到普通 LLM
            return await self.llm_chat(query, system_prompt=system_prompt)

    async def llm_stream(self, user_message: str, **kwargs):
        """流式输出（返回异步迭代器）。

        Usage:
            async for chunk in agent.llm_stream("讲个故事"):
                print(chunk, end="")
        """
        if not self.ENABLE_LLM or not self.llm_client:
            yield "[LLM 未启用，使用模拟响应]"
            return

        try:
            async for chunk in self.llm_client.chat_stream(user_message, **kwargs):
                yield chunk
        except Exception as e:
            logger.error(f"[{self.agent_name}] Stream error: {e}")
            yield f"[错误: {e}]"

    # ---- Prompt 模板管理 ----

    def get_prompt_template(self, name: str, **kwargs) -> str:
        """获取并填充业务 Prompt 模板（委派给 `ai_infra.llm` 的注册表）。

        ★ 三处同名方法（本方法 / `DashScopeLLM.get_prompt_template` /
          模块级 `get_prompt_template`）现在**共用同一实现**，「缺键」只会
          抛 `KeyError`，不再有「某一处返回空串」的第二套语义。
          原实现 `.get(name, "")` 返回空串 ⇒ 拿着空 system prompt 请求 LLM，
          不报错不降级，属静默失效。

        业务提示词在各业务模块的 `prompts.py`，由该模块 import 时注册。
        """
        from ai_infra.llm import get_prompt_template as _get

        return _get(name, **kwargs)

    # ---- 降级与统计 ----

    def _mock_result(
        self, original_query: str, reason: str, structured: bool = False
    ) -> LLMCallResult:
        """生成降级结果（LLM 不可用 / 调用失败时）。

        ★ 关键：`success=False`（不是 True）。

        降级结果**不是一次成功的分析**，而是「LLM 本次不可用」这一事实的显式表达。
        原实现在此返回 `success=True` + `"[模拟响应] 由于 …"` 文案，会让调用方把
        「LLM 挂了」误判成「分析成功」，属于项目判据明令禁止的「静默 mock」。
        另外原实现有个 `_generate_mock_response` 钩子，但 6 个业务 Agent
        **无一实现它** ⇒ 该分支永远走不到，等同于没有兜底。

        现在统一为：成功与否由 `success` 诚实表达，失败原因走 `error`，
        内容留空（空状态优于虚构默认），由调用方决定如何对外降级。
        """
        self._llm_stats["mock_calls"] += 1
        logger.warning(f"[{self.agent_name}] LLM 降级（{reason}）")

        return LLMCallResult(
            success=False,
            content="",
            raw_text="",
            fallback=True,
            error=f"LLM 不可用：{reason}",
        )

    def _update_llm_stats(self, tokens: int, cost: float, latency: float):
        """更新统计"""
        self._llm_stats["llm_calls"] += 1
        self._llm_stats["total_tokens"] += tokens
        self._llm_stats["total_cost"] += cost

    @property
    def llm_stats(self) -> Dict:
        """获取 LLM 使用统计"""
        return {
            **self._llm_stats,
            "agent_name": self.agent_name,
            "llm_enabled": self.ENABLE_LLM,
            "rag_enabled": self.ENABLE_RAG,
        }

    def reset_stats(self):
        """重置统计"""
        self._llm_stats = {
            "total_calls": 0,
            "llm_calls": 0,
            "mock_calls": 0,
            "errors": 0,
            "total_tokens": 0,
            "total_cost": 0.0,
        }

    # ====== HITL 工具包装 ======

    def _wrap_hitl_tools(self, tools: list[BaseTool]) -> list[BaseTool]:
        """
        为需要 HITL 的工具添加人工审批包装器

        参考：项目1 (tools.py:32-101) add_human_in_the_loop()
        """
        from ai_infra.tools.hitl_decorator import add_human_in_the_loop
        from ai_infra.tools.side_effects import derive_hitl_tools

        # ★★★ 第 145 轮 批 B1/B2：审批名单不再由业务侧手写，改为由
        #   `ai_infra.tools.side_effects` 的**副作用策略**推导（唯一真源）。
        #   显式传入的 `hitl_tools=` 仍然生效（取并集），但它从此是**补充**
        #   而非前提 —— 漏写不再造成漏审批：`has_side_effects()` 的默认分支
        #   是 fail-closed 的 True，未登记为只读的工具**自动**获得审批包装。
        #   旧形态（`hitl_tools=["save_candidate"]` 手写名单）的病根是「默认
        #   不审批」——新增写库工具时没人记得改名单，且不报错、测试全绿。
        derived = set(derive_hitl_tools(tools))
        if derived - self.hitl_tool_names:
            logger.info(
                f"🔒 [{self.agent_name}] 副作用策略推导出待审批工具: "
                f"{sorted(derived - self.hitl_tool_names)}"
            )
        # 就地更新：`router.hitl_tool_names` 是外部可读的契约（测试与前端都看它），
        # 必须反映**生效**的名单，而不是构造参数里那一份。
        self.hitl_tool_names = derived | self.hitl_tool_names
        effective_names = self.hitl_tool_names

        wrapped_tools = []
        for tool in tools:
            if tool.name in effective_names:
                # ★ 形态守卫（第 131 轮加）：工厂必须返回**真的 BaseTool**。
                #   原 `add_human_in_the_loop` 是 `async def`，此处同步调用 ⇒
                #   拿到 coroutine 被原样塞进 `self.tools`、`bind_tools` 随后
                #   拿到非 BaseTool（全仓 0 个 `hitl_tools=` 调用点 ⇒ 从未暴露）。
                #   显式断言把「哪天有人把工厂改回 async」升级成
                #   **装配期即报错**，而不是「工具静默损坏、调用时才炸」。
                wrapped = add_human_in_the_loop(tool)
                if not isinstance(wrapped, BaseTool):
                    raise TypeError(
                        "HITL 包装器必须返回 BaseTool，实际拿到 "
                        f"{type(wrapped).__name__}（工具={tool.name}）"
                        "—— add_human_in_the_loop 被改成 async 了吗？"
                    )
                logger.info(f"🔒 为工具 [{tool.name}] 添加 HITL 审批")
                wrapped_tools.append(wrapped)
            else:
                wrapped_tools.append(tool)

        return wrapped_tools

    # ====== LangGraph 图（懒构建） ======

    @property
    def graph(self):
        """LangGraph 工作流（懒构建，首次访问时编译）。"""
        if self._graph is None:
            self._graph = self._build_graph(self.checkpointer)
        return self._graph

    def _build_graph(self, checkpointer: Optional[Any] = None) -> StateGraph:
        """
        构建 LangGraph 工作流

        流程图：
            START → llm_call → [should_continue] → tool_node → llm_call → ...
                                      ↓ (无工具调用)
                                   respond → END

        参考：项目2 (base_agent.py:69-81)
        """
        # 创建状态图
        workflow = StateGraph(AgentState)

        # 添加节点（tools 为空时 ToolNode 仍可构建，实测 tools_by_name={}）
        workflow.add_node("llm_call", self._llm_call_node)
        workflow.add_node("tool_node", ToolNode(self.tools))
        workflow.add_node("respond", self._respond_node)

        # 添加边
        workflow.add_edge(START, "llm_call")
        workflow.add_conditional_edges(
            "llm_call",
            self._should_continue,
            {"tool_node": "tool_node", "respond": "respond"},
        )
        workflow.add_edge("tool_node", "llm_call")
        workflow.add_edge("respond", END)

        # 编译图（checkpointer 在编译期绑定，非运行时 config 传入）
        # ★ 形参默认 `None` = **不带记忆**编译；要记忆的一方由调用方显式传
        #   `self.checkpointer`（见 `graph` 属性 / `_memoryless_graph()`）。
        #   为什么不在函数体里回退到 `self.checkpointer`：那样就**编译不出**
        #   一张"不带记忆"的图，而"无会话就不留记忆"正需要它。
        return workflow.compile(checkpointer=checkpointer)

    # ====== 节点函数 ======

    @staticmethod
    def _sanitize_tool_call_pairing(messages: list) -> tuple[list, int]:
        """清洗消息序列，修复 tool_calls / ToolMessage 配对断裂（读时自愈）。

        背景：checkpointer 恢复的历史里可能存在「AIMessage 带 tool_calls，但没有
        对应 ToolMessage」的孤儿消息（成因：工具执行中途异常、达成 max_iterations
        被强制结束、HITL 中断、或修复前的旧数据）。OpenAI 兼容 API（DashScope）
        对历史做严格校验，会以 400 拒绝整条会话：

            400 An assistant message with "tool_calls" must be followed by tool
            messages responding to each "tool_call_id".

        这里只清洗「传给 LLM 的副本」，**不修改 state / checkpoint**，
        保证历史仍可被 route() 的 prev_count、action 提取等逻辑正常读取。
        旧数据因此无需手工清理，任何会话都能自愈。

        Returns:
            (清洗后的消息列表, 被剔除/修剪的消息条数)
        """
        # 1) 声明方：所有 AIMessage 声明的 tool_call_id
        declared: set = set()
        for m in messages:
            if isinstance(m, AIMessage):
                for tc in (getattr(m, "tool_calls", None) or []):
                    if tc.get("id"):
                        declared.add(tc["id"])

        # 2) 响应方：所有 ToolMessage 回应的 tool_call_id
        responded = {
            m.tool_call_id
            for m in messages
            if isinstance(m, ToolMessage) and getattr(m, "tool_call_id", None)
        }

        # 3) 有效集合 = 声明 ∩ 响应（双向都满足才算配对成功）
        valid = declared & responded

        changed = 0
        out: list = []
        for m in messages:
            if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
                kept = [tc for tc in m.tool_calls if tc.get("id") in valid]
                if len(kept) != len(m.tool_calls):
                    changed += 1
                    m = m.model_copy(
                        update={"tool_calls": kept, "invalid_tool_calls": []}
                    )
                    # 剥空且无文本内容 → 整条丢弃，避免产生空 AIMessage
                    if not kept and not (m.content or "").strip():
                        continue
            elif isinstance(m, ToolMessage):
                # 孤立的 ToolMessage（其 AIMessage 已不在或未声明该 id）→ 丢弃
                if getattr(m, "tool_call_id", None) not in valid:
                    changed += 1
                    continue
            out.append(m)

        return out, changed

    @staticmethod
    def _iterations_in_current_turn(messages: list) -> int:
        """统计「本轮」的 AI 迭代次数（最后一条 HumanMessage 之后的 AIMessage 数）。

        为什么不能直接数全部 AIMessage：
        checkpointer 恢复的 messages 是**跨轮完整历史**。若直接用「AIMessage 总数」
        判断迭代上限，多轮会话累积几条 AIMessage 后就会立刻判定「已达上限」，
        症状是——
          • `_llm_call_node`：每轮都被判超限，强制清空 tool_calls；
          • `_should_continue`：直接 return "respond"，永不进入 tool_node。
        结果 LLM 再也无法调用任何工具，前端一直收到「处理完成」、actions 为空。

        因此迭代计数必须锚定在**本轮输入**（最后一条 HumanMessage）之后。
        LLM 只产出 AIMessage / ToolMessage，不会再产生 HumanMessage，
        故最后一条 HumanMessage 必然是本轮输入。
        """
        last_human_idx = -1
        for i, m in enumerate(messages):
            if isinstance(m, HumanMessage) or m.__class__.__name__ == "HumanMessage":
                last_human_idx = i
        turn_messages = messages[last_human_idx + 1:]
        return sum(
            1 for m in turn_messages
            if isinstance(m, AIMessage) or m.__class__.__name__ == "AIMessage"
        )

    @staticmethod
    def _carried_tokens(state: dict, *, iterations_done: int) -> int:
        """本轮**此前**已消耗的 token（0 表示本轮第一次迭代）。

        ★ 为什么从 state 读、不记在实例上：Agent 实例是**进程内单例**
          （`get_secretary_agent()` 就是），记在 `self` 上等于把一个会话的
          耗用记到另一个会话头上 —— 并发下预算会随机误伤。state 随图执行走，
          一次调用一份。

        ★ 为什么 `iterations_done == 0` 一定要归零：`state["budget"]` 会随
          checkpointer **跨轮持久化**。不归零的话预算会被历史越攒越多，
          一个健康的会话聊到第 N 轮突然被判「token 超限」。口径与
          `_iterations_in_current_turn` 一致：预算按**轮**算，不按会话算。
        """
        if iterations_done <= 0:
            return 0
        return int((state.get("budget") or {}).get("spent_tokens") or 0)

    def _system_prompt_with_plan(self, state: dict, *, sections: str = "") -> str:
        """本轮要发给模型的 system prompt。

        组成**按顺序**（空的部分整段跳过）：
            业务提示词 → 外部段落（`sections`）→ 规划说明 → 当前计划

        ★★ 这是「计划不随历史裁剪丢失」的**第二半**（第一半是计划不在 `messages`
          里）。计划存在 `state["todos"]`，但模型不会自动知道它 —— 必须每轮把它
          渲染进 system prompt。因为渲染是**每轮现算**的，历史被裁掉多少轮都不影响
          这一段：裁剪器只看 messages，看不见这里。

        ★★ 第 152 轮修：原实现在未开启规划时 `return self.system_prompt`，
          把**后来加的一切**一起丢掉了。任何「附加段落」只要不属于规划器，
          在那个早退分支上都会静默消失 —— 而「静默」正是最难发现的那种失效：
          未开规划的 Agent 上记忆永远不注入、日志全绿、门禁全绿。
          ⇒ 早退只能跳过**规划器那两段**，不能跳过整个拼接。
          由 `tests/test_memory_injection.py::test_sections_survive_without_planning`
          钉住（关规划 + 有 sections ⇒ sections 必须仍在）。

        ★ 为什么拼进 system prompt、而不是往 `messages` 里塞一条 SystemMessage：
          messages 会被 `trim_history()` 按轮裁剪，塞进去等于把刚建好的保障
          又交回给裁剪器去处理。
        """
        parts = [self.system_prompt]
        if sections:
            parts.append(sections)
        if self.enable_planning:
            parts.append(PLANNING_GUIDE)
            block = render_plan_block(normalize_todos(state.get(TODOS_STATE_KEY)))
            if block:
                parts.append(block)
        return "\n\n".join(p for p in parts if p)

    async def _llm_call_node(self, state: AgentState) -> dict:
        """LLM 决策节点：决定是否调用工具或直接回复"""
        raw_messages = state["messages"]

        # 关键健壮性修复：checkpointer 恢复的历史可能带着 orphan tool_calls，
        # 直接喂给 LLM 会被 DashScope 以 400 拒绝（整条会话不可用）。
        # 清洗副本，不污染持久化历史。
        clean_messages, dropped = self._sanitize_tool_call_pairing(raw_messages)
        if dropped:
            logger.warning(
                f"🧹 历史中存在 {dropped} 条无法配对的 tool_calls/ToolMessage，"
                f"已从本次 LLM 输入中剔除（checkpoint 历史保持不变，下次读取仍会清洗）"
            )

        # ★★★ 第 147 轮 批 C4：**上下文裁剪** —— 按 token 预算裁历史 +
        #   折叠旧工具结果为摘要。在此之前这里只有**结构性**清洗
        #   （上一行的 orphan 配对剔除），它不减少一个字节 ⇒ 多轮会话的输入
        #   token 单调增长，直到被对端以「上下文超长」拒绝，而那时**整条会话
        #   从此不可用**（每次恢复历史都会再次超长）。
        #
        #   ★ 裁剪只作用于 `clean_messages`（不含 system prompt）；
        #   ★ **当前轮永不裁** —— 裁掉它等于把用户这次问的话删了；
        #   ★ 保底保留 `keep_recent_turns` 轮 —— 否则一次裁剪就把上下文炸成空。
        #   四条不变量详见 `ai_infra/context.py`。
        clean_messages, context_report = trim_history(clean_messages, self.context_policy)
        if context_report.changed:
            logger.info(
                f"✂️ [{self.agent_name}] 上下文裁剪：轮 {context_report.turns_total} → "
                f"{context_report.turns_kept}（删 {context_report.turns_dropped}），"
                f"折叠工具结果 {context_report.folded_tool_results} 条，"
                f"估算 token {context_report.tokens_before} → {context_report.tokens_after}"
                f"（档位 {context_report.label}）"
            )
        if context_report.over_budget:
            # ★ 显式声明「没裁到位」：保底轮数用尽后仍超预算。
            #   这里**不抛异常** —— 此刻消息里装的是用户这次问的东西，
            #   丢掉它比超长更糟。让请求照发、由对端决定，但日志必须说清
            #   是**这里没做到**，而不是让下一次失败看起来像对端的问题。
            logger.warning(
                f"⚠️ [{self.agent_name}] 上下文裁剪未回到预算内：估算 "
                f"{context_report.tokens_after} > {self.context_policy.max_input_tokens}"
                f"（已保留保底 {self.context_policy.keep_recent_turns} 轮）"
            )

        # ★ 第 148 轮 批 C3：system prompt 里带上当前计划（开启规划时）。
        #   从 `state` 取而不是从 `self` 取：计划是**这个会话**的，
        #   而 Agent 实例是进程内单例。
        #
        # ★ 第 152 轮 批 C2 读口：**每轮现取**外部段落（今天是长期记忆）。
        #   它与 `state["todos"]` 一样不进 messages ⇒ 历史裁剪动不到它；
        #   不同的是它的真源在库里（用户跨会话的画像），不在图状态里。
        #   ★ 身份**只从服务端上下文取**（`core.observability.context`，
        #     由鉴权依赖写入）：工具入参由 LLM 生成，塞不进身份；
        #     客户端自报的身份也不该被采纳。
        #   ★ 匿名请求（或 Celery 里的任务）`current_user_id()` 是空串
        #     ⇒ provider 返回空串 ⇒ 本段为空，这一轮**照常继续**：
        #     记忆是增益不是门禁，让增益的故障否决主流程是更差的选择。
        injected = await collect_prompt_sections(
            PromptContext(
                agent_name=self.agent_name,
                user_id=current_user_id() or None,
            )
        )
        if injected.failed:
            # ★ 「失败了」必须与「本来就没有内容」**可分**：这里点名说是哪几段。
            #   只记一条没有主语的数量没有价值 —— 排查时不知道去找谁。
            logger.warning(
                f"⚠️ [{self.agent_name}] system prompt 段落注入失败 "
                f"{len(injected.failed)} 段，本次已跳过（其余段落照常注入）："
                f"{list(injected.failed)}"
            )
        messages = [
            SystemMessage(
                content=self._system_prompt_with_plan(state, sections=injected.text)
            )
        ] + clean_messages

        response = await self._llm_with_tools().ainvoke(messages)

        # ★ 记录 Token 使用量 + 计入请求级计费计量器。
        # 原实现**只写 logger.debug、不落库**（测试之所以绿，是因为 conftest 的
        # 离线桩**自己**调了 record_llm_usage 顶替了这一行）。真实 ChatOpenAI 返回的
        # token 因此只进日志、不进 subscriptions 表 —— 店秘书与 router 层的消耗从未计费。
        # ChatOpenAI 的 usage_metadata 键名是 input_tokens/output_tokens/total_tokens；
        # LangChain 在 on_llm_end 时挂上，ainvoke 返回的 AIMessage 亦带该属性。
        usage = getattr(response, "usage_metadata", None)
        # ★ 批 C5：本次 token 消耗提到外层 —— 预算的 token 维度要用它。
        #   原实现里这两个名字只活在 `if usage:` 的 try 块内，无 usage 时
        #   根本不存在（下游直接引用会 NameError）。
        in_tok = 0
        out_tok = 0
        if usage:
            try:
                in_tok = int(usage.get("input_tokens") or 0)
                out_tok = int(usage.get("output_tokens") or 0)
                meta = getattr(response, "response_metadata", None) or {}
                model_name = meta.get("model_name") or self.DEFAULT_MODEL

                # 复用 DashScopeLLM 的定价口径（唯一真源），不另写一套单价表
                from ai_infra.llm.dashscope_client import DashScopeLLM
                from core.metering.llm_meter import record_llm_usage

                record_llm_usage(
                    input_tokens=in_tok,
                    output_tokens=out_tok,
                    cost=DashScopeLLM._compute_cost(model_name, in_tok, out_tok),
                    model=model_name,
                )
            except Exception as e:  # 记账失败不得影响主流程
                logger.warning(f"[{self.agent_name}] LLM 用量记账失败: {e}")
            logger.debug(f"Token 使用: {usage}")

        # 关键修复：达到 max_iterations 时，本次 LLM 输出会触发 _should_continue → "respond"
        # 但响应里的 tool_calls 没有对应的 ToolMessage → 下次 invoke 时 checkpointer 恢复
        # 历史会因「AIMessage 有 tool_calls 但没有连续 ToolMessage」被 OpenAI 兼容 API 400 拒绝。
        # 此处统一在节点内清理：若已是最后一次允许的 AIMessage，强制去掉 tool_calls。
        #
        # 注意：计数必须用「本轮迭代数」而非全部历史 AIMessage 数（否则多轮会话
        # 累积几条后每轮都被判超限，工具调用彻底失效）——见 _iterations_in_current_turn。
        # ★★★ 第 145 轮 批 C5：预算从「只数迭代」扩到「迭代 + token」两维，
        #   且**超限必须留下调用方读得到的状态**。
        #
        #   改之前：只有一条 `logger.warning`。图返回的 state 与「模型自己
        #   答完了」一模一样，调用方（前端 / 业务 Agent）无从分辨「这次是被
        #   截断的」—— 用户看到一句像样的回答，以为任务完成了。
        #   改之后：`state["budget"]["truncated"]` 是显式结论，`_respond_node`
        #   据此把 status 标成非 completed；日志升到 ERROR（可告警）。
        #
        #   ⚠️ 清空 tool_calls 这一步**不能删** —— 它是「本轮到此为止」的善后，
        #   否则下一轮 checkpointer 恢复历史时会因 orphan tool_calls 被
        #   DashScope 400 拒绝（见 test_max_iterations_strips_orphan_tool_calls）。
        #
        #   ⚠️ **墙钟**维度不在这里判：节点内看不到本轮起点（state 随
        #   checkpointer 跨轮持久化，塞进去的 t0 下一轮就过期了），它由入口层
        #   `run_session` / `stream_session` 用 `asyncio.timeout` 兜。
        #   两个层次不是「一处做了另一处没做」，而是同一个预算的两种正确反应。
        existing_ai_count = self._iterations_in_current_turn(raw_messages)
        spent_tokens = (
            self._carried_tokens(state, iterations_done=existing_ai_count)
            + in_tok
            + out_tok
        )
        # 迭代维度用 `existing_ai_count + 1`：本次输出将成为本轮第 N 条
        # AIMessage ⇒ 与旧写法 `existing_ai_count >= max_iterations - 1` 等价。
        verdict = check_budget(
            {"iterations": existing_ai_count + 1, "tokens": spent_tokens},
            self.budget,
        )

        budget_state: dict = {
            "spent_tokens": spent_tokens,
            "iterations": existing_ai_count + 1,
            # ★ 批 C4：把上下文裁剪结论落到**调用方读得到**的地方。
            #   它不参与「是否截断」的判定（裁剪是常态、截断是终局），
            #   但消费方需要它来解释「模型为什么像忘了前几轮」。
            "context": context_report.as_dict(),
        }

        if verdict is not None and response.tool_calls:
            dropped_calls = len(response.tool_calls)
            # 用更干净的构造方式去掉 tool_calls（保留 content）
            response = response.model_copy(update={"tool_calls": [], "invalid_tool_calls": []})
            budget_state.update(
                {
                    "truncated": verdict.dimension,
                    "limit": verdict.limit,
                    "used": verdict.used,
                    "message": verdict.message,
                }
            )
            logger.error(
                f"🛑 [{self.agent_name}] {verdict.message} —— 本次 AIMessage 的 "
                f"{dropped_calls} 个 tool_calls 已被清空以避免留下 orphan "
                f"tool_calls 污染历史；本轮到此为止（已产出的消息与工具结果保留）"
            )

        return {"messages": [response], "budget": budget_state}

    def _llm_with_tools(self) -> BaseChatModel:
        """绑定工具的 LLM。

        关键：必须 bind_tools，否则 LLM 永不输出 tool_calls，
        _should_continue 永远走 "respond"，工具循环形同虚设。
        """
        llm = self.llm
        if llm is None:
            raise RuntimeError(
                f"[{self.agent_name}] 图路径需要 LangChain 模型，但当前不可用"
                f"（ENABLE_LLM={self.ENABLE_LLM}，或 DASHSCOPE_API_KEY 未配置/初始化失败）。"
                "若只想用 LLM 原语，请改用 llm_chat / llm_structured。"
            )
        if not self.tools:
            return llm
        return llm.bind_tools(self.tools)

    async def _respond_node(self, state: AgentState) -> dict:
        """
        响应节点：格式化最终输出

        参考：项目2 (base_agent.py:91-111)
        """
        last_message = state["messages"][-1]

        # 构建结构化响应
        response_content = ""
        if isinstance(last_message, AIMessage):
            response_content = last_message.content or "处理完成"
        elif isinstance(last_message, ToolMessage):
            response_content = f"工具执行结果: {str(last_message.content)[:500]}"

        # ★ 第 145 轮 批 C5：把「被预算截断」写进终态结论。
        #   此前无论正常答完还是被截断，`status` 恒为 "completed" ——
        #   调用方拿到的是一份**看起来成功**的结构化结果。
        budget_state = state.get("budget") or {}
        truncated = budget_state.get("truncated")
        structured: dict = {
            "status": "budget_truncated" if truncated else "completed",
            "message": response_content,
            "agent_name": self.agent_name,
            "timestamp": datetime.now().isoformat(),
        }
        # ★ 第 148 轮 批 C3：「子任务状态可在 UI 展示」靠的是这一处 ——
        #   前端读 `structured_response.plan` 即可，不必再去翻 checkpointer。
        # ★ 只在**开启规划且确实有计划**时才带这个键：恒带一个 `{"total": 0}`
        #   会让消费方分不清「这个 Agent 没开启规划」与「开启了但还没规划」——
        #   前者永远不会有计划，后者只是时候未到。
        if self.enable_planning:
            todos = normalize_todos(state.get(TODOS_STATE_KEY))
            if todos:
                structured["plan"] = plan_summary(todos)
        if truncated:
            structured["budget"] = {
                "truncated": truncated,
                "limit": budget_state.get("limit"),
                "used": budget_state.get("used"),
                "reason": budget_state.get("message"),
            }

        return {"structured_response": structured}

    def _should_continue(self, state: AgentState) -> str:
        """
        路由决策：继续调工具 vs 返回结果

        参考：项目2 (base_agent.py:113-125)
        """
        messages = state["messages"]
        last_message = messages[-1]

        # 检查是否超过最大迭代次数（只数「本轮」，避免跨轮历史累积导致误判）
        #
        # ★ 第 145 轮 批 C5：这条分支**不**记 ERROR —— 它只在「计数到顶」时
        #   触发，而「到顶」不等于「被截断」：模型恰好在最后一轮给出完整回答
        #   也会走到这里。真正的截断（想调工具但预算已尽）由 `_llm_call_node`
        #   判定并写 `state["budget"]["truncated"]` + 记 ERROR。
        #   两处都记 ERROR 的话，正常收尾的长会话会持续刷错误日志，
        #   把信号稀释成噪声。
        if self._iterations_in_current_turn(messages) >= self.max_iterations:
            logger.warning(f"⚠️ 达到最大迭代次数 ({self.max_iterations})，强制结束")
            return "respond"

        # 如果没有工具调用，直接返回
        if not last_message.tool_calls or len(last_message.tool_calls) == 0:
            return "respond"

        # 如果有工具调用，继续执行
        return "tool_node"

    # ====== 会话记忆：统一入口（session_id → thread_id）======
    #
    # ★★★ 本仓唯一的 thread_id 生成点。此前散在 3 处、各写一份：
    #     `secretary/agent.py`       → `session_id or "secretary-default"`
    #     `listing_generator`        → `f"listing-{id(self)}"`            ← 内存地址
    #     `product_research`         → `f"product-research-{context_id or id(self)}"`
    # 后两处拿**对象内存地址**当 thread_id ⇒ 进程一重启就换键，于是永远命中不到
    # 上一轮的 checkpoint，表现为「记忆看着有一轮、重启就没了」。
    #
    # ★ 为什么名字不是 `invoke()`：见文件末「关于『统一调用入口』」。本组方法
    #   **原样返回 state / 事件流**、不预设返回结构 ⇒ 不与业务 `invoke()` 的
    #   `AgentResponse` 契约冲突（防回流门禁只拦 `invoke`/`stream`/`stream_chat`
    #   这三个**同名**方法，本组名字不撞）。

    def attach_checkpointer(self, checkpointer: Optional[AsyncPostgresSaver]) -> None:
        """
        绑定 / 更换 checkpointer（并丢弃已编译的图）。

        ★ 必须丢图重编译：`workflow.compile(checkpointer=...)` 是**编译期**绑定。
          编译完成后再改 `self.checkpointer`，对已编译的图**没有任何影响** ——
          不报错、只是不生效，属于典型静默失效。
        """
        self.checkpointer = checkpointer
        self._graph = None
        self._graph_memoryless = None

    def resolve_thread_id(
        self, session_id: str, user_id: Optional[str] = None
    ) -> str:
        """
        ★ 唯一实现：会话 `session_id` → checkpointer 的 `thread_id`。

        规则：`thread_id = ":".join(p for p in (ns, user_id, session_id) if p)`
        —— 空段直接跳过。所以 `ns` 为空时是 `user_id:session_id`，
        `user_id` 为空时是 `ns:session_id`，两者都空就是裸 `session_id`
        （`secretary` 的历史口径，见下）。

        ★ 为什么要命名空间：LangGraph 的 checkpoint 按 `thread_id` 分片，
          **不看图的身份**，而本仓所有图共用同一个 `AgentState` schema。
          两个 Agent 拿到同一个 `session_id` ⇒ 写进同一条消息历史 ——
          用户与 listing 的对话会出现在 secretary 的上下文里。schema 相同
          所以不报错，只是**静默串味**。前缀把两者隔开。

        ★ 为什么 `secretary` 的 `ns` 是空串（`CHECKPOINT_NAMESPACE = ""`）：
          它从一开始就用裸 `session_id` 当 thread_id，本地库里已有落盘记忆。
          改键会让那些记忆**全部失联**（不报错，只是"历史突然没了"）
          ⇒ 保持原口径、不动既有数据；新接的 Agent 一律带前缀。

        ★ 为什么还要带 `user_id`（第 131 轮）：
          命名空间只隔开**不同 Agent**，隔不开**同一 Agent 的不同用户**。
          会话 ID 可能由客户端提供、也可能由服务端颁发，两条路都可能撞上
          同一个串；一旦相同，两个用户的 checkpoint 就落在同一个 thread 上，
          互相看得见对方的消息、且不报任何错。把 `user_id` 拼进键 =
          **纵深防御**：即使上层归属校验被绕过，两人的键在物理上不可能相等。
          ⚠️ 这是**公开契约变更**：键里加了 `user_id`，此前已落库的
          checkpoint 行会全部失联（不报错，只是"历史突然没了"）。
        """
        ns = self.checkpoint_namespace
        return ":".join(p for p in (ns, user_id, session_id) if p)

    def graph_for_session(
        self, session_id: Optional[str], user_id: Optional[str] = None
    ):
        """
        统一入口（底层）：按**有无会话**返回 `(graph, config)`。

        · 有 `session_id` **且有** `user_id` ⇒ 带记忆：`self.graph` +
          `{"configurable": {"thread_id": ...}}`
        · 缺任一个 ⇒ **不留记忆**：走不带 checkpointer 的图，且**不伪造 thread_id**

        ★ 为什么"没有会话"不等于"用一个默认 thread_id 兜底"：
          默认 thread_id 是**全进程共享**的 —— 所有匿名 / 无会话请求会挤进同一段
          记忆、互相看到对方的消息，且没有任何报错。原则与
          `core.auth.accounts.filter_accessible_stores` 同一条：
          **没有身份 ⇒ 没有数据；没有会话 ⇒ 不留记忆。**

        ★ 第 131 轮补上后半句的「身份」条件：只有 `session_id` 时，
          `thread_id` 仍是「一个与用户无关的串」—— 只要两个用户拿到同一个
          串，记忆就串了。会话与身份**缺一不可**：拿不到身份就如同拿不到
          会话 —— 不留记忆，而不是留到一个"公共"记忆里。
        """
        if session_id and user_id:
            return self.graph, {
                "configurable": {
                    "thread_id": self.resolve_thread_id(session_id, user_id)
                }
            }
        # ★ 第 145 轮 批 B4：不再返回**空** config，而是显式声明「为什么没有会话」。
        #   空 config 的问题不是"缺信息"，而是它把「无会话」这件事变成了一个
        #   **不可观测的状态**：下游只能从"没有 thread_id"反推，且无从知道
        #   原因。现在这条原因随 config 传播，HITL 守卫可以原样引用它。
        #   （仍然不伪造 thread_id —— 「没有会话 ⇒ 不留记忆」这条原则不变，
        #     见上面 docstring：默认 thread_id 是全进程共享的，比没有更危险。）
        return self._memoryless_graph(), {
            "configurable": {},
            "metadata": {
                "session_mode": "memoryless",
                "session_mode_reason": self.MEMORYLESS_REASON,
            },
        }

    def _memoryless_graph(self):
        """不带 checkpointer 的图（懒构建 + 缓存）。"""
        if self.checkpointer is None:
            return self.graph   # 本来就没绑 ⇒ 是同一张图，无需重复编译
        if self._graph_memoryless is None:
            self._graph_memoryless = self._build_graph(checkpointer=None)
        return self._graph_memoryless

    async def run_session(
        self,
        state: dict,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        """
        ★ 统一入口（一次性）：驱动本 Agent 的图，返回**原始 state**。

        ★ 与业务 `invoke()` 的分工：本方法**不组装业务响应**，原样返回
          `{"messages": [...]}`，由调用方按自己的契约解析 —— 这正是 `self.graph`
           的既有用法，只是补上了此前缺的两条语义：`session_id + user_id →
          thread_id`、以及「缺任一个就不留记忆」。
        """
        graph, cfg = self.graph_for_session(session_id, user_id)
        # ★ 第 145 轮 批 C5：**墙钟预算**在入口层执行。
        #   · 为什么不在节点里：节点看不到「本轮」的起点 —— state 随
        #     checkpointer 跨轮持久化，塞进去的 t0 下一轮就是过期的，
        #     会把历史累计成耗时。
        #   · 为什么这里**抛异常**而节点内只标记：入口层没有「部分结果」
        #     可保，超时就是这次调用失败；静默返回半截比报错更糟。
        #     见 `BudgetExceeded` 的 docstring。
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.budget.max_seconds):
                return await graph.ainvoke(state, config=cfg)
        except TimeoutError as e:
            verdict = BudgetVerdict(
                dimension="seconds",
                used=time.monotonic() - started,
                limit=self.budget.max_seconds,
                label=self.budget.label,
            )
            logger.error(f"🛑 [{self.agent_name}] {verdict.message} —— 本次调用已中止")
            raise BudgetExceeded(verdict) from e

    async def stream_session(
        self,
        state: dict,
        *,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
        version: str = "v2",
    ) -> AsyncIterable:
        """★ 统一入口（流式）：同 `run_session`，产出 `astream_events` 事件流。"""
        graph, cfg = self.graph_for_session(session_id, user_id)
        # 墙钟预算同 `run_session`（理由见那里）。★ 流式场景的代价更明确：
        # 超时会把**已经开始下发**的事件流切断，调用方拿到半个流 ——
        # 这正是「显式报错」要的效果：宁可让调用方看到 BudgetExceeded，
        # 也不要让它以为流是正常结束的。
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.budget.max_seconds):
                async for ev in graph.astream_events(state, config=cfg, version=version):
                    yield ev
        except TimeoutError as e:
            verdict = BudgetVerdict(
                dimension="seconds",
                used=time.monotonic() - started,
                limit=self.budget.max_seconds,
                label=self.budget.label,
            )
            logger.error(f"🛑 [{self.agent_name}] {verdict.message} —— 本次流式调用已中止")
            raise BudgetExceeded(verdict) from e

    # ====== 关于「统一调用入口」 ======
    #
    # ★ 本类**故意不提供** `invoke()` / `stream()`。
    #
    # 6 个业务 Agent 都是「不成为一张图」的 Agent —— 它们把本类当**原语提供者**
    # 用（LLM / 工具 / RAG / 提示词 / SSE），入口契约由各业务模块自定义：
    #
    #     async def invoke(self, query, context=None) -> AgentResponse
    #
    # 旧版本曾在此提供 `invoke(query, context_id, metadata) -> dict`（内部驱动
    # `self.graph`）。那套入口的**动态可达性为 0**，实测（r71-why.txt）：
    #   · 全仓 21 处 `agent.invoke(` 调用点的 receiver 全部在子类重写了同名
    #     方法 ⇒ 分派永远落子类，基类实现从不执行；
    #   · 而真正继承它的 3 个 Agent（aigc / competitor / secretary）恰好
    #     **一处 `invoke` 调用点都没有**（前者只调 stream_chat，后者直接
    #     用 `agent.graph.ainvoke`）。
    #   · ★ 「有调用点」≠「方法可达」：只数调用点会得出「人人都在用」的错觉。
    #
    # 更危险的是**契约冲突**：基类返回 `dict`（`structured_response`），业务返回
    # `AgentResponse`（Pydantic），调用方按后者取字段 ⇒ 一旦真分派到基类实现，
    # `response.content` 立刻 `AttributeError`。**"没人调"比"调了炸"安全，
    # 但这份安全是巧合**，所以删掉而不是留着。
    #
    # 需要图驱动的一方**直接用 `self.graph`** —— 它返回**原始 state**，不预设返回
    # 结构，因此对不同业务契约都成立。本仓现有两种用法（均实测在跑）：
    #
    #   ① 继承式：secretary 直接
    #        state = await agent.graph.ainvoke(
    #            {"messages": [...]},
    #            config={"configurable": {"thread_id": ...}},
    #        )
    #   ② 组合式：listing / product_research 各自 `_build_router()` **new 一个裸
    #      BaseAgent 实例**当路由子层（`checkpoint_ns="listing"` / `"product_research"`），
    #      再 `self._router.graph.ainvoke(...)`，自己解析 messages 组装业务响应。
    #
    # ★ 为什么 `invoke()` 的抽象层级是错的：①② 都需要**原始 state（messages
    #   流）**来自行组装业务响应，而 `invoke()` 恰好把 state 换成了
    #   `structured_response` —— 拿走的正是它们唯一需要的东西。所以不是
    #   「忘了用」，而是**用不上**。
    #
    # 防回流门禁：`tests/test_infra_layering.py` 的
    #             `test_base_agent_exposes_no_conflicting_entry`。
    #
    # ★ 2026-09-17 补充：本类新增了**会话记忆统一入口** —— `run_session()` /
    #   `stream_session()` / `graph_for_session()` / `resolve_thread_id()`（见上）。
    #   它们与 `invoke()` 不冲突的理由是**返回原始 state、不预设结构**，
    #   而 `invoke()` 恰好会在"返回什么"上与业务契约打架。两者不是同一件事：
    #     · 驱动图的**机制**（thread_id / checkpointer / 无会话不留记忆）⇒ 归基类
    #     · 业务响应的**结构**（AgentResponse / 结果卡形状）⇒ 归业务模块


__all__ = ["BaseAgent", "LLMCallResult", "AgentState"]
