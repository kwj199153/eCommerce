"""
业务 Agent 会话记忆：统一入口 `session_id → thread_id`（2026-09-17，第 131 轮）

★★★ 这条链路此前是「看着接了、其实没接」：

  · `BaseAgent` **没有**统一入口 —— `thread_id` 散在 3 处各写一份：
      `secretary/agent.py`  → `session_id or "secretary-default"`
      `listing_generator`   → `f"listing-{id(self)}"`          ← 对象内存地址
      `product_research`    → `f"product-research-{context_id or id(self)}"`
    后两处拿 `id(self)` 当 `thread_id` ⇒ 进程一重启就换键，
    于是**永远命中不到上一轮的 checkpoint**（现象："记忆看着有一轮、重启就没了"）。
  · 两个 router 子层（listing / product_research）**根本没传 checkpointer**
    ⇒ 主 Agent 就算传了 `session_id` 也没有任何东西可被持久化
    （`langgraph.types.interrupt()` 更是会直接抛）。
  · `secretary` 在**没有** `session_id` 时仍把 `"secretary-default"` 填进 config，
    而它的图是绑了 checkpointer 的 ⇒ 所有无会话请求（含匿名）挤进同一段
    消息历史、互相看得见对方说过什么（跨用户串记忆，且不报任何错）。

现在口径全部收在 `BaseAgent.resolve_thread_id()` / `graph_for_session()`：

  · `session_id` **与** `user_id` 都非空 ⇒ 图**带** checkpointer，
    `thread_id = ":".join(p for p in (ns, user_id, session_id) if p)`；
  · 缺任一个 ⇒ **不留记忆**：走不带 checkpointer 的图 + **空 config**。

  ★ 为什么"没有会话"不能拿默认 `thread_id` 兜底：默认值是**全进程共享**的，
    所有匿名 / 无会话请求会挤进同一段消息历史、互相看得见对方说过什么
    （schema 相同所以不报错）。原则同 `accounts.filter_accessible_stores`：
    **没有身份 ⇒ 没有数据；没有会话 ⇒ 不留记忆。**

  ★★ 第 131 轮（item 3）：**光有会话还不够，必须有身份。**
    命名空间只隔开「不同 Agent」，隔不开「同一 Agent 的不同用户」——
    两个用户只要拿到同一个 `session_id`，就落在同一个 thread 上、共享记忆。
    所以 `thread_id` 里再拼一段 `user_id`（只从 `current_user.id` 取，
    **不接受任何自报字段**）。⚠️ 这是**公开契约变更**：键变了，
    此前已落库的 checkpoint 行会全部失联（不报错，只是"历史突然没了"）。

★ 反向注入（必须做，否则不知道这几条是不是空跑）
  ① 把 `graph_for_session()` 的 `if session_id:` 改成恒真 ⇒
     `test_no_session_leaves_no_memory` 转红（无会话也拿带记忆的图、还伪造了 thread_id）；
  ② 把 `resolve_thread_id()` 的 `f"{ns}:{session_id}"` 改回裸 `session_id` ⇒
     `test_namespaces_do_not_collide` 转红（两个 Agent 的会话挤进同一段历史）；
  ③ 把 `run_session` 改名成 `invoke` ⇒ 撞 `test_infra_layering.py` 的防回流门禁；
  ④ 把 `resolve_thread_id` 的 `user_id` 段去掉 ⇒
     `test_same_session_different_users_are_isolated` 转红；
  ⑤ 把 `graph_for_session` 条件里的 `and user_id` 去掉 ⇒
     `test_session_and_identity_are_both_required` 转红。
"""

import json
import pathlib
import subprocess
import sys

import pytest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]


# ====== 1. thread_id 规则（纯函数，零 IO）======


