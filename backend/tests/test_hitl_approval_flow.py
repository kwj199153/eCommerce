"""
HITL 审批闭环：中断态回传 + resume 契约 + **关键词旁路门禁**（2026-09-17，第 131 轮 item2-B）

背景 —— 本轮实测到一条**绕过审批的路**：
  `_classify_intent()` 的 `save_keywords` 含「选品库 / 候选库 / 候选池 / 入库 …」，
  命中即 `invoke()` / `stream_chat()` 里走 `_process_query()` → `_save_candidate()`
  ⇒ **零审批直写**，完全绕开 router 工具路径。
  而同一件事若未被关键词命中、由 LLM 判定为入库，则**要审批**。
  同一个操作两套规矩，且被绕过的那条恰好是最高频的表达（「入库」）。

修法：有副作用的意图收成一处名单 `_APPROVAL_GATED_INTENTS`，两个入口都先看它，
命中则改走带审批的工具路径；审批通道不可用时**拒绝写入**（而非降级直写）。

★ 反向注入（改坏了必须转红）：
  ① 把 `save_candidate` 从 `_APPROVAL_GATED_INTENTS` 里去掉 ⇒
     `test_invoke_never_writes_directly_for_gated_intent` 与
     `test_stream_chat_never_writes_directly_for_gated_intent` 双双转红。
  ② 把 `stream_chat()` 里那段 gated 分支删回「元组含 save_candidate」⇒
     `test_stream_chat_never_writes_directly_for_gated_intent` 转红。
  ③ 在 `_pending_approval_from_interrupt()` 的 data 里加上 thread_id ⇒
     `test_pending_approval_never_leaks_thread_id` 转红。
  ④ 把 `ApprovalResumeRequest.decision` 从 `Literal` 改回 `str` ⇒
     `test_approval_resume_request_rejects_unknown_decision` 转红。
  ⑤ 把 `_build_resume_payload` 的 reject 分支改成 `{"type": "reject"}`（丢 args）⇒
     `test_build_resume_payload_contract` 转红（包装器读不到 reason）。
"""

import json

import pytest

from langchain_core.messages import AIMessage, ToolMessage


# ====== 工具：可控的假 router / 假分类器 ======


class _Snapshot:
    """替身：`graph.aget_state()` 的返回值（默认「没有待审批中断」）。"""

    tasks = ()


class _FakeRouter:
    """替身 router：既是「图」也是「router」。

    `resume_approval()` 需要 `router.checkpointer`、
    `router.graph_for_session()`、`graph.ainvoke()` 与 `graph.aget_state()`。
    """

    def __init__(self, state=None):
        self.checkpointer = object()  # 非 None 即可
        self.state = state if state is not None else {"messages": []}
        self.invocations = []

    def graph_for_session(self, context_id, user_id):
        return self, {"configurable": {"thread_id": f"probe:{user_id}:{context_id}"}}

    async def ainvoke(self, inp, config=None):
        self.invocations.append(inp)
        return self.state

    async def aget_state(self, config):
        return _Snapshot()


def _mk_classify(intent: str):
    async def _c(self, query):
        return intent

    return _c


