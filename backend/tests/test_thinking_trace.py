"""思考过程（工具轨迹）的**实时下发**门禁（第 210 轮）

背景 —— 老板原话：

    现在给agent增加一个思考过程的展示，目前只是转圈显示几秒钟，然后有结果出结果（过程折叠掉）

根因不是「前端不会画」，而是**过程从未被留存**：
  · `progress` 事件此前只被前端当 `a-spin` 的 tip 文案，在 `setLoading(false)` 里
    被清空 —— 它是「会被覆盖的单行提示」，用完即弃，**折不起来**；
  · `product_research` 的 `_stream_via_tools` 走 `astream_events`，本来**已经拿到**
    `on_tool_start` / `on_tool_end`，但只用来解析最终结果，**过程信息整段丢掉**。

修法分两层：
  · 公共层 `ai_infra.sse.ToolTrace` 把工具事件翻译成**步骤事件**（有状态：算耗时）；
  · 各 Agent 的流式工具环路把它 `yield` 出去 ⇒ 自动成为 `event: step`，
    因为它走 `sse_event_stream` 的 dict 分支，**不计入正文**。

⇒ 本文件钉住三件事（缺任一，「过程」就会退化成看不见）：
  ① 步骤事件真的被发出（不是只建了翻译器）；
  ② 步骤**不污染正文**（对照实验：带工具与不带工具，正文逐字相同）；
  ③ 一条完整 SSE 帧里 `step` 与 `delta` 并存，且 `done` 的文本里没有步骤文案。

★ 反向注入（改坏了必须转红）：
  ① 删掉 `_stream_via_tools` 里的 `yield trace_step` ⇒
     `test_pr_stream_emits_thinking_steps_for_each_tool` 转红（步骤数为 0）；
  ② 把 `trace.feed(ev)` 挪进 `on_tool_start` 分支（只喂一半）⇒ 完成态步骤消失，同红；
  ③ 把步骤改成 `yield s["data"]["title"]`（当正文发）⇒
     ②③ 两条正文断言（`..._body_is_byte_identical...` /
     `..._survive_the_sse_framing...`）同时转红。

★ 覆盖进度（如实标注，别把空当绿）：
   7 家里 **5 家**真的在流式路径上有工具环路（`product_research` / `ad_analysis`
   / `customer_service` / `competitor_intel` / `aigc_media`），已接线并进
   `WIRED_STREAM_AGENTS` 名单。剩下两家的原因**在代码形态上成立**，不是漏做：
     · `listing_generator` 的 `stream_chat` **只走关键词表**，工具环路只存在于
       非流式 `invoke()` 里 ⇒ 没有流式工具环路可接；
     · `review_analyst` **根本没有 `stream_chat`**。
   名单加了却不接线会红（见末尾三条用例）。

★ 第 210 轮补的门禁（被一次真回归逼出来的）：
   上面 ①② 用的 `_StubRouter` 按 `astream_events` 的**理想**形态吐
   `on_chat_model_stream`，而真图里 `_llm_call_node` 调的是 `ainvoke`
   ⇒ 一条 stream 事件都没有。**只测假 router，「改成流式但答复被丢掉」
   测不到（当时全套绿）**。末尾 ⑤ 用**真 router + 离线桩 LLM**
   把两条路的答复摆在一起比。
"""

import ast
import json
from pathlib import Path

from pkg_source import class_mro_body, merge_files  # noqa: E402


# ============================================================ 可控的假 router


class _Chunk:
    """替身：`astream_events` 里 `on_chat_model_stream` 的 chunk 对象。"""

    def __init__(self, content: str) -> None:
        self.content = content


def _text_ev(text: str):
    return {
        "event": "on_chat_model_stream", "name": "", "run_id": "m1",
        "data": {"chunk": _Chunk(text)},
    }


#: 一条最小但真实的事件序列：起工具 → 模型说一句话 → 工具返回
TOOL_EVENTS = [
    {"event": "on_tool_start", "name": "blue_ocean_finder", "run_id": "run-1",
     "data": {"input": {"category": "kitchen"}}},
    _text_ev("我先查一下。"),
    {"event": "on_tool_end", "name": "blue_ocean_finder", "run_id": "run-1",
     "data": {"output": '{"type": "blue_ocean", "ok": true}'}},
]


class _StubRouter:
    """假 router：按 `astream_events` v2 的形态吐事件，完全不碰 LLM / 图。"""

    def __init__(self, events: list) -> None:
        self._events = events

    async def stream_session(self, state, *, session_id=None, user_id=None, version="v2"):
        for ev in self._events:
            yield ev

    async def run_session(self, state, *, session_id=None, user_id=None):  # pragma: no cover
        raise AssertionError("流式路径不应调 run_session（两条路径的口径会分叉）")


async def _aiter(items):
    for i in items:
        yield i


