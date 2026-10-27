# -*- coding: utf-8 -*-
"""能力层（第 400 轮 P1-1 · A 档：只读三原语）。

    spec.py      —— 纯函数：OpenAPI spec → 只读能力目录（可喂假 spec 单测）
    registry.py  —— 进程内单例：绑定应用、检索、盘面读数
    invoke.py    —— 内部只读调用（ASGI 进程内 HTTP + 身份转发 + `sent` 三态）
    tools.py     —— 三个工具：find / describe / read

## 这一层要解决的具体痛点

「后端 242 条端点，Agent 只够得到 65 个手写工具」。新增一个能力要人工同步
3～6 处（工具定义 / `TOOL_CATALOG` 条目 / 审批名单 / 计数断言），
而**读端点**本来就不需要人挑 —— 它们的 `summary` / `tags` / 参数签名
是端点作者写的，是唯一会随代码同步的东西。

## 为什么敢自动暴露（安全边界）

1. **只暴露 GET**（结构性判据，不猜语义）：写操作一条都进不来 ⇒ 审批面不变；
2. **拒绝清单按前缀**：`auth`（会签 token）/ `orchestrator` 与 `agents`
   （会递归回自己）/ `admin` / `internal`；
3. **身份只能转发、不能自报**：白名单三个头，任何 `x-user-id` 类自报头
   都不在里面（见 `core/observability/context.py::FORWARD_HEADER_ALLOW`）；
4. **缺身份 / 缺店铺一律本地拦下**（`sent: false`），不发请求 ——
   绝不以匿名或跨租户身份读数据。

## 没有绑定应用时

`bind_app()` 由 `main.py` 在装配完成后调用一次。测试 / 脚本里没绑定时，
工具返回 `{"bound": false}`，**不抛异常也不假装成功**。
"""
from .invoke import call_read
from .registry import (
    bind_app,
    catalog,
    find,
    get_capability,
    is_bound,
    stats,
)
from .spec import (
    BLOCKED_METHODS,
    BLOCKED_PREFIXES,
    Capability,
    ParamInfo,
    build_catalog,
    effect_of,
    is_exposed,
)
from .tools import (
    CAPABILITY_TOOL_NAMES,
    DESCRIBE_CAPABILITY_TOOL_NAME,
    FIND_CAPABILITIES_TOOL_NAME,
    READ_CAPABILITY_TOOL_NAME,
    build_capability_tools,
    capability_stats,
    describe_capability,
    find_capabilities,
    read_capability,
)

__all__ = [
    # ---- 目录（spec.py / registry.py）----
    "Capability",
    "ParamInfo",
    "BLOCKED_METHODS",
    "BLOCKED_PREFIXES",
    "build_catalog",
    "effect_of",
    "is_exposed",
    "bind_app",
    "catalog",
    "find",
    "get_capability",
    "is_bound",
    "stats",
    # ---- 调用（invoke.py）----
    "call_read",
    # ---- 工具（tools.py）----
    "CAPABILITY_TOOL_NAMES",
    "FIND_CAPABILITIES_TOOL_NAME",
    "DESCRIBE_CAPABILITY_TOOL_NAME",
    "READ_CAPABILITY_TOOL_NAME",
    "build_capability_tools",
    "capability_stats",
    "describe_capability",
    "find_capabilities",
    "read_capability",
]