def _fake_agent(monkeypatch, intent="save_candidate", router=None):
    """造一个 ProductResearchAgent，并把意图分类 / router / 直写通道全部接管。"""
    from modules.product_research.agent_product_research import (
        AgentResponse,
        ProductResearchAgent,
    )

    agent = ProductResearchAgent()
    direct_writes = []
    routed_queries = []

    async def _fake_direct_save(*a, **k):
        direct_writes.append((a, k))
        return {"type": "candidate_saved", "saved": [{"asin": "B0X"}]}

    async def _fake_route_via_tools(self, query, context_id=None, user_id=None):
        routed_queries.append(query)
        return AgentResponse(
            content="这一步需要你确认：准备执行「save_candidate」。",
            data={"type": "pending_approval", "session_id": context_id},
            display_type="pending_approval",
        )

    async def _fake_stream_via_tools(
        self, query, context_id=None, user_id=None, gated=False
    ):
        # ★ 流式入口走的是 `_stream_via_tools`（不是 `_route_via_tools`）——
        #   两条入口各有自己的底层实现，patch 必须成对，否则这条用例会在
        #   「压根没走到路由」上失败，看起来像被测代码的错。
        # ★ 第 131 轮起该函数多了一个 `gated` 形参（有副作用意图不得掉进闲聊兜底），
        #   桩必须同步签名，否则真实调用会以 TypeError 形式炸在这里。
        assert gated, "有副作用意图必须以 gated=True 走工具路径（否则会掉进闲聊兜底）"
        routed_queries.append(query)
        yield "这一步需要你确认：准备执行「save_candidate」。"
        yield {
            "event": "meta",
            "data": {"display_type": "pending_approval", "data": {"type": "pending_approval"}},
        }

    monkeypatch.setattr(agent, "_classify_intent", _mk_classify(intent).__get__(agent, type(agent)))
    monkeypatch.setattr(agent, "_save_candidate", _fake_direct_save)
    monkeypatch.setattr(agent, "_route_via_tools", _fake_route_via_tools.__get__(agent, type(agent)))
    monkeypatch.setattr(
        agent, "_stream_via_tools", _fake_stream_via_tools.__get__(agent, type(agent))
    )
    if router is not None:
        monkeypatch.setattr(agent, "_get_router", lambda: router)
    return agent, direct_writes, routed_queries


# ====== A. 名单本身 ======


