"""店秘书计划读口（`GET /api/v1/orchestrator/plan`）的契约与归属门禁。

背景（第 155 轮）
-----------------
批 C3（第 148 轮）把规划器做完了，但计划只有一条出口：`POST /orchestrator/chat`
的响应。老板一刷新页面，前端手上就没有"最近一次响应"，计划条只能空着 ——
直到他再随便说一句话。而计划是**跨轮持续的状态**（后端刻意把它放在图状态而不是
消息序列里，正是为了让它不随上下文裁剪消失），所以它需要一个**不依赖"刚好聊过
一句话"**的读取方式 ⇒ 本读口。

本文件钉住四件事
----------------
  · **注册形态**：端点真的挂上了、是 GET、`session_id` 按 **query** 解析
    （不是 body —— 本仓踩过"裸标量按 query 解析、前端发 body ⇒ 稳定 422 ⇒
    功能看起来做了但从未生效"）；
  · **只读性**：`current_plan()` 只 `aget_state`、**绝不** `ainvoke`
    （读一次状态不该产生 LLM 费用，也不该在图里留下痕）；
  · **归属**：别人拿着你的 `session_id` 来读，读到的是**他自己**的线程 ⇒ `None`。
    这不是"多一层守卫"，而是 `thread_id = ns:user_id:session_id` 的物理结果；
  · **同一个响应**：没会话 / 没身份 / 没计划 / 读失败 ⇒ 一律 `None`，不区分原因
    （一旦区分，这个端点就成了"这个 session_id 存不存在"的探针）。

★ 归属用例走的是 `BaseAgent.resolve_thread_id` 的**真实现**（不是手写一个
  `"U:%s" % sid` 的假键）——否则测的是测试自己编的口径，不是产品的口径。
"""

import asyncio
import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
AGENT_PY = BACKEND / "modules" / "secretary" / "agent.py"
ROUTER_PY = BACKEND / "modules" / "secretary" / "router.py"
PLAN_PATH = "/api/v1/orchestrator/plan"


# ============================================================
# 一、注册形态
# ============================================================


def _route(path: str):
    from main import app

    hits = [r for r in app.routes if getattr(r, "path", "") == path]
    assert len(hits) == 1, f"{path} 在运行时路由表里有 {len(hits)} 条（期望恰好 1 条）"
    return hits[0]


def test_plan_endpoint_is_registered_as_get():
    """端点必须**真的挂在运行时路由表**上 —— 写了但没 include 是最常见的空转形态。"""
    route = _route(PLAN_PATH)
    assert "GET" in (route.methods or set()), f"{PLAN_PATH} 的方法集是 {route.methods}"


def test_session_id_is_parsed_as_query_not_body():
    """`session_id` 必须按 **query** 解析。

    ★ 这条不是形式主义：本仓有过一次「裸标量形参按 query 解析、前端按 body 发
      ⇒ 稳定 422 ⇒ 刷新令牌从未生效」的事故。读口与它的客户端必须同口径，
      所以这里把"按 query"钉成断言，而不是靠 review 记得。
    """
    route = _route(PLAN_PATH)
    query_names = {q.name for q in (route.dependant.query_params or [])}
    body_names = set()
    for b in route.dependant.body_params or []:
        body_names.add(getattr(b, "name", None) or getattr(b, "alias", None))

    assert "session_id" in query_names, (
        f"session_id 不在 query 参数里（query={sorted(query_names)}）—— "
        "前端发 query 会拿不到它，端点稳定 400"
    )
    assert "session_id" not in body_names, "session_id 被当成了请求体字段"


def test_plan_response_has_exactly_one_field():
    """`PlanResponse` 只该有 `plan` 一个字段。

    ★ 为什么值得一条断言：这个端点的**信息量本身就是风险** —— 每多一个字段
      （`session_exists` / `owner_id` / `updated_at`…）都可能变成枚举探针。
      把"只有一个字段"钉住，是为了让后来的人加字段时**必须先想清楚**。
    """
    from modules.secretary.router import PlanResponse

    fields = set(PlanResponse.model_fields)
    assert fields == {"plan"}, f"PlanResponse 的字段集是 {sorted(fields)}，期望只有 plan"


# ============================================================
# 二、`current_plan()` 的纯逻辑：穷尽拒绝 + 只读
# ============================================================


def test_current_plan_returns_none_without_session_or_user():
    """缺 session_id 或缺 user_id ⇒ 直接 None，不猜默认线程。"""
    from modules.secretary.agent import current_plan

    cases = [
        (None, "user-A"),  # 没有会话
        ("sess-1", None),  # 没有身份
        (None, None),
        ("", "user-A"),  # 空串同"没有"
        ("sess-1", ""),
    ]
    for sid, uid in cases:
        assert asyncio.run(current_plan(sid, uid)) is None, (
            f"current_plan({sid!r}, {uid!r}) 没有返回 None —— "
            "缺任一个都不该去猜一个默认 thread_id（那会让匿名请求共用一个线程）"
        )


