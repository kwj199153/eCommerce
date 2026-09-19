"""批 D1 门禁：子层「结构化摘要回传」契约（第 159 轮）。

r141 批 D1 原文：`子 Agent 跑独立 checkpoint_ns + 结构化摘要回传，替代共用一个历史`。

实测现状（拆成两半看，别混为一谈）：

* **独立 `checkpoint_ns` 早在**（`listing` / `product_research` 各自一个 ns，
  `BaseAgent.resolve_thread_id` 把 ns 拼进 `thread_id`）⇒ 与主层不共用历史。
  本文件用 **AST 形态判据**把它钉住（两个装配点的 ns 必须不同且非空）。
* **缺的是「结构化摘要回传」**：父层 `_route_via_tools` 此前必须自己扫整段
  `state["messages"]` 才能还原「调了哪个工具 / 结果是什么 / 最后由谁作答」
  —— 即「拿原始 state 自行组装业务响应」，对**历史形态**硬依赖。

★ 本组门禁钉的是**性质**而不是形式：
  「摘要有没有被生产」+「父层有没有真的读它」+「读不到时会不会安全失败」。

★ 刻意**不动** `_stream_via_tools`（pr）：它走 `astream_events` 事件流，
  本来就不读历史（注释明写「只给事件、不给最终 state」）；
  为「统一」把它改成扫 state 反而**退化**。最后一条门禁把这个判断钉住。

★ 写这组断言时踩到的两个自身缺陷（记下来免得再犯）：
  ① 生产代码用的是 `state.get("x")` / `(…).get("x")`，**不是 `[]` 下标** ⇒
     只扫 `ast.Subscript` 会**恒空**（门禁空跑）；
  ② `return {"structured_response": …}` 里的键是 **`ast.Dict` 的 key**，
     既不是下标也不是 `.get` 实参 ⇒ 需要第三种取法。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from ai_infra.base_agent import BaseAgent

BACKEND = Path(__file__).resolve().parents[1]
BASE_AGENT = BACKEND / "ai_infra" / "base_agent.py"
LISTING = BACKEND / "modules" / "listing_generator" / "agent_listing.py"
PR = BACKEND / "modules" / "product_research" / "agent_product_research.py"

_summary = BaseAgent.tool_activity_in_turn


def _ai(content="", tool_calls=None):
    return AIMessage(content=content, tool_calls=tool_calls or [])


def _tc(name):
    return {"name": name, "args": {}, "id": "call_%s" % name}


# --------------------------------------------------------------------------- #
# A 纯函数语义（摘要怎么形成）
# --------------------------------------------------------------------------- #

def test_no_activity_yields_empty_dict_not_an_empty_skeleton():
    """★ 没有工具活动 ⇒ 返回 `{}`，**不是**「三个空键的骨架」。

    恒带空键会让消费方分不清「这轮没调工具」与「摘要压根没生成」——
    后者要走回退路径，前者不该退。
    """
    assert _summary([]) == {}
    assert _summary([HumanMessage(content="你好")]) == {}
    # ★ 只有 AI 回复、**没调工具**的轮次同样返回 `{}`：判据是「有没有工具活动」，
    #   不是「有没有内容」。父层会走回退路径拿 reply ⇒ 行为与改造前完全一致
    #   （这也正是「没有活动就不带这个键」那条断言的实现依据）。
    assert _summary([HumanMessage(content="你好"), _ai("在的")]) == {}


def test_tool_calls_are_ordered_and_deduplicated():
    """`tool_calls` = **保序去重**：父层用它定 `display_type`，同一工具调 3 次不该出 3 个候选。"""
    msgs = [
        HumanMessage(content="查一下"),
        _ai(tool_calls=[_tc("get_detail"), _tc("get_detail")]),
        ToolMessage(content="{}", tool_call_id="call_get_detail"),
        _ai(tool_calls=[_tc("track_batch_asins")]),
        ToolMessage(content="{}", tool_call_id="call_track_batch_asins"),
    ]
    assert _summary(msgs)["tool_calls"] == ["get_detail", "track_batch_asins"]


def test_tool_result_is_the_last_non_empty_one():
    """最后一个**非空**的工具结果才是决定性的（前置工具常常只做查询）。"""
    msgs = [
        HumanMessage(content="查"),
        _ai(tool_calls=[_tc("a")]),
        ToolMessage(content="first", tool_call_id="call_a"),
        _ai(tool_calls=[_tc("b")]),
        ToolMessage(content="", tool_call_id="call_b"),
        _ai(tool_calls=[_tc("c")]),
        ToolMessage(content="last", tool_call_id="call_c"),
    ]
    assert _summary(msgs)["tool_result"] == "last"


def test_reply_is_the_last_ai_message_with_content():
    msgs = [
        HumanMessage(content="查"),
        _ai(tool_calls=[_tc("a")]),
        ToolMessage(content="{}", tool_call_id="call_a"),
        _ai("中间说一句"),
        _ai("最终答复"),
    ]
    assert _summary(msgs)["reply"] == "最终答复"


def test_turn_boundary_matches_iteration_counter():
    """★★ 切轮口径必须与 `_iterations_in_current_turn` **完全一致**：
    都锚在「最后一条 `HumanMessage` 之后」。

    两份口径若不一致，摘要与迭代计数在多轮会话里会指向不同的两段 ——
    而**不会报任何错**：父层只是静默拿到上一轮的工具名。
    """
    msgs = [
        HumanMessage(content="上一轮"),
        _ai(tool_calls=[_tc("old_tool")]),
        ToolMessage(content="old_result", tool_call_id="call_old_tool"),
        HumanMessage(content="本轮"),
        _ai(tool_calls=[_tc("new_tool")]),
        ToolMessage(content="new_result", tool_call_id="call_new_tool"),
    ]
    got = _summary(msgs)
    assert got["tool_calls"] == ["new_tool"], "上一轮的工具被算进来了"
    assert got["tool_result"] == "new_result"

    # 与迭代计数同口径的**反向**证据：去掉本轮的 HumanMessage ⇒ 本轮 = 上一轮那批
    assert _summary(msgs[:3])["tool_calls"] == ["old_tool"]
    assert BaseAgent._iterations_in_current_turn(msgs) == 1
    assert BaseAgent._iterations_in_current_turn(msgs[:3]) == 1


def test_summary_does_not_truncate_tool_result():
    """★ `tool_result` **不许截断**：父层把它交给 `_parse_tool_output` 解析 JSON，
    截断会破坏解析（体积不会累积 —— `structured_response` 是每轮覆盖写的终态快照）。"""
    big = "x" * 50000
    msgs = [HumanMessage(content="q"), _ai(tool_calls=[_tc("t")]),
            ToolMessage(content=big, tool_call_id="call_t")]
    assert _summary(msgs)["tool_result"] == big


# --------------------------------------------------------------------------- #
# B 接线形态（AST，不看源码字符串）
# --------------------------------------------------------------------------- #

def _fn_node(path: Path, name: str):
    tree = ast.parse(path.read_bytes().decode("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _string_keys(fn) -> list:
    """函数体里所有「取某个字符串键」的三种写法：

    · `X["常量"]`            → `ast.Subscript`
    · `X.get("常量")`        → `ast.Call` + `Attribute(attr="get")` ← ★ 本轮漏掉的那种
    · `{"常量": …}`（字典字面量） → `ast.Dict` 的 key
    """
    keys = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            keys.append(node.slice.value)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "get" and node.args
              and isinstance(node.args[0], ast.Constant)):
            keys.append(node.args[0].value)
        elif isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant):
                    keys.append(k.value)
    return keys


def _node_reads_state_key(node, key: str) -> bool:
    """单个节点是不是「读 `state.<key>`」的写法（`state.get(k)` 或 `state[k]`）。

    ★ 为什么要跟 `_string_keys` 分开：后者会把**字典字面量的键**也算进去 ——
      而 `router.stream_session({"messages": [...]})` 里的 `"messages"` 是**入参**，
      不是「读了 state 的历史」。宽判据会把「不读历史」的流式路径误判成读历史
      （本轮实测过一条**假红**）。
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
            and node.func.attr == "get" and node.args \
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == key:
        return ast.unparse(node.func.value).split(".")[0] == "state"
    if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
            and node.slice.value == key:
        return ast.unparse(node.value).split(".")[0] == "state"
    return False