def test_gated_intents_contains_save_candidate():
    """
    有副作用的意图必须登记在**唯一名单**里。

    ★ 为什么这条断言值得单独存在：整条旁路修复都挂在「名单里有没有它」上。
      断言名单内容 = 把「哪些意图需要审批」这件事变成**显式、可 review、可门禁**
      的声明，而不是散在两个 `if` 里的字面量。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    assert "save_candidate" in ProductResearchAgent._APPROVAL_GATED_INTENTS


# ====== B. 旁路门禁（本轮最重要的一组）======


async def test_invoke_never_writes_directly_for_gated_intent(monkeypatch):
    """
    ★★★ 关键词命中的入库**不得直接写库**（必须走审批路径）。

    ★ 为什么用「直写通道的调用次数」而不是断言返回值：
      返回值可以伪装 —— `_route_gated_intent` 返回一个「待审批」文案，
      而代码里若**先偷偷写了一次**再返回，只看返回值同样会绿。
      只有数 `_save_candidate` 的调用次数能证明「没绕过审批」。
    """
    agent, direct, routed = _fake_agent(monkeypatch)
    # ★ 必须带 shop_id：本条测的是「审批通道」，不是「缺店铺」；
    #   缺店铺时会先被入口校验拦下（那由下面两条专门的用例覆盖）。
    result = await agent.invoke("把这个品加进选品库", shop_id="shop-hitl")

    assert direct == [], (
        "关键词命中的入库走了 `_save_candidate` 直写 ⇒ **绕过 HITL 审批**。"
        "这条旁路恰好覆盖最高频的表达（『入库』就在 save_keywords 里）。"
    )
    assert routed, "没有走带审批的工具路径"
    assert result.display_type == "pending_approval"


async def test_stream_chat_never_writes_directly_for_gated_intent(monkeypatch):
    """
    ★★★ 流式入口同样不得直写（与非流式**同一条规矩**）。

    ★ 为什么单独测流式：`invoke()` 与 `stream_chat()` 是两条独立入口，
      修一处漏一处是本项目反复出现的形态（「同一件事两种表现」）。
      只测非流式，等于给流式旁路留了一扇门。
    """
    agent, direct, routed = _fake_agent(monkeypatch)
    # ★ 同非流式：带 shop_id，专测「流式也不得直写」
    chunks = [
        c
        async for c in agent.stream_chat(
            "把这个品加进选品库", shop_id="shop-hitl"
        )
    ]

    assert direct == [], "流式入口走了直写 ⇒ 流式可绕过审批"
    assert routed, "流式入口没有走带审批的工具路径"
    assert chunks, "流式入口没有任何输出"


async def test_gated_intent_refuses_when_approval_channel_unavailable(monkeypatch):
    """
    审批通道不可用时**拒绝写入**，而不是降级直写。

    ★ 为什么这条比「写成功」更重要：降级直写意味着
      **基础设施一抖，审批就自动失效** —— 那是比拒绝危险得多的行为。
      原则与 `core.auth.accounts` 同源：「没有身份 ⇒ 没有数据」，
      这里是「没有审批通道 ⇒ 不执行有副作用的操作」。
    """
    agent, direct, routed = _fake_agent(monkeypatch, router=None)
    monkeypatch.setattr(agent, "_get_router", lambda: None)

    # ★ 必须带 shop_id：本条测的是「审批通道」，不是「缺店铺」；
    #   缺店铺时会先被入口校验拦下（那由下面两条专门的用例覆盖）。
    result = await agent.invoke("把这个品加进选品库", shop_id="shop-hitl")

    assert direct == [], "审批通道不可用却仍然直写"
    assert result.data.get("error") == "approval_channel_unavailable"
    assert "没有写入" in result.content


async def test_gated_intent_refuses_without_shop_before_any_write(monkeypatch):
    """
    ★ 缺店铺 ⇒ 在**入口**就拒绝（零 DB 往返、零写入），并给出指向店铺的可读原因。

    ★ 为什么提前到入口（第 131 轮补）：
      此处意图**已确定为写**，不存在「只读意图被误伤」的顾虑
      （`chat` 用豁免版依赖正是为了不误伤只读意图）。
      而等到审批走完再报「没选店铺」，等于让用户白点一次批准，
      失败还被推迟到看不见的地方。
    ★ 反向注入：删掉 `_route_gated_intent` 里那段前置校验 ⇒ 本条转红
      （会变成 pending_approval 或 approval_channel_unavailable，
        两者都不是「请选店铺」）。
    """
    agent, direct, routed = _fake_agent(monkeypatch)

    result = await agent.invoke("把这个品加进选品库")  # 刻意不传 shop_id

    assert direct == [], "缺店铺却仍然直写"
    assert routed == [], (
        "缺店铺时不该去调工具路径 —— 即便用户点了批准也写不进去，"
        "白点一次还把失败推迟到看不见的地方"
    )
    assert result.data.get("error") == "no_shop_selected"
    assert "店铺" in result.content, f"必须指向店铺：{result.content[:200]}"
    assert "没有写入" in result.content, "必须明说这次没有写入"


async def test_stream_gated_intent_refuses_without_shop_before_any_write(monkeypatch):
    """
    流式入口同样「缺店铺 ⇒ 入口拒绝」，且文案与非流式**逐字同源**。

    ★ 为什么单独测流式：`invoke()` 与 `stream_chat()` 是两条独立入口，
      修一处漏一处是本项目反复出现的形态（「同一件事两种表现」）。
    """
    agent, direct, routed = _fake_agent(monkeypatch)

    chunks = [c async for c in agent.stream_chat("把这个品加进选品库")]
    text = "".join(c for c in chunks if isinstance(c, str))

    assert direct == [], "缺店铺却仍然直写"
    assert routed == [], "缺店铺时不该去调工具路径"
    assert "店铺" in text, f"必须指向店铺：{text[:200]}"
    assert "没有写入" in text, "必须明说这次没有写入"


# ====== C. resume 载荷契约（与 hitl_decorator 逐字段对齐）======


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        (dict(decision="accept"), {"type": "accept", "args": {}}),
        (
            dict(decision="reject", reason="老板说不要"),
            {"type": "reject", "args": {"reason": "老板说不要"}},
        ),
        (
            dict(decision="reject"),
            {"type": "reject", "args": {"reason": "未提供原因"}},
        ),
        (
            dict(decision="edit", args={"asin": "B0Y"}),
            {"type": "edit", "args": {"args": {"asin": "B0Y"}}},
        ),
        (
            dict(decision="response", feedback="先别存"),
            {"type": "response", "args": "先别存"},
        ),
    ],
    ids=["accept", "reject-with-reason", "reject-default", "edit", "response"],
)
def test_build_resume_payload_contract(kwargs, expected):
    """
    决策 → 载荷的映射必须与 `hitl_decorator.call_tool_with_hitl` 读取的字段**逐字一致**。

    ★ 对不上的表现是「点了批准但什么都没发生」：包装器按
      `response.get("type")` 分派，认不出就落到 else 抛
      `不支持的 HITL 响应类型` —— 而它抛在**图内部**，用户侧只看到一次无反应。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    assert ProductResearchAgent._build_resume_payload(**kwargs) == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        dict(decision="approve"),  # 近义词，不是契约值
        dict(decision=""),
        dict(decision="edit"),  # edit 缺 args
        dict(decision="edit", args={}),  # edit 给了空 args
    ],
    ids=["approve-typo", "empty", "edit-no-args", "edit-empty-args"],
)
def test_build_resume_payload_rejects_bad_decision(kwargs):
    """非法决策必须**当场抛错**，而不是构造出一个包装器认不出的载荷。"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    with pytest.raises(ValueError):
        ProductResearchAgent._build_resume_payload(**kwargs)


# ====== D. 中断态渲染（不得泄露 thread_id）======


class _FakeInterrupt:
    id = "interrupt-abc"

    def __init__(self, tool_name="save_candidate", args=None, require_reason=False):
        self.value = {
            "action_request": {
                "action": tool_name,
                "args": args if args is not None else {"asin": "B0X", "title": "T"},
                "require_reason": require_reason,
                "timeout": 3600,
            },
            "config": {},
            "description": "⚠️ 准备执行操作",
        }


def test_pending_approval_shape():
    """中断渲染成前端可直接展示的审批卡载荷。"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    r = ProductResearchAgent._pending_approval_from_interrupt(_FakeInterrupt(), "sess-1")
    assert r.display_type == "pending_approval"
    assert r.data["type"] == "pending_approval"
    ap = r.data["approval"]
    assert ap["action"] == "save_candidate"
    assert ap["args"] == {"asin": "B0X", "title": "T"}
    assert ap["interrupt_id"] == "interrupt-abc"
    assert r.data["session_id"] == "sess-1"


