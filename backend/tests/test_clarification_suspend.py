# -*- coding: utf-8 -*-
"""澄清**真挂起**的机制门禁（第 400 轮 P0-3）。

## 这一条链之前缺什么

改造前 `ask_clarification` 只是 `return json.dumps(payload)`：模型读到这条
tool result 后**在正文里复述一遍问题**，本轮就结束了。老板的回答进的是
**下一轮的新对话**（上一轮 AIMessage 只有 `tool_calls`、没有正文可承接），
前端也没有任何结构化入口（`clarification_request` 零消费者）。
」协议定义了、执行侧只吐字符串、UI 侧没人接「—— 半条链。

改完之后要钉住三件事，缺一条链子就静默断掉：

  ① **图真的停住**（`interrupt()` 没被 `except Exception` 吞掉）；
  ② **停住的形状**能被读成一张卡（中立层 + 店秘书的正文取口）；
  ③ **续跑值喂对了**（澄清读的是一句原话，不是审批的 `{"type":"accept"}`）。
     喂错**不会报错** —— 工具只是把那个 dict 当答案读走了。

## 反向注入

* 把 `ask_clarification` 里的 `except GraphBubbleUp: raise` 删掉 ⇒ 判据 1/2 红
  （`GraphInterrupt` 落进 `except Exception`，图不再停）；
* 把 `_pending_kind` 改成恒返回 `"approval"` ⇒ 判据 5 红（续跑值形状不对）；
* 从 `_digest_graph_state` 删掉澄清那段 ⇒ 判据 4 红（`reply` 退回「处理完成」）。
"""
from __future__ import annotations

import json
from typing import Optional, TypedDict

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Interrupt


# ============================================================
# 1. 真的会挂起
# ============================================================


class _State(TypedDict, total=False):
    messages: list


def _one_node_graph(node_fn):
    """把 `node_fn` 装成一张最小图（带内存 checkpointer）。"""
    from langgraph.checkpoint.memory import InMemorySaver

    g = StateGraph(_State)
    g.add_node("ask", node_fn)
    g.add_edge(START, "ask")
    g.add_edge("ask", END)
    return g.compile(checkpointer=InMemorySaver())


async def test_tool_form_suspends_the_graph():
    """**工具形态**（模型实际调用的那条）必须把图停住。

    ★ 为什么用 `tool.ainvoke` 而不是直接调函数：生产路径是 langchain 的
      工具调用。`config` 要靠**注解是 `RunnableConfig`** 才会被注入 ——
      写成 `Optional[RunnableConfig]` 时注入失效，`interrupt()` 拿不到
      run 上下文 ⇒ **永远不挂起且零报错**（eEducation 第 559 轮实测）。
      本判据同时钉住"注解形态"与"挂起行为"。
    """
    from ai_infra.tools.clarification import CLARIFICATION_TYPE, make_clarification_tool

    tool = make_clarification_tool()

    async def node(_state):
        raw = await tool.ainvoke({"question": "做这张主图想突出什么卖点？", "options": ["防水", "轻便"]})
        return {"messages": [raw]}

    graph = _one_node_graph(node)
    cfg = {"configurable": {"thread_id": "t-tool"}}

    out = await graph.ainvoke({"messages": []}, config=cfg)
    interrupts = out.get("__interrupt__") or ()
    assert interrupts, (
        "图没有停在澄清上 —— `interrupt()` 被吞掉了（`except Exception` 里漏了 "
        "`GraphBubbleUp` 的重新抛出，或 config 注解不再是 `RunnableConfig`）"
    )
    payload = interrupts[0].value
    assert payload["type"] == CLARIFICATION_TYPE == "clarification_request"
    assert payload["question"] == "做这张主图想突出什么卖点？"
    assert payload["options"] == [{"label": "防水"}, {"label": "轻便"}]


async def test_direct_call_also_suspends_inside_graph():
    """直接调用（不经工具包装）也要挂起 —— 证明挂起不依赖 langchain 的注入。

    ★ 两条口都要有用例：生产走工具形态，单测与脚本常直接调函数。
      只测一条时，另一条坏了没人知道。
    """
    from ai_infra.tools.clarification import ask_clarification

    async def node(_state):
        return {"messages": [await ask_clarification("你指的是哪个店铺？")]}

    graph = _one_node_graph(node)
    out = await graph.ainvoke({"messages": []}, config={"configurable": {"thread_id": "t-direct"}})
    assert out.get("__interrupt__"), "直接调用没有挂起"