async def _run_pr_stream(monkeypatch, events=None, query="厨房用品有什么机会"):
    """跑一次 `ProductResearchAgent._stream_via_tools`，返回它产出的全部 chunk。"""
    from modules.product_research.agent_product_research import ProductResearchAgent

    agent = ProductResearchAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: _StubRouter(events or TOOL_EVENTS))

    async def _no_pending(context_id=None, user_id=None):
        return None

    monkeypatch.setattr(agent, "_detect_pending_approval", _no_pending)
    return [c async for c in agent._stream_via_tools(query)]


def _body(chunks) -> str:
    """正文 = 迭代器里的 str（dict 是结构化事件，不算正文）。"""
    return "".join(c for c in chunks if isinstance(c, str))


def _steps(chunks) -> list:
    return [c["data"] for c in chunks if isinstance(c, dict) and c.get("event") == "step"]


# =============================================== ① 步骤真的被发出 + 不碰正文


async def test_pr_stream_emits_thinking_steps_for_each_tool(monkeypatch):
    """一次工具调用必须产出**两条**步骤：开始（无耗时）与完成（有耗时）。"""
    chunks = await _run_pr_stream(monkeypatch)

    steps = _steps(chunks)
    assert [s["status"] for s in steps] == ["running", "done"], (
        f"应产出「开始 + 完成」两条步骤，实为 {steps}"
    )

    first, last = steps[0], steps[1]
    assert first["tool"] == "blue_ocean_finder"
    assert first["id"] == "run-1", "步骤 id 必须来自 run_id（并发同名工具靠它区分）"
    assert "kitchen" in first["detail"], "开始态应带入参摘要"
    assert "ms" not in first, "开始态不该有耗时"

    assert isinstance(last["ms"], int) and last["ms"] >= 0
    assert last["id"] == "run-1", "完成态必须与开始态同一个 id（前端靠它配对/去重）"


async def test_pr_stream_body_is_identical_with_and_without_tool_events(monkeypatch):
    """★ 「只做加法」的硬证据：**正文逐字不变**。

    对照实验：同一段模型文本，一次带工具事件、一次不带 —— 两次拼出的正文
    必须完全相等。步骤事件若混进正文，这条立刻红。
    """
    with_tool = await _run_pr_stream(monkeypatch)
    without_tool = await _run_pr_stream(monkeypatch, events=[_text_ev("我先查一下。")])

    assert _body(with_tool) == _body(without_tool) == "我先查一下。", (
        "步骤事件不得进入正文（正文必须与不带工具时逐字相同）"
    )


async def test_pr_stream_without_tool_events_emits_no_steps(monkeypatch):
    """没有工具事件 ⇒ 一条步骤都不该有（防「凭空造步骤」的假过程）。"""
    chunks = await _run_pr_stream(monkeypatch, events=[_text_ev("这是一段纯闲聊。")])
    assert _steps(chunks) == []
    assert _body(chunks) == "这是一段纯闲聊。"


# =============================================== ② SSE 帧：step 与 delta 并存


async def test_step_events_survive_the_sse_framing_without_touching_done(monkeypatch):
    """★ 端到端形态：`_stream_via_tools` 的输出经 `sse_event_stream` 后，
    `event: step` 独立成帧，而 `done` 的文本里**只有正文**。
    """
    from ai_infra.sse import sse_event_stream

    chunks = await _run_pr_stream(monkeypatch)
    raw = "".join([e async for e in sse_event_stream(_aiter(chunks))])

    frames = []
    for block in raw.split("\n\n"):
        if not block.strip():
            continue
        event, data = None, {}
        for line in block.splitlines():
            if line.startswith("event: "):
                event = line[7:].strip()
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        frames.append((event, data))

    kinds = [e for e, _ in frames]
    assert kinds.count("step") == 2, f"应有两帧 step，实为 {kinds}"
    assert "delta" in kinds and kinds[-1] == "done", kinds
    assert kinds.index("step") < kinds.index("delta"), (
        f"步骤应先于正文出现（否则「实时逐步」退化成事后日志）：{kinds}"
    )

    done_text = frames[-1][1]["text"]
    assert done_text == "我先查一下。", f"done 的文本被污染了：{done_text!r}"

    step_titles = [d["title"] for e, d in frames if e == "step"]
    assert all(t not in done_text for t in step_titles), "步骤标题不得出现在正文里"


# =============================================== ④ 批量接线的行为抽查（4 家里挑 1 家）


async def test_ad_analysis_stream_emits_steps_and_keeps_body(monkeypatch):
    """抽查 `AdAnalysisAgent`：步骤实时下发，且**正文与旧行为逐字相同**。

    为什么只抽查一家：4 家的 `_stream_via_tools` 是同一份模板生成的（见接线脚本），
    结构不变量由上面那组 AST 用例对**每一家**逐一钉住；这里再用一家做行为验证，
    确认模板本身在真实调用形态下成立（构造函数 / 参数个数 / 归属 ContextVar 都对得上）。
    """
    from modules.ad_analysis.agent_ad import AdAnalysisAgent

    agent = AdAnalysisAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: _StubRouter(TOOL_EVENTS))

    chunks = [c async for c in agent._stream_via_tools("看看我的广告有没有问题", {})]

    steps = _steps(chunks)
    assert [s["status"] for s in steps] == ["running", "done"], steps
    assert steps[0]["tool"] == "blue_ocean_finder"
    assert isinstance(steps[1]["ms"], int)
    assert _body(chunks) == "我先查一下。", "答复必须与旧行为一致：整段、且不含步骤文案"


