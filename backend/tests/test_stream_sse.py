"""
SSE 流式输出回归测试

覆盖：
1. 7 个 Agent 的 /chat/stream 端点均已注册
2. SSE 响应头正确（text/event-stream）
3. 事件协议正确：delta 增量 + done 收尾
4. LLM 不可用时降级为规则引擎文本（不报错）
5. progress 阶段进度事件：结构化意图应先发进度再出结果，且不计入正文
6. preview 预览通道（第 238 轮）：模型 token 实时下发，**不进正文 / 不进 done**
"""

import json

import pytest
pytestmark = pytest.mark.tenant_identity



# 第 142 轮 A2-3 起：`ad_analysis` / `competitor_intel` 的 router 挂了 **strict**
# 店铺依赖（`get_current_shop_id`）。这两个端点都是 POST ⇒ 被守卫判为写方法
# ⇒ 缺 `X-Shop-ID` 时返回 400（可读原因），而不是 200 + 空结果。
# 前端 `api/request.ts` 与 `api/stream.ts` 都会自动带该头，故真实用户不会撞到；
# 这里补上 header 是为了让本用例继续验证它真正要验的东西：**SSE 协议本身**。
# 新契约由 `test_shop_scoped_stream_endpoints_require_shop_header` 单独钉住。
SHOP_FOR_STREAM = "store_test"

