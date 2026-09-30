"""
店秘书**流式通道**回归测试（`POST /api/v1/orchestrator/chat/stream`）—— 第 212 轮。

背景（老板原话）
----------------
    「为什么目前看到的还是正在思考，没有具体思考过程？」

实测根因：店秘书是 `AGENT_LIST[0]`（打开应用默认选中），而它此前只走
`POST /orchestrator/chat` —— **一次性 JSON**：整张图（含工具调用）跑完才吐
响应，中途**一个事件都不发** ⇒ `thinkingSteps` 永远为空 ⇒ 界面上只有转圈。
（另外 6 家都有 `/chat/stream`，所以"过程可见"在默认入口上恰好缺席。）

本文件钉住四件事
----------------
1. **形态**：端点注册在**运行期路由表**里（不是"源码里写了"），且它走的是
   共用实现（`route_stream` / `_resolve_session`）—— 用手写 AST 扫描器判，
   并**反向注入**证明这个扫描器不是空跑。
2. **短路路径不跑图**：打桩让 `stream_session` 一被调用就炸，断言响应里
   既没有 `step` 也没有 `error` —— 证明"省掉整次 LLM 调用"这条价值还在。
3. **结构化字段真的经 `meta` 下发**：`actions` / `session_id` / `route_mode`
   少一个前端就少一种能力（切不了 Agent / 恢复不了会话），且**不报错**。
4. **正文与 `/chat` 逐字相同**（+ 工具轨迹带**人话标题**）：这是「只做加法」的
   可执行版本 —— 只断言"非空"是假绿（兜底链自己也会产出文本）。
"""

import ast
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.tenant_identity

BACKEND = Path(__file__).resolve().parents[1]
ROUTER = BACKEND / "modules" / "secretary" / "router.py"
AGENT = BACKEND / "modules" / "secretary" / "agent.py"

STREAM_PATH = "/api/v1/orchestrator/chat/stream"
PLAIN_PATH = "/api/v1/orchestrator/chat"


def _parse_sse(text: str):
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


def _meta_of(events) -> dict:
    metas = [d for e, d in events if e == "meta"]
    assert metas, f"一条 meta 都没有 ⇒ 前端拿不到动作/会话/计划：{[e for e, _ in events]}"
    return metas[-1]


def _delta_text(events) -> str:
    return "".join(d.get("text", "") for e, d in events if e == "delta")


# ============================================================================
# ① 形态：端点存在且走共用实现
# ============================================================================

async def test_stream_endpoint_is_registered():
    """**运行期**路由表里必须有这条端点，且原 `/chat` 不许被顺手删掉。

    ★ 为什么查路由表而不是源码：源码里有 `@router.post("/chat/stream")` 但
      router 没被 `main.py` 挂上，是完全可能的 —— 那时源码"看起来做了"。
    """
    from main import app

    from scripts.route_inventory import route_paths

    # ★ 第 247 轮：FastAPI 0.141 起 `app.routes` 里是惰性容器，直接遍历读不到
    #   业务路由 ⇒ 走 `scripts/route_inventory`（唯一真源，盘点为 0 时抛错）。
    paths = route_paths(app)
    assert STREAM_PATH in paths, f"流式端点没注册：{sorted(p for p in paths if 'orchestrator' in p)}"
    assert PLAIN_PATH in paths, "非流式 /chat 被删了 —— 它是脚本/降级链的稳定契约"


# ---------------------------------------------------------------------------
# 形态扫描器（★ 吃源码的**纯函数**，供下面的反向注入自检喂违规样本）
# ---------------------------------------------------------------------------

def _router_prefix(tree: ast.Module) -> str:
    """取模块级 `router = APIRouter(prefix=...)` 的前缀（取不到 ⇒ 空串）。

    ★ 端点装饰器上写的是**相对路由前缀**的路径（`/chat/stream`），HTTP 上的完整
      路径 = 本前缀 + 它。扫描器若直接拿完整路径去比装饰器字面量，会**恒判违规**。
    """
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "router" for t in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        for kw in node.value.keywords:
            if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                return kw.value.value
    return ""


