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

import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

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

from core.config import config
from core.logger import get_logger

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
    # 元数据：**自由字典**。基类只保证 `agent_name` / `created_at`；
    # 租户、店铺等维度由调用方经 `invoke(..., metadata={...})` 注入。
    #
    # ★ 原先这里硬编码了 `tenant_id` / `shop_id` / `token_usage` / `cost_estimate`
    #   四个键 —— 基类因此认识了「店铺」这一电商业务概念；而且这些键**只写不读**
    #   （全仓 0 处读 `state["metadata"]`），属死重量而非真耦合。
    metadata: dict = {}


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

    def __init__(
        self,
        agent_name: Optional[str] = None,
        system_prompt: str = "",
        tools: Optional[list[BaseTool]] = None,
        llm: Optional[BaseChatModel] = None,
        hitl_tools: Optional[list[str]] = None,
        max_iterations: int = 10,
        metadata: Optional[dict] = None,
        checkpointer: Optional[AsyncPostgresSaver] = None,
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
            max_iterations: 最大推理迭代次数（防止死循环）
            metadata: 额外元数据
            checkpointer: LangGraph checkpointer（PostgreSQL 持久化，None 则内存态）
        """
        self.agent_name = agent_name or self.__class__.__name__
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        # ★ 可变默认参数的经典坑：`def f(x=[])` 的默认对象在**函数定义时创建一次**，
        #   所有调用者共享同一个 list/dict。原写法 `hitl_tools=[]` / `metadata={}`
        #   意味着任意 Agent 实例对它们的改动会传染给后续所有实例 ——
        #   在「一个进程内建多个 Agent」的场景下会串数据。
        #   改用 None 哨兵 + 进函数体后新建，彻底切断共享。
        hitl_tools = list(hitl_tools) if hitl_tools else []
        metadata = dict(metadata) if metadata else {}
        self.hitl_tool_names = set(hitl_tools)
        self.checkpointer = checkpointer
        self._metadata_extra = metadata

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
        self.tools = self._wrap_hitl_tools(list(tools) if tools else [])

        # ---- LangGraph 图懒构建 ----
        # ★ 不在 __init__ 建图：业务 Agent 只用 LLM 原语、不成为一张图，
        #   没有理由为它们付 ToolNode/StateGraph 的构建成本。
        #   需要图的一方（secretary、router 层）首次访问 `self.graph` 时构建。
        self._graph: Optional[Any] = None

        # 前向兼容：当前 MRO 的下一环是 object（无副作用）；保留此调用可确保
        # 未来若引入 mixin，基类初始化链不会断在中间。
        super().__init__()

        logger.info(
            f"✅ Agent 初始化完成: {self.agent_name} | "
            f"工具数: {len(self.tools)} | "
            f"HITL工具: {hitl_tools}"
        )

    # ====== 元数据 ======

    @property
    def default_metadata(self) -> dict:
        """默认元数据。

        用 property 而非实例属性：子类常在 `super().__init__()` **之后**才设置
        `self.agent_name`，若在 __init__ 里固化成 dict，会一直挂着构造时的旧值。
        """
        return {"agent_name": self.agent_name, **self._metadata_extra}

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

        wrapped_tools = []
        for tool in tools:
            if tool.name in self.hitl_tool_names:
                logger.info(f"🔒 为工具 [{tool.name}] 添加 HITL 审批")
                wrapped_tools.append(add_human_in_the_loop(tool))
            else:
                wrapped_tools.append(tool)

        return wrapped_tools

    # ====== LangGraph 图（懒构建） ======

    @property
    def graph(self):
        """LangGraph 工作流（懒构建，首次访问时编译）。"""
        if self._graph is None:
            self._graph = self._build_graph()
        return self._graph

    def _build_graph(self) -> StateGraph:
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
        return workflow.compile(checkpointer=self.checkpointer)

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

        messages = [SystemMessage(content=self.system_prompt)] + clean_messages

        response = await self._llm_with_tools().ainvoke(messages)

        # ★ 记录 Token 使用量 + 计入请求级计费计量器。
        # 原实现**只写 logger.debug、不落库**（测试之所以绿，是因为 conftest 的
        # 离线桩**自己**调了 record_llm_usage 顶替了这一行）。真实 ChatOpenAI 返回的
        # token 因此只进日志、不进 subscriptions 表 —— 店秘书与 router 层的消耗从未计费。
        # ChatOpenAI 的 usage_metadata 键名是 input_tokens/output_tokens/total_tokens；
        # LangChain 在 on_llm_end 时挂上，ainvoke 返回的 AIMessage 亦带该属性。
        usage = getattr(response, "usage_metadata", None)
        if usage:
            try:
                in_tok = int(usage.get("input_tokens") or 0)
                out_tok = int(usage.get("output_tokens") or 0)
                meta = getattr(response, "response_metadata", None) or {}
                model_name = meta.get("model_name") or self.DEFAULT_MODEL

                # 复用 DashScopeLLM 的定价口径（唯一真源），不另写一套单价表
                from ai_infra.llm.dashscope_client import DashScopeLLM
                from core.billing.llm_meter import record_llm_usage

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
        existing_ai_count = self._iterations_in_current_turn(raw_messages)
        if existing_ai_count >= self.max_iterations - 1 and response.tool_calls:
            # 用更干净的构造方式去掉 tool_calls（保留 content）
            response = response.model_copy(update={"tool_calls": [], "invalid_tool_calls": []})
            logger.warning(
                f"⚠️ 已达 max_iterations={self.max_iterations}，本次 AIMessage 的 "
                f"tool_calls 被清空以避免留下 orphan tool_calls 污染历史"
            )

        return {"messages": [response]}

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

        return {
            "structured_response": {
                "status": "completed",
                "message": response_content,
                "agent_name": self.agent_name,
                "timestamp": datetime.now().isoformat(),
            },
        }

    def _should_continue(self, state: AgentState) -> str:
        """
        路由决策：继续调工具 vs 返回结果

        参考：项目2 (base_agent.py:113-125)
        """
        messages = state["messages"]
        last_message = messages[-1]

        # 检查是否超过最大迭代次数（只数「本轮」，避免跨轮历史累积导致误判）
        if self._iterations_in_current_turn(messages) >= self.max_iterations:
            logger.warning(f"⚠️ 达到最大迭代次数 ({self.max_iterations})，强制结束")
            return "respond"

        # 如果没有工具调用，直接返回
        if not last_message.tool_calls or len(last_message.tool_calls) == 0:
            return "respond"

        # 如果有工具调用，继续执行
        return "tool_node"

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
    #      BaseAgent 实例**当路由子层（`metadata={"role": "sub_agent_router"}`），
    #      再 `self._router.graph.ainvoke(...)`，自己解析 messages 组装业务响应。
    #
    # ★ 为什么 `invoke()` 的抽象层级是错的：①② 都需要**原始 state（messages
    #   流）**来自行组装业务响应，而 `invoke()` 恰好把 state 换成了
    #   `structured_response` —— 拿走的正是它们唯一需要的东西。所以不是
    #   「忘了用」，而是**用不上**。
    #
    # 防回流门禁：`tests/test_infra_layering.py` 的
    #             `test_base_agent_exposes_no_conflicting_entry`。


__all__ = ["BaseAgent", "LLMCallResult", "AgentState"]