async def test_ad_analysis_stream_chat_forwards_steps(monkeypatch):
    """`stream_chat` 这一层也必须把步骤转出去（不只是 `_stream_via_tools` 产出）。"""
    from modules.ad_analysis.agent_ad import AdAnalysisAgent

    agent = AdAnalysisAgent()
    monkeypatch.setattr(agent, "_get_router", lambda: _StubRouter(TOOL_EVENTS))

    out = [c async for c in agent.stream_chat("看看我的广告有没有问题", {})]
    steps = [c for c in out if isinstance(c, dict) and c.get("event") == "step"]
    assert len(steps) == 2, f"stream_chat 没有把步骤转出来：{out}"
    assert "".join(c for c in out if isinstance(c, str)) == "我先查一下。"

# =============================================== ③ 接线进度：名单必须与代码同步


#: 已经把「工具轨迹 → step 事件」接进**流式**工具环路的 Agent 类名。
#: ★ 这是**进度记录**，不是判据的全部 —— 判据是「名单里的每一家都真的接了」，
#:   所以「加了名单不接线」会红，而不是靠人记得更新。
#:
#: ★ 为什么**只有 5 家**（而全仓有 7 处 `_route_via_tools`）—— 实测结论：
#:   · `listing_generator`：它的 `stream_chat` **只走关键词表**，工具环路只在
#:     非流式的 `invoke()` 里。给它补实时轨迹 = 顺手把 LLM 工具路由塞进流式路径
#:     ⇒ **行为变更**，不在本轮「只做加法」的范围内。
#:   · `review_analyst`：**根本没有 `stream_chat`**（前端走非流式端点）。
#:   ⇒ 把这两家写进名单是错的（会要求一个不存在的东西）；它们要接，得先回答
#:     「流式路径该不该走工具路由」——那是产品决定，不是接线问题。
WIRED_STREAM_AGENTS = {
    "ProductResearchAgent",
    "AdAnalysisAgent",
    "CustomerServiceAgent",
    "CompetitorIntelligenceAgent",
    "AIGCMediaAgent",
}

#: 能把 `astream_events` 翻成 step 的两个原语（都在 `ai_infra/sse.py`）。
#:   · `StreamDigest` —— 流式工具环路用（顺带攒答复，见它的 docstring）；
#:   · `ToolTrace`    —— 只要轨迹、答复另有来源时直接用（product_research 就是：
#:                      它的 token 是**边收边发**的，不需要 StreamDigest 攒答复）。
STEP_PRIMITIVES = {"StreamDigest", "ToolTrace"}


def _uses_step_primitive(tree: ast.Module) -> bool:
    """AST 判「这个模块有没有用上能产出 step 的原语」。

    ★ 为什么不用 `"ToolTrace" in src`：注释 / docstring 里提一嘴就能骗过
      字符串判据 —— 那是假绿（本仓已有同源判据）。
    """
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id in STEP_PRIMITIVES:
            return True
        if isinstance(n, ast.Attribute) and n.attr in STEP_PRIMITIVES:
            return True
    return False


def _agent_units(backend: Path) -> list:
    """→ [(单元名, 该单元的 .py 文件清单)]。

    **单元** = 一个 `agent*.py` 文件，**或** 一个 `agent*/` 包（含嵌套）。

    ★ 为什么必须是「文件 **或** 包」而不是只认文件（第 356 轮实测教训）：
      拆包前 `CustomerServiceAgent` 住在 `customer_service/agent_cs.py`；
      拆包后住在 `customer_service/agent_cs/__init__.py` —— 文件名不再匹配
      `agent*.py`。旧扫描面因此**静默漏掉**这个类，三条用例转红：
      「找不到实现类」。这是「拆包打断路径 glob」的又一实例
      （同族：`test_tool_catalog.ASSEMBLY_HOSTS`、`test_agent_tool_wiring.WIRED_AGENTS`）。

    ★ 已被包覆盖的文件不再单列（防同一份代码被两个单元各算一次 ⇒
      `test_wired_names_are_unambiguous_and_real` 会误报「重名」）。
    """
    mods = backend / "modules"
    units: list = []
    for py in sorted(mods.rglob("agent*.py")):
        units.append((py.relative_to(backend).as_posix(), [py]))
    for d in sorted(mods.rglob("agent*")):
        if not d.is_dir():
            continue
        files = sorted(p for p in d.rglob("*.py") if p.is_file())
        if files:
            units.append((d.relative_to(backend).as_posix() + "/", files))
    covered = {p for name, fs in units if name.endswith("/") for p in fs}
    return [(n, f) for n, f in units if not (n.endswith(".py") and f[0] in covered)]