def _scan_stream_endpoint(src: str) -> set:
    """返回端点形态的违规项集合（空集 = 合规）。"""
    bad = set()
    tree = ast.parse(src)
    fn = next(
        (n for n in ast.walk(tree)
         if isinstance(n, ast.AsyncFunctionDef) and n.name == "secretary_chat_stream"),
        None,
    )
    if fn is None:
        return {"no_endpoint"}

    routes = {
        d.args[0].value
        for d in fn.decorator_list
        if isinstance(d, ast.Call)
        and isinstance(d.func, ast.Attribute)
        and d.func.attr == "post"
        and d.args
        and isinstance(d.args[0], ast.Constant)
    }
    # ★ 装饰器上写的是**相对路由前缀**的路径（`/chat/stream`），而 HTTP 上的
    #   完整路径 = 模块级 `APIRouter(prefix=...)` + 它。直接拿 `STREAM_PATH`
    #   比会**恒判违规**（本测试首跑就是这样：实得 {'wrong_route'}）。
    prefix = _router_prefix(tree)
    if not prefix:
        bad.add("no_router_prefix")  # 取不到前缀 ⇒ 下面这条比对没有意义
    if STREAM_PATH not in {prefix + p for p in routes}:
        bad.add("wrong_route")

    calls = {
        n.func.id for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    attrs = {
        n.func.attr for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    if "route_stream" not in calls:
        bad.add("no_route_stream")
    if "sse_event_stream" not in calls:
        bad.add("no_sse_event_stream")
    if "StreamingResponse" not in calls:
        bad.add("no_streaming_response")

    # ★ 归属判定必须是**共用**的那一份：自己抄一遍 `get_owned_conversation`
    #   就等于同一授权判定有了两份实现（本仓：至少一份永远测不到）。
    if "_resolve_session" not in calls:
        bad.add("no_shared_resolution")
    if "get_owned_conversation" in calls or "create_conversation" in calls:
        bad.add("duplicated_session_resolution")
    return bad


def test_stream_endpoint_gate_is_not_vacuous():
    """门禁自检：5 类违规样本必须各自被抓到，而**真实** router.py 必须 0 违规。

    ★ 没有这一步，`_scan_stream_endpoint` 写错（函数改名 / AST 属性取错）也只是
      **恒返回空集** —— 而空集与"全部合规"在读数上无法区分。
    """
    clean = ROUTER.read_text(encoding="utf-8")
    got = _scan_stream_endpoint(clean)
    assert got == set(), f"真实 router.py 就不合规：{sorted(got)}（先修产品代码）"

    samples = {
        "no_endpoint": clean.replace("async def secretary_chat_stream", "async def _renamed"),
        "no_route_stream": clean.replace("async for chunk in route_stream(", "async for chunk in route("),
        "no_sse_event_stream": clean.replace("sse_event_stream(_chunks())", "route_stream(_chunks())"),
        "no_streaming_response": clean.replace("return StreamingResponse(", "return None  # "),
        "wrong_route": clean.replace('@router.post("/chat/stream"', '@router.post("/chat-stream"'),
        # ★ 锚点只取 `APIRouter(prefix=` 片段：真源里它是 `APIRouter(prefix="/api/v1/orchestrator", tags=[...])`，
        #   若把收尾括号一起写进锚点 ⇒ 0 命中 ⇒ 本组空跑（自检会报出来）。
        "no_router_prefix": clean.replace(
            'APIRouter(prefix=',
            'APIRouter(prefix_renamed=',
        ),
        "no_shared_resolution": clean.replace(
            "await _resolve_session(request, current_user)",
            "await get_owned_conversation(current_user, request.session_id)",
        ),
    }
    bad = []
    for expect, text in samples.items():
        if text == clean:
            bad.append(f"{expect}: 样本没改到任何东西（替换锚点失效 ⇒ 本组会空跑）")
            continue
        hit = _scan_stream_endpoint(text)
        if expect not in hit:
            bad.append(f"{expect}: 没被抓到（实得 {sorted(hit)}）")
    assert not bad, "反向注入自检失败：\n  " + "\n  ".join(bad)


# ============================================================================
# ② 短路路径：不跑图，但结构化字段要齐
# ============================================================================

async def test_shortcut_path_skips_the_graph_but_sends_meta(client, monkeypatch):
    """纯导航（「打开设置」）⇒ **一次图都不驱动**，但 meta 必须带全动作与会话。

    ★ 「不驱动图」用**打桩让它一被调用就炸**来证明：比断言"没有 step 事件"
      更强 —— 后者在"跑了图但没工具调用"时同样成立（那是假绿）。
      短路层的全部价值就是**省掉整次 LLM 调用**；为了"有过程"去跑一次假图，
      等于把加速器拆掉，而这件事在界面上看起来完全正常。
    """
    from modules.secretary.agent import SecretaryAgent

    async def _boom(self, *a, **kw):
        raise AssertionError("短路路径不该驱动图（那会把「省掉整次 LLM 调用」拆掉）")
        yield  # noqa: F811 —— 让它成为 async generator，调用时**不**立刻炸

    monkeypatch.setattr(SecretaryAgent, "stream_session", _boom)

    r = await client.post(STREAM_PATH, json={"message": "打开设置"})
    assert r.status_code == 200, r.text
    assert "text/event-stream" in r.headers.get("content-type", "")

    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    assert "error" not in kinds, f"图被驱动了（桩炸了）：{events}"
    assert "step" not in kinds, f"短路路径不该有工具轨迹：{kinds}"
    assert "delta" in kinds and "done" in kinds, kinds

    meta = _meta_of(events)
    assert meta["route_mode"] == "shortcut", meta
    assert [a.get("action") for a in meta["actions"]] == ["account_menu"], meta
    assert meta["actions"][0].get("target") == "settings", meta
    # ★ session_id 必须带回：前端靠它做跨会话记忆（刷新后恢复历史）。
    assert meta.get("session_id"), "meta 没带 session_id —— 前端无法持久化会话"
    # ★ `plan` 键**只在该轮真有计划时才在**：前端 `setPlan` 的三态语义
    #   （undefined ⇒ 保留旧值 / null ⇒ 清掉）依赖这个区别。恒发 null 会把
    #   老板的计划条在短路路径上**误清**。
    assert "plan" not in meta, "短路路径没有图、也就没有计划，不该发 plan 键"

    assert _delta_text(events).strip(), "短路路径也必须给正文"


# ============================================================================
# ③ 正文与 /chat 逐字相同（「只做加法」的可执行版本）
# ============================================================================

async def test_stream_body_equals_non_stream_body(client, fake_llm):
    """★ 同一句话，两条通道的正文（delta 累积 / done / `/chat` 的 reply）必须逐字相同。

    ★ 为什么不是断言"非空"：那是**假绿** —— 工具环路拿不到答复时会落回兜底链，
      而兜底自己就会产出文本 ⇒ "非空"恒真，恰好钉不住它声称要钉的东西。
      对账之后：一旦流式版换了取口（例如改用 `StreamDigest.reply`），
      两边立刻不等。
    """
    msg = "你好"  # 不含导航前缀 / 业务动词 ⇒ 必走 LLM 兜底分支（不是短路）
    r1 = await client.post(PLAIN_PATH, json={"message": msg})
    assert r1.status_code == 200, r1.text
    plain = (r1.json().get("reply") or "").strip()

    r2 = await client.post(STREAM_PATH, json={"message": msg})
    assert r2.status_code == 200, r2.text
    events = _parse_sse(r2.text)
    streamed = _delta_text(events).strip()
    done = next((d.get("text", "") for e, d in events if e == "done"), "").strip()

    assert plain, "非流式路径自己就没给出正文 —— 先修那一段（此处不该兜底）"
    assert plain == streamed == done, (
        "两条通道正文不一致（流式版换了取口 / 兜底混进正文）：\n"
        f"  /chat       = {plain[:200]!r}\n"
        f"  /chat/stream= {streamed[:200]!r}\n"
        f"  done        = {done[:200]!r}\n"
        f"  事件序列    = {[e for e, _ in events]}"
    )

    # ★ 「第一秒零输出」也是本轮修复的一半：图里要先跑 LLM 再跑工具，期间
    #   一个字节都不发，界面就是**转圈**。所以 `progress` 必须排在正文之前 ——
    #   只断言"有没有发 progress"是不够的：排在 delta 之后等于没用
    #   （那时正文都出来了，谁还看阶段提示）。
    kinds = [e for e, _ in events]
    assert kinds and kinds[0] == "progress", f"首个事件应为 progress：{kinds}"
    assert kinds.index("progress") < kinds.index("delta"), f"progress 排在正文之后 ⇒ 白做：{kinds}"

    meta = _meta_of(events)
    assert meta["route_mode"] == "llm", meta
    assert meta.get("session_id"), "meta 没带 session_id"


# ============================================================================
# ④ 工具轨迹：实时 step + **人话标题**（第 211 轮的注入要在这条新链路上也生效）
# ============================================================================

async def test_stream_emits_steps_with_human_titles(client, monkeypatch):
    """有工具调用时 `step` 必须逐条下发，标题是**人话名**，且两条共享同一 id。

    ★ 为什么打桩 `stream_session`：测试环境的 LLM 是离线桩
      （`conftest._no_real_llm`），它**不会发 `tool_calls`** ⇒ 真图跑不出工具调用。
      这里喂的是 `astream_events` 的**真实事件形状**，验的是本项目自己那段
      翻译与组装（`ToolTrace` → `sse_event_stream` → `meta`），
      以及**注入的 resolver 真的被这条链路用上**（而不是回落成通用措辞）。
    """
    from modules.secretary.agent import SecretaryAgent
    from modules.skills import tool_title

    REAL_TOOL = "analyze_blue_ocean"  # ★ 必须真的在工具目录里（否则本用例空跑）
    # 对照有效性自检：真源若恰好等于回落文案，下面那条断言就恒真而失效。
    assert tool_title(REAL_TOOL) != REAL_TOOL, f"{REAL_TOOL!r} 不在工具目录里 ⇒ 本用例会空跑"

    async def _fake_stream_session(self, state, *, session_id=None, user_id=None, version="v2"):
        from langchain_core.messages import AIMessage, HumanMessage

        yield {"event": "on_tool_start", "name": REAL_TOOL, "run_id": "r-1",
               "data": {"input": {"category": "厨房"}}}
        yield {"event": "on_tool_end", "name": REAL_TOOL, "run_id": "r-1",
               "data": {"output": {"ok": True}}}
        # 根图的 on_chain_end 排在所有子事件之后 ⇒ 它才是"图最终 state"
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "root",
               "data": {"output": {"messages": [
                   HumanMessage(content="找蓝海"),
                   AIMessage(content="蓝海结论如下"),
               ]}}}

    monkeypatch.setattr(SecretaryAgent, "stream_session", _fake_stream_session)

    r = await client.post(STREAM_PATH, json={"message": "帮我看看厨房用品的蓝海机会"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    steps = [d for e, d in events if e == "step"]

    assert len(steps) == 2, f"应有开始/结束两条 step：{[e for e, _ in events]}"
    assert steps[0]["status"] == "running" and steps[1]["status"] == "done", steps
    assert steps[0]["tool"] == REAL_TOOL, steps[0]
    assert steps[0]["title"] == tool_title(REAL_TOOL), (
        f"标题没走注入的 resolver（回落成通用措辞了）：{steps[0]['title']!r}"
    )
    assert steps[0]["title"] != "正在调用工具", "标题是通用措辞 ⇒ 注入没生效"
    # ★ 前端按 `id` 把开始/结束**合并成一行**；两条 id 不同就会出现两行、
    #   且第一行永远停在「正在」（看起来像卡死）。
    assert steps[0]["id"] == steps[1]["id"] == "r-1", steps

    done = next((d.get("text", "") for e, d in events if e == "done"), "")
    assert done.strip() == "蓝海结论如下", done


# ============================================================================
# ⑤ 归属：别人的 session_id 不许回显（与非流式同一份实现）
# ============================================================================

async def test_stream_does_not_echo_a_foreign_session_id(client, make_user):
    """传一个"别人的/不存在的" `session_id` ⇒ 既不回显它，也要带回新建的会话 id。

    ★ 为什么"不回显"是硬要求：回显等于向调用方确认"这个 ID 是真实的"，
      于是这个端点就成了**会话枚举探针**。判定与非流式完全同源
      （`_resolve_session`）；这里钉的是"换成流式之后它依然在"。
    """
    a = await make_user("stream-owner")
    foreign = "conv-probe-not-mine"

    r = await client.post(
        STREAM_PATH,
        json={"message": "你好", "session_id": foreign},
        headers=a["headers"],
    )
    assert r.status_code == 200, r.text
    meta = _meta_of(_parse_sse(r.text))
    assert meta.get("session_id") != foreign, "回显了传入的 session_id —— 等于确认它存在"
    assert meta.get("session_id"), "必须带回**新建**的会话 id，否则前端无法持久化"


async def test_stream_allowed_without_shop_header(client):
    """店秘书的流式入口也在**写守卫豁免**之列（与 `/chat` 同构）。

    否则「一家店铺都还没有」的新用户一开口就被 400 拦住 —— 而那时他恰恰
    只能靠店秘书去创建第一家店铺（自救路径被自己堵死）。
    """
    r = await client.post(STREAM_PATH, json={"message": "你好"}, headers={})
    assert r.status_code == 200, f"流式入口被写守卫拦了: {r.status_code} {r.text[:200]}"


# ============================================================================
# ⑥ 落库：切到 SSE 之后**照旧把这一轮写进历史**
# ============================================================================

async def _turns_of(session_id: str):
    """直接读库拿会话消息（按 `seq` 排），形状 `[(role, content), ...]`。

    ★ 为什么直读库、不走 `/conversations/{id}/history`：那条路自己也有归属判定
      与响应包装，用它验"有没有落库"会把两个问题搅在一起。
    """
    from sqlalchemy import text

    from core.database import get_async_session

    async with get_async_session() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT role, content FROM conversation_messages "
                    "WHERE conversation_id = :s ORDER BY seq"
                ),
                {"s": session_id},
            )
        ).all()
    return [(r[0], r[1]) for r in rows]


