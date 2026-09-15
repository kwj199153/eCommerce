"""
BaseAgent 基类 - 所有业务 Agent 的共享基础架构

设计思路（融合两个参考项目）：
- 推理循环：参考项目2 (A2A LangGraph-a2a/common/base_agent.py)
  • StateGraph 构建: LLM Call → Tool Call → Respond
  • 路由逻辑: should_continue() 决定下一步
- HITL 机制：参考项目1 (ReActAgentHIL/infrastructure/tools.py)
  • interrupt() 包装器实现人工审批
  • 支持 accept/reject/edit/response 四种响应
- 记忆管理：PostgreSQL Checkpoint 持久化
- Token 统计 & 成本控制

使用方式：
    from ai_infra.base_agent import BaseAgent

    class ProductResearchAgent(BaseAgent):
        def __init__(self):
            super().__init__(
                system_prompt=PRODUCT_SYSTEM_PROMPT,
                tools=[blue_ocean_analysis, pain_point_mining, ...],
                hitl_tools=["export_report"],  # 需要人工审批的工具
            )
"""

from collections.abc import AsyncIterable
from typing import Any, Optional
from datetime import datetime

from langchain_core.messages import (
    SystemMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
)
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.graph import MessagesState, StateGraph, START, END
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.prebuilt import ToolNode

from core.config import config
from core.logger import get_logger

logger = get_logger(__name__)


# ====== Agent 状态定义 ======
class AgentState(MessagesState):
    """Agent 状态 Schema"""
    # 结构化响应（用于返回标准化结果）
    structured_response: Optional[dict] = None
    # 元数据
    metadata: dict = {
        "agent_name": "",
        "tenant_id": "",
        "shop_id": "",
        "created_at": "",
        "token_usage": {},
        "cost_estimate": 0.0,
    }


class BaseAgent:
    """
    所有业务 Agent 的基类

    提供通用能力：
    1. LangGraph 推理循环（LLM → Tool → LLM → ... → Respond）
    2. HITL 人工审批机制（可选工具级别）
    3. PostgreSQL Checkpoint 持久化
    4. Token 用量统计 & 成本估算
    5. 错误处理 & 重试机制
    """

    def __init__(
        self,
        agent_name: str,
        system_prompt: str,
        tools: list[BaseTool],
        llm: Optional[BaseChatModel] = None,
        hitl_tools: Optional[list[str]] = None,
        max_iterations: int = 10,
        metadata: Optional[dict] = None,
        checkpointer: Optional[AsyncPostgresSaver] = None,
    ):
        """
        初始化 Agent

        Args:
            agent_name: Agent 名称（用于日志和标识）
            system_prompt: 系统 Prompt（业务专属，由子类定义）
            tools: 工具列表（业务专属，由子类定义）
            llm: LLM 实例（默认使用 DashScope Qwen）
            hitl_tools: 需要 HITL 审批的工具名列表
            max_iterations: 最大推理迭代次数（防止死循环）
            metadata: 额外元数据
            checkpointer: LangGraph checkpointer（PostgreSQL 持久化，None 则内存态）
        """
        self.agent_name = agent_name
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

        # 配置 LLM（默认使用 Qwen-max）
        self.llm = llm or self._get_default_llm()

        # 处理 HITL 工具包装
        self.tools = self._wrap_hitl_tools(tools)

        # 元数据
        self.default_metadata = {
            "agent_name": agent_name,
            **metadata,
        }

        # 构建 LangGraph 工作流
        self.graph = self._build_graph()

        logger.info(
            f"✅ Agent 初始化完成: {agent_name} | "
            f"工具数: {len(self.tools)} | "
            f"HITL工具: {hitl_tools}"
        )

    def _get_default_llm(self) -> BaseChatModel:
        """获取默认 LLM（DashScope Qwen）"""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=config.llm_default_model,
            openai_api_key=config.dashscope_api_key,
            openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
            temperature=config.llm_temperature,
            max_tokens=config.llm_max_tokens,
            timeout=config.llm_timeout_seconds,
        )

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

        # 添加节点
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

        # 记录 Token 使用量
        if hasattr(response, 'usage_metadata'):
            token_usage = response.usage_metadata
            logger.debug(f"Token 使用: {token_usage}")

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
        if not self.tools:
            return self.llm
        return self.llm.bind_tools(self.tools)

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

    # ====== 公开接口 ======

    async def invoke(
        self,
        query: str,
        context_id: str,
        tenant_id: str = "",
        shop_id: str = "",
    ) -> dict:
        """
        同步调用 Agent

        Args:
            query: 用户输入
            context_id: 会话 ID（= checkpointer 的 thread_id，用于多轮持久化）
            tenant_id: 租户 ID
            shop_id: 店铺 ID

        Returns:
            结构化响应字典
        """
        # checkpointer 已在编译期绑定，config 只传 thread_id
        graph_config = {"configurable": {"thread_id": context_id}}

        # 更新元数据
        metadata = {
            **self.default_metadata,
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "created_at": datetime.now().isoformat(),
        }

        # 执行工作流
        inputs = {
            "messages": [HumanMessage(content=query)],
            "metadata": metadata,
        }

        result = await self.graph.ainvoke(inputs, config=graph_config)

        # 返回结构化响应
        return result.get("structured_response", {
            "status": "error",
            "message": "无法获取响应",
        })

    async def stream(
        self,
        query: str,
        context_id: str,
        tenant_id: str = "",
        shop_id: str = "",
    ) -> AsyncIterable[dict]:
        """
        流式调用 Agent（支持进度推送）

        Yields:
            - {type: "thinking", content: "正在分析..."}
            - {type: "tool_call", tool_name: "...", content: "..."}
            - {type: "tool_result", content: "..."}
            - {type: "hitl_required", tool_name: "...", args: {...}}
            - {type: "final", response: {...}}
        """
        graph_config = {"configurable": {"thread_id": context_id}}

        metadata = {
            **self.default_metadata,
            "tenant_id": tenant_id,
            "shop_id": shop_id,
            "created_at": datetime.now().isoformat(),
        }

        inputs = {
            "messages": [HumanMessage(content=query)],
            "metadata": metadata,
        }

        async for event in self.graph.astream_events(
            inputs,
            config=graph_config,
            version="v2",
        ):
            event_type = event.get("event")

            if event_type == "on_chat_model_start":
                yield {"type": "thinking", "content": "正在思考..."}

            elif event_type == "on_chat_model_stream":
                chunk = event.get("data", {}).get("chunk", {})
                if hasattr(chunk, 'content') and chunk.content:
                    yield {"type": "streaming", "content": chunk.content}

            elif event_type == "on_tool_start":
                tool_name = event.get("name", "unknown")
                yield {
                    "type": "tool_call",
                    "tool_name": tool_name,
                    "content": f"正在调用工具: {tool_name}",
                }

            elif event_type == "on_tool_end":
                output = event.get("data", {}).get("output", "")
                yield {
                    "type": "tool_result",
                    "content": str(output)[:1000],  # 截断过长输出
                }

        # 最终响应
        final_state = await self.graph.aget_state(graph_config)
        yield {
            "type": "final",
            "response": final_state.values.get("structured_response"),
        }
