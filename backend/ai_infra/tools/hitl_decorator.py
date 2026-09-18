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


class HITLPrerequisiteError(RuntimeError):
    """HITL 的**前置条件**不满足（第 131 轮新增）。

    ★ 为什么单独建类、而不是裸 `raise RuntimeError`：
      调用方（router / 服务层 / 前端）需要把「这次操作因为缺会话上下文而
      **压根没执行**」与「工具自己执行失败」区分开 —— 前者是**拒绝**
      （fail-closed，没有人被扣钱、没有脏数据落库），后者才是故障。

    ★ 为什么继承 `RuntimeError`（即 `Exception` 子类）、**不是** `BaseException`：
      本仓的 `ToolNode` 与各层兜底都按 `except Exception` 写。让本异常逃出
      `Exception` 会把整张图的安全网（含 `GraphRecursionError` 兜底）一并绕过
      —— 那是"更安全"的反面：一个本该被优雅降级的**拒绝**，变成了穿透
      全链路的**崩溃**。
    """


def add_human_in_the_loop(
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

        # 在 Agent 中使用（★ 同步工厂，**不要**加 await）：
        hitl_tool = add_human_in_the_loop(publish_listing)

    ★ 为什么必须是**同步工厂**（第 131 轮运行时实证，两处硬 bug）：
      ① `BaseAgent._wrap_hitl_tools` 在 `__init__` 里装配工具，是**同步**方法、
         手上没有可跑的事件循环 ⇒ 同步调用 `async def` 拿到的是 **coroutine 对象**，
         会被原样塞进 `self.tools`，`bind_tools` 随后拿到非 `BaseTool`；
         而全仓 `hitl_tools=` 调用点数为 **0** ⇒ 这个坏形态从未暴露。
      ② 本函数体内**没有任何 await** —— `async` 关键字纯属装饰性。
      ③ `add_batch_human_in_the_loop` 曾用
         `asyncio.get_event_loop().run_until_complete(...)` 强行同步化，
         在**已在运行的事件循环**里（FastAPI / Celery worker）会直接抛。
      同步化是同时满足「构造期装配」与「运行期批处理」两条路径的唯一形态。

    ⚠️ `name` 只能作**第一位置参数**传（`create_tool(tool.name, ...)`）：
       `langchain_core` 的 `tool()` 签名里没有 `name` 关键字，
       写 `@create_tool(name=...)` 会直接
       `TypeError: tool() got an unexpected keyword argument 'name'`。

    ⚠️ `interrupt()` **要求图带 checkpointer + 调用时给 `thread_id`** ——
       无 checkpointer 时它直接抛，而不是「降级为不审批」。接线方必须为
       需要审批的图显式绑 checkpointer（见 `BaseAgent.graph_for_session`）。
    """
    if not isinstance(tool, BaseTool):
        tool = create_tool(tool)

    @create_tool(
        tool.name,
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

        # ★★★ fail-closed 守卫（第 131 轮）：`interrupt()` 要求**当前图绑了
        #   checkpointer 且运行时 config 带 `thread_id`**。两者缺一，它会在图
        #   内部抛一个上下文缺失的底层错 —— 归因不明确，且在「无会话 / 无身份」
        #   场景下会把整次对话打崩。本仓 `BaseAgent.graph_for_session()` 在
        #   `session_id` 与 `user_id` 缺任一个时，返回的正是**不带 checkpointer
        #   的图 + 空 config**，所以这条路径是真会被走到的。
        #   这里提前把条件讲明白：**拒绝执行**并把原因交给调用链。
        #   原则同 `_write_candidates`：没有身份 / 没有会话 ⇒ 这个动作就不该
        #   发生，而不是"悄悄照做"。
        thread_id = ((config or {}).get("configurable") or {}).get("thread_id")
        if not thread_id:
            raise HITLPrerequisiteError(
                f"[{tool.name}] 该操作需人工审批，但当前调用没有可用的会话上下文"
                "（缺少 `thread_id`）—— 审批记录无处落盘、操作无法被追溯，"
                "因此**拒绝执行**。请带上 `session_id` 与登录身份后重试。"
            )

        logger.info(f"🔒 HITL 等待审批: 工具=[{tool.name}] 参数={tool_input}")

        # 触发中断，等待用户响应
        response = interrupt(hitl_request)

        response_type = response.get("type", "unknown")
        logger.info(f"✅ HITL 收到响应: 工具=[{tool.name}] 类型={response_type}")

        # 处理不同响应类型
        if response_type == "accept":
            logger.info(f"⏳ 用户批准执行: [{tool.name}]")
            try:
                result = await tool.ainvoke(tool_input, config=config)
                return f"✅ 操作已执行 [{tool.name}]\n结果: {result}"
            except Exception as e:
                logger.error(f"❌ 工具执行失败: [{tool.name}] 错误={e}")
                raise

        elif response_type == "edit":
            # 用户修改了参数
            modified_args = response.get("args", {}).get("args", tool_input)
            logger.info(f"✏️ 用户修改参数: 原始={tool_input} → 修改后={modified_args}")
            try:
                result = await tool.ainvoke(modified_args, config=config)
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
            wrapped_tools.append(add_human_in_the_loop(tool))
        else:
            wrapped_tools.append(tool)

    return wrapped_tools