def test_pending_approval_never_leaks_thread_id():
    """
    ★★★ 审批卡载荷里**不能出现 thread_id**。

    ★ 为什么这是一条安全断言：`thread_id` = `命名空间:user_id:session_id`，
      里面**含 user_id**。把它交给客户端，就等于让请求方持有一个
      「我是谁」的凭证片段 —— resume 时服务端必须按与首轮相同的口径
      **自己算** thread_id，而不是相信客户端交回来的那个。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    r = ProductResearchAgent._pending_approval_from_interrupt(_FakeInterrupt(), "sess-1")
    blob = json.dumps(r.data, ensure_ascii=False)
    assert "thread_id" not in blob
    assert "thread" not in blob.lower()


# ====== E. 结果解包 ======


def test_unwrap_hitl_tool_output():
    """
    从包装器文案里取回内层工具的结构化结果。

    ★ 为什么要解包：审批通过后的结果应与「没走审批」时**长得一模一样**
      （同一个结果卡、同一套字段）。否则前端要为「审批后」单独写渲染，
      两边字段一漂移就又回到「同一件事两种表现」。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    raw = '✅ 操作已执行 [save_candidate]\n结果: {"type": "candidate_saved", "saved": [{"asin": "B0X"}]}'
    assert ProductResearchAgent._unwrap_hitl_tool_output(raw) == {
        "type": "candidate_saved",
        "saved": [{"asin": "B0X"}],
    }
    # 解包失败一律 None（调用方降级展示原文案，不让「文案变了」升级成「审批报错」）
    assert ProductResearchAgent._unwrap_hitl_tool_output("") is None
    assert ProductResearchAgent._unwrap_hitl_tool_output("没有任何标记") is None
    assert ProductResearchAgent._unwrap_hitl_tool_output("结果: 不是 JSON") is None


# ====== F. 入口校验 + 失败分支 ======


def test_approval_resume_request_rejects_unknown_decision():
    """
    ★ 非法 `decision` 必须在**入口**（pydantic）就被挡掉，不能落到图内部。

    反向注入：把 `Literal[...]` 改回 `str` ⇒ 本条转红。
    """
    from pydantic import ValidationError

    from modules.product_research.schemas import ApprovalResumeRequest

    ok = ApprovalResumeRequest(context_id="s-1", decision="accept")
    assert ok.decision == "accept"

    with pytest.raises(ValidationError):
        ApprovalResumeRequest(context_id="s-1", decision="approve")  # 近义词不是契约值
    with pytest.raises(ValidationError):
        ApprovalResumeRequest(context_id="s-1", decision="")


