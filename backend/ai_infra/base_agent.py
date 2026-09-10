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
        hitl_tools: list[str] = [],
        max_iterations: int = 10,
        metadata: dict = {},
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
        """
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.hitl_tool_names = set(hitl_tools)

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
        from langchain_community.chat_models import ChatOpenAI

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

        # 编译图（不绑定 checkpointer，在调用时动态传入）
        return workflow.compile()

    # ====== 节点函数 ======

    async def _llm_call_node(self, state: AgentState) -> dict:
        """LLM 决策节点：决定是否调用工具或直接回复"""
        messages = [SystemMessage(content=self.system_prompt)] + state["messages"]

        response = await self.llm.ainvoke(messages)

        # 记录 Token 使用量
        if hasattr(response, 'usage_metadata'):
            token_usage = response.usage_metadata
            logger.debug(f"Token 使用: {token_usage}")

        return {"messages": [response]}

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
            response_content = f"工具执行结果: {last_content[:500]}"

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

        # 检查是否超过最大迭代次数
        if len([m for m in messages if isinstance(m, AIMessage)]) >= self.max_iterations:
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
        checkpointer: AsyncPostgresSaver = None,
        tenant_id: str = "",
        shop_id: str = "",
    ) -> dict:
        """
        同步调用 Agent

        Args:
            query: 用户输入
            context_id: 会话 ID（用于持久化）
            checkpointer: Checkpointer 实例（PostgreSQL 持久化）
            tenant_id: 租户 ID
            shop_id: 店铺 ID

        Returns:
            结构化响应字典
        """
        # 构建配置
        graph_config = {"configurable": {"thread_id": context_id}}
        if checkpointer:
            graph_config["configurable"]["checkpointer"] = checkpointer

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
        checkpointer: AsyncPostgresSaver = None,
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
        if checkpointer:
            graph_config["configurable"]["checkpointer"] = checkpointer

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