def _merged_tree(files: list) -> ast.Module:
    """把若干文件的 AST **合并**成一棵 —— 供 `ast.walk` 跨文件查找类与方法。

    ★ 合并后 lineno 不再指向真实文件，但本文件所有判据**只做结构遍历**
      （找 ClassDef / FunctionDef / Call / Yield），不读 lineno ⇒ 安全。

    ★ 合并逻辑**收口到 `tests/pkg_source.py::merge_files`**（第 356 轮）：
      本函数原先自己抄了一份逐字相同的实现 —— 同一判定两份实现，
      改口径时必然漏一处（本仓明令禁止）。
    """
    return merge_files(files)


def _class_methods(tree: ast.Module, cls_name: str):
    """→ 该类**及其全部（递归）基类**的方法节点；类不存在则 `None`。

    ★ 为什么不能只看 `cls.body`（第 356 轮实测教训）：
      mixin 拆包后 `class CustomerServiceAgent(MixinCore, MixinFaq, ..., BaseAgent)`
      的**自身类体几乎是空的**，`stream_chat` / `_stream_via_tools` 住在
      `agent_cs/core.py::MixinCore` 里 ⇒ 只看类体必然判「没调用」= **假红**。
      按基类名递归收集 = 复刻 Python 的方法查找 ⇒ 判据语义与拆包前**等价**
      （既没有放宽，也没有把窗口扩大到「整个包随便哪个方法」）。

    ★ 实现**收口到 `tests/pkg_source.py::class_mro_body`**（第 356 轮）：
      `test_hitl_policy::_assembly_facts` 需要**完全相同**的能力（沿基类收集装配点），
      而它是在同一轮被同一次拆包打红的 —— 说明这类判据会**成组出现**，
      各留一份实现必然漂移（本仓明令禁止）。
    """
    return class_mro_body(tree, cls_name)


def _scan_agent_modules() -> dict:
    """→ {类名: {"files": [...], "used": bool, "tree": <单元合并 AST>}}。

    覆盖 `modules/**/agent*.py` **以及**同名包目录（见 `_agent_units`）。
    """
    backend = Path(__file__).resolve().parents[1]
    out: dict = {}
    for rel, files in _agent_units(backend):
        merged = _merged_tree(files)
        used = _uses_step_primitive(merged)
        for n in ast.walk(merged):
            if isinstance(n, ast.ClassDef):
                e = out.setdefault(n.name, {"files": [], "used": False, "tree": None})
                e["files"].append(rel)
                e["used"] = e["used"] or used
                e["tree"] = merged
    return out


def _stream_tool_loop_forwards_steps(tree: ast.Module, cls_name: str) -> tuple:
    """→ (找到调用点?, 转发出去了吗?, 说明)。

    两种**都合法**的转发形态（实测各家各用一种，判据必须都认）：

        A 直通：`async for c in self._stream_via_tools(...): yield c`
                —— `_stream_via_tools` 只吐「步骤 + 答复」两类，不必分辨。
        B 分诊：`if isinstance(c, dict): yield c else: acc.append(c)`
                —— 还要把答复攒起来**延后一次性**吐（保持旧时序：正文零变化）。

    ⇒ 「接了环路但忘了把步骤转出去」会在这里红 —— 那是最容易漏的一步，
      漏了之后零报错：界面只是又退化成那个转圈。
    """
    methods = _class_methods(tree, cls_name)
    if methods is None:
        return False, False, "类不存在"

    found_call = False
    for fn in methods:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        calls_loop = any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_stream_via_tools"
            for n in ast.walk(fn)
        )
        if not calls_loop:
            continue
        found_call = True

        # 形态 A：直通 —— 循环变量被直接 yield
        for loop in ast.walk(fn):
            if not isinstance(loop, (ast.AsyncFor, ast.For)):
                continue
            if not isinstance(loop.target, ast.Name):
                continue
            if not any(
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_stream_via_tools"
                for n in ast.walk(loop.iter)
            ):
                continue
            for sub in loop.body:
                if (
                    isinstance(sub, ast.Expr)
                    and isinstance(sub.value, ast.Yield)
                    and isinstance(sub.value.value, ast.Name)
                    and sub.value.value.id == loop.target.id
                ):
                    return True, True, ""

        # 形态 B：分诊 —— `if isinstance(x, dict): yield x`
        for if_node in ast.walk(fn):
            if not isinstance(if_node, ast.If):
                continue
            test = if_node.test
            guarded = None
            if (
                isinstance(test, ast.Call)
                and isinstance(test.func, ast.Name)
                and test.func.id == "isinstance"
                and len(test.args) == 2
                and isinstance(test.args[0], ast.Name)
                and isinstance(test.args[1], ast.Name)
                and test.args[1].id == "dict"
            ):
                guarded = test.args[0].id
            if guarded is None:
                continue
            for sub in ast.walk(if_node):
                if isinstance(sub, ast.Expr) and isinstance(sub.value, ast.Yield):
                    y = sub.value.value
                    if isinstance(y, ast.Name) and y.id == guarded:
                        return True, True, ""
    return found_call, False, ("没有调用 self._stream_via_tools" if not found_call
                               else "调了环路但没有把 dict 步骤 yield 出去")


