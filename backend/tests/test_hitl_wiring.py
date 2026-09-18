"""
HITL 真接入：`save_candidate` 的人工审批闸门（2026-09-17，第 131 轮 item2-A2）

背景 —— 为什么此前是「零接入」：
  · `add_human_in_the_loop` 曾是 `async def`，而 `BaseAgent._wrap_hitl_tools`
    是**同步**方法 ⇒ 同步调用拿到的是 **coroutine 对象**，被原样塞进 `self.tools`，
    `bind_tools` 随后拿到非 `BaseTool`。全仓 `hitl_tools=` 调用点数 = **0**，
    所以这个坏形态从未暴露（详见 `hitl_decorator.py` 的 docstring）。
  · 即便修好工厂，还有一个前提：**`interrupt()` 要求图绑了 checkpointer
    且运行时 config 带 `thread_id`**，缺一它就在图内部直接抛 —— 不是
    「降级为不审批」。而本仓 `graph_for_session()` 在缺会话 / 缺身份时，
    返回的正是**不带 checkpointer 的图 + 空 config**。

挂载目标为什么只有一个：
  全仓 8 个工具注册表 / 41 个工具（AST 全盘扫描，见
  `.workbuddy/probes/out-r131-a2-toolmatrix.txt`）：

    · 只有 `product_research_tools` 与 `listing_tools` 被**生产代码装配**；
      其余 6 张注册表（ad_analysis / aigc_media / competitor_intel /
      customer_service / review_analyst）的生产装配点数都是 **0**（死代码）。
    · `listing_tools` 的 8 个工具全是「生成 / 优化 / 评分」——**零副作用**。
    · `product_research_tools` 里真正写库的只有 `save_candidate`；
      `create_ticket` 只构造对象返回（`ticket_id` 现编、零持久化），
      `track_batch_asins` 只读内存 mock。

  ⇒ 「有外部副作用 + 真被装配」的 agent 工具，**全仓恰好 1 个**。

★ 反向注入（改坏了必须转红，否则这些用例是在空跑）：
  ① 把 `_build_router()` 里的 `hitl_tools=["save_candidate"]` 删掉 ⇒
     `test_router_wraps_save_candidate_only` 转红（`hitl_tool_names` 为空）。
  ② 把 `call_tool_with_hitl` 里的 `thread_id` 守卫删掉 ⇒
     `test_hitl_refuses_without_thread_id` 转红（不再是明确拒绝，
     而是 `interrupt()` 的底层错穿透）。
  ③ 把 `reject` 分支改成「也执行工具」⇒
     `test_reject_does_not_execute_the_tool` 转红（内层调用次数 0 → 1）。
  ④ 把 `_build_router()` 的 `checkpointer=get_checkpointer()` 删掉 ⇒
     `test_hitl_construction_carries_checkpointer` 转红（编译期 AST 门禁）。
  ⑤ 把 `tools.py::_save_candidate_tool` 的 `shop_id=` 实参删掉 ⇒
     `test_save_candidate_tool_passes_shop_id` 转红（回到 100% 写不进库）。
"""

import ast
import pathlib

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]


# ====== A. 挂载形态（零 IO）======