def test_resolve_thread_id_rules():
    """
    `resolve_thread_id` 的两条规则，**逐条**钉住。

    ★ 为什么 `ns=""` 必须**不加前缀**：`secretary` 从一开始就用裸 `session_id`
      当 thread_id，本地库里已有落盘的会话记忆。加前缀 = 换键 ⇒ 那些记忆
      **全部失联**（不报错，只是"历史突然没了"）—— 这是最难查的一类回归。
    """
    from ai_infra.base_agent import BaseAgent

    plain = BaseAgent(agent_name="secretary_like")
    assert plain.checkpoint_namespace == "", (
        "默认命名空间必须是空串（secretary 的历史口径，改了就丢既有记忆）"
    )
    assert plain.resolve_thread_id("s-1") == "s-1", (
        "ns 为空串时不得加前缀 —— 会让人已落库的会话记忆全部失联"
    )

    ns = BaseAgent(agent_name="listing_router", checkpoint_ns="listing")
    assert ns.resolve_thread_id("s-1") == "listing:s-1"

    # ★ 第 131 轮：带身份时是**三段**拼接，空段一律跳过
    assert ns.resolve_thread_id("s-1", "u-1") == "listing:u-1:s-1"
    assert plain.resolve_thread_id("s-1", "u-1") == "u-1:s-1", (
        "ns 为空串时必须跳过该段（不能拼出 `:u-1:s-1`）"
    )
    assert ns.resolve_thread_id("s-1", None) == "listing:s-1", (
        "user_id 为 None 时必须跳过该段（不能拼出 `listing::s-1`）"
    )
    assert ns.resolve_thread_id("s-1") == ns.resolve_thread_id("s-1", None), (
        "不传 user_id 与显式传 None 必须等价"
    )


def test_namespaces_do_not_collide():
    """
    ★ 两个 Agent 的同一个 `session_id` 必须落到**不同** thread_id。

    成因：LangGraph 的 checkpoint 按 `thread_id` 分片，**不看图的身份**，
    而本仓所有图共用同一个 `AgentState` schema ⇒ 同一个 thread_id
    会让用户与 listing 的对话出现在 secretary 的上下文里。schema 相同
    所以不会报错，只是**静默串味**。

    反向注入：把 `f"{ns}:{session_id}"` 改回裸 `session_id` ⇒ 本条转红。
    """
    from ai_infra.base_agent import BaseAgent

    a = BaseAgent(agent_name="a_router", checkpoint_ns="listing")
    b = BaseAgent(agent_name="b_router", checkpoint_ns="product_research")
    assert a.resolve_thread_id("s-1") != b.resolve_thread_id("s-1"), (
        "两个 Agent 的同一会话挤进了同一条历史 —— 记忆会互相串"
    )
    # 同一实例同一会话必须稳定（否则每轮都开新线程 = 等于没有记忆）
    assert a.resolve_thread_id("s-1") == a.resolve_thread_id("s-1")


async def test_session_and_identity_are_both_required():
    """
    ★★★ 会话与身份**缺一不可** —— 只给其中一个都不留记忆。

    ★ 为什么"只有会话"也不行：`thread_id` 若不含身份，就仍是「一个与用户
      无关的串」。会话 ID 可能由客户端提供、也可能由服务端颁发，两条路都
      可能撞上同一个串 ⇒ 两个用户共享一段记忆。这不是"记忆少了"，
      而是**记忆错人**，比没有记忆严重得多。

    反向注入：把 `graph_for_session` 条件里的 `and user_id` 去掉 ⇒ 本条转红。
    """
    from ai_infra.base_agent import BaseAgent

    a = BaseAgent(agent_name="probe3", checkpoint_ns="probe3")
    used: list = []
    a.checkpointer = object()
    a._graph = _stub("memory", used)
    a._graph_memoryless = _stub("memoryless", used)

    await a.run_session({"messages": []}, session_id="s-1")
    assert used == [("memoryless", {})], (
        f"只有会话、没有身份时不该用带记忆的图: {used}"
    )

    used.clear()
    await a.run_session({"messages": []}, user_id="u-1")
    assert used == [("memoryless", {})], (
        f"只有身份、没有会话时不该用带记忆的图: {used}"
    )

    used.clear()
    await a.run_session({"messages": []}, session_id="s-1", user_id="u-1")
    assert used == [("memory", {"configurable": {"thread_id": "probe3:u-1:s-1"}})], (
        f"两者齐全时必须走带记忆的图: {used}"
    )


