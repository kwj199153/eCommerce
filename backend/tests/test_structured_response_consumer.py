# -*- coding: utf-8 -*-
"""`structured_response` 的**真消费者**行为（第 159 轮 · 批 D3）。

背景
====
`_respond_node` 一直把「本轮是否被预算截断」写进 `structured_response["status"]`，
但全仓生产代码 **0 处读它** ⇒ 截断与正常答完在调用方看来完全一样。
（形态门禁 `test_agent_state_fields_have_readers.py` 把那件事钉住了；
本文件钉**行为**：真读、且真的改变了输出。）

做法：`route()` 在截断时把提示**拼进 reply** —— 所以**不依赖前端渲染**，
用户也看得到「结果可能不完整」。
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage

from modules.secretary import agent as sec


def _state(status, reply="答完了", reason=None):
    sr = {"status": status, "message": reply, "agent_name": "secretary"}
    if reason:
        sr["budget"] = {"truncated": "tokens", "reason": reason}
    return {
        "messages": [HumanMessage(content="随便问一句"), AIMessage(content=reply)],
        "structured_response": sr,
    }


class _StubGraph:
    def __init__(self, state):
        self._state = state

    async def ainvoke(self, *a, **kw):          # noqa: ANN002, ANN003
        return self._state


class _StubAgent:
    checkpointer = None
    agent_name = "secretary"

    def __init__(self, state):
        self._state = state

    def graph_for_session(self, session_id, user_id):   # noqa: ARG002
        return _StubGraph(self._state), {"configurable": {}}


@pytest.mark.asyncio
async def test_route_surfaces_budget_truncation(monkeypatch):
    """被预算截断时：`truncated=True` + `reply` 带提示前缀 + 透出原因。"""
    monkeypatch.setattr(sec, "get_secretary_agent",
                        lambda shop_id=None: _StubAgent(_state("budget_truncated", reason="token 预算耗尽")))
    out = await sec.route("随便问一句", shop_id=None, history=[], session_id=None, user_id=None)

    assert out.get("truncated") is True, "route() 没把 structured_response 的截断结论透出来"
    assert out["reply"].startswith(sec.TRUNCATED_NOTICE), \
        "截断时 reply 必须带提示前缀 —— 否则「不依赖前端」这条保证不成立"
    assert out.get("truncated_reason") == "token 预算耗尽"


@pytest.mark.asyncio
async def test_route_normal_completion_is_untouched(monkeypatch):
    """正常完成时：不加提示、不带 truncated —— 消费者必须**能区分**两种情况。"""
    monkeypatch.setattr(sec, "get_secretary_agent",
                        lambda shop_id=None: _StubAgent(_state("completed")))
    out = await sec.route("随便问一句", shop_id=None, history=[], session_id=None, user_id=None)

    assert "truncated" not in out, "正常完成不该带 truncated 键"
    assert not out["reply"].startswith(sec.TRUNCATED_NOTICE), "正常完成被误加了截断提示"
    assert sec.TRUNCATED_NOTICE not in out["reply"]


@pytest.mark.asyncio
async def test_route_without_structured_response_still_works(monkeypatch):
    """图没产出 `structured_response`（老图 / 无 planning）⇒ 不得抛错。

    判据：消费者对「字段缺失」必须**安全失败**（当作未截断），
    而不是把缺字段变成一次 500。
    """
    monkeypatch.setattr(sec, "get_secretary_agent",
                        lambda shop_id=None: _StubAgent(
                            {"messages": [HumanMessage(content="q"), AIMessage(content="答完了")]}))
    out = await sec.route("随便问一句", shop_id=None, history=[], session_id=None, user_id=None)
    assert out["reply"] == "答完了"
    assert "truncated" not in out
