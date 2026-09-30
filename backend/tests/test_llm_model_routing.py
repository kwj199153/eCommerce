# -*- coding: utf-8 -*-
"""第一轮模型分流门禁（第 238 轮 · P2）。

老板原话：
    「P2 闲聊分流到更快的模型 / 收紧 max_tokens 缩短时长，不解决空窗」

P2 修的不是「空窗」（那是 P0 的活），而是**空窗本身的长度** ——
实测（238k：真 uvicorn + 真 HTTP）秘书链路 14.9s 里有 11.4s 是模型首 token
延迟（TTFT）。首轮「理解 + 决策」这一轮的产出是**一个意图判定 + 可能的工具
调用**，不是长文写作 ⇒ 用默认的 `qwen-max` 干这件事等于用重锤敲核桃。

★ 本文件钉住的**安全属性**（不是实现细节）：

    P2-1 **第一轮**才换模型，而「本轮」的口径与 `_iterations_in_current_turn`
         **同一份** —— 不另立第二份「轮次」定义。本仓铁律：同一个可观察量
         只许有一条真源；两份轮次口径迟早在「第 2 轮算不算第一轮」上打架。
    P2-2 换不换由**两个开关**共同决定，缺一不可：
         类开关 `FAST_FIRST_ROUND`（**默认 False**，只该店秘书打开）
         + 配置开关 `llm_fast_first_round`。
         类开关默认关 ⇒ 其余 5 家 Agent 的行为**零变化**。
    P2-3 备用模型名**为空**、或**等于默认模型**时 ⇒ 回落默认。
         否则会产生「换了但没换」的假象：日志说换了、行为没变、排查时
         先怀疑网络。
    P2-4 拿不到备用模型时**可见地回落**默认模型 + 一条 warning ——
         加速手段不得变成故障源（宁可这一轮慢一点，也不要对话打不开）。
    P2-5 接线点在 `_llm_call_node` 体内，且**真的**把 `model=` 传给了
         `_llm_with_tools`。这一条必须是**行为判据**（驱动节点、看实参）：
         只判「源码里出现过 `_first_round_model`」会被一行注释、一个死方法、
         或「算了但不传」骗过。

★ 反面（误报）同样钉住：
    * **上一轮**的 AIMessage 不算本轮 ⇒ 多轮会话第 2 轮仍走快模型；
    * 本轮**已经发过言**（有 AIMessage）⇒ 必须回落默认模型
      （那是长文写作轮次，快模型在这里是净损失）。

★ 反向注入对照（已实测，见第 238 轮记录）：
    RI-1 `_first_round_model` 改成恒 `None` ⇒ 本文件「换快模型」类断言转红；
    RI-2 调用点 `model=self._first_round_model(...)` 改成 `model=None` ⇒ P2-5 转红；
    RI-3 类开关默认值改成 `True` ⇒ P2-2 的「其余 Agent 零变化」转红。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from langchain_core.messages import AIMessage, HumanMessage
from loguru import logger as _loguru

from ai_infra.base_agent import BaseAgent
from core.config import config

PROBE_AGENT = "p2-routing-probe"


def _capture_loguru(level: str = "WARNING"):
    """把 loguru 的 WARNING 及以上收进列表（返回 `(messages, handler_id)`）。

    ★ **不要用 pytest 的 `caplog`**：`caplog` 抓的是 stdlib `logging`，而
      `ai_infra/base_agent.py` 用的是 **loguru** —— 本仓两套日志栈并存。
      用 caplog 抓 loguru 会「抓不到、但不报错」，于是"日志有没有说清"
      这条判据永远假绿（本文件首版就是这么写的，实测踩到）。
    """
    messages: list[str] = []

    def sink(message):  # pragma: no cover - 纯转发
        messages.append(message.record["message"])

    handler_id = _loguru.add(sink, level=level)
    return messages, handler_id


def _agent() -> BaseAgent:
    """造一个最轻的 Agent —— 本文件判的是**分流决策**，与具体业务 Agent 无关。"""
    return BaseAgent(agent_name=PROBE_AGENT)


def _first_round_agent(monkeypatch) -> BaseAgent:
    """打开两个开关的探针 Agent（两个开关都开才算「启用分流」）。"""
    monkeypatch.setattr(config, "llm_fast_first_round", True)
    a = _agent()
    a.FAST_FIRST_ROUND = True
    return a


# ==================================================================== 决策本身
def test_first_round_uses_the_faster_model(monkeypatch):
    """★ P2-1 正例：本轮只有一条 HumanMessage ⇒ 第一轮，走备用（更快）模型。"""
    a = _first_round_agent(monkeypatch)
    fast = config.llm_fallback_model
    assert fast and fast != config.llm_default_model, (
        f"夹具前提不成立：备用模型必须非空且与默认不同（fast={fast!r}, "
        f"default={config.llm_default_model!r}）"
    )
    got = a._first_round_model([HumanMessage(content="q")])
    assert got == fast, f"第一轮没有走备用模型：{got!r}"


def test_previous_turn_ai_message_does_not_close_the_first_round(monkeypatch):
    """★ P2-1 反面（关键）：**上一轮**的 AIMessage 不算本轮。

    若这里判成「不是第一轮」，多轮会话从第 2 轮起就再也享受不到加速 ——
    而且没有任何报错，只是"感觉一直很慢"，属于最难发现的那一类失效。
    """
    a = _first_round_agent(monkeypatch)
    msgs = [AIMessage(content="上一轮的回答"), HumanMessage(content="这一轮的提问")]
    assert a._first_round_model(msgs) == config.llm_fallback_model, (
        "上一轮的 AIMessage 被当成了本轮发言 —— 多轮会话第 2 轮起不再加速"
    )


def test_ai_message_in_this_turn_falls_back_to_default(monkeypatch):
    """★ P2-1 反面：本轮已发过言 ⇒ 回落默认模型（长文写作轮次，别用快模型）。"""
    a = _first_round_agent(monkeypatch)
    msgs = [HumanMessage(content="q"), AIMessage(content="本轮已发言")]
    assert a._first_round_model(msgs) is None, (
        "本轮已发言却仍在换快模型 —— 长文写作轮次被降级"
    )


def test_both_switches_are_required(monkeypatch):
    """★ P2-2：类开关与配置开关**缺一不可**，谁关都回到默认模型。"""
    ok = [HumanMessage(content="q")]

    monkeypatch.setattr(config, "llm_fast_first_round", True)
    a = _agent()
    a.FAST_FIRST_ROUND = False
    assert a._first_round_model(ok) is None, "类开关关了却仍在换模型"

    monkeypatch.setattr(config, "llm_fast_first_round", False)
    b = _agent()
    b.FAST_FIRST_ROUND = True
    assert b._first_round_model(ok) is None, "配置开关关了却仍在换模型"


def test_base_defaults_off_and_only_secretary_turns_it_on(monkeypatch):
    """★ P2-2：底座默认**关**（其余 5 家 Agent 行为零变化），只有店秘书打开。

    这条同时是「别忘了登记」的反面：新增 Agent 若想享受加速必须**显式**打开，
    不会因为继承底座而悄悄换掉生产模型。
    """
    assert BaseAgent.FAST_FIRST_ROUND is False, (
        "底座类开关默认值被改成 True —— 5 家非店秘书 Agent 的模型被静默换掉"
    )
    from modules.secretary.agent import SecretaryAgent  # noqa: PLC0415

    assert SecretaryAgent.FAST_FIRST_ROUND is True, (
        "店秘书没有打开第一轮加速开关 —— P2 对生产链路无效"
    )


def test_fallback_equal_to_default_is_a_noop(monkeypatch):
    """★ P2-3：备用 == 默认（或空串 / 纯空白）⇒ 回落默认，不制造「换了但没换」。"""
    a = _first_round_agent(monkeypatch)
    ok = [HumanMessage(content="q")]

    monkeypatch.setattr(config, "llm_fallback_model", config.llm_default_model)
    assert a._first_round_model(ok) is None, "备用模型与默认相同却宣称在分流"

    for blank in ("", "   "):
        monkeypatch.setattr(config, "llm_fallback_model", blank)
        assert a._first_round_model(ok) is None, f"备用模型是空值 {blank!r} 却仍在分流"


# ================================================================ 取数与回落
def test_fallback_model_is_built_once_and_cached(monkeypatch):
    """★ 按名缓存：同一轮里可能被问多次，不能每次都新建一个客户端对象。

    ★ 另外钉住「`None` / 默认模型名 ⇒ 走 `self.llm`」—— 这条是 P2-3 在
      **取数层**的对应物：`_first_round_model` 负责"要不要换"，
      `_llm_for` 负责"换的话给谁"，两层对"等于默认"必须给同一答案。
    """
    a = _agent()
    calls: list[str] = []

    class _Fake:
        def __init__(self, model: str) -> None:
            self.model = model

    def _build(self, model: str):
        calls.append(model)
        return _Fake(model)

    monkeypatch.setattr(BaseAgent, "_build_chat_model", _build, raising=False)

    first = a._llm_for("qwen-plus")
    second = a._llm_for("qwen-plus")
    assert isinstance(first, _Fake) and first is second, "同名的备用模型被重复构造"
    assert calls == ["qwen-plus"], f"构造调用次数/入参不对：{calls}"

    assert a._llm_for(None) is a.llm, "缺省模型名没有走默认模型"
    assert a._llm_for(config.llm_default_model) is a.llm, "默认模型名没有走默认模型"


def test_build_failure_falls_back_visibly(monkeypatch):
    """★ P2-4：备用模型构造失败 ⇒ **可见地**回落默认模型（不是静默、也不是崩）。

    静默回落与"正在用备用模型"无法区分；直接抛异常则把"想加速"变成"打不开"。
    """
    a = _agent()
    default = a.llm
    assert default is not None, "夹具前提：默认模型应可用（conftest 离线桩）"

    def _boom(self, model: str):
        raise RuntimeError("model 不存在")

    monkeypatch.setattr(BaseAgent, "_build_chat_model", _boom, raising=False)

    messages, handler_id = _capture_loguru()
    try:
        got = a._llm_for("qwen-does-not-exist")
    finally:
        _loguru.remove(handler_id)

    assert got is default, "备用模型构造失败时没有回落默认模型"
    assert any("qwen-does-not-exist" in m for m in messages), (
        f"回落是静默的 —— 日志里没有点名是哪个模型失败了：{messages}"
    )


# ==================================================================== 接线
def test_llm_call_node_passes_the_first_round_model(monkeypatch):
    """★ P2-5 接线判据（行为式）：驱动 `_llm_call_node`，看它**真的**传了什么。

    为什么不能只判源码串：`_build_chat_model` / `_first_round_model` 都实现正确、
    但调用点写成 `model=None`（或忘了传）时，源码里那些名字**照样都在**。
    只有"驱动一次、看实参"才能把这种「实现了但没接上」区分出来。
    """
    monkeypatch.setattr(config, "llm_fast_first_round", True)
    monkeypatch.setattr(config, "llm_fallback_model", "qwen-turbo-probe")
    a = _agent()
    a.FAST_FIRST_ROUND = True

    seen: list = []

    def _run(state: dict) -> dict:
        with patch.object(a, "_llm_with_tools") as m:
            m.return_value.ainvoke = AsyncMock(return_value=AIMessage(content="ok"))
            out = asyncio.run(a._llm_call_node(state))
            seen.append(m.call_args.kwargs.get("model"))
            return out

    _run({"messages": [HumanMessage(content="第一轮")]})
    _run({"messages": [HumanMessage(content="第一轮"), AIMessage(content="已发言")]})

    assert seen == ["qwen-turbo-probe", None], (
        f"调用点没有按轮次分流（第一轮应换快模型、第二轮应回落默认）：{seen}"
    )