async def test_stream_persists_the_turn(client, make_user):
    """★ 流式链路必须**照旧落库**，且落库的答复与下发的正文**同源**。

    ★ 为什么这条不可省：前端一旦切到 SSE，`_persist_turn` 漏调的话，
      「以后翻历史少一轮」在界面上**没有任何报错** —— 而店秘书是默认入口，
      等于**所有对话都不再进历史**。
    ★ 为什么还要断言"与 delta 累积相同"：落库取的是 `event: meta` 的 `reply`
      字段（**唯一真源** —— 第 238 轮从"拼接 yield 出去的 str"改成这个，
      因为那条口径的正确性只靠一个**隐式前提**：只会 yield 一段 str），
      下发给前端的是 delta。两者若不同源（例如有人图省事在 `_wrapped` 里
      再 `await route(...)` 取一次答复），症状是"重开页面看到的历史和当时看到的
      回答不一样"，同样零报错。
    """
    u = await make_user("stream-persist")
    r = await client.post(STREAM_PATH, json={"message": "你好"}, headers=u["headers"])
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    sid = _meta_of(events)["session_id"]
    reply = _delta_text(events).strip()
    assert reply, "本用例前提：这一轮有正文"

    turns = await _turns_of(sid)
    assert len(turns) == 2, f"这一轮应写入 user + assistant 两条，实得 {turns}"
    assert turns[0] == ("user", "你好"), turns
    assert turns[1][0] == "assistant", turns
    assert turns[1][1].strip() == reply, (
        "落库的答复与流式下发的正文不同源（重开页面会看到不一样的历史）：\n"
        f"  库里 = {turns[1][1][:200]!r}\n  流里 = {reply[:200]!r}"
    )