def test_wired_agents_forward_steps_out_of_the_stream_loop():
    """★ 名单里的每一家：流式工具环路产出的 step 必须真的被 `yield` 出去。

    「接了 `_stream_via_tools` 但 `stream_chat` 忘了转发」是本轮最容易漏的一步，
    而且漏了之后**零报错**：界面只是又退化成那个转圈。
    """
    # ★ 复用 `_scan_agent_modules()` 这**唯一一份**扫描实现：
    #   此前本用例自己又 glob 了一遍（同一判定两份实现 ⇒ 拆包后两处会各自漂移，
    #   而只有一处被修到）。改为单一真源后，扫描面的演进只需改一个地方。
    scanned = _scan_agent_modules()
    missing: list = []
    for cls in sorted(WIRED_STREAM_AGENTS):
        unit = scanned.get(cls)
        if unit is None:
            missing.append(f"{cls}（找不到实现类）")
            continue
        tree = unit["tree"]
        found, fwd, why = _stream_tool_loop_forwards_steps(tree, cls)
        if not (found and fwd):
            missing.append(f"{cls}（{why}）")
    assert not missing, (
        "以下 Agent 的思考过程断在中间（步骤产出了却没下发）：\n  "
        + "\n  ".join(missing)
    )


def test_step_primitives_live_in_the_shared_sse_module():
    """两个原语必须来自 `ai_infra/sse.py`（不许本地造同名类骗过上面的判据）。"""
    import importlib

    mod = importlib.import_module("ai_infra.sse")
    absent = sorted(p for p in STEP_PRIMITIVES if not hasattr(mod, p))
    assert not absent, f"`ai_infra.sse` 里找不到这些原语：{absent}（改名了？请同步本文件）"


def test_scan_covers_the_agent_tree():
    """防「路径写错 ⇒ 空集 ⇒ 恒绿」：扫描必须真的看到若干 Agent 类。"""
    found = _scan_agent_modules()
    assert len(found) >= 5, f"只扫到 {len(found)} 个类，扫描路径可疑：{sorted(found)}"
    assert "ProductResearchAgent" in found and "AdAnalysisAgent" in found


def test_wired_agents_really_use_a_step_primitive():
    """★ 名单里的每一家都必须真的用上 step 原语（拿掉接线 ⇒ 本条红）。"""
    found = _scan_agent_modules()

    missing = sorted(WIRED_STREAM_AGENTS - set(found))
    assert not missing, f"名单里的 Agent 找不到实现类：{missing}（类名或文件名改了？）"

    not_wired = sorted(c for c in WIRED_STREAM_AGENTS if not found[c]["used"])
    assert not not_wired, (
        f"这些 Agent 在 WIRED_STREAM_AGENTS 里，模块里却没有真的用 step 原语：{not_wired}"
        " —— 要么补接线，要么从名单里拿掉（别让它假装已接入）。"
    )


def test_wired_names_are_unambiguous_and_real():
    """名单里不能有**重名类**（扫描会串）或**不存在的类**（「全员已接入」是自欺）。"""
    found = _scan_agent_modules()
    phantom = sorted(WIRED_STREAM_AGENTS - set(found))
    assert not phantom, f"WIRED_STREAM_AGENTS 里有不存在的类：{phantom}"

    ambiguous = {c: found[c]["files"] for c in WIRED_STREAM_AGENTS if len(found[c]["files"]) > 1}
    assert not ambiguous, (
        f"名单里的类名在多个 agent 模块里重名，扫描结果会串：{ambiguous}"
        " —— 请改用「模块 + 类名」定位。"
    )


def test_wiring_gate_is_not_vacuous():
    """★ 门禁自检：判据必须能分辨「真用」与「只在注释里提一嘴」。"""
    assert _uses_step_primitive(ast.parse("from ai_infra.sse import StreamDigest\nx = StreamDigest()\n"))
    assert _uses_step_primitive(ast.parse("from ai_infra.sse import ToolTrace\nx = ToolTrace()\n"))
    assert _uses_step_primitive(ast.parse("import ai_infra.sse as s\nx = s.StreamDigest()\n"))

    # 下面两条正是字符串判据会**误判成已接入**的形态
    assert not _uses_step_primitive(ast.parse("# 本文件已接入 StreamDigest\nx = 1\n"))
    assert not _uses_step_primitive(ast.parse('"""已接入 StreamDigest。"""\nx = 1\n'))
    assert not _uses_step_primitive(ast.parse("from ai_infra.sse import progress\nx = progress('a')\n"))