# (path, payload, kind, needs_shop)
STREAM_ENDPOINTS = [
    ("/api/v1/listing/chat/stream", {"message": "生成一款便携咖啡研磨器的标题"}, "json", False),
    ("/api/v1/ad-analysis/chat/stream", {"message": "给我一些广告优化建议"}, "json", True),
    ("/api/v1/customer-service/chat/stream", {"message": "你们的退换货政策是什么"}, "json", False),
    ("/api/v1/aigc/chat/stream", {"message": "帮我写一段品牌故事"}, "json", False),
    ("/api/v1/competitor/chat/stream?query=分析市场", None, "query", True),
    ("/api/v1/product-research/chat/stream", {"message": "帮我分析厨房用品"}, "json", False),
    # ★ 第 212 轮新增（第 7 家）：**店秘书**。它是 `AGENT_LIST[0]`
    #   （打开应用默认选中），此前走 `POST /orchestrator/chat` —— 一次性
    #   JSON、中途零事件 ⇒ 「思考过程」在默认入口上永远是空的。
    #   不带 X-Shop-ID：它是对话入口，豁免写守卫
    #   （真源 `test_shop_id_guard.ALLOWED_OPTIONAL`）。
    ("/api/v1/orchestrator/chat/stream", {"message": "你好"}, "json", False),
]


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    """把 SSE 文本解析成 [(event, data_dict), ...]"""
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event, data = None, {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                except json.JSONDecodeError:
                    data = {"raw": line[6:]}
        if event:
            events.append((event, data))
    return events


def test_all_seven_stream_endpoints_registered():
    """7 个 Agent 都应有 /chat/stream 端点（第 212 轮店秘书是第 7 家）"""
    from main import app

    from scripts.route_inventory import route_paths

    # ★ 第 247 轮：FastAPI 0.141 起 `app.routes` 里是惰性容器，直接遍历读不到
    #   业务路由 ⇒ 走 `scripts/route_inventory`（唯一真源，盘点为 0 时抛错）。
    paths = route_paths(app)
    expected = [
        "/api/v1/listing/chat/stream",
        "/api/v1/ad-analysis/chat/stream",
        "/api/v1/customer-service/chat/stream",
        "/api/v1/aigc/chat/stream",
        "/api/v1/competitor/chat/stream",
        "/api/v1/product-research/chat/stream",
        "/api/v1/orchestrator/chat/stream",
    ]
    missing = [p for p in expected if p not in paths]
    assert not missing, f"缺失流式端点: {missing}"


async def test_listing_stream_returns_sse_events(client, auth_off, fake_llm):
    r = await client.post(
        "/api/v1/listing/chat/stream",
        json={"message": "生成一款便携咖啡研磨器的标题"},
    )
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers.get("content-type", "")

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "delta" in kinds, f"缺少 delta 事件: {kinds}"
    assert "done" in kinds, f"缺少 done 事件: {kinds}"

    streamed = "".join(d.get("text", "") for e, d in events if e == "delta")
    done_text = next(d.get("text", "") for e, d in events if e == "done")
    assert streamed, "delta 内容为空"
    assert done_text == streamed, "done 的完整文本应与 delta 累积一致"


async def test_listing_stream_degrades_without_llm(client, auth_off, monkeypatch):
    """关闭 LLM 时，流式端点应降级为规则引擎文本而非报错"""
    from modules.listing_generator.agent_listing import ListingGeneratorAgent

    monkeypatch.setattr(ListingGeneratorAgent, "ENABLE_LLM", False)

    r = await client.post(
        "/api/v1/listing/chat/stream",
        json={"message": "生成一款便携咖啡研磨器的标题"},
    )
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "error" not in kinds, f"降级路径不应报错: {events}"
    assert any(e in ("delta", "done") for e in kinds), f"降级应有文本输出: {kinds}"
    total = "".join(d.get("text", "") for e, d in events)
    assert total.strip(), "降级输出为空"


@pytest.mark.parametrize("path,payload,kind,needs_shop", STREAM_ENDPOINTS)
async def test_all_stream_endpoints_respond(client, auth_off, fake_llm, path, payload, kind, needs_shop):
    """所有流式端点都应返回 SSE 且不 5xx（挂了店铺依赖的端点带头调用）"""
    headers = {"X-Shop-ID": SHOP_FOR_STREAM} if needs_shop else None
    if kind == "json":
        r = await client.post(path, json=payload, headers=headers)
    else:
        r = await client.post(path, headers=headers)
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
    assert "text/event-stream" in r.headers.get("content-type", ""), path


@pytest.mark.parametrize(
    "path,payload,kind",
    [t[:3] for t in STREAM_ENDPOINTS if t[3]],
)
async def test_shop_scoped_stream_endpoints_require_shop_header(
    client, auth_off, fake_llm, path, payload, kind
):
    """★ 新契约（第 142 轮 A2-3）：挂了 strict 店铺依赖的流式端点，缺头 ⇒ 400 且原因可读。

    为什么是 400 而不是「200 + 在 SSE 里说没数据」：
      这两个端点的 Agent 要按店铺取数，没有店铺时任何回答都是编的。
      「请先在界面左上角选择一个店铺」是**可行动**的指引；
      换成 200 + 空结果，用户读到的是「AI 变笨了」——那是归因错误。

    为什么允许在**流式**端点上做这种硬拒绝：SSE 的契约是"连上之后才流"，
      参数级前置校验失败就该在握手阶段（HTTP 状态码）说清楚，
      而不是先建立 200 的连接再往里推一条 error 事件。
    """
    if kind == "json":
        r = await client.post(path, json=payload)
    else:
        r = await client.post(path)
    assert r.status_code == 400, (
        f"{path} 缺 X-Shop-ID 应为 400（fail-closed），实为 {r.status_code}：{r.text[:200]}"
    )
    assert "店铺" in r.text, f"拒绝原因不可读（应指明缺店铺上下文）：{r.text[:200]}"


async def test_sse_event_stream_emits_progress_without_polluting_body():
    """progress 事件单独下发，且不进正文累积（长任务提示专用，不能污染结果文本）"""
    from ai_infra.sse import progress, sse_event_stream

    async def gen():
        yield progress("正在挖掘蓝海品类数据…")
        yield "正文A"
        yield "正文B"

    raw = "".join([e async for e in sse_event_stream(gen())])
    events = _parse_sse(raw)
    kinds = [e for e, _ in events]

    assert kinds == ["progress", "delta", "delta", "done"], kinds
    assert events[0][1]["text"] == "正在挖掘蓝海品类数据…"
    assert events[-1][1]["text"] == "正文A正文B", "progress 文案不应被拼进最终正文"


async def test_product_research_stream_emits_progress_before_delta(client, auth_off, fake_llm):
    """结构化意图（蓝海）应「先发阶段进度、再出结果」，避免长任务期间零输出空转"""
    r = await client.post(
        "/api/v1/product-research/chat/stream",
        json={"message": "帮我找厨房用品类的蓝海机会"},
    )
    assert r.status_code == 200, r.text

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "progress" in kinds, f"缺少 progress 事件: {kinds}"
    assert kinds.index("progress") < kinds.index("delta"), f"progress 应先于 delta: {kinds}"
    assert "蓝海" in events[kinds.index("progress")][1]["text"]


# ============================================================================
# 第 210 轮 · step 事件与工具轨迹（「思考过程」的**可留档**事件）
# ============================================================================
#
# 为什么这组用例必须存在：`progress` 事件此前只被当作 `a-spin` 的 tip 文案，
# 在 `setLoading(false)` 里被清空 —— 也就是说**过程从未被留存**。
# 「过程折叠掉」这个需求因此不可能只靠前端实现：先得有一条值得留的事件。
# 下面钉的就是那条事件的**形态与语义**（后端侧）：
#   · 它是独立事件，不污染正文；
#   · 有开始 / 完成 / 失败三态，完成态带耗时；
#   · 同一工具并行时不串（键是 run_id 而不是工具名）。


def _ev(kind, name, run_id, *, tool_input=None, output=None, error=None):
    """造一条 astream_events 形态的事件（只保留翻译器真正会读的字段）。"""
    data = {}
    if tool_input is not None:
        data["input"] = tool_input
    if output is not None:
        data["output"] = output
    if error is not None:
        data["error"] = error
    return {"event": kind, "name": name, "run_id": run_id, "data": data}


def test_step_payload_only_carries_present_fields():
    """`step()` 只下发**有值**的可选字段 —— 空串占位会让界面渲染出空行。"""
    from ai_infra.sse import step

    bare = step("tool", "正在调用工具")
    assert bare == {
        "event": "step",
        "data": {"kind": "tool", "title": "正在调用工具", "status": "running"},
    }

    full = step("tool", "工具调用完成", tool="t", result="r", status="done", ms=12, step_id="r1")
    assert full["data"] == {
        "kind": "tool", "title": "工具调用完成", "status": "done",
        "tool": "t", "result": "r", "ms": 12, "id": "r1",
    }

    # ★ 入参与返回是**两个字段**：前端按 `id` 把开始/结束合成一行（见
    #   `stores/chat.ts::appendThinkingStep`），所以两者都要能同时存在 ——
    #   挤进同一个 `detail` 必然丢掉一半。
    both = step("tool", "工具调用完成", tool="t", detail="args", result="out", status="done")
    assert both["data"]["detail"] == "args" and both["data"]["result"] == "out"


def test_tool_trace_ignores_non_tool_events():
    """模型 token 流等事件必须原样放过：正文归属由调用方决定，翻译器不越权。"""
    from ai_infra.sse import ToolTrace

    trace = ToolTrace()
    for kind in ["on_chat_model_stream", "on_chain_start", "on_llm_end", "on_retriever_end"]:
        assert trace.feed(_ev(kind, "x", "r")) is None


def test_tool_trace_start_then_end_carries_duration_and_result():
    """开始态带入参、无耗时；完成态带耗时与返回值摘要。"""
    from ai_infra.sse import ToolTrace

    trace = ToolTrace()
    s1 = trace.feed(_ev("on_tool_start", "optimize_listing_title", "run-1",
                        tool_input={"asin": "B0TEST"}))
    assert s1["event"] == "step"
    assert s1["data"]["status"] == "running"
    assert s1["data"]["tool"] == "optimize_listing_title"
    assert s1["data"]["id"] == "run-1"
    assert "B0TEST" in s1["data"]["detail"]
    assert "ms" not in s1["data"], "开始态不该给耗时（还没跑完）"

    s2 = trace.feed(_ev("on_tool_end", "optimize_listing_title", "run-1", output='{"ok": true}'))
    assert s2["data"]["status"] == "done"
    assert isinstance(s2["data"]["ms"], int) and s2["data"]["ms"] >= 0
    assert "ok" in s2["data"]["result"], "结束态的返回值摘要应写在 result（不是 detail）"


def test_tool_trace_keys_by_run_id_not_tool_name():
    """★ 两个**同名**工具并行时耗时不能互相顶掉 —— 这正是用 run_id 当键的理由。"""
    from ai_infra.sse import ToolTrace

    trace = ToolTrace()
    trace.feed(_ev("on_tool_start", "same_name", "run-A"))
    trace.feed(_ev("on_tool_start", "same_name", "run-B"))

    a = trace.feed(_ev("on_tool_end", "same_name", "run-A", output="A"))
    b = trace.feed(_ev("on_tool_end", "same_name", "run-B", output="B"))
    assert a["data"]["id"] == "run-A" and "A" in a["data"]["result"]
    assert b["data"]["id"] == "run-B" and "B" in b["data"]["result"]
    assert isinstance(a["data"]["ms"], int) and isinstance(b["data"]["ms"], int)


def test_tool_trace_error_branch_is_not_silent():
    """工具抛错必须**留下一条 error 步骤**，否则界面上的过程会凭空断掉一截。"""
    from ai_infra.sse import ToolTrace

    trace = ToolTrace()
    trace.feed(_ev("on_tool_start", "boom", "r1"))
    s = trace.feed(_ev("on_tool_error", "boom", "r1", error="KeyError: 'asin'"))
    assert s["data"]["status"] == "error"
    assert "KeyError" in s["data"]["result"]


def test_tool_trace_end_without_start_still_emits_step():
    """★ 只有 end 没有 start（事件流被截断 / 换了进程）时**仍要发步骤**，只是无耗时。

    安全失败方向：宁可少一个耗时数字，也不要整条步骤消失 —— 那等于过程被静默吞掉。
    """
    from ai_infra.sse import ToolTrace

    s = ToolTrace().feed(_ev("on_tool_end", "t", "r", output="o"))
    assert s is not None and s["data"]["status"] == "done" and "ms" not in s["data"]


def test_tool_trace_detail_is_one_line_and_bounded():
    """摘要必须压成一行且截断 —— 工具返回值可能很大，直接灌给界面会撑爆。"""
    from ai_infra.sse import ToolTrace

    trace = ToolTrace(max_detail=40)
    trace.feed(_ev("on_tool_start", "t", "r"))
    big = "行1\n行2\n" + "x" * 500
    d = trace.feed(_ev("on_tool_end", "t", "r", output=big))["data"]["result"]
    assert "\n" not in d, "摘要里不得残留换行"
    assert len(d) <= 41 and d.endswith("…")


def test_tool_trace_survives_unserialisable_payload():
    """工具返回不可 JSON 序列化的对象时不得抛错 —— 抛错 = 整条流被打断。"""

    from ai_infra.sse import ToolTrace

    class Weird:
        def __repr__(self):
            return "<weird>"

    trace = ToolTrace()
    trace.feed(_ev("on_tool_start", "t", "r", tool_input=Weird()))
    s = trace.feed(_ev("on_tool_end", "t", "r", output=Weird()))
    assert s["data"]["status"] == "done"


async def test_step_events_do_not_pollute_body():
    """★★ 核心判据：step 单独下发，且**不拼进正文**（「只做加法」在形态上的证明）。"""
    from ai_infra.sse import sse_event_stream, step

    async def gen():
        yield step("tool", "正在调用工具", tool="t", status="running", step_id="r1")
        yield "正文A"
        yield step("tool", "工具调用完成", tool="t", status="done", ms=7, step_id="r1")
        yield "正文B"

    raw = "".join([e async for e in sse_event_stream(gen())])
    events = _parse_sse(raw)
    kinds = [e for e, _ in events]
    assert kinds == ["step", "delta", "step", "delta", "done"], kinds
    assert events[-1][1]["text"] == "正文A正文B", "step 不得被拼进正文"
    steps = [d for e, d in events if e == "step"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert "ms" not in steps[0], "开始态不该带耗时"
    assert steps[1]["ms"] == 7


# ============================================================================
# 第 210 轮 · 答复取口（**这组门禁是被一次真回归逼出来的**）
# ============================================================================
#
# 事故（证据：`.workbuddy/probes/210_ok_d3.out`、`210_ab_verdict.txt`）：
#   `StreamDigest` 最初只从 `on_chat_model_stream` 累积答复。而真图里
#   `BaseAgent._llm_call_node` 调的是 `ainvoke`（`base_agent.py:1150`）
#   ⇒ 实测**一条 `on_chat_model_stream` 都没有** ⇒ `reply` 恒为空
#   ⇒ 上层「静默走兜底」：工具环路跑出来的答复被**整段丢掉**。
#   ★ 当时**全套测试是绿的** —— 因为没有一条断言「流式路径的答复非空」。
# 三条用例的分工（**别把第 3 条当成前两条的端到端版**）：
#   · 第 1 条 —— `StreamDigest` 的**取口**：没有 stream 事件也要拿到答复；
#   · 第 2 条 —— 它的**反向自证**：什么情况下才允许空答复；
#   · 第 3 条 —— 走 HTTP 的 `product_research`，而它**不用 `StreamDigest`**
#     （自带内联循环消费 `on_chat_model_stream`）⇒ 它钉的是
#     「兜底不许顶替工具环路的答复」，与 1、2 是**两件不同的事**。
#     用了 `StreamDigest` 那 4 家的端到端对账在 `test_thinking_trace.py` ⑤
#     （真 router；反向注入会同时转红那两条）。


def test_stream_digest_takes_the_reply_from_the_graph_final_state():
    """★ 没有任何 `on_chat_model_stream` 时也必须拿到答复（本仓 `ainvoke` 的常态）。

    取法与非流式路径同源：图最终 state 里**最后一条**有内容的 `AIMessage`。
    只认 stream 事件的话，这里必然拿到空串。
    """
    from langchain_core.messages import AIMessage, HumanMessage

    from ai_infra.sse import StreamDigest

    digest = StreamDigest()
    digest.feed(_ev("on_chain_start", "LangGraph", "root"))
    # 子节点（llm_call）的中间态先到 —— 它**不是**答复
    digest.feed({"event": "on_chain_end", "name": "llm_call", "run_id": "n1",
                 "data": {"output": {"messages": [
                     HumanMessage(content="问"),
                     AIMessage(content="我先查一下。")]}}})
    # 根图的最终 state 后到 —— 它才是答复
    digest.feed({"event": "on_chain_end", "name": "LangGraph", "run_id": "root",
                 "data": {"output": {"messages": [
                     HumanMessage(content="问"),
                     AIMessage(content="我先查一下。"),
                     AIMessage(content="结论：市场份额如下")]}}})

    assert digest.reply == "结论：市场份额如下", digest.reply


def test_stream_digest_reply_is_empty_only_when_the_graph_said_nothing():
    """★ 反向自证：只有「图里真的没有 AIMessage」才允许空答复，否则上一条是假绿。"""
    from types import SimpleNamespace

    from langchain_core.messages import HumanMessage

    from ai_infra.sse import StreamDigest

    digest = StreamDigest()
    digest.feed({"event": "on_chain_end", "name": "LangGraph", "run_id": "root",
                 "data": {"output": {"messages": [HumanMessage(content="问")]}}})
    assert digest.reply == ""

    # 没有根图输出时退回**流式累积**（另一种合法来源，不能一起删掉）
    digest2 = StreamDigest()
    digest2.feed({"event": "on_chat_model_stream", "name": "", "run_id": "m1",
                  "data": {"chunk": SimpleNamespace(content="流式来的答复")}})
    assert digest2.reply == "流式来的答复"


async def test_stream_body_equals_the_tool_loop_reply(client, auth_off, fake_llm):
    """★ 端到端对账：SSE 正文必须**逐字等于工具环路自己的答复**。

    ★ 为什么不是「断言非空」：那样写是**假绿**（反向注入实测）。工具环路拿不到
      答复时会落回兜底链，而兜底**自己就会产出文本** ⇒ 「非空」恒真，
      恰好钉不住它声称要钉的东西（答复被丢掉）。
      改成对账之后：一旦答复丢了、兜底混进正文，两边立刻不等。

    ★ 覆盖范围要说准：本用例走 `product_research`，它**没有**用 `StreamDigest`
      （自带内联消费 `on_chat_model_stream`，见 `agent_product_research.py:1050`）。
      所以**反向注入 `StreamDigest.reply` 不会让本用例转红** —— 那不是它管的事。
      `StreamDigest` 的端到端对账在 `test_thinking_trace.py` ⑤。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    # 绕开关键词表，走工具环路；这条路径不碰数据库
    expected = "".join([c async for c in ProductResearchAgent()._stream_via_tools(
        "你好呀，随便聊聊") if isinstance(c, str)])
    assert expected.strip(), "工具环路本身就没给出答复 —— 先修那一段（此处不该兜底）"

    r = await client.post("/api/v1/product-research/chat/stream",
                          json={"message": "你好呀，随便聊聊"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    got = "".join(d.get("text", "") for e, d in events if e == "delta")
    assert got.strip() == expected.strip(), (
        f"SSE 正文与工具环路的答复不一致（答复丢了、兜底混进来了）：\n"
        f"  帧内   = {got[:200]!r}\n  工具环路 = {expected[:200]!r}\n"
        f"  事件序列 = {[e for e, _ in events]}"
    )

# ============================================================================
# ⑥ 预览通道：模型 token 实时下发（第 238 轮 · 治「十几秒零输出」）
# ============================================================================
#
# 老板原话：「14.7 秒零输出」。
# 实测根因（探针 238d，真 secretary 图）：闲聊场景 **10 条**
# `on_chat_model_stream`、带工具 **11 条** —— 管子是真的，只是没人取。
# 取出来的东西**不能**当正文发（正文必须走 `_digest_graph_state` 唯一取口，
# 它要带 `TRUNCATED_NOTICE` 前缀、要与 `/chat` 逐字相同），所以走 `preview`。
#
# 本组钉三件事，缺一条就退回"转圈"或"正文被拼脏"：
#   ① `preview` 发了，且**不进正文 / 不进 done**；
#   ② `ToolTrace` 的 token 转发口**只在注入时**生效（默认档只做工具轨迹）；
#   ③ 分段列表形态（`content` 是 list）也要能解出文本 —— 本仓踩过的老坑。

async def test_preview_is_not_counted_as_body():
    r'''★★ `preview` 是**预览**通道：发了，但**不进正文**。

    为什么必须有这条：`preview` 与 `delta` 都是"流式文本"，肉眼看着一模一样 ——
    一旦 `sse_event_stream` 把它当普通文本累进 `accumulated`，`done` 与落库
    就会变成「预览 + 正文」拼两遍，**而且零报错**（表现只是"那段话悄悄变长了"）。
    这正是加这条通道时唯一的风险点，所以判据必须钉在**事件序列**上：
    预览帧在、正文帧只有一段、done 里没有预览。
    '''
    from ai_infra.sse import preview, sse_event_stream

    async def gen():
        yield preview("我先查一下。", segment="m1")
        yield preview("蓝海结论如下", segment="m2")
        yield "蓝海结论如下"

    frames = [f async for f in sse_event_stream(gen())]
    kinds = [f.split("\n", 1)[0] for f in frames]
    assert kinds == ["event: preview", "event: preview", "event: delta", "event: done"], kinds

    def _text(frame):
        return json.loads(frame.split("data: ", 1)[1])["text"]

    body = "".join(_text(f) for f in frames if f.startswith("event: delta"))
    done = _text(frames[-1])
    assert body == "蓝海结论如下", f"正文里混进了预览：{body!r}"
    assert done == "蓝海结论如下", f"done 被预览拼脏了：{done!r}"
    assert "我先查一下" not in done, done


def test_preview_segment_is_only_sent_when_present():
    r'''`segment` 只在非空时下发 —— 缺字段时前端按"还是同一段"处理。

    ★ 为什么刻意**不**发空串占位：前端拿到空串会当成"换段"而**清屏**
      （它无从区分"后端没给"与"这一段的 id 恰好是空"）⇒ 预览被凭空抹掉，
      而且零报错。宁可两段黏在一起（多显示一句中间轮的话），也不要丢内容。
    '''
    from ai_infra.sse import preview

    assert preview("x") == {"event": "preview", "data": {"text": "x"}}
    assert preview("x", segment="m1") == {
        "event": "preview", "data": {"text": "x", "segment": "m1"},
    }


def test_tool_trace_forwards_model_tokens_only_when_wired():
    r'''★ 第 238 轮的第二条出口：`on_model_stream` **只在注入时**转发 token。

    ★ 为什么把 token 解包放在 `ToolTrace` 而不是各 Agent 自己 if/elif：
      解包（chunk → 文本）与 `on_tool_*` 一样是**协议细节**，抄一份多一份漂移
      （本仓上一个同形坑：`content` 是分段列表时被当成空答复，上层据此走兜底）。
    ★ 为什么默认档必须**不转发**：`feed()` 的返回口是"要不要发 step"，
      与 token 无关；默认转发 = 替所有调用方擅自多发一种事件，
      而"发成什么事件名"是**语义决定**（`delta` 还是 `preview`），本层无权代劳。
    '''
    from ai_infra.sse import ToolTrace

    class _Chunk:
        def __init__(self, content):
            self.content = content

    ev = {"event": "on_chat_model_stream", "name": "ChatOpenAI", "run_id": "m1",
          "data": {"chunk": _Chunk("你好")}}

    assert ToolTrace().feed(ev) is None, "默认档不得产出任何东西"

    got = []
    assert ToolTrace(on_model_stream=lambda t, s: got.append((t, s))).feed(ev) is None
    assert got == [("你好", "m1")], got

    # 分段列表形态（部分模型返回 `[{"type": "text", ...}]`）也要能解出文本
    got2 = []
    ev2 = {"event": "on_chat_model_stream", "name": "ChatOpenAI", "run_id": "m2",
           "data": {"chunk": _Chunk([{"type": "text", "text": "分"},
                                     {"type": "text", "text": "段"}])}}
    ToolTrace(on_model_stream=lambda t, s: got2.append((t, s))).feed(ev2)
    assert got2 == [("分段", "m2")], got2

    # 空块不转发：省得前端收一串空帧（表现是"打字机一顿一顿"）
    got3 = []
    ev3 = {"event": "on_chat_model_stream", "name": "ChatOpenAI", "run_id": "m3",
           "data": {"chunk": _Chunk("")}}
    ToolTrace(on_model_stream=lambda t, s: got3.append(t)).feed(ev3)
    assert got3 == [], got3


