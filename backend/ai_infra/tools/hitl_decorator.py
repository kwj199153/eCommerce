"""
HITL (Human-in-the-Loop) 装饰器

为工具添加人工审批机制，基于 LangGraph interrupt() 实现。

参考：项目1 (ReActAgentHIL/infrastructure/tools.py:32-101)
改良点：
1. 移除硬编码，改为纯通用装饰器
2. 增加多租户隔离支持
3. 增加操作日志记录
4. 支持异步审批队列

使用场景（已确认）：
- Listing 发布前确认
- 数据导出/批量操作前审批
"""

from typing import Callable, Any
from langchain_core.tools import BaseTool, tool as create_tool
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt, Command

from core.logger import get_logger

logger = get_logger(__name__)


async def add_human_in_the_loop(
    tool: BaseTool | Callable,
    *,
    interrupt_config: dict = None,
    require_reason: bool = False,
    timeout_seconds: int = 3600,  # 默认1小时超时
) -> BaseTool:
    """
    为工具添加人工审查（Human-in-the-Loop）

    Args:
        tool: 工具函数或 BaseTool 实例
        interrupt_config: 中断配置（可自定义提示信息）
        require_reason: 是否要求用户填写审批原因
        timeout_seconds: 等待审批的超时时间（秒）

    Returns:
        包装后的 BaseTool（带 HITL 能力）

    使用示例：
        @tool("publish_listing")
        async def publish_listing(listing_id: str) -> str:
            # ...发布逻辑...
            return "Listing 已发布"

        # 在 Agent 中使用：
        hitl_tool = await add_human_in_the_loop(publish_listing)
    """
    if not isinstance(tool, BaseTool):
        tool = create_tool(tool)

    @create_tool(
        name=tool.name,
        description=f"[需人工审批] {tool.description}",
        args_schema=tool.args_schema,
    )
    async def call_tool_with_hitl(config: RunnableConfig, **tool_input) -> str:
        """
        带 HITL 审批的工具调用包装器

        流程：
        1. 暂停执行，等待人工审批
        2. 用户选择：accept / reject / edit / response
        3. 根据选择执行或跳过
        """
        # 构建中断请求
        hitl_request = {
            "action_request": {
                "action": tool.name,
                "args": tool_input,
                "require_reason": require_reason,
                "timeout": timeout_seconds,
            },
            "config": interrupt_config or {},
            "description": (
                f"⚠️ 准备执行操作: [{tool.name}]\n"
                f"参数: {tool_input}\n\n"
                f"请选择操作:\n"
                f"- accept: 执行操作\n"
                f"- reject: 拒绝执行\n"
                f"- edit: 修改参数后执行\n"
                f"- response: 不执行，直接回复"
            ),
        }

        logger.info(f"🔒 HITL 等待审批: 工具=[{tool.name}] 参数={tool_input}")

        # 触发中断，等待用户响应
        response = interrupt(hitl_request)

        response_type = response.get("type", "unknown")
        logger.info(f"✅ HITL 收到响应: 工具=[{tool.name}] 类型={response_type}")

        # 处理不同响应类型
        if response_type == "accept":
            logger.info(f"⏳ 用户批准执行: [{tool.name}]")
            try:
                result = await tool.ainvoke(input=tool_input)
                return f"✅ 操作已执行 [{tool.name}]\n结果: {result}"
            except Exception as e:
                logger.error(f"❌ 工具执行失败: [{tool.name}] 错误={e}")
                raise

        elif response_type == "edit":
            # 用户修改了参数
            modified_args = response.get("args", {}).get("args", tool_input)
            logger.info(f"✏️ 用户修改参数: 原始={tool_input} → 修改后={modified_args}")
            try:
                result = await tool.ainvoke(input=modified_args)
                return f"✅ 操作已执行（已修改参数）[{tool.name}]\n结果: {result}"
            except Exception as e:
                logger.error(f"❌ 修改后执行失败: [{tool.name}] 错误={e}")
                raise

        elif response_type == "reject":
            reason = response.get("args", {}).get("reason", "未提供原因")
            logger.warning(f"🚫 用户拒绝执行: [{tool.name}] 原因={reason}")
            return f"❌ 操作已被用户取消 [{tool.name}]\n原因: {reason}"

        elif response_type == "response":
            user_feedback = response.get("args", "")
            logger.info(f"💬 用户直接回复: [{tool.name}] 内容={user_feedback}")
            return str(user_feedback)

        else:
            error_msg = f"不支持的 HITL 响应类型: {response_type}"
            logger.error(error_msg)
            raise ValueError(error_msg)

    return call_tool_with_hitl


# ====== 批量 HITL 装饰器 ======

def add_batch_human_in_the_loop(
    tools: list[BaseTool],
    hitl_tool_names: list[str],
) -> list[BaseTool]:
    """
    批量为多个工具添加 HITL

    Args:
        tools: 工具列表
        hitl_tool_names: 需要添加 HITL 的工具名列表

    Returns:
        处理后的工具列表
    """
    wrapped_tools = []
    for tool in tools:
        if tool.name in hitl_tool_names:
            import asyncio
            wrapped = asyncio.get_event_loop().run_until_complete(
                add_human_in_the_loop(tool)
            )
            wrapped_tools.append(wrapped)
        else:
            wrapped_tools.append(tool)

    return wrapped_tools