def test_forwarding_scanner_is_not_vacuous():
    """★ 门禁自检：转发扫描器必须能分辨「真转发」与「忘了转发」。"""
    good = ast.parse(
        "class A:\n"
        "    async def stream_chat(self):\n"
        "        async for chunk in self._stream_via_tools(1):\n"
        "            if isinstance(chunk, dict):\n"
        "                yield chunk\n"
        "            else:\n"
        "                acc.append(chunk)\n"
    )
    assert _stream_tool_loop_forwards_steps(good, "A") == (True, True, "")

    # 形态 A（直通）必须也算「转发出去了」—— product_research 就是这个形态，
    # 判据只认分诊的话会把真代码判红（本门禁第一版正是如此）。
    passthrough = ast.parse(
        "class A:\n"
        "    async def stream_chat(self):\n"
        "        async for chunk in self._stream_via_tools(1):\n"
        "            yield chunk\n"
    )
    assert _stream_tool_loop_forwards_steps(passthrough, "A") == (True, True, "")

    # 反向对照：直通形态下**没有** yield 循环变量（只推进了容器）⇒ 必须红
    swallowed = ast.parse(
        "class A:\n"
        "    async def stream_chat(self):\n"
        "        async for chunk in self._stream_via_tools(1):\n"
        "            acc.append(chunk)\n"
        "        yield acc\n"
    )
    found, fwd, _ = _stream_tool_loop_forwards_steps(swallowed, "A")
    assert found and fwd is False, "直通形态下漏 yield 循环变量没被发现"

    forgot = ast.parse(
        "class A:\n"
        "    async def stream_chat(self):\n"
        "        async for chunk in self._stream_via_tools(1):\n"
        "            acc.append(chunk)\n"
    )
    found, fwd, why = _stream_tool_loop_forwards_steps(forgot, "A")
    assert found and not fwd, f"「忘了转发」没被发现：{why}"

    never_calls = ast.parse(
        "class A:\n"
        "    async def stream_chat(self):\n"
        "        await self._route_via_tools(1)\n"
    )
    found, fwd, _ = _stream_tool_loop_forwards_steps(never_calls, "A")
    assert not found, "「压根没走流式环路」没被发现"

    assert _stream_tool_loop_forwards_steps(ast.parse("class B:\n    pass\n"), "A")[0] is False


# ==================== ⑤ 真 router：流式答复 == 非流式答复（正文零变化）
#
# 与 ①② 的关键差别：这里**不**打桩 router，用 `_get_router()`（conftest 的
# 离线桩 LLM 负责不出网）。假 router 只能证明「翻译器写对了」，证明不了
# 「答复还在」—— 而答复丢失恰恰是实际发生的那个缺陷。
#
# 反向注入：把 `StreamDigest.reply` 改回只读 `on_chat_model_stream`
#   ⇒ 下面这条转红，而 ①② 仍然绿 —— 这正是它当时漏网的原因。

#: 用了 `StreamDigest` 的 **4 家**。第 5 家 `product_research` **不是**它的用户
#: （自带内联循环消费 `on_chat_model_stream`，`agent_product_research.py:1050`），
#: 由 `tests/test_stream_sse.py` 的 HTTP 用例覆盖 —— 分工别混。
DIGEST_AGENTS = [
    ("ad_analysis", "modules.ad_analysis.agent_ad", "AdAnalysisAgent"),
    ("customer_service", "modules.customer_service.agent_cs", "CustomerServiceAgent"),
    ("competitor_intel", "modules.competitor_intel.agent_competitor",
     "CompetitorIntelligenceAgent"),
    ("aigc_media", "modules.aigc_media.agent_aigc", "AIGCMediaAgent"),
]


async def test_real_router_stream_reply_equals_the_non_streaming_reply(fake_llm):
    """★ 真 router 下，4 家 `StreamDigest` 用户的答复必须与非流式**逐字相同**。

    这一条同时钉住两件事：
      · **非空**（空答复会被上层当成「这轮没产出」而静默落回兜底）；
      · **不变**（「只做加法、正文零变化」是这一轮对老板的承诺）。
    对照失效（非流式自己就是空）时单独报出来，免得把「两边都空」当成通过。

    ★ 一次性收集**全部**不一致再断言，不在第一家就中断 —— 否则修好一家
      会让人误以为剩下三家也没问题。
    """
    import importlib
    import inspect

    ctx, query = {"store_id": "store_test"}, "帮我看看现在的情况"
    bad = []
    for label, mod, cls in DIGEST_AGENTS:
        agent = getattr(importlib.import_module(mod), cls)()
        r_sig = inspect.signature(agent._route_via_tools)
        non_stream = await (agent._route_via_tools(query, ctx)
                            if len(r_sig.parameters) >= 2
                            else agent._route_via_tools(query))
        s_sig = inspect.signature(agent._stream_via_tools)
        it = (agent._stream_via_tools(query, ctx) if len(s_sig.parameters) >= 2
              else agent._stream_via_tools(query))
        streamed = _body([c async for c in it])

        if not (non_stream or "").strip():
            bad.append(f"{label}: 非流式路径就没给出答复 —— 对照失效，本条对它不适用")
        elif streamed.strip() != non_stream.strip():
            bad.append(f"{label}: 流式={streamed[:60]!r} / 非流式={non_stream[:60]!r}")

    assert not bad, ("改走流式之后答复变了或丢了（「只做加法」的承诺被破坏）：\n  "
                     + "\n  ".join(bad))