def test_current_plan_is_read_only_by_ast():
    """`current_plan()` 只读：必须调 `aget_state`，**不得**调 `ainvoke`。

    ★ 形态判据走 AST 而不是源码字符串：本仓被 docstring 骗过多次
      （注释里写着"只读"，实现却在推进图）。
    """
    tree = ast.parse(AGENT_PY.read_text(encoding="utf-8"))
    fn = next(
        (
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "current_plan"
        ),
        None,
    )
    assert fn is not None, "agent.py 里找不到模块级的 async def current_plan"

    called = {
        n.func.attr
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    assert "aget_state" in called, (
        f"current_plan 没有调 aget_state（实际调用：{sorted(called)}）—— 那它从哪读计划？"
    )
    for forbidden in ("ainvoke", "astream", "invoke"):
        assert forbidden not in called, (
            f"current_plan 调了 {forbidden} —— 读一次计划不该推进图（会产生 LLM 费用，"
            "还会往图里写消息）"
        )


# ============================================================
# 三、归属：读到的只可能是你自己的计划
# ============================================================


class _FakeSnapshot:
    def __init__(self, values):
        self.values = values


class _FakeGraph:
    """按 thread_id 返回数据的假图 —— 键空间与真实现完全一致（见 `_FakeAgent`）。"""

    def __init__(self, store):
        self._store = store

    async def aget_state(self, cfg):
        tid = (cfg.get("configurable") or {}).get("thread_id")
        return _FakeSnapshot({"todos": self._store.get(tid, [])})


class _FakeAgent:
    """只实现 `current_plan()` 用到的两样东西，且**复用真的 `resolve_thread_id`**。"""

    checkpointer = object()  # 非 None 即可
    checkpoint_namespace = ""  # secretary 的口径（见 BaseAgent.resolve_thread_id docstring）

    def __init__(self, store):
        self._store = store

    def graph_for_session(self, session_id, user_id=None):
        from ai_infra.base_agent import BaseAgent

        tid = BaseAgent.resolve_thread_id(self, session_id, user_id)
        return _FakeGraph(self._store), {"configurable": {"thread_id": tid}}


def _patch_agent(monkeypatch, store):
    import modules.secretary.agent as agent_mod

    monkeypatch.setattr(agent_mod, "get_secretary_agent", lambda shop_id=None: _FakeAgent(store))


def test_plan_read_is_scoped_by_user(monkeypatch):
    """★★ A 的计划，B 拿同一个 session_id 读不到。

    ★ 关键：假图的键空间由**真的** `resolve_thread_id` 算出（`ns:user_id:session_id`），
      所以这条用例验证的是产品口径，而不是测试自己编的口径。
    """
    from modules.secretary.agent import current_plan

    todos = [{"id": "t1", "content": "先选品", "status": "completed"}]
    # A 的线程（user-A:sess-shared）里有计划；键空间里没有 user-B 的那条。
    store = {"user-A:sess-shared": todos}
    _patch_agent(monkeypatch, store)

    plan_a = asyncio.run(current_plan("sess-shared", "user-A"))
    assert plan_a is not None and plan_a["total"] == 1, "A 读自己的计划应该是有的"

    plan_b = asyncio.run(current_plan("sess-shared", "user-B"))
    assert plan_b is None, (
        "B 用同一个 session_id 读到了 A 的计划 —— thread_id 里的 user_id 没生效，"
        "两个用户的 checkpoint 落在同一个线程上了"
    )


def test_plan_read_distinguishes_agents_by_namespace(monkeypatch):
    """命名空间（`checkpoint_ns`）同样要隔开 —— 本仓所有图共用同一个 `AgentState`。"""
    from modules.secretary.agent import current_plan

    store = {"other-agent:user-A:sess-1": [{"id": "t1", "content": "x", "status": "pending"}]}

    class _NsAgent(_FakeAgent):
        checkpoint_namespace = "secretary"

    import modules.secretary.agent as agent_mod

    monkeypatch.setattr(agent_mod, "get_secretary_agent", lambda shop_id=None: _NsAgent(store))

    assert asyncio.run(current_plan("sess-1", "user-A")) is None, (
        "secretary 读到了别的 Agent 命名空间下的计划 —— ns 前缀没拼进 thread_id"
    )


def test_empty_or_missing_plan_returns_none(monkeypatch):
    """有会话、有身份，但线程里没有 todos ⇒ None（而不是 `{total: 0}`）。"""
    from modules.secretary.agent import current_plan

    _patch_agent(monkeypatch, {})
    assert asyncio.run(current_plan("sess-1", "user-A")) is None


def test_read_failure_returns_none_and_does_not_raise(monkeypatch):
    """读失败（DB 抖动 / 连接池超时）⇒ None，**不抛**。

    ★ 理由：这个端点是"锦上添花"的读口，它挂掉不该把前端的整个计划区
      变成错误页。★ 同时断言它与"没有计划"返回同一个东西 —— 区分即成为探针。
    """
    from modules.secretary.agent import current_plan

    class _Boom:
        async def aget_state(self, cfg):
            raise RuntimeError("connection pool timeout")

    class _BoomAgent(_FakeAgent):
        def graph_for_session(self, session_id, user_id=None):
            return _Boom(), {"configurable": {"thread_id": "user-A:sess-1"}}

    import modules.secretary.agent as agent_mod

    monkeypatch.setattr(
        agent_mod, "get_secretary_agent", lambda shop_id=None: _BoomAgent({})
    )
    assert asyncio.run(current_plan("sess-1", "user-A")) is None


# ============================================================
# 四、真源对账（防止两份实现漂移）
# ============================================================


def test_plan_shape_comes_from_plan_summary():
    """读口返回的形状必须来自 `ai_infra.plan.plan_summary`（唯一真源）。

    ★ 形态判据：`current_plan` 体内必须有对 `plan_summary` 的调用。
      自己手拼一个 `{"total": len(todos), ...}` 就是第二份实现 ——
      加一个状态字段时两处会不一致，而 UI 只信其中一份。
    """
    tree = ast.parse(AGENT_PY.read_text(encoding="utf-8"))
    fn = next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "current_plan"
    )
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    assert "plan_summary" in names, (
        "current_plan 没有用 plan_summary —— 形状会与 route() 那条路漂移"
    )