async def test_resume_requires_identity(monkeypatch):
    """没有登录身份 ⇒ 回绝（定位不到「你那条」待审批的操作）。"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    agent = ProductResearchAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: _FakeRouter())
    r = await agent.resume_approval("sess-1", "accept", user_id=None)
    assert r.data["error"] == "missing_session_or_identity"


async def test_resume_requires_checkpointer(monkeypatch):
    """会话存储没就绪 ⇒ 回绝（审批记录无处落盘）。"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    class _NoCp(_FakeRouter):
        def __init__(self):
            super().__init__()
            # ★ 必须覆盖**实例**属性：父类 `__init__` 把 checkpointer 设成了
            #   `object()`，只写类属性会被实例属性盖过，用例会静默走错分支。
            self.checkpointer = None

    agent = ProductResearchAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: _NoCp())
    r = await agent.resume_approval("sess-1", "accept", user_id="u-1")
    assert r.data["error"] == "checkpointer_unavailable"


async def test_resume_accept_returns_unwrapped_result(monkeypatch):
    """
    批准 → 把 `Command(resume=...)` 喂回图 → 返回**内层工具的结构化结果**。

    ★ 断言 `Command(resume=...)` 真的被传进去：`resume_approval` 若把
      普通 state 当 input 传（而不是 `Command(resume=)`），图会**从头再跑一遍**
      —— 表现是「批准后又说了一句一样的话」，且 `interrupt()` 再次触发，
      用户会看到一个**永远批准不完**的审批卡。
    """
    from langgraph.types import Command

    from modules.product_research.agent_product_research import ProductResearchAgent

    fake = _FakeRouter(
        state={
            "messages": [
                ToolMessage(
                    content='✅ 操作已执行 [save_candidate]\n结果: '
                            '{"type": "candidate_saved", "saved": [{"asin": "B0X"}]}',
                    tool_call_id="c1",
                ),
                AIMessage(content="已加入选品库。"),
            ]
        }
    )
    agent = ProductResearchAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: fake)
    monkeypatch.setattr(agent, "_bind_context", staticmethod(lambda *a, **k: None))

    r = await agent.resume_approval("sess-1", "accept", user_id="u-1", shop_id="sh-1")

    assert fake.invocations, "resume 压根没驱动图"
    assert isinstance(fake.invocations[0], Command), "resume 必须用 Command(resume=...) 而不是普通 state"
    assert fake.invocations[0].resume == {"type": "accept", "args": {}}
    assert r.data["type"] == "candidate_saved"
    assert r.data["approval_decision"] == "accept"


async def test_resume_rebind_context_before_rerun(monkeypatch):
    """
    续跑前必须重新绑定 ContextVar（会话 + 店铺归属）。

    ★ 为什么这条单独钉：被中断的工具在 resume 时会**重新执行**，而它靠
      ContextVar 读 `shop_id`。不重绑 ⇒ `_write_candidates` 拿到 `None`
      ⇒ 用户「批准了」却收到「请先选一个店铺」——这条链路上最迷惑的表现。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    fake = _FakeRouter()
    agent = ProductResearchAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: fake)
    bound = []
    # ★ 第 145 轮批 C1：形参从 `(ctx, shop)` 变成 `(ctx, shop, user)` ——
    #   会话状态的作用域键含 `user_id`，不绑 ⇒ 被中断的工具会在**另一个作用域**
    #   里找会话状态（`_save_candidate` 要靠它把「第 1 个」解析成具体商品）。
    #   这里**不写成 `*a`**：那样等于放弃对实参的断言，把新增的身份约束放走。
    monkeypatch.setattr(
        agent,
        "_bind_context",
        staticmethod(lambda ctx, shop=None, user=None: bound.append((ctx, shop, user))),
    )

    await agent.resume_approval("sess-9", "reject", user_id="u-1", shop_id="sh-9")
    assert bound == [("sess-9", "sh-9", "u-1")], (
        f"续跑前没绑定完整上下文（会话 + 归属 + 身份），实际 {bound}"
    )