async def test_resume_delivers_the_answer_back_to_the_model():
    """续跑后，工具读到的是**老板的原话**，并交回模型（同一轮继续）。"""
    from ai_infra.tools.clarification import CLARIFICATION_ANSWER_TYPE, make_clarification_tool

    tool = make_clarification_tool()

    async def node(_state):
        raw = await tool.ainvoke({"question": "卖点是什么？"})
        return {"messages": [raw]}

    graph = _one_node_graph(node)
    cfg = {"configurable": {"thread_id": "t-resume"}}
    await graph.ainvoke({"messages": []}, config=cfg)

    out = await graph.ainvoke(Command(resume={"type": "clarification_answer", "answer": "防水"}), config=cfg)
    data = json.loads(out["messages"][-1])
    assert data["type"] == CLARIFICATION_ANSWER_TYPE
    assert data["answer"] == "防水"
    assert data["question"] == "卖点是什么？"
    assert data["status"] == "ok"


async def test_blank_answer_is_reported_as_empty_not_as_ok():
    """空回答要标 `status=empty` —— 让模型自己决定再问一次还是先做。

    ★ 为什么不在工具里替模型决定：那是**业务**判断。工具只负责把事实说清。
    """
    from ai_infra.tools.clarification import make_clarification_tool

    tool = make_clarification_tool()

    async def node(_state):
        raw = await tool.ainvoke({"question": "卖点是什么？"})
        return {"messages": [raw]}

    graph = _one_node_graph(node)
    cfg = {"configurable": {"thread_id": "t-empty"}}
    await graph.ainvoke({"messages": []}, config=cfg)
    out = await graph.ainvoke(Command(resume=""), config=cfg)
    data = json.loads(out["messages"][-1])
    assert data["status"] == "empty" and data["answer"] == ""


# ============================================================
# 2. 停住的形状 → 一张卡
# ============================================================


def _clarification_interrupt(**over) -> Interrupt:
    value = {
        "type": "clarification_request",
        "action": "ask_user",
        "question": "做这张主图想突出什么卖点？",
        "options": [{"label": "防水"}],
        "missing_fields": ["卖点"],
        "status": "awaiting_user_input",
    }
    value.update(over)
    return Interrupt(value=value, id="int-1")


def test_pending_payload_becomes_a_card():
    """中立层把中断渲染成 `{content, data, display_type}`，且不回传 thread_id。"""
    from modules.hitl.clarification import pending_clarification_payload

    p = pending_clarification_payload(_clarification_interrupt(), "sess-1", "secretary")
    assert p is not None
    assert p["display_type"] == "clarification_request"
    assert p["content"] == "做这张主图想突出什么卖点？"   # 正文＝问题本身
    assert p["data"]["session_id"] == "sess-1"
    assert p["data"]["agent"] == "secretary"
    assert "thread_id" not in json.dumps(p["data"]), "thread_id 不许出服务端（含 user_id）"


def test_approval_interrupt_is_not_mistaken_for_clarification():
    """审批中断不能被当成澄清（同一个 Agent 既有写工具也有提问工具）。"""
    from modules.hitl.clarification import pending_clarification_payload

    approval = Interrupt(value={"action_request": {"action": "create_ticket", "args": {}}}, id="i2")
    assert pending_clarification_payload(approval, "s", "customer-service") is None


def test_blank_question_is_skipped_not_rendered():
    """空问题一律跳过（渲染成一张空卡＝用户侧「AI 卡住了」）。"""
    from modules.hitl.clarification import pending_clarification_payload

    assert pending_clarification_payload(_clarification_interrupt(question="   "), "s", "x") is None


def test_secretary_digest_exposes_the_question_as_reply():
    """★ 店秘书的正文取口必须把「问题」当正文，而不是默认的「处理完成」。

    ★ 为什么这条最值钱：图被 interrupt 冻结时，最后一条 AIMessage 只有
      `tool_calls`、没有正文 ⇒ 改造前 `reply` 保持默认值「处理完成」。
      老板看到"处理完成"，而实际上还有一句话在等他回答 ——
      他会去干别的，那个待回答的提问永远挂着。
    """
    from langchain_core.messages import HumanMessage

    from modules.secretary.agent import _digest_graph_state

    state = {
        "messages": [HumanMessage(content="帮我做主图")],
        "__interrupt__": (_clarification_interrupt(),),
    }
    result = _digest_graph_state(state, session_id="sess-9")
    assert result["reply"] == "做这张主图想突出什么卖点？"
    assert result["display_type"] == "clarification_request"
    assert result["clarification"]["session_id"] == "sess-9"
    assert result["clarification"]["agent"] == "secretary"


