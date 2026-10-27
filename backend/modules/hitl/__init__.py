# -*- coding: utf-8 -*-
"""人机协同层（HITL）：与具体业务 Agent 无关的**审批**与**澄清挂起**。

    hitl.py      —— 审批的领域逻辑（渲染卡片 / 翻译决策 / 探测中断 / 续跑）
    registry.py  —— 「哪个 Agent 能续跑审批」的分发表
    clarification.py —— 模型主动向用户提问（真挂起，同一轮继续；见 P0-3）

## 为什么单独成包（而不是塞进 `modules/conversation/`）

`modules/conversation/` 是**会话持久化**门面，它的 `__init__` 已 import
`service` / `state_store`（会拉起 DB），且被门禁钉成「跨模块只允许
`from modules.conversation import <name>`，`__all__` 之外取不到」。
把审批逻辑塞进去会同时发生两件坏事：

  · 任何只想渲染一张审批卡的模块，被迫拖上会话持久化依赖；
  · 那个包的 `__all__` 从「四个动作」变成「四个动作 + 一堆审批函数」，
    门面契约变得没有意义。

## 为什么也不放进 `ai_infra/`

`ai_infra` 是**与业务无关的底座**（`layers` 门禁：`ai_infra` 不许 import
`modules.*`）。而审批要拿业务的 Agent / service 去续跑 —— 那属于 `modules` 层。
所以本包住 `modules/`，只依赖 `core.*` / `langgraph.*` / `langchain_core.*`。

★ 例外且仅此一处：`registry.py` 里出现的业务模块路径是**字符串**（惰性 import），
  AST 看到的是一条 `str` 常量，不构成 import 依赖 —— 这正是把「分发表」
  与「实现」解耦的方式（见该文件 docstring 的三种做法对比）。
"""
from .clarification import (
    DISPLAY_CLARIFICATION,
    DISPLAY_CLARIFICATION_ANSWERED,
    build_clarification_resume,
    clarification_from_state,
    detect_pending_clarification,
    pending_clarification_payload,
)
from .hitl import (
    DISPLAY_APPROVAL_FAILED,
    DISPLAY_APPROVAL_RESOLVED,
    DISPLAY_PENDING_APPROVAL,
    build_resume_payload,
    detect_pending_approval,
    pending_approval_payload,
    resume_approval,
    unwrap_hitl_tool_output,
)
from .registry import (
    RESUME_SPECS,
    ResumeSpec,
    canonical_agent_id,
    get_resumer,
    supported_agents,
)

__all__ = [
    # ---- 审批（hitl.py）----
    "DISPLAY_APPROVAL_FAILED",
    "DISPLAY_APPROVAL_RESOLVED",
    "DISPLAY_PENDING_APPROVAL",
    "build_resume_payload",
    "detect_pending_approval",
    "pending_approval_payload",
    "resume_approval",
    "unwrap_hitl_tool_output",
    # ---- 澄清挂起（clarification.py）----
    "DISPLAY_CLARIFICATION",
    "DISPLAY_CLARIFICATION_ANSWERED",
    "build_clarification_resume",
    "clarification_from_state",
    "detect_pending_clarification",
    "pending_clarification_payload",
    # ---- 分发表（registry.py）----
    "RESUME_SPECS",
    "ResumeSpec",
    "canonical_agent_id",
    "get_resumer",
    "supported_agents",
]
