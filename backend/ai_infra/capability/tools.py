# -*- coding: utf-8 -*-
"""只读能力的**三个工具**（A 档）：找 → 看参数 → 读。

## 为什么是三个而不是一个

* `find_capabilities` —— 只回 `name / summary / path`（**不含** schema）。
  目录里有 90+ 条读端点，把参数 schema 全塞进 schema 里是不可能的
  （本仓单条 op 的 JSON 平均 1.4KB，全量 343KB）。
* `describe_capability` —— 按需取某一个的参数与位置。
* `read_capability` —— 真的去读。

## 为什么读写不合成一个工具（B 档再考虑）

本仓的审批闸门判据是**静态工具名**（`derive_hitl_tools` 按 `metadata` 推导）。
把一个"也许写也许读"的万能工具塞进去，只有两种结果：
要么每次查数据都弹审批（用户把确认点成肌肉记忆 ⇒ 闸等于没有），
要么写操作永远不过闸。⇒ A 档只做 `read_capability`，名字本身就是"读"。

## schema 预算

四个工具（含将来的 `call_capability`）schema 合计必须 < 4000 字符 ——
schema 是**每一轮**都要发给模型的固定成本。操作知识不在 schema 里，
靠 `describe_capability` 按需取。门禁见 `tests/test_capability_readonly.py`。

## 降级（没有绑定应用 / 没有身份）

工具**不抛异常**，返回一句结构化 JSON：`{"bound": false, ...}` /
`{"sent": false, "error": "no_identity", ...}`。
★ 不抛：能力层是增强项，它不该让后台任务里的 Agent 整轮崩掉；
★ 也不假装成功：`bound` 与 `sent` 两个标记就是给模型看"我为什么什么都没读到"。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from langchain_core.tools import BaseTool, StructuredTool

from ai_infra.tools.side_effects import READ_ONLY_METADATA

from .invoke import call_read
from .registry import find, get_capability, is_bound, stats, top_tags

__all__ = [
    "CAPABILITY_TOOL_NAMES",
    "FIND_CAPABILITIES_TOOL_NAME",
    "DESCRIBE_CAPABILITY_TOOL_NAME",
    "READ_CAPABILITY_TOOL_NAME",
    "find_capabilities",
    "describe_capability",
    "read_capability",
    "build_capability_tools",
]

FIND_CAPABILITIES_TOOL_NAME = "find_capabilities"
DESCRIBE_CAPABILITY_TOOL_NAME = "describe_capability"
READ_CAPABILITY_TOOL_NAME = "read_capability"

CAPABILITY_TOOL_NAMES = (
    FIND_CAPABILITIES_TOOL_NAME,
    DESCRIBE_CAPABILITY_TOOL_NAME,
    READ_CAPABILITY_TOOL_NAME,
)

FIND_DESCRIPTION = (
    "在本系统已有的**读端点**里按关键词检索能力（只读，不含写操作）。"
    "当你要查的东西没有现成工具时用它：先 find 找名字 → describe 看参数 → read 取数。"
    "参数：query —— 业务关键词（如「库存」「断货」「广告花费」）；limit —— 最多几条（默认 8）。"
)

DESCRIBE_DESCRIPTION = (
    "看某个读能力的**参数**（名字 / 位置 path|query / 必填 / 说明）。"
    "先 find_capabilities 拿到 name 再调它。参数：name —— operationId。"
)

READ_DESCRIPTION = (
    "按名字读取数据（只读操作，不修改任何东西）。"
    "参数：name —— operationId；params —— 参数字典（键名与 describe_capability 给的一致）。"
    "返回 `sent`（是否真的发出了请求）与 `status`（HTTP 状态码）。"
    "`sent=false` 表示本地就拦下了（没身份 / 参数不认识），不要原样重试。"
)


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def find_capabilities(query: str = "", limit: int = 8) -> str:
    """检索读能力；返回 `{bound, count, items:[{name, summary, path}]}`。"""
    try:
        n = max(1, min(int(limit or 8), 30))
    except (TypeError, ValueError):
        n = 8
    rows, bound = find(query, n)
    out: Dict[str, Any] = {
        "bound": bound,
        "query": query,
        "count": len(rows),
        "items": [c.as_row() for c in rows],
    }
    if not bound:
        out["hint"] = "能力层未绑定（启动期未执行 bind_app）—— 这不是「没有匹配」"
    elif not rows:
        out["hint"] = "没有匹配的读能力：换更短的关键词，或用空 query 列出全部"
        # ★ 把可用业务域列给它，才有第二次机会（响应里 summary 有相当一部分是英文）
        out["available_tags"] = top_tags()
    return _dump(out)


def describe_capability(name: str) -> str:
    """看一个读能力的参数清单。"""
    cap = get_capability(name)
    if cap is None:
        return _dump({
            "found": False,
            "name": name,
            "hint": "名字必须与 find_capabilities 返回的 name 完全一致（operationId）",
        })
    return _dump({
        "found": True,
        "name": cap.name,
        "method": cap.method,
        "path": cap.path,
        "summary": cap.summary,
        "tags": list(cap.tags),
        "params": [p.as_dict() for p in cap.params],
    })


async def read_capability(name: str, params: Optional[Dict[str, Any]] = None) -> str:
    """执行一次只读调用。"""
    return _dump(await call_read(name, params or {}))


def build_capability_tools() -> List[BaseTool]:
    """构造三个只读能力工具（供各 Agent 装配）。

    ★ 三者都声明 `READ_ONLY_METADATA`：`find` / `describe` 本来就不碰数据，
      `read` 只发 GET。判成"需审批"会让"查一下库存"也弹卡片 ——
      那正是 B 档之前不能混进来的形态。
    """
    return [
        StructuredTool.from_function(
            func=find_capabilities,
            name=FIND_CAPABILITIES_TOOL_NAME,
            description=FIND_DESCRIPTION,
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            func=describe_capability,
            name=DESCRIBE_CAPABILITY_TOOL_NAME,
            description=DESCRIBE_DESCRIPTION,
            metadata=READ_ONLY_METADATA,
        ),
        StructuredTool.from_function(
            coroutine=read_capability,
            name=READ_CAPABILITY_TOOL_NAME,
            description=READ_DESCRIPTION,
            metadata=READ_ONLY_METADATA,
        ),
    ]


def capability_stats() -> Dict[str, Any]:
    """盘面读数（排查 / 端点 / 门禁用）。"""
    return {**stats(), "tool_names": list(CAPABILITY_TOOL_NAMES), "bound_flag": is_bound()}