def test_secretary_digest_unchanged_without_interrupt():
    """没有中断时不得凭空造出 clarification（否则每条回复都会多一张卡）。"""
    from langchain_core.messages import AIMessage, HumanMessage

    from modules.secretary.agent import _digest_graph_state

    result = _digest_graph_state(
        {"messages": [HumanMessage(content="你好"), AIMessage(content="你好，老板")]},
        session_id="s",
    )
    assert "clarification" not in result and "display_type" not in result
    assert result["reply"] == "你好，老板"


# ============================================================
# 3. 续跑值：澄清读原话，审批读四档
# ============================================================


class _FakeSnapshot:
    def __init__(self, interrupts):
        self.tasks = [type("T", (), {"interrupts": interrupts})()]


class _FakeGraph:
    def __init__(self, interrupts, reply="好的，按防水来做。"):
        self._interrupts = interrupts
        self.captured: Optional[Command] = None
        self._reply = reply

    async def aget_state(self, _cfg):
        return _FakeSnapshot(self._interrupts)

    async def ainvoke(self, command, config=None):  # noqa: ARG002
        self.captured = command
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content=self._reply)]}


class _FakeRouter:
    checkpointer = object()  # 只要有值即可（判据只判 None）

    def __init__(self, graph):
        self._graph = graph

    def graph_for_session(self, _session_id, _user_id):
        return self._graph, {"configurable": {"thread_id": "x"}}


async def _resume_with(interrupts):
    from modules.hitl import resume_approval

    graph = _FakeGraph(list(interrupts))
    out = await resume_approval(
        "sess-1",
        "response",
        user_id="u1",
        shop_id=None,
        feedback="用防水卖点",
        get_router=lambda: _FakeRouter(graph),
        bind_context=lambda *_a: None,
        log_tag="test",
    )
    return out, graph


async def test_resume_feeds_clarification_answer_not_approval_payload():
    """★ 停在澄清上时，续跑值必须是「一句原话」，不能是审批的四档载荷。

    ★ 喂错**不会报错**：`interrupt()` 收下那个 dict，工具把它当答案读走，
      模型读到一坨 `{"type": "response", ...}` 的 JSON —— 没有异常、
      没有日志，只是回答得莫名其妙。这条判据就是为这个形态写的。
    """
    out, graph = await _resume_with([_clarification_interrupt()])
    assert graph.captured is not None
    resume_value = graph.captured.resume
    assert isinstance(resume_value, dict)
    assert resume_value["type"] == "clarification_answer"
    assert resume_value["answer"] == "用防水卖点"
    assert out["display_type"] == "text"
    assert out["content"] == "好的，按防水来做。"
    assert "approval_decision" not in out["data"], "澄清结果里混进了审批专有字段"


async def test_resume_still_feeds_approval_payload_when_stopped_on_approval():
    """停在审批上时仍然走四档载荷（澄清的加入不能改写审批的行为）。"""
    from modules.hitl import resume_approval

    approval = Interrupt(value={"action_request": {"action": "save_candidate", "args": {}}}, id="a1")
    graph = _FakeGraph([approval])
    await resume_approval(
        "sess-1",
        "accept",
        user_id="u1",
        shop_id=None,
        reason=None,
        args=None,
        feedback=None,
        get_router=lambda: _FakeRouter(graph),
        bind_context=lambda *_a: None,
        log_tag="test",
    )
    assert graph.captured.resume == {"type": "accept", "args": {}}


async def test_resume_without_feedback_fails_closed():
    """停澄清上但没带回答 ⇒ 明确拒绝（而不是把空字符串喂给模型）。"""
    from modules.hitl import resume_approval

    graph = _FakeGraph([_clarification_interrupt()])
    out = await resume_approval(
        "sess-1",
        "response",
        user_id="u1",
        shop_id=None,
        feedback="   ",
        get_router=lambda: _FakeRouter(graph),
        bind_context=lambda *_a: None,
        log_tag="test",
    )
    assert graph.captured is None, "空回答不该真的去续跑"
    assert out["data"]["error"] == "missing_feedback"