def test_router_wraps_save_candidate_only():
    """
    `product_research` 的 router 子层里：**只有** `save_candidate` 被审批包装。

    ★ 为什么「只有」也要断言：包装是**按工具名**命中的（`tool.name in
      hitl_tool_names`）。一旦名单写错（比如写成了 `save_candidates`），
      包装会**静默落空**——`hitl_tool_names` 看着非空、日志也不报错，
      但没有任何工具受保护。反向断言「其余工具没被误包」则挡住写反成
      「全都包」的另一头（那会让只读工具也要审批，功能直接不可用）。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    router = ProductResearchAgent()._build_router()
    assert router is not None, "router 子层没建起来（ENABLE_LLM 被关了？）"

    assert router.hitl_tool_names == {"save_candidate"}

    by_name = {t.name: t for t in router.tools}
    assert "save_candidate" in by_name, "工具名漂移 ⇒ 名单永远命中不到"

    tgt = by_name["save_candidate"]
    assert tgt.description.startswith("[需人工审批]"), "没有审批前缀 ⇒ 未被包装"

    others = {n: t for n, t in by_name.items() if n != "save_candidate"}
    for n, t in others.items():
        assert not t.description.startswith("[需人工审批]"), (
            f"{n} 也被包了审批 —— 只读工具不该要审批（会让功能不可用）"
        )


def test_wrapped_tool_keeps_name_and_schema():
    """
    包装**不得改变**工具名与入参 schema。

    ★ 为什么这两条是硬要求：
      · 名字变了 ⇒ LangGraph 的 `ToolMessage` 对不上 `tool_calls`，
        `_sanitize_tool_call_pairing()` 会把整轮工具调用当孤儿消息剔掉；
      · schema 里多出 `config` 字段 ⇒ LLM 会试图**自己编一个** config 传进来
        （`create_tool` 本应把它识别成隐藏参数，不暴露给模型）。
    """
    from modules.product_research.agent_product_research import ProductResearchAgent

    router = ProductResearchAgent()._build_router()
    assert router is not None

    unwrapped = {
        t.name for t in router.tools if not t.description.startswith("[需人工审批]")
    }
    wrapped = [t for t in router.tools if t.description.startswith("[需人工审批]")]
    assert len(wrapped) == 1

    tgt = wrapped[0]
    assert tgt.name == "save_candidate", "包装后工具名被改了"
    props = set((tgt.args_schema.model_json_schema().get("properties") or {}).keys())
    assert props == {"asin", "title", "source_keyword"}, (
        f"入参 schema 漂移：{sorted(props)}（`config` 绝不能出现在这里）"
    )
    assert "save_candidate" not in unwrapped


# ====== B. fail-closed：没有会话上下文 ⇒ 明确拒绝 ======


@pytest.mark.parametrize(
    "cfg",
    [
        None,  # 完全不传 config
        {},  # 空 config
        {"configurable": {}},  # 有 configurable 但没 thread_id
        {"configurable": {"thread_id": None}},  # 显式 None
        {"configurable": {"thread_id": ""}},  # 空串（= 无）
    ],
    ids=["none", "empty", "no-thread-id", "null-thread-id", "blank-thread-id"],
)
async def test_hitl_refuses_without_thread_id(cfg):
    """
    没有 `thread_id` ⇒ **拒绝执行**，且抛的是本仓自己的 `HITLPrerequisiteError`。

    ★ 为什么要专门建这个异常，而不是让 `interrupt()` 自己抛：
      `interrupt()` 的裸错是「图上下文缺失」，看不出"是审批没地方落盘"。
      更糟的是「空串 `thread_id`」这种**半有效**输入：它 falsy 但不是 None，
      若用 `is None` 判断就会漏过去，然后在图里炸在一个**离现场很远**的地方。

    ★ 为什么这是 fail-closed 而不是 bug：原则同 `_write_candidates` ——
      「没有身份 / 没有会话 ⇒ 这个动作就不该发生」。审批记录无处落盘时
      **照做**才是真正的缺陷（等于审批闸门形同虚设）。
    """
    from ai_infra.tools.hitl_decorator import HITLPrerequisiteError, add_human_in_the_loop
    from langchain_core.tools import StructuredTool

    async def _inner(x: int = 1) -> str:
        return "inner-ran"

    tool = StructuredTool.from_function(coroutine=_inner, name="save_candidate", description="测试")
    wrapped = add_human_in_the_loop(tool)

    with pytest.raises(HITLPrerequisiteError) as ei:
        await wrapped.ainvoke({"x": 1}, config=cfg)
    assert "thread_id" in str(ei.value), "拒绝理由必须点明缺失的是 thread_id"


async def test_hitl_guard_does_not_fire_when_thread_id_present(monkeypatch):
    """
    有 `thread_id` ⇒ 守门**放行**，进到 `interrupt()`。

    ★ 反向面：如果守卫写成永远抛（或条件写反），上面那条 fail-closed 用例
      仍然会绿 —— 所以必须补这一条「正例」，否则等于用一条断言同时
      证明了「该拒的拒了」和「该放的也拒了」。
    """
    import ai_infra.tools.hitl_decorator as hd
    from langchain_core.tools import StructuredTool

    async def _inner(x: int = 1) -> str:
        return "inner-ran"

    tool = StructuredTool.from_function(coroutine=_inner, name="save_candidate", description="测试")
    wrapped = hd.add_human_in_the_loop(tool)

    seen = {}

    def _fake_interrupt(payload):
        seen["called"] = True
        return {"type": "reject", "args": {"reason": "probe"}}

    monkeypatch.setattr(hd, "interrupt", _fake_interrupt)
    await wrapped.ainvoke({"x": 1}, config={"configurable": {"thread_id": "t-1"}})
    assert seen.get("called"), "有 thread_id 却没走到 interrupt()"


# ====== C. ★ 未审批则不执行（直接数内层副作用的调用次数）======


async def test_reject_does_not_execute_the_tool(monkeypatch):
    """
    ★★★ 「未审批则不执行」的**直接证据**：reject 时内层工具**零调用**。

    ★ 为什么数「内层调用次数」而不是断言返回值：
      返回值是可以伪装的（`reject` 分支返回一句「已取消」同样能让断言通过，
      哪怕它已经偷偷把数据写进了库）。只有**副作用本身的调用计数**能证明
      "没执行"。这也是 HITL 唯一真正重要的性质。
    """
    import ai_infra.tools.hitl_decorator as hd
    from langchain_core.tools import StructuredTool

    calls: list[int] = []

    async def _side_effect(x: int = 1) -> str:
        calls.append(x)
        return "SIDE-EFFECT-DONE"

    tool = StructuredTool.from_function(
        coroutine=_side_effect, name="save_candidate", description="有副作用的假工具"
    )
    wrapped = hd.add_human_in_the_loop(tool)

    def _fake_interrupt(payload):
        return {"type": "reject", "args": {"reason": "老板说不要"}}

    monkeypatch.setattr(hd, "interrupt", _fake_interrupt)
    result = await wrapped.ainvoke({"x": 7}, config={"configurable": {"thread_id": "t-1"}})

    assert calls == [], f"被拒绝了却仍然执行了副作用 {calls} —— 审批闸门形同虚设"
    assert "取消" in result or "拒绝" in result


async def test_response_does_not_execute_the_tool(monkeypatch):
    """`response`（不执行、直接回复）同样不得触发副作用。"""
    import ai_infra.tools.hitl_decorator as hd
    from langchain_core.tools import StructuredTool

    calls: list[int] = []

    async def _side_effect(x: int = 1) -> str:
        calls.append(x)
        return "SIDE-EFFECT-DONE"

    tool = StructuredTool.from_function(
        coroutine=_side_effect, name="save_candidate", description="有副作用的假工具"
    )
    wrapped = hd.add_human_in_the_loop(tool)
    monkeypatch.setattr(hd, "interrupt", lambda payload: {"type": "response", "args": "先别存"})

    out = await wrapped.ainvoke({"x": 7}, config={"configurable": {"thread_id": "t-1"}})
    assert calls == []
    assert out == "先别存"


async def test_accept_executes_exactly_once(monkeypatch):
    """
    批准后**恰好执行一次**。

    ★ 为什么要「恰好」：`accept` 分支里若顺手写成 `await tool.ainvoke(...)`
      **两次**（例如先探测再执行），副作用会翻倍 —— 对写库是重复落库、
      对付款是重复扣款。这条断言把「一次」钉死。
    """
    import ai_infra.tools.hitl_decorator as hd
    from langchain_core.tools import StructuredTool

    calls: list[int] = []

    async def _side_effect(x: int = 1) -> str:
        calls.append(x)
        return "SIDE-EFFECT-DONE"

    tool = StructuredTool.from_function(
        coroutine=_side_effect, name="save_candidate", description="有副作用的假工具"
    )
    wrapped = hd.add_human_in_the_loop(tool)
    monkeypatch.setattr(hd, "interrupt", lambda payload: {"type": "accept", "args": {}})

    out = await wrapped.ainvoke({"x": 7}, config={"configurable": {"thread_id": "t-1"}})
    assert calls == [7], f"批准后副作用调用次数应为 1，实际 {len(calls)}"
    assert "SIDE-EFFECT-DONE" in out


# ====== D. 编译期门禁：hitl_tools 必须与 checkpointer 同现 ======


def test_hitl_construction_carries_checkpointer():
    """
    编译期 AST 门禁：凡是传了 `hitl_tools=` 的 `BaseAgent(...)` 构造点，
    **同一个调用里必须同时给 `checkpointer=`**，且不能是字面量 `None`。

    ★ 为什么这个门禁必须存在：`interrupt()` 在没有 checkpointer 的图上
      **直接抛**。这意味着「给工具挂了审批」与「图绑了 checkpointer」
      是**同一个前提** —— 但两者写在同一个构造调用的不同行上，
      后来的人很容易删掉其中一行而察觉不到（不报错、直到线上某次
      审批型操作才炸）。这条门禁把这层耦合固化下来。

    ★ 为什么先断言 `hits` 非空：`all(...)` 对空列表恒真 —— 如果哪天
      构造点被挪走或改名，这个门禁会**真空通过**（看着绿、其实什么都没查）。
    """
    hits = []
    for p in sorted(BACKEND_DIR.rglob("*.py")):
        parts = set(p.parts)
        if "tests" in parts or "__pycache__" in parts or ".workbuddy" in parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"), str(p))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            kw = {k.arg: k for k in node.keywords if k.arg}
            if "hitl_tools" in kw:
                hits.append((p, node, kw))

    assert hits, (
        "全仓找不到任何 `hitl_tools=` 构造点 —— 本门禁失去目标、会真空通过。"
        "若确实移除了 HITL 接线，请一并删除本门禁并说明原因。"
    )

    for p, node, kw in hits:
        rel = p.relative_to(BACKEND_DIR)
        assert "checkpointer" in kw, (
            f"{rel}:{node.lineno} 传了 hitl_tools 却没给 checkpointer —— "
            "interrupt() 会在无 checkpointer 的图上直接抛，审批闸门不可用"
        )
        val = kw["checkpointer"].value
        assert not (isinstance(val, ast.Constant) and val.value is None), (
            f"{rel}:{node.lineno} checkpointer 被显式写成 None —— 同上，审批闸门不可用"
        )


# ====== E. 连带修复回归：工具路径必须把 shop_id 传进写库 ======


async def test_save_candidate_tool_passes_shop_id(monkeypatch):
    """
    工具路径必须读取 `_current_shop_id` 并透传给 `_save_candidate`。

    ★ 修的是什么：`tools.py::_save_candidate_tool` 此前**只读了
      `_current_context_id`**，漏读 `_current_shop_id` ⇒ `_write_candidates`
      拿到 `shop_id=None` 会**硬拒绝写入**，返回的文案还是「请先在界面左上角
      选一个店铺」—— 用户明明选过店铺，这是一句**归因错误的假拒绝**
      （把人支去查一个不存在的问题）。实测：`shop_id` 已绑定时工具路径
      仍 100% 拒写、`create_candidate` 零调用。

    ★ 为什么这条测试用「零真实写库」的方式写：把 `create_candidate` /
      `candidate_exists` 换成记录器，只断言**归属被传下去了**。
      真去连库会让这条用例依赖环境（PG 起没起、店铺存不存在），
      而它要钉的是一个**纯参数传递**问题。
    """
    import json as _json

    import modules.candidates.service as cserv
    import modules.product_research.tools as pr_tools
    from modules.product_research.agent_product_research import (
        _current_context_id,
        _current_shop_id,
    )

    seen = {"create": [], "exists": []}

    async def _fake_create(payload, shop_id=None):
        seen["create"].append({"asin": payload.get("asin"), "shop_id": shop_id})
        return {"id": "probe", "asin": payload.get("asin"), "shop_id": shop_id}

    async def _fake_exists(asin, shop_id=None):
        seen["exists"].append({"asin": asin, "shop_id": shop_id})
        return False

    monkeypatch.setattr(cserv, "create_candidate", _fake_create)
    monkeypatch.setattr(cserv, "candidate_exists", _fake_exists)

    singleton = pr_tools._service.agent
    original_last_products = singleton._last_products
    singleton._last_products = lambda ctx=None: [
        {
            "asin": "B0TEST1234",
            "title": "回归测试商品",
            "price": 9.99,
            "monthly_sales": 500,
            "reviews": 12,
            "blue_ocean_score": 88,
            "roi": 35,
        }
    ]
    # ContextVar 是模块级全局：用完必须还原，否则污染同进程的其它用例
    tok_ctx = _current_context_id.set("probe-ctx")
    tok_shop = _current_shop_id.set("probe-shop-A")
    try:
        raw = await pr_tools._save_candidate_tool(asin="B0TEST1234", title="回归测试商品")
        data = _json.loads(raw)
        assert data.get("type") == "candidate_saved", (
            f"工具路径没写进库：{data.get('error') or data} —— shop_id 又没传进去？"
        )
        assert seen["create"], "create_candidate 零调用 ⇒ 副作用压根没发生"
        assert seen["create"][0]["shop_id"] == "probe-shop-A", (
            "写库归属不是已校验的 shop_id —— 漏传会让 _write_candidates 硬拒绝 "
            "（症状：提示『请先选一个店铺』，而用户明明选过）"
        )
    finally:
        singleton._last_products = original_last_products
        _current_context_id.reset(tok_ctx)
        _current_shop_id.reset(tok_shop)


async def test_save_candidate_tool_still_refuses_without_shop(monkeypatch):
    """
    反向面：没有店铺归属时**仍要拒绝**（不能为了修上面那条就把守卫一起拆了）。

    ★ 这条守的是「修 bug 修过头」：把 `shop_id` 补上很容易，但也很容易
      顺手把 `_write_candidates` 的 None 守卫改成「用个默认店铺兜底」。
      那样会让候选落进**不属于任何人的店铺**，比拒写危险得多。
    """
    import json as _json

    import modules.candidates.service as cserv
    import modules.product_research.tools as pr_tools
    from modules.product_research.agent_product_research import (
        _current_context_id,
        _current_shop_id,
    )

    async def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("无归属时不该走到写库")

    monkeypatch.setattr(cserv, "create_candidate", _boom)
    monkeypatch.setattr(cserv, "candidate_exists", _boom)

    singleton = pr_tools._service.agent
    original_last_products = singleton._last_products
    singleton._last_products = lambda ctx=None: [
        {"asin": "B0TEST1234", "title": "回归测试商品", "price": 9.99}
    ]
    tok_ctx = _current_context_id.set("probe-ctx-none")
    tok_shop = _current_shop_id.set(None)
    try:
        raw = await pr_tools._save_candidate_tool(asin="B0TEST1234", title="回归测试商品")
        data = _json.loads(raw)
        assert data.get("type") == "candidate_save_failed"
        assert "店铺" in (data.get("error") or "")
    finally:
        singleton._last_products = original_last_products
        _current_context_id.reset(tok_ctx)
        _current_shop_id.reset(tok_shop)