@pytest.mark.parametrize("field", ["total", "completed", "by_status", "items"])
def test_plan_summary_contract_fields_exist(field):
    """`plan_summary` 的四字段契约（前端 `PlanSummary` 按它声明）。"""
    from ai_infra.plan import plan_summary

    out = plan_summary([{"id": "t1", "content": "x", "status": "pending"}])
    assert field in out, f"plan_summary 少了 {field} —— 前端 PlanSummary 是按它声明的"


# ============================================================
# 五、端到端（**真发 HTTP**）
# ============================================================
#
# ★ 为什么单独一节：上面四节里，前三条查的是**运行时路由表**，
#   其余全是 `current_plan()` 的**纯逻辑**（打桩假 agent）—— **没有一条把请求
#   真的发进 ASGI 栈**。而依赖注入形态错误（本仓刚在 memory 儨共 6 个端点上
#   撞过：`partial` 包 async 依赖 ⇒ FastAPI 不 await）**只有真发请求才能暴露**。


async def test_plan_endpoint_returns_200_null_for_anonymous(client):
    """匿名 + 不存在的 session ⇒ **200 + `{"plan": null}`**。

    ★ 三个非 200 的情形各自错在哪：
      · 401：读一个「你本来就没有的东西」不该要求登录（而且会把
        「未登录」与「没计划」分成两种状态，前端反而更难处理）；
      · 400/422：说明 `session_id` 没按 query 解析（本仓踩过这个坑）；
      · 500：依赖形态 / 引用注入坏了 —— 而前端的 catch 是静默的，
        界面上只会“计划条空着”，与「真的没计划」**长一模一样**。
    """
    r = await client.get(PLAN_PATH, params={"session_id": "sess-does-not-exist"})
    assert r.status_code == 200, (
        f"匿名读计划应为 200，实际 {r.status_code}：{r.text[:200]}"
    )
    assert r.json() == {"plan": None}, (
        f"响应体应严格等于 {{'plan': None}}，实际 {r.json()!r} "
        "—— 多一个字段（如 session_exists / owner_id）就是枚举探针"
    )


async def test_plan_endpoint_requires_non_empty_session_id(client):
    """缺 `session_id` / 传空串 ⇒ 422（`Query(..., min_length=1)` 的契约）。

    ★ 前端 `loadSecretaryPlan` 有 `if (!sid) return` 护栏，正常路径不会踩到；
      但把它钉住是为了防“为了容忍空串而把参数改成可选”
      —— 一旦可选，后端就得去猜一个默认线程（等于让匿名请求共用一个线程）。
    """
    r1 = await client.get(PLAN_PATH)
    assert r1.status_code == 422, f"缺 session_id 应为 422，实际 {r1.status_code}"

    r2 = await client.get(PLAN_PATH, params={"session_id": ""})
    assert r2.status_code == 422, (
        f"空串 session_id 应为 422，实际 {r2.status_code} —— 空串等于「没有会话」"
    )