# ==================== ⑥ 工具人话标题：注入 resolver（第 211 轮）
#
# 老板原话：「步骤标题是通用措辞『正在调用工具』，工具名是原始英文名」。
# 人话标题的**唯一真源**是 `modules/skills/tools_catalog.py::tool_title()`
# （每条 `TOOL_CATALOG` 项都带 `title`，如 `optimize_bids` → 「出价优化建议」）。
#
# ★ 为什么不把那张表抄一份（前端抄 / 抄进 `ai_infra`）：
#     · `ai_infra` 反向依赖业务是本仓硬红线（`test_infra_layering.py`）；
#     · 抄第二份 = 同一判定两份实现 ⇒ 必然与工具目录漂移（本仓既有判据）。
#   ⇒ 只能**依赖注入**：业务侧在装配点把查询口传进去。
#
# ★ 本段三层分工（不可互相替代）：
#     形态（G1/G2）：`modules/**` 下**每个**装配点都传了，且传的是唯一真源；
#     行为（G3/G4）：注入生效；三档失败都**可见地**降级；
#     端到端（G5）：Agent 的真装配路径产出的 step 真的带人话名。
#   ★ 漏注入**零报错** —— 界面只是退回通用措辞。所以 G1 是这里唯一能防
#     「新 Agent 忘接线」的一层。

#: 用**真实**工具名。★ 不能沿用 ①~④ 的 `blue_ocean_finder` —— 那个名字不在
#: `TOOL_CATALOG` 里，`tool_title()` 会**原样返回**它 ⇒ 拿它做标题门禁会空跑
#: （「title != 通用措辞」恒真，却证明不了 resolver 被调过）。
REAL_TOOL = "analyze_blue_ocean"

#: 未注入 resolver 时的回落措辞（`ToolTrace` 里的字面量，这里只作对照）。
FALLBACK_TITLE = "正在调用工具"

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _tool_start(name: str, rid: str) -> dict:
    """最小的一条 `on_tool_start` 事件（形态与 `astream_events` v2 一致）。"""
    return {
        "event": "on_tool_start", "name": name, "run_id": rid,
        "data": {"input": {"category": "kitchen"}},
    }


def _injection_scan(tree: ast.Module) -> tuple:
    """→ (全部实例化点, 漏注入的点, 注入的不是真源的点)。

    ★ 抽成**吃源码**的纯函数（而不是直接扫磁盘）：这样下面那条
      `test_title_injection_gate_is_not_vacuous` 可以喂人工构造的违规样本，
      证明它**真的会报** —— 本仓既有判据：没被反向注入验证过的门禁 = 没有门禁。
    """
    sites, missing, wrong_src = [], [], []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        else:
            continue
        if name not in STEP_PRIMITIVES:
            continue
        sites.append((name, n.lineno))
        kw = {k.arg: k.value for k in n.keywords}
        if "title_resolver" not in kw:
            missing.append((name, n.lineno))
            continue
        # 只认「传了业务侧唯一查询口」这一种形态：字面量表 / lambda 都是
        # 第二份真源的入口（G2 就是为它设的）。
        val = kw["title_resolver"]
        if not (isinstance(val, ast.Name) and val.id == "tool_title"):
            wrong_src.append((name, n.lineno, ast.unparse(val)[:60]))
    return sites, missing, wrong_src


def _module_trees():
    """逐个产出 `modules/**/*.py` 的 (路径, AST)。"""
    for py in sorted((BACKEND_DIR / "modules").rglob("*.py")):
        yield py, ast.parse(py.read_bytes().decode("utf-8", errors="replace"))


def test_every_step_primitive_site_injects_a_title_resolver():
    """★ 形态：`modules/**` 下**每个** `ToolTrace(...)` / `StreamDigest(...)`
    都必须注入 `title_resolver`。漏一个 ⇒ 那家的界面静默退回通用措辞。"""
    sites, missing, wrong = [], [], []
    for py, tree in _module_trees():
        rel = py.relative_to(BACKEND_DIR).as_posix()
        s, m, w = _injection_scan(tree)
        sites += [(rel, n, ln) for n, ln in s]
        missing += [f"{rel}:{ln} {n}()" for n, ln in m]
        wrong += [f"{rel}:{ln} {n}(title_resolver={t})" for n, ln, t in w]

    # ★ 空集自检：改名 / 搬家会让扫描口径失效，此时「没有缺」是**假绿**。
    assert len(sites) >= 5, (
        f"只扫到 {len(sites)} 个实例化点（应为 5）—— 扫描口径可能已失效：{sites}"
    )
    assert not missing, (
        "这些装配点没注入 title_resolver —— 界面会退回通用措辞且**零报错**：\n  "
        + "\n  ".join(missing)
    )
    assert not wrong, (
        "title_resolver 必须传业务侧唯一真源 `tool_title`，不得传字面量表 / lambda"
        "（那是第二份真源，必然与工具目录漂移）：\n  " + "\n  ".join(wrong)
    )