def _reads_state_key(fn, key: str) -> bool:
    """函数体内**任意位置**有没有读 `state.<key>`。"""
    return any(_node_reads_state_key(n, key) for n in ast.walk(fn))


def test_respond_node_writes_the_activity_summary():
    """生产者必须真的写：`_respond_node` 里出现 `structured["activity"] = …`。

    ★ `"structured_response"` 是 `return {"structured_response": …}` 的**字典键**
      （第三种取法），顺便一起钉住 —— 它保证摘要确实挂在结构化响应下。
    """
    fn = _fn_node(BASE_AGENT, "_respond_node")
    assert fn is not None, "找不到 _respond_node"
    keys = _string_keys(fn)
    assert "activity" in keys, "「本轮工具活动」没被写进结构化摘要：%s" % keys
    assert "structured_response" in keys
    assert "messages" in keys


def test_both_consumers_read_the_summary():
    """★★ 消费者必须真的读 —— 只写不读就是批 D3 刚清算掉的那种死重量。

    ★ 判据走 AST 取**该函数内**的取键（含 `.get` 与下标）：直接 `'activity' in src`
      会被注释与别的函数骗过（本仓已踩三次）。
    """
    for path, fn_name in ((LISTING, "_route_via_tools"), (PR, "_route_via_tools")):
        fn = _fn_node(path, fn_name)
        assert fn is not None, "%s 里找不到 %s" % (path.name, fn_name)
        keys = _string_keys(fn)
        assert "structured_response" in keys, "%s 没读 structured_response" % path.name
        assert "activity" in keys, "%s 没读摘要 activity" % path.name
        assert _reads_state_key(fn, "messages"), "%s 的回退分支不见了" % path.name