def test_same_session_different_users_are_isolated():
    """
    ★★★ 两个用户的**同一个** `session_id` 必须落到**不同** thread_id。

    这是 item 3「记忆不按人隔离」的直接判据。命名空间只隔 Agent、隔不了
    用户；拼上 `user_id` 之后，即使上层归属校验被绕过，两个人也不可能
    撞到同一个键（纵深防御）。

    反向注入：把 `resolve_thread_id` 的 `user_id` 段去掉 ⇒ 本条转红。
    """
    from ai_infra.base_agent import BaseAgent

    a = BaseAgent(agent_name="router", checkpoint_ns="listing")
    assert a.resolve_thread_id("shared-sess", "user-A") != a.resolve_thread_id(
        "shared-sess", "user-B"
    ), "两个用户共用一段 thread ⇒ 记忆会串人（比没有记忆更危险）"
    assert a.resolve_thread_id("shared-sess", "user-A") == a.resolve_thread_id(
        "shared-sess", "user-A"
    ), "同一用户同一会话必须稳定，否则每轮都开新线程 = 等于没有记忆"


def test_new_entry_names_do_not_collide_with_business_contract():
    """
    统一入口必须存在，且名字**不得**与业务契约撞名（`invoke` / `stream` / `stream_chat`）。

    ★ 这里只断言"新入口确实在"；撞名由
      `tests/test_infra_layering.py::test_base_agent_exposes_no_conflicting_entry`
      用 AST 拦。两处判据不同、不是重复：本条防"改名改没了"，那条防"改回旧名"。
    """
    from ai_infra.base_agent import BaseAgent

    for name in ("run_session", "stream_session", "graph_for_session",
                 "resolve_thread_id", "attach_checkpointer"):
        assert callable(getattr(BaseAgent, name, None)), f"统一入口 {name} 不见了"


# ====== 2. 「没有会话 ⇒ 不留记忆」（桩图，确定性，无需 PG / LLM）======


def _stub(tag, used):
    class _StubGraph:
        async def ainvoke(self, state, config=None):
            used.append((tag, config))
            return state

    return _StubGraph()


async def test_no_session_leaves_no_memory():
    """
    ★★★ 没有 `session_id` ⇒ **既不**用带 checkpointer 的图，**也不**伪造 thread_id。

    ★ 为什么必须两条都断言：只断言 config 为空不够 —— 若实现改成
      「一张默认 thread_id 的 config + 带记忆的图」，config 里就会冒出 `thread_id`，
      于是所有无会话请求共用一段历史（这正是 `secretary` 改前的形态）。

    反向注入：把 `graph_for_session()` 的 `if session_id:` 改成恒真 ⇒ 本条转红。
    """
    from ai_infra.base_agent import BaseAgent

    a = BaseAgent(agent_name="probe", checkpoint_ns="probe")
    used: list = []
    a.checkpointer = object()            # 非空 ⇒ 逼 `_memoryless_graph()` 另编译一张
    a._graph = _stub("memory", used)
    a._graph_memoryless = _stub("memoryless", used)

    await a.run_session({"messages": []})
    assert used == [("memoryless", {})], (
        f"无会话时用错了图 / 伪造了 thread_id: {used}。"
        "守卫应为「没有会话 ⇒ 不留记忆」（无 checkpointer 的图 + 空 config）。"
    )

    used.clear()
    await a.run_session({"messages": []}, session_id="s-9", user_id="u-9")
    assert used == [
        ("memory", {"configurable": {"thread_id": "probe:u-9:s-9"}})
    ], f"有会话 + 有身份时没走带记忆的图 / thread_id 不对: {used}"


