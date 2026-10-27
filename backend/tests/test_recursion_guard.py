# -*- coding: utf-8 -*-
"""`ai_infra/recursion_guard.py` 的门禁（第 400 轮 · P2）。

## 这一层最容易出的三种"看起来对"的失效

① **上限算错量级**：`recursion_limit` 的单位是**超步**（模型节点 + 工具节点各 1），
   而 `max_iterations` 的单位是**模型轮次**。按 1:1 换算 ⇒ 上限比实际需要小一半，
   多步任务会在"再走一步就答完"的地方被误判成跑飞，用户看到兜底话术。
② **改到了调用方那份 config**：`apply_limit` 原地写 ⇒ 这一次调用的上限渗透到
   下一次（同族事故：转发头不清会带上一轮的 `authorization`）。
③ **按文案判异常**：`GraphRecursionError` 继承 `RecursionError`，
   而"真的递归溢出"也是 `RecursionError`。按字符串判会把两者混成一个。

## 反向注入

`r400u_inject_guards.py`：
  · 把 `2 * n` 改成 `n` ⇒ 判据 1 红
  · `apply_limit` 原地改入参 ⇒ 判据 2 红
  · `is_recursion_error` 改成 `"recursion" in str(exc).lower()` ⇒ 判据 3 红
"""
from __future__ import annotations

import asyncio

import pytest
from langgraph.errors import GraphRecursionError

from ai_infra.base_agent import BaseAgent
from ai_infra.recursion_guard import (
    RECURSION_LIMIT_MARGIN,
    AgentRecursionExceeded,
    apply_limit,
    is_recursion_error,
    raise_exceeded,
    recursion_limit_for,
)


# ============================================================
# 1. 上限的量级
# ============================================================


def test_limit_counts_supersteps_not_iterations():
    """★ 一次迭代至少占 2 个超步 ⇒ 上限必须 ≥ 2n，否则会**先于**软上限触发。"""
    for n in (1, 6, 10, 25):
        got = recursion_limit_for(n)
        assert got >= 2 * n, f"max_iterations={n} 只给了 {got} 步（少于 2n，量级错了）"
        assert got == 2 * n + RECURSION_LIMIT_MARGIN


def test_limit_never_below_one_even_for_garbage():
    """非法入参不许算成 0 —— 那会让第二次超步就报错，且看起来像"图坏了"。"""
    for bad in (0, -5, None, "abc", 0.0):
        assert recursion_limit_for(bad) >= 1 + 2, f"{bad!r} 算出了 {recursion_limit_for(bad)}"


def test_limit_margin_is_positive():
    """松弛必须 > 0：规划器 / HITL 包装会额外吃超步。"""
    assert RECURSION_LIMIT_MARGIN > 0


# ============================================================
# 2. 不改调用方那份 config
# ============================================================


def test_apply_limit_does_not_mutate_input():
    """★ 原地写会把"这一次的上限"渗透到下一次调用。"""
    cfg = {"configurable": {"thread_id": "t1"}}
    out = apply_limit(cfg, 10)
    assert "recursion_limit" not in cfg, "入参被写入了 recursion_limit（调用方那份被改了）"
    assert out["recursion_limit"] == recursion_limit_for(10)
    # 内层也要复制：只浅拷外层会与调用方共用同一个 configurable
    assert out["configurable"] == {"thread_id": "t1"}
    out["configurable"]["thread_id"] = "t2"
    assert cfg["configurable"]["thread_id"] == "t1", "`configurable` 被共享了（浅拷贝只拷了外层）"


def test_apply_limit_tolerates_missing_configurable():
    out = apply_limit({}, 3)
    assert out["recursion_limit"] == recursion_limit_for(3)
    assert "configurable" not in out


# ============================================================
# 3. 按类型判异常（不按文案）
# ============================================================


def test_is_recursion_error_is_type_based():
    assert is_recursion_error(GraphRecursionError("Recursion limit of 25 reached"))
    # ★ 真正的递归溢出**不是**"图跑超步"，不该被翻译成兜底话术
    assert not is_recursion_error(RecursionError("maximum recursion depth exceeded"))
    assert not is_recursion_error(RuntimeError("recursion limit reached"))
    # ★ 文案对、类型不对的伪造异常也不许过
    assert not is_recursion_error(Exception("GraphRecursionError: Recursion limit of 25"))


def test_exceeded_message_is_human_readable_and_names_the_agent():
    exc = AgentRecursionExceeded("店秘书", 20)
    text = str(exc)
    assert "店秘书" in text and "20" in text, text
    assert "recursion" not in text.lower(), "兜底话术里不该出现英文内部术语"
    assert isinstance(exc, RuntimeError)


def test_raise_exceeded_keeps_the_original_cause():
    original = GraphRecursionError("boom")
    with pytest.raises(AgentRecursionExceeded) as ei:
        raise_exceeded("listing", 16, original)
    assert ei.value.limit == 16
    assert ei.value.agent_name == "listing"
    assert ei.value.__cause__ is original, "原始异常丢了 —— 排查时看不到真因"


# ============================================================
# 4. 入口真的接上了（不是只有一堆纯函数）
# ============================================================


class _BoomGraph:
    """`ainvoke` / `astream_events` 都抛 `GraphRecursionError`。"""

    def __init__(self):
        self.seen_config = None

    async def ainvoke(self, state, config=None):
        self.seen_config = config
        raise GraphRecursionError("Recursion limit of 25 reached")

    async def astream_events(self, state, config=None, version="v2"):
        self.seen_config = config
        raise GraphRecursionError("Recursion limit of 25 reached")
        yield  # pragma: no cover —— 让它是 async generator


def _agent_with(graph):
    agent = BaseAgent(agent_name="probe", max_iterations=5)
    agent.graph_for_session = lambda sid, uid=None: (graph, {"configurable": {}})
    return agent


def test_run_session_sets_limit_and_translates_error():
    """★ 端到端：入口必须①设上限 ②把原始异常翻译成兜底话术。"""
    graph = _BoomGraph()
    agent = _agent_with(graph)
    with pytest.raises(AgentRecursionExceeded) as ei:
        asyncio.run(agent.run_session({"messages": []}))
    assert ei.value.limit == recursion_limit_for(5)
    assert graph.seen_config.get("recursion_limit") == recursion_limit_for(5), (
        "入口没把推导出来的上限传给图 —— 那就还是在吃 LangGraph 的隐形默认 25"
    )


def test_stream_session_sets_limit_and_translates_error():
    graph = _BoomGraph()
    agent = _agent_with(graph)

    async def _drain():
        async for _ in agent.stream_session({"messages": []}):
            pass

    with pytest.raises(AgentRecursionExceeded):
        asyncio.run(_drain())
    assert graph.seen_config.get("recursion_limit") == recursion_limit_for(5)


def test_entry_points_do_not_swallow_other_errors():
    """★ 只翻译"图跑超步"，其它异常必须原样抛（否则真因被兜底话术吃掉）。"""

    class _Other(_BoomGraph):
        async def ainvoke(self, state, config=None):
            raise ValueError("真正的别的问题")

    agent = _agent_with(_Other())
    with pytest.raises(ValueError, match="真正的别的问题"):
        asyncio.run(agent.run_session({"messages": []}))