# ============================================================================
# ⑦ 预览通道：模型 token 实时下发（第 238 轮 · 治「十几秒零输出」）
# ============================================================================

def _preview_frames(events):
    return [d for e, d in events if e == "preview"]


def _stub_stream_with_tokens(reply: str, *, tool_called: bool = False):
    r'''造一个 `stream_session` 替身：两段 token 流 + 根图最终 state。

    ★ 喂的是 `astream_events` 的**真实事件形状**（`chunk` 是带 `content` 的对象），
      验的是本项目自己那段翻译与组装（`ToolTrace.on_model_stream` → `preview`
      → `sse_event_stream`）以及**落库口径**。
    ★ 为什么不能靠真图跑出来：测试环境的 LLM 是离线桩（`conftest._no_real_llm`），
      它**不是** `BaseChatModel` ⇒ `astream_events` 不会给它挂流式 handler ⇒
      `_should_stream` 恒 False ⇒ 桩上一条 token 事件都不会有。
      「真图会不会发 token 流」由探针 `238d` 实测（闲聊 10 条 / 带工具 11 条），
      与本用例**分工不同、不可互替**：探针证"管子通"，本用例证"我们接对了"。
    '''
    from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

    async def _fake_stream_session(self, state, *, session_id=None, user_id=None, version="v2"):
        # ★ 每段 token 之前先发 `on_chat_model_start`（真图实测会发，238d）——
        #   P1 的第二条进度文案就挂在这个事件上，替身不喂它那条判据就空跑。
        yield {"event": "on_chat_model_start", "name": "ChatOpenAI", "run_id": "m1",
               "data": {"input": {}}}
        # 第一段（ReAct 中间轮）：会被第二段作废 —— 前端换段即清零
        for piece in ("我先", "查一下。"):
            yield {"event": "on_chat_model_stream", "name": "ChatOpenAI", "run_id": "m1",
                   "data": {"chunk": AIMessageChunk(content=piece)}}
        if tool_called:
            yield {"event": "on_tool_start", "name": "analyze_blue_ocean", "run_id": "t1",
                   "data": {"input": {"category": "厨房"}}}
            yield {"event": "on_tool_end", "name": "analyze_blue_ocean", "run_id": "t1",
                   "data": {"output": {"ok": True}}}
        # 第二段（末轮正文）
        yield {"event": "on_chat_model_start", "name": "ChatOpenAI", "run_id": "m2",
               "data": {"input": {}}}
        for piece in ("蓝海", "结论如下"):
            yield {"event": "on_chat_model_stream", "name": "ChatOpenAI", "run_id": "m2",
                   "data": {"chunk": AIMessageChunk(content=piece)}}
        # 根图的 on_chain_end 排在所有子事件之后 ⇒ 它才是"图最终 state"
        yield {"event": "on_chain_end", "name": "LangGraph", "run_id": "root",
               "data": {"output": {"messages": [
                   HumanMessage(content="找蓝海"),
                   AIMessage(content=reply),
               ]}}}

    return _fake_stream_session