async def test_stream_session_shares_the_same_thread_rule():
    """
    流式入口与非流式入口必须走**同一个** thread_id 口径 ——
    否则同一会话的两条路径各记一半、互相看不见（"聊了 3 轮，切一次流式就失忆"）。
    """
    from ai_infra.base_agent import BaseAgent

    a = BaseAgent(agent_name="probe2", checkpoint_ns="probe2")
    used: list = []

    class _StubGraph:
        async def astream_events(self, state, config=None, version="v2"):
            used.append((config, version))
            yield {"event": "on_chat_model_stream"}

    a._graph = _StubGraph()
    out = [
        ev
        async for ev in a.stream_session(
            {"messages": []}, session_id="s-7", user_id="u-7"
        )
    ]
    assert used == [
        ({"configurable": {"thread_id": "probe2:u-7:s-7"}}, "v2")
    ], used
    assert out == [{"event": "on_chat_model_stream"}]

    used.clear()
    _ = [ev async for ev in a.stream_session({"messages": []})]
    assert used == [({}, "v2")], f"无会话的流式请求不该带 thread_id: {used}"

    used.clear()
    _ = [ev async for ev in a.stream_session({"messages": []}, session_id="s-7")]
    assert used == [({}, "v2")], (
        f"只有会话没有身份时也不该带 thread_id（否则两个用户会共享记忆）: {used}"
    )


# ====== 3. 端到端：真 checkpointer + 真图，两轮真的能互相看见 ======


async def test_real_checkpointer_accumulates_only_within_one_session():
    """
    ★★★ 端到端（真 `AsyncPostgresSaver` + 真图）：
      同一会话的第二轮**看得见**第一轮；换会话与无会话都**看不见**。

    这是"多轮记忆真的在工作"的唯一硬证据 —— 上面那两条只证明**配置对了**，
    证明不了 checkpointer 真的按 thread_id 恢复历史。

    ★ 为什么走子进程而不是进程内：本机实测 psycopg3 异步**不能用 Windows 默认的
      `ProactorEventLoop`**（实测 `PoolTimeout: couldn't get a connection after
      30.00 sec`），而 `backend/pytest.ini` 的 loop scope 是 **session** ⇒
      在用例里换循环策略等于**改全局**、会波及全部测试。
      所以把「selector 循环 + 真 checkpointer」整体关进
      `scripts/check_multi_turn_memory.py`，这里只解析它的 `RESULT_JSON`。

    ★ 依赖本机 PG ⇒ 不可用时显式 skip（判据：依赖**本机数据** ⇒ skip；
      依赖**仓库内容** ⇒ 漏配就该起不来）。
    """
    r = subprocess.run(
        [sys.executable, "-X", "utf8", "scripts/check_multi_turn_memory.py"],
        cwd=BACKEND_DIR, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("RESULT_JSON: ")]
    assert lines, (
        f"探针没有输出 RESULT_JSON（exit={r.returncode}）\n"
        f"--- stdout tail ---\n{r.stdout[-1500:]}\n--- stderr tail ---\n{r.stderr[-1500:]}"
    )
    res = json.loads(lines[-1][len("RESULT_JSON: "):])

    if not res.get("ok") and "PoolTimeout" in str(res.get("error", "")):
        pytest.skip(f"checkpoint 库不可用，跳过端到端记忆验证: {res['error']}")

    checks = res.get("checks", {})
    assert checks.get("turn2_sees_turn1"), (
        f"第二轮看不见第一轮 ⇒ 服务端多轮记忆没生效。checks={checks}"
    )
    assert checks.get("other_session_isolated"), (
        f"换了会话还看得见上一段历史 ⇒ thread_id 没起隔离作用。checks={checks}"
    )
    assert checks.get("no_session_leaves_no_memory"), (
        f"无会话的两轮互相看见了 ⇒ 拿默认 thread_id 兜底了（跨用户串记忆）。checks={checks}"
    )
    assert checks.get("other_user_isolated"), (
        f"换一个用户、同一个 session_id 仍看得见上一段 ⇒ 记忆没按人隔离。checks={checks}"
    )
    assert checks.get("no_identity_leaves_no_memory"), (
        f"只有会话没有身份时留了记忆 ⇒ thread_id 里没带身份。checks={checks}"
    )
