"""读口：把长期记忆接进 system prompt（第 152 轮 · 批 C2 读口）。

r141 对 C2 的判词是「要么接真后端，要么下线；**不能留一个假页面承诺
「每晚自动整理」**」。第 149 轮把写入侧补齐了（三张表 + 服务 + HTTP + 每晚任务），
但**「整理出来的东西被读了」是另一件事**：一份每晚更新、却从不影响模型回答的
记忆，与一份不存在的记忆，对用户而言完全等价 —— 只是前者更贵。

本文件就是最后那一步：把该用户的记忆渲染成一段文本，注册进
`ai_infra.prompt_sections` 的注册表，由 `BaseAgent` 每轮 LLM 调用时取走。

★ 五件**不在这里**实现的事（本仓已有唯一实现，重复一份就是两份真源）
--------------------------------------------------------------------
  · 渲染与截断 —— `ai_infra.memory.entry.render_prompt_block`：含硬上限
    `MAX_PROMPT_CHARS`、整行截断（半条记忆 = 给出错误信息）、
    `（记忆过长，本次只注入前 N/M 条）` 与「连一条都放不下」的显式说明。
    已有门禁断言它在 2000 字处按整行截断。
  · 开关的默认值 —— `modules.memory.service.DEFAULT_ENABLED`（只在 service 里解释一次）。
  · 归属判空 —— `service.load_injectable_entries`（本文件不自己判 `user_id`，
    否则「什么算有身份」立刻出现第二份实现）。
  · 注入时机与拼接顺序 —— `ai_infra.base_agent.BaseAgent._llm_call_node`。
  · 「注入了几段 / 失败了几段」的日志 —— `ai_infra.prompt_sections.collect_prompt_sections`。

★★ 为什么 provider 拿不到身份时返回空串，而不是抛错
--------------------------------------------------
`service._require_owner` 对 HTTP 面是 fail-closed（401）：用户点「保存」必须
知道"为什么没存上"。但读口完全不同 —— 它在**图的节点里**执行，一次匿名请求
（或 Celery 里的任务）走到这里抛异常 ⇒ **整轮对话挂掉**。而"这个人没有记忆"
本身是完全正常的状态（新用户、没登录、自己关了开关）。
⇒ 读口把「没有可归属对象」与「开关关闭」都收敛成**不注入**，
  并由 `load_injectable_entries` 显式给出 `injectable` 标志（可观测）。

★★ 注册为什么写在模块级、又套一层 `ensure_registered()`
-----------------------------------------------------
「注册」是 import 副作用：本模块被 import 即完成注册，`BaseAgent` 不需要知道
有谁注册过（它只问注册表）。这与本仓既有的 `register_prompt_template`
（各业务模块的 `prompts.py` 模块级调用）是同一套机制。

套一层幂等函数的原因：重名注册会 raise（那是判据，见 `prompt_sections`），
而 `importlib.reload` 会让模块级代码**再跑一遍**、注册表却还在
⇒ 直接写在模块级的话，reload 即崩。而 reload 是本仓测试的常规手段。
"""

from __future__ import annotations

import logging

from ai_infra.memory import MAX_PROMPT_CHARS, render_prompt_block
from ai_infra.prompt_sections import (
    PromptContext,
    register_prompt_section,
    registered_sections,
)

from .service import load_injectable_entries

logger = logging.getLogger(__name__)

#: 注册名。与业务语义绑定的字符串，只能出现在业务层（`ai_infra` 的字符串层
#: 有零业务内容的硬门禁）。
PROMPT_SECTION_NAME = "long_term_memory"


async def memory_prompt_section(ctx: PromptContext) -> str:
    """给这个人返回他的长期记忆注入块；没有可注入内容时返回**空串**。

    ★ 空串是「本次不注入」的表达方式，不是错误：注册表那一层会把空串丢掉
      （见 `collect_prompt_sections`）。所以「新用户第一轮对话」不会在
      system prompt 里留下一个只有标题、内容为空的小节。
    """
    got = await load_injectable_entries(ctx.user_id)
    if not got.injectable:
        return ""
    return render_prompt_block(got.entries, max_chars=MAX_PROMPT_CHARS)


def ensure_registered() -> None:
    """幂等注册（理由见模块 docstring 末段）。"""
    if PROMPT_SECTION_NAME in registered_sections():
        return
    register_prompt_section(PROMPT_SECTION_NAME, memory_prompt_section)


ensure_registered()


__all__ = [
    "PROMPT_SECTION_NAME",
    "memory_prompt_section",
    "ensure_registered",
]