async def test_stream_emits_token_previews_without_polluting_the_body(client, monkeypatch):
    r'''★ `on_chat_model_stream` 必须**逐块**下发成 `preview`，且**不进正文**。

    治的是什么（老板原话「14.7 秒零输出」）：**一个工具都没调**时，`step` 面板
    必然是空的 —— 工具轨迹再好也救不了这一档，屏上唯一能显示的只有正在生成的
    token。三条硬要求，缺一条就退回"转圈"或"正文被拼脏"：

      ① 预览**逐块**下发、带 `segment`（前端换段即清零）；
      ② 预览**不得**混进 `delta` / `done`（⇒ 落库也就干净了）；
      ③ 预览必须**早于**正文（排在正文之后等于没用 —— 那时正文都出来了）。
    '''
    from modules.secretary.agent import SecretaryAgent

    reply = "蓝海结论如下"
    monkeypatch.setattr(SecretaryAgent, "stream_session", _stub_stream_with_tokens(reply))

    r = await client.post(STREAM_PATH, json={"message": "帮我看看厨房用品的蓝海机会"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    previews = _preview_frames(events)

    # ① 逐块下发（不是攒成一坨），段号跟着后端那次模型调用走
    assert [d["text"] for d in previews] == ["我先", "查一下。", "蓝海", "结论如下"], (
        f"预览没有逐块下发（或整段丢了）：{[e for e, _ in events]}"
    )
    assert [d.get("segment") for d in previews] == ["m1", "m1", "m2", "m2"], previews
    assert len({d.get("segment") for d in previews}) == 2, (
        "换段信号丢了 ⇒ 前端不知道中间轮那句该清零，会与最终正文黏在一起"
    )

    # ② 预览绝不进正文 / 不进 done
    done = next((d.get("text", "") for e, d in events if e == "done"), "")
    assert done.strip() == reply, f"done 被预览拼脏了：{done!r}"
    assert _delta_text(events).strip() == reply, (
        f"正文里混进了预览：{_delta_text(events)!r}"
    )
    assert "我先" not in done and "查一下" not in done, done

    # ③ 预览早于正文
    kinds = [e for e, _ in events]
    assert kinds.index("preview") < kinds.index("delta"), kinds


async def test_stream_preview_is_not_persisted(client, make_user, monkeypatch):
    r'''★ 预览是**预览**：落库的必须只有权威正文，不能是「预览 + 正文」。

    为什么单独钉：预览与正文跑在同一条 SSE 通道上，落库口径一旦"顺手把所有流式
    文本拼起来"，库里就会多出一截，而**零报错** —— 表现只是"重开页面看到的历史
    比当时屏幕上的长"。第 238 轮正是把这个口径从"拼 str"改成"取 meta.reply"。
    '''
    from modules.secretary.agent import SecretaryAgent

    reply = "蓝海结论如下"
    monkeypatch.setattr(SecretaryAgent, "stream_session", _stub_stream_with_tokens(reply))

    u = await make_user("stream-preview-persist")
    r = await client.post(STREAM_PATH, json={"message": "看蓝海"}, headers=u["headers"])
    assert r.status_code == 200, r.text
    sid = _meta_of(_parse_sse(r.text))["session_id"]
    turns = await _turns_of(sid)

    assert len(turns) == 2, turns
    assert turns[1][0] == "assistant", turns
    assert turns[1][1].strip() == reply, (
        "落库的不是权威正文（预览混进去了 / 正文丢了）：\n"
        f"  库里 = {turns[1][1][:200]!r}\n  应为 = {reply!r}"
    )


async def test_stream_preview_and_steps_coexist(client, monkeypatch):
    r'''★ 有工具调用时：`step`（过程）与 `preview`（token）**同时**在，互不干扰。

    这是最接近真实的一档（探针 238d：带工具时 11 条 token 事件 + 工具轨迹），
    也是老板真正会看到的形态 —— 既知道"调了什么工具"，也看到"模型正在写什么"。
    '''
    from modules.secretary.agent import SecretaryAgent

    reply = "蓝海结论如下"
    monkeypatch.setattr(SecretaryAgent, "stream_session",
                        _stub_stream_with_tokens(reply, tool_called=True))

    r = await client.post(STREAM_PATH, json={"message": "帮我看看厨房用品的蓝海机会"})
    assert r.status_code == 200, r.text
    kinds = [e for e, _ in _parse_sse(r.text)]

    assert kinds.count("step") == 2, f"工具轨迹丢了：{kinds}"
    assert kinds.count("preview") == 4, f"预览丢了：{kinds}"
    assert kinds.index("preview") < kinds.index("step") < kinds.index("delta"), kinds


async def test_preview_channel_gate_is_not_vacuous(client, monkeypatch):
    r'''★ 反向注入自检：拆掉接线（不注入 `on_model_stream`）⇒ 预览必须**消失**。

    没有这条，上面三条可能是"空跑绿"—— 例如预览根本不是
    `ToolTrace.on_model_stream` 产生的（那就证明不了接线是对的）。
    这里不改源码，而是**换掉 `ToolTrace` 这个符号**并吞掉 `on_model_stream`
    参数 —— 等价于"忘了接线"。若预览照旧出现，说明产生预览的另有其人，
    整组判据就得重写。
    '''
    import modules.secretary.agent as agent_mod
    from ai_infra.sse import ToolTrace as _RealToolTrace
    from modules.secretary.agent import SecretaryAgent

    class _NoStreamTrace(_RealToolTrace):
        def __init__(self, *args, **kwargs):
            kwargs.pop("on_model_stream", None)          # ← 拆掉接线
            super().__init__(*args, **kwargs)

    reply = "蓝海结论如下"
    monkeypatch.setattr(agent_mod, "ToolTrace", _NoStreamTrace)
    monkeypatch.setattr(SecretaryAgent, "stream_session", _stub_stream_with_tokens(reply))

    r = await client.post(STREAM_PATH, json={"message": "帮我看看厨房用品的蓝海机会"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)

    assert _preview_frames(events) == [], (
        "拆掉 on_model_stream 接线后仍有预览 ⇒ 预览另有来源，本组判据失效："
        f"{[e for e, _ in events]}"
    )
    # 同时证明"拆的是预览、不是整条链"：正文照旧
    assert _delta_text(events).strip() == reply, _delta_text(events)


async def test_stream_reports_two_honest_progress_beats(client, monkeypatch):
    r'''★ 第 238 轮 P1：两段等待要**分开报**，且第二条只报一次。

    实测（238k：真 uvicorn + 真 HTTP 流式）：0.11s 出第一条 progress →
    3.20s 出首帧 token → 11.40s 结束。两段等待**性质不同** ——
    前者是"解析会话 + 组装 system prompt"（我们自己的活），后者是"模型首
    token 延迟 TTFT"（对端的活）；处置方式也完全不同（前者查自己、后者换模型）。
    一句笼统话把两段混成一句 ⇒ 用户无从判断"是卡住了还是在思考"。所以钉三件事：

      ① 两条 progress 的**文案不同**（还是同一句 = 等于没改）；
      ② 第二条必须排在**首帧 token 之前**（排在后面等于没用，那时字都出来了）；
      ③ **只报一次** —— ReAct 后续轮次由 `event: step` 的 running 态覆盖，
         重复报只会让 tip 反复闪（同一句话看两遍没有信息量）。
    '''
    from modules.secretary.agent import SecretaryAgent

    monkeypatch.setattr(SecretaryAgent, "stream_session",
                        _stub_stream_with_tokens("蓝海结论如下"))

    r = await client.post(STREAM_PATH, json={"message": "帮我看看厨房用品的蓝海机会"})
    assert r.status_code == 200, r.text
    events = _parse_sse(r.text)
    kinds = [e for e, _ in events]
    progresses = [d.get("text", "") for e, d in events if e == "progress"]

    assert progresses == ["正在准备上下文…", "正在向模型提问…"], (
        f"进度文案不是两段式（或丢了）：{progresses}"
    )
    assert kinds.count("progress") == 2, f"第二条进度被重复报了：{kinds}"
    assert kinds.index("progress") < kinds.index("preview"), kinds
    second = kinds.index("progress", kinds.index("progress") + 1)
    assert second < kinds.index("preview"), (
        f"第二条进度排在首帧 token 之后 ⇒ 那时字都出来了，等于没用：{kinds}"
    )