def test_step_title_uses_the_injected_resolver():
    """注入生效：`title` 变成工具人话名，**原始工具名仍保留**（排查要用）。"""
    from ai_infra.sse import ToolTrace
    from modules.skills.tools_catalog import tool_title

    expected = tool_title(REAL_TOOL)
    # ★ 对照有效性自检：真源若恰好等于回落文案，下面那条断言就恒真而失效。
    assert expected and expected != FALLBACK_TITLE, (
        f"{REAL_TOOL!r} 在工具目录里没有独立标题（得到 {expected!r}）—— 本条会空跑"
    )

    data = ToolTrace(title_resolver=tool_title).feed(_tool_start(REAL_TOOL, "r1"))["data"]
    assert data["title"] == expected, data
    assert data["title"] != FALLBACK_TITLE, data
    assert data["tool"] == REAL_TOOL, "原始工具名必须保留（排查时要用）"


def test_title_resolver_failures_degrade_visibly():
    """★ 三档失败都回落通用措辞，且**工具名照旧下发** —— 可见的降级，不丢步骤。

    · **未注入** —— 本类在没有业务目录的场景（纯协议单测 / 第三方图）也要能用；
    · **抛异常** —— resolver 是业务侧注入的回调，它炸不该把整条 SSE 流带走
      （为一个展示用的名字丢掉「过程 + 答复」，代价与收益完全不对称）；
    · **返回空** —— 查到了但给空串 ⇒ 界面渲染出一个空白步骤，看着像丢了。
    """
    from ai_infra.sse import ToolTrace

    cases = [
        ("未注入", None),
        ("抛异常", lambda _n: 1 / 0),
        ("返回空", lambda _n: "   "),
    ]
    bad = []
    for why, resolver in cases:
        data = ToolTrace(title_resolver=resolver).feed(_tool_start(REAL_TOOL, "r1"))["data"]
        if data["title"] != FALLBACK_TITLE or data.get("tool") != REAL_TOOL:
            bad.append(f"{why}: {data}")
    assert not bad, (
        "失败档没有可见地降级（应回落通用措辞、且保留原始工具名）：\n  "
        + "\n  ".join(bad)
    )


async def test_agent_wiring_carries_the_human_title_end_to_end(monkeypatch):
    """★ 端到端：Agent 的**装配路径**真的把 resolver 传下去了。

    与 G1/G2 的分工：那两条是 AST 形态判据（**写对了**），本条是行为判据
    （**真的生效**）—— 两者不可互替：形态对但回调绑错对象、闭包捕获了空值，
    只有行为层能抓。

    覆盖两种装配形态：
      · `product_research` —— 直接用 `ToolTrace`（token 边收边发，不攒答复）；
      · `ad_analysis`      —— 用 `StreamDigest`（顺带攒答复，见其 docstring）。
    """
    from modules.ad_analysis.agent_ad import AdAnalysisAgent
    from modules.skills.tools_catalog import tool_title

    expected = tool_title(REAL_TOOL)
    events = [
        _tool_start(REAL_TOOL, "r1"),
        _text_ev("我先查一下。"),
        {"event": "on_tool_end", "name": REAL_TOOL, "run_id": "r1",
         "data": {"output": {"ok": True}}},
    ]

    pr_steps = _steps(await _run_pr_stream(monkeypatch, events=list(events)))

    ad_agent = AdAnalysisAgent()
    monkeypatch.setattr(ad_agent, "_get_router", lambda: _StubRouter(list(events)))
    ad_steps = _steps([c async for c in ad_agent._stream_via_tools("查广告", {})])

    bad = []
    for label, steps in [("product_research", pr_steps), ("ad_analysis", ad_steps)]:
        if not steps:
            # 没步骤 ⇒ 本条对它**空跑**，必须自己报出来（否则是假绿）。
            bad.append(f"{label}: 没产出步骤 —— 门禁口径失效，本条对它空跑")
            continue
        for s in steps:
            if s["title"] != expected:
                bad.append(f"{label}: title={s['title']!r}（应为 {expected!r}）")
    assert not bad, "装配路径没有把工具人话标题带出来：\n  " + "\n  ".join(bad)


def test_title_injection_gate_is_not_vacuous():
    """★ 反向注入自检：合成样本喂给扫描器，三种违规必须都被报出来。"""
    ok = ast.parse(
        "from modules.skills.tools_catalog import tool_title\n"
        "d = StreamDigest(title_resolver=tool_title)\n"
    )
    sites, missing, wrong = _injection_scan(ok)
    assert [n for n, _ in sites] == ["StreamDigest"], sites
    assert not missing and not wrong, (missing, wrong)

    assert _injection_scan(ast.parse("d = StreamDigest()\n"))[1], "「忘了注入」没被发现"
    assert _injection_scan(
        ast.parse("d = StreamDigest(title_resolver={'optimize_bids': 'x'})\n")
    )[2], "「自己抄了一张表」没被发现"
    assert _injection_scan(
        ast.parse("d = ToolTrace(title_resolver=lambda n: n.upper())\n")
    )[2], "lambda 兜底没被发现"
    assert _injection_scan(
        ast.parse("d = sse.StreamDigest()\n")
    )[1], "属性形态（sse.StreamDigest）没被认出来"

    # 干净样本不误报；无关调用不误抓
    assert _injection_scan(ast.parse("x = 1\ny = foo(title_resolver=tool_title)\n"))[0] == []