def test_consumers_keep_a_safe_fallback():
    """★ 摘要缺失时必须**安全失败**（回退扫历史），不能把工具名静默留空。

    ★ 判据必须限定在 **`else` 分支**里：只在函数体内搜一遍的话，`if activity:` 的
      **真分支**（本来就在读摘要）会把判据满足掉 —— 那时「回退分支被删了」也照样绿。
      实测过：宽版（在 `ast.dump(If)` 里找 `"'messages'"`）在 RI-4 下**没红**，
      这条判据等于**不存在**。⇒ 收紧成「`orelse` 子树里真的读 `state.messages`」。
    """
    for path in (LISTING, PR):
        fn = _fn_node(path, "_route_via_tools")
        found = False
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and node.orelse:
                for sub in node.orelse:
                    if any(_node_reads_state_key(inner, "messages")
                           for inner in ast.walk(sub)):
                        found = True
        assert found, "%s 的回退分支不见了（else 里没读 state.messages）" % path.name


# --------------------------------------------------------------------------- #
# C 端到端（桩 state 直接跑图节点，不调 LLM）
# --------------------------------------------------------------------------- #

@pytest.mark.asyncio
async def test_respond_node_end_to_end_puts_activity_in_structured_response():
    """直接喂一个假 state 给 `_respond_node`（**它是 async**），
    断言终态摘要里真有工具活动。

    ★ 用 `object.__new__` 绕开 `__init__`：本门禁测的是**节点逻辑**，
      不需要 LLM / checkpointer / 工具注册表（那会把纯逻辑断言变成环境依赖）。
    """
    agent = object.__new__(BaseAgent)
    agent.agent_name = "listing_test"
    agent.enable_planning = False
    state = {
        "messages": [
            HumanMessage(content="帮我写个标题"),
            AIMessage(content="", tool_calls=[_tc("generate_title")]),
            ToolMessage(content='{"type":"listing","title":"T"}',
                        tool_call_id="call_generate_title"),
            AIMessage(content="已经生成好了"),
        ],
        "budget": {},
    }
    out = await agent._respond_node(state)
    structured = out["structured_response"]
    act = structured.get("activity")
    assert act is not None, "结构化摘要里没有 activity"
    assert act["tool_calls"] == ["generate_title"]
    assert act["tool_result"] == '{"type":"listing","title":"T"}'
    assert act["reply"] == "已经生成好了"
    assert structured["status"] == "completed"


@pytest.mark.asyncio
async def test_respond_node_omits_activity_when_no_tool_was_used():
    """★ 与 `plan` / `budget` 同口径：没有活动就**不带这个键**。"""
    agent = object.__new__(BaseAgent)
    agent.agent_name = "listing_test"
    agent.enable_planning = False
    out = await agent._respond_node({
        "messages": [HumanMessage(content="你好"), AIMessage(content="在的")],
        "budget": {},
    })
    assert "activity" not in out["structured_response"]


# --------------------------------------------------------------------------- #
# D D1 的另一半：独立 checkpoint_ns（形态判据）
# --------------------------------------------------------------------------- #

def _checkpoint_ns_of(path: Path, fn_name: str):
    """取 `_build_router` 里 `BaseAgent(...)` 调用的 `checkpoint_ns=` 实参字面量。"""
    fn = _fn_node(path, fn_name)
    assert fn is not None
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "checkpoint_ns":
                    return ast.literal_eval(kw.value)
    return None


def test_sub_agents_run_in_their_own_checkpoint_namespace():
    """★★ 两个子层必须各有**非空且互不相同**的 `checkpoint_ns`。

    为什么是「互不相同」而不是「有值就行」：`resolve_thread_id` 把 ns 拼进
    `thread_id`，而本仓所有图共用同一个 `AgentState` schema ⇒
    两个 Agent 拿到同一个 `session_id` 时**不报错、只是静默串味**
    （用户与 listing 的对话会出现在选品分析师的上下文里）。
    """
    a = _checkpoint_ns_of(LISTING, "_build_router")
    b = _checkpoint_ns_of(PR, "_build_router")
    assert a and b, "子层 checkpoint_ns 缺失：listing=%r pr=%r" % (a, b)
    assert a != b, "两个子层共用一个 ns（%r）⇒ 会静默串味" % a
    assert a != BaseAgent.CHECKPOINT_NAMESPACE, "listing 子层没和主层隔开"
    assert b != BaseAgent.CHECKPOINT_NAMESPACE, "pr 子层没和主层隔开"


def test_streaming_path_still_reads_the_event_stream_not_history():
    """★★ **刻意不动**的判定：pr 的流式路径必须继续走 `astream_events` 事件流。

    理由：它本来就不读 `state["messages"]`（注释明写「只给事件、不给最终 state」）。
    为了「与非流式统一」把它改成扫 state，等于**退化** ——
    本仓已有多条「同一件事在两条路径上表现不一致」的教训，方向不能反过来用。
    """
    fn = _fn_node(PR, "_stream_via_tools")
    assert fn is not None
    assert "stream_session" in ast.dump(fn), "流式路径不再走 stream_session"
    assert not _reads_state_key(fn, "messages"), (
        "流式路径开始读 `state` 的 messages 了 —— 它应当只消费事件流"
    )
