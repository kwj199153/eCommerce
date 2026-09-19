"""Agent 会话级状态：有界容器 + PG 持久化（第 145 轮 · 批 C1）。

对应 r141《Agent 能力缺口评审》批 C 的 C1：
    「`_session_state` 从进程内存搬到 **PG 会话表**（或并入 `AgentState`）；
      口径与 checkpointer 统一」

★ 本文件钉住的**安全属性**（不是实现细节）：

    P1 **作用域只有一份口径**：`_state_scope()` 是 `resolve_thread_id()` 在
       业务侧**唯一**的调用点，而 `_session()` / `_state_key()` /
       `_hydrate_state()` / `_flush_state()` 全都经它取键。
       ★ 反面：hydrate 用「入参 user_id」算键、`_session()` 用 ContextVar 算键
       ⇒ 一旦 `_bind_context` 被替换或漏调，两者就分叉 —— **不报错，只丢状态**。
       所以 `_state_scope` 只读 ContextVar，**不接受 user_id 入参**。
    P2 **状态与 checkpoint 同键**：落盘用的 `thread_id` 就是
       `BaseAgent.resolve_thread_id()`（`ns:user_id:session_id`）。
       两处各拼一份 = 两份 ID 空间 ⇒「历史还在、槽位没了」。
    P3 **归属是查询条件**：`owner_id` 出现在 `where` 里（读与删都是），
       不是返回值里的一件装饰品。
    P4 **脏容器不被驱逐、不被覆盖**：脏 = 有改动还没落盘。驱逐/覆盖都是
       **静默丢用户刚补的槽位**。
    P5 **出口失败不炸本轮**：落盘在「回答已生成完」的出口，那里抛异常等于把
       一次成功的回答换成 500；同时**不清脏标记**（下次重试）。
    P6 **入口先补写再读**：上一轮可能落盘失败或被客户端断流取消 ⇒ 内存仍脏，
       而 hydrate 对脏容器不覆盖 ⇒ 不先补写，那笔改动永远出不了门。
    P7 **有界**：键只增不减 = 长跑进程持续泄漏（原形态就是这样一个 dict）。

★ 反面（误报）也钉住了：
    · 干净容器被 hydrate 覆盖是**正常**的（读到的就是全部）—— 别把「不覆盖」
      写成无条件不覆盖；
    · 不脏的入口**不该**写库（否则每个请求白写一次）；
    · 写入**相同值**不该置脏（同上）。

反向注入对照（每条都能打穿本文件的某一条）：
    · `_state_scope` 改成接 `user_id` 形参          → C 组形态门禁转红
    · `_state_scope` 里自己拼 `f"x:{user_id}:{cid}"`  → C 组「唯一调用点」转红
    · `load_states` 去掉 `owner_id ==` 条件          → E 组归属隔离转红
    · `save_states` 的 delete 去掉 `owner_id` 条件    → E 组「越权删不掉」转红
    · `persist_state` 把 `mark_persisted` 改成无条件清空 → B 组「只清写过的键」转红
    · `persist_state` 里异常改成向上抛               → B 组「失败不炸」转红
    · `hydrate_state` 去掉 `if state.is_dirty`        → B 组「脏容器不被覆盖」转红
    · `_make_room` 去掉 `if not st.is_dirty`          → A 组「脏容器不驱逐」转红
    · `invoke` 的 `try/finally` 改成直线代码          → C/D 组形态与异常路径转红
    · `_invoke_impl` 里再 `_bind_context` 一次        → C 组「实现体不绑上下文」转红
    · `_UPSERT_CONSTRAINT` 改成不存在的名字           → B 组约束名转红；E 组真库落盘转红
    · `SessionState.__setitem__` 去掉 `_changed` 判断  → A 组「同值不置脏」转红
"""

from __future__ import annotations

import ast
import contextlib
import json
import pathlib
import uuid
from datetime import datetime
from unittest.mock import patch

import pytest

from ai_infra.session_state import (
    _changed,  # noqa: PLC2701  (自检常量，供门禁直接引用)
    SessionState,
    SessionStateRegistry,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"
AI_INFRA = BACKEND / "ai_infra"
AGENT_PY = MODULES / "product_research" / "agent_product_research.py"
STATE_PY = AI_INFRA / "session_state.py"
STORE_PY = MODULES / "conversation" / "state_store.py"

_TABLE = "agent_session_state"


# ==================================================================== 工具
def _tree(path: pathlib.Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _funcdefs(node: ast.AST, name: str) -> list[ast.AST]:
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    ]


def _attr_calls(node: ast.AST, attr: str) -> list[ast.Call]:
    """该子树里所有 `xxx.<attr>(...)` 形态的调用。"""
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == attr
    ]


def _dotted(node: ast.AST) -> str:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _cmp_operands(node: ast.AST) -> set[str]:
    """子树里所有 `ast.Compare` 两侧的**点分名**（用于证明某列真的进了 where）。"""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Compare):
            out.add(_dotted(n.left))
            out.update(_dotted(c) for c in n.comparators)
    return out


def _attr_uses(node: ast.AST, attr: str) -> list[ast.Attribute]:
    """子树里所有 `xxx.<attr>` 的**属性访问**（不要求被调用）。

    ★ 与 `_attr_calls` 的区别是必须的，不是风格：`state.is_dirty` 是属性，
      不是调用。用 `_attr_calls` 去找它恒空 ⇒ 形态断言恒假（假绿）。
    """
    return [
        n for n in ast.walk(node) if isinstance(n, ast.Attribute) and n.attr == attr
    ]


def _enclosing_calls(tree: ast.AST) -> list[tuple[str, ast.Call]]:
    """返回 `(最内层函数名, Call 节点)` —— 用于问「是**谁**在调这个」."""
    out: list[tuple[str, ast.Call]] = []

    def visit(node: ast.AST, fn_name: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if isinstance(child, ast.Call):
                out.append((fn_name, child))
            visit(child, fn_name)

    visit(tree, "<module>")
    return out


def _module_files(root: pathlib.Path) -> list[pathlib.Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


@contextlib.contextmanager
def _as_user(user_id):
    """把当前身份写进 ContextVar（`_state_scope` 的**唯一**真源）。"""
    from modules.product_research import agent_product_research as mod

    token = mod._current_user_id.set(user_id)
    try:
        yield
    finally:
        mod._current_user_id.reset(token)


def _agent():
    from modules.product_research.agent_product_research import ProductResearchAgent

    return ProductResearchAgent()


def _patch_store(*, hydrate=None, persist=None):
    """替换业务侧对存储层的两个门面别名（`agent_product_research` 的模块级引用）。"""
    from modules.product_research import agent_product_research as mod

    stack = contextlib.ExitStack()
    if hydrate is not None:
        stack.enter_context(patch.object(mod, "_hydrate_session_state", hydrate))
    if persist is not None:
        stack.enter_context(patch.object(mod, "_persist_session_state", persist))
    return stack


class _Ambiguous:
    """`bool(...)` 会抛的对象 —— 模拟 numpy 数组的逐元素比较结果。"""

    def __bool__(self):
        raise ValueError("truth value of an array with more than one element is ambiguous")


class _Weird:
    def __eq__(self, other):  # noqa: D105
        return _Ambiguous()

    def __ne__(self, other):  # noqa: D105
        return _Ambiguous()


# ================================================ A 组 · 机制层（无 IO）
def test_container_is_a_full_mutable_mapping():
    """★ 容器必须对 `MutableMapping` **协议全兼容**。

    8 个消费点在同步私有方法里直接用它（`_ask_for_save` / `_last_products` /
    `_resolve_named_product`），用的是 `.get()` / `setdefault` / `pop(k, None)` /
    `dict(...)`。少一个方法就会在**业务路径深处**抛 AttributeError，
    而那里离"我把状态换了个容器"很远。
    """
    st = SessionState({"a": 1}, scope_id="s")
    assert st.get("a") == 1 and st.get("missing") is None
    assert st.setdefault("a", 999) == 1, "setdefault 覆盖了既有值"
    assert st.setdefault("b", 2) == 2
    assert st.pop("b", None) == 2
    assert st.pop("nope", None) is None, "pop 缺省值语义不对 ⇒ `session.pop(k, None)` 会炸"
    st.update({"c": 3})
    assert dict(st) == {"a": 1, "c": 3}
    assert "a" in st and len(st) == 2
    assert repr(st), "repr 不该抛（日志/调试路径会调它）"


def test_same_value_write_is_not_dirty():
    """★ 写入**相同值**不得置脏 —— 否则每个请求都会白写一次库。

    业务侧有「读到再写回」的写法（`_session(cid)["last_blue_ocean"] = result`），
    同值时置脏 = 每请求一次 upsert，库里 `updated_at` 一直变，还看不出原因。
    """
    st = SessionState(scope_id="s")
    st["x"] = 1
    assert st.dirty_keys == frozenset({"x"})
    st.mark_persisted(keys=["x"])
    assert not st.is_dirty

    st["x"] = 1
    assert not st.is_dirty, "同值写入被误判为改动 ⇒ 每次请求白写一次库"
    st["x"] = 2
    assert st.dirty_keys == frozenset({"x"}), "真变化却没置脏 ⇒ 改动永远不会落盘"


def test_deleted_keys_are_not_writes():
    """删除要记在 `deleted` 而不是 `dirty` —— 两者在落盘时走不同语句。"""
    st = SessionState(scope_id="s")
    st["k"] = 1
    st.mark_persisted(keys=["k"])
    del st["k"]
    assert st.deleted_keys == frozenset({"k"})
    assert st.dirty_keys == frozenset(), "已删的键不该再出现在待写集合里"
    assert st.pending_writes() == {}, "pending_writes 里混进了已删的键"
    assert st.is_dirty, "只删不写也是改动 —— 否则那次删除永远不会被落盘"


def test_pending_writes_only_covers_changed_keys():
    """★ 增量落盘的判据：只回传**改动过**的键。

    整行读写的问题就在这里 —— `last_blue_ocean` 可以到几百 KB，
    为了改一个几十字节的 `pending_save` 把它重写一遍，且并发两次请求互相覆盖。
    """
    st = SessionState(scope_id="s")
    st["big"] = {"products": [{"t": i} for i in range(50)]}
    st.mark_persisted(keys=["big"])
    st["small"] = 7
    assert st.pending_writes() == {"small": 7}
    assert st.dirty_keys == frozenset({"small"})


def test_mark_persisted_clears_only_the_keys_it_wrote():
    """★★★ `mark_persisted` 只清**传入的**那些键。

    `await` 落盘期间可能有新的改动进来（并发请求 / 业务在出口前又改一次）。
    无差别清空会让那笔新改动**永远不会被写出去**，而且不报任何错 ——
    表现是「我明明刚说的，下一轮又忘了」。
    """
    st = SessionState(scope_id="s")
    st["a"] = 1
    st.mark_persisted(keys=["a"])
    assert not st.is_dirty

    st["a"] = 2
    st["b"] = 3
    st.mark_persisted(keys=["a"])  # 只写了 a
    assert st.dirty_keys == frozenset({"b"}), "无差别清空 ⇒ 落盘期间的改动永不落盘"


def test_reset_replaces_content_and_clears_dirty():
    """`reset` = 「从库读回来」的语义：读到的就是全部，没有待写增量。"""
    st = SessionState(scope_id="s")
    st["a"] = 1
    st["b"] = 2
    del st["b"]
    st.reset({"z": 9})
    assert dict(st) == {"z": 9}
    assert not st.is_dirty and not st.dirty_keys and not st.deleted_keys


def test_changed_degrades_to_true_when_comparison_is_ambiguous():
    """★ `old != new` **不保证返回 bool**。

    numpy 数组 / pandas Series 会比较出逐元素结果，`bool()` 直接抛
    `ValueError: truth value ... is ambiguous`。那个异常会从 `__setitem__`
    里冒出来，位置离真正的原因很远（"我只是给状态赋了个值"）。
    收敛方式：比不出来就**当作变了** —— 多写一次库，不会丢数据。
    """
    assert _changed(1, 2) is True
    assert _changed(1, 1) is False
    assert _changed(_Weird(), _Weird()) is True, "比不出来时必须按「变了」处理（保守侧）"

    st = SessionState(scope_id="s")
    st["x"] = _Weird()
    st["x"] = _Weird()  # 不得抛
    assert st.dirty_keys == frozenset({"x"})


def test_registry_is_bounded_and_evicts_clean_first():
    """★ 有界（LRU）是必须的：旧形态键只增不减 ⇒ 长跑进程持续吃内存。"""
    reg = SessionStateRegistry(max_scopes=2)
    reg.scope("a")
    reg.scope("b")
    reg.scope("c")
    assert "a" not in reg and "b" in reg and "c" in reg, "驱逐的不是最旧的干净容器"
    assert reg.evicted == 1

    # 命中即续期：a 被访问过之后，该被赶的是 b
    reg2 = SessionStateRegistry(max_scopes=2)
    reg2.scope("a")
    reg2.scope("b")
    reg2.scope("a")
    reg2.scope("c")
    assert "a" in reg2 and "b" not in reg2, "LRU 没有续期 ⇒ 热会话被误驱逐"


def test_default_bound_actually_applies():
    """默认上限必须真的生效（不是个只写在常量里的数字）。"""
    n = SessionStateRegistry.DEFAULT_MAX_SCOPES
    assert isinstance(n, int) and 0 < n < 10**6, f"默认上限不像是有限值：{n}"
    reg = SessionStateRegistry()
    for i in range(n + 5):
        reg.scope("s%d" % i)
    assert len(reg) <= n, "默认上限没生效 ⇒ 键只增不减（内存泄漏）"


def test_dirty_scopes_are_not_evicted():
    """★★★ 脏容器**不得驱逐** —— 那是静默丢用户刚补的槽位。

    极端情况（全部脏）下宁可让缓存暂时超出上限：那是内存问题，
    而丢状态是**正确性**问题。两类问题的代价不对称 ⇒ 选安全的那一侧。
    """
    reg = SessionStateRegistry(max_scopes=2)
    reg.scope("a")["x"] = 1
    reg.scope("b")["x"] = 1
    reg.scope("c")["x"] = 1
    for k in ("a", "b", "c"):
        assert k in reg, "脏容器 %s 被驱逐 ⇒ 用户刚补的槽位被静默丢掉" % k
    assert reg.evicted == 0, "一个脏容器都不该被驱逐"
    assert len(reg) == 3 and reg.max_scopes == 2, "全脏时应允许暂时超出上限"

    # 一半脏一半干净：只能赶干净的
    reg2 = SessionStateRegistry(max_scopes=2)
    reg2.scope("dirty")["x"] = 1
    reg2.scope("clean")
    reg2.scope("new")
    assert "dirty" in reg2 and "clean" not in reg2


def test_dirty_scopes_is_observable():
    """调用方要能问出「现在谁有未落盘的改动」。"""
    reg = SessionStateRegistry()
    reg.scope("x")["k"] = 1
    reg.scope("y")
    assert reg.dirty_scopes() == ("x",)
    reg.scope("x").mark_persisted(keys=["k"])
    assert reg.dirty_scopes() == ()


def test_state_module_is_storage_free():
    """★ 机制层**不认识数据库** —— 反过来它就会被业务键名绑架。

    判据用 AST（不看源码字符串）：本模块不得 import 任何 DB / 业务符号。
    """
    tree = _tree(STATE_PY)
    imported = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            imported.update(a.name for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            imported.add(n.module or "")
    forbidden = [
        m
        for m in imported
        if m.startswith(("core.", "modules.", "sqlalchemy", "alembic"))
    ]
    assert not forbidden, f"机制层被存储/业务污染了：{forbidden}"


# ============================================ B 组 · 持久层契约（桩，无 IO）
async def test_store_short_circuits_without_owner_or_thread():
    """★ 缺 `owner_id` 或 `thread_id` ⇒ **零 DB 往返**。

    两种都不可接受：当成「谁都读得到」是越权，当成「谁都读不到」则所有
    无身份路径每次请求都白打一次库。
    """
    from modules.conversation import state_store

    st = SessionState({"k": 1}, scope_id="s")

    calls: list = []

    async def _record(*a, **kw):
        calls.append((a, kw))
        return {}

    with (
        patch.object(state_store, "load_states", _record),
        patch.object(state_store, "save_states", _record),
    ):
        assert await state_store.hydrate_state(st, owner_id=None, thread_id="t") is False
        assert await state_store.hydrate_state(st, owner_id="o", thread_id=None) is False
        assert await state_store.hydrate_state(st, owner_id="", thread_id="") is False
        assert (
            await state_store.persist_state(st, owner_id=None, thread_id="t") is False
        )
        assert (
            await state_store.persist_state(st, owner_id="o", thread_id=None) is False
        )

    assert calls == [], f"缺身份却去查/写库了：{calls}"


async def test_persist_failure_does_not_raise_and_keeps_dirty():
    """★★★ 落盘在**回答已生成完**的出口。

    在那里抛异常等于把一次成功的回答换成 500 —— 用户丢的是**回答**，
    而不是状态。所以吞掉异常 + warning，且**不清赃标记**（下次重试）。
    """
    from modules.conversation import state_store

    st = SessionState(scope_id="s")
    st["k"] = 1

    async def _fail(*a, **kw):
        raise RuntimeError("db down")

    with patch.object(state_store, "save_states", _fail):
        ok = await state_store.persist_state(st, owner_id="o", thread_id="t")

    assert ok is False
    assert st.is_dirty, "落盘失败却清了脏标记 ⇒ 这笔改动永远不会被写出去（且不报错）"
    assert st.pending_writes() == {"k": 1}


async def test_persist_clears_only_what_it_actually_wrote():
    """★★★ 落盘期间进来的改动不得被一起清掉。

    这条与 `test_mark_persisted_clears_only_the_keys_it_wrote` **不是重复**：
    那条钉的是容器 API 语义，本条钉的是**持久层有没有正确使用它**
    （`persist_state` 里传的是 `writes.keys()` 还是「全部」）。
    """
    from modules.conversation import state_store

    st = SessionState(scope_id="s")
    st["early"] = 1
    seen: dict = {}

    async def _save(*, owner_id, thread_id, session_id=None, writes=None, deletes=()):
        seen["writes"] = dict(writes or {})
        st["late"] = 2  # 模拟 await 期间业务又改了一个键

    with patch.object(state_store, "save_states", _save):
        ok = await state_store.persist_state(st, owner_id="o", thread_id="t")

    assert ok is True
    assert seen["writes"] == {"early": 1}, f"落盘内容不对: {seen}"
    assert st.dirty_keys == frozenset({"late"}), "落盘期间的改动被一起清掉了 ⇒ 永不落盘"


async def test_hydrate_does_not_overwrite_a_dirty_container():
    """★★★ 脏容器不被库里的旧值覆盖。

    内存里还有没落盘的改动 ⇒ 库里的值一定**不比内存新**。覆盖 = 确定性的数据丢失；
    保留内存最差也只是"比库新一点"。★ 注意反面：**干净**容器是照常被覆盖的
    （读到的就是全部），别把这条写成无条件不覆盖。
    """
    from modules.conversation import state_store

    async def _read(*, owner_id, thread_id):
        return {"k": "from-db"}

    dirty = SessionState(scope_id="s")
    dirty["k"] = "in-memory"
    with patch.object(state_store, "load_states", _read):
        got = await state_store.hydrate_state(dirty, owner_id="o", thread_id="t")
    assert got is False, "对脏容器也声称「读了」 ⇒ 调用方会以为内存已被库刷新"
    assert dirty["k"] == "in-memory", "脏容器被库里的旧值覆盖 ⇒ 用户刚补的槽位丢了"

    clean = SessionState(scope_id="s2")
    with patch.object(state_store, "load_states", _read):
        got2 = await state_store.hydrate_state(clean, owner_id="o", thread_id="t")
    assert got2 is True and clean["k"] == "from-db", "干净容器也必须真的被刷新"


async def test_hydrate_read_failure_falls_back_to_empty():
    """读失败 ⇒ 当作「这个会话还没有状态」并**保留**内存内容。

    把一次可用的对话变成错误页，代价远大于「少记一轮槽位」。
    """
    from modules.conversation import state_store

    st = SessionState(scope_id="s")
    st["keep"] = 1
    st.mark_persisted(keys=["keep"])

    async def _fail(*a, **kw):
        raise RuntimeError("db down")

    with patch.object(state_store, "load_states", _fail):
        got = await state_store.hydrate_state(st, owner_id="o", thread_id="t")
    assert got is False
    assert st.get("keep") == 1, "读失败却把内存清空了 —— 比「少读一轮」严重得多"
    assert not st.is_dirty, "读失败不该产出待写增量"


async def test_persist_without_changes_is_a_noop():
    """无改动 ⇒ 不写库、返回 True（不是 False：那不是失败）。"""
    from modules.conversation import state_store

    st = SessionState(scope_id="s")
    calls: list = []

    async def _save(*a, **kw):  # pragma: no cover - 被调用即失败
        calls.append(kw)

    with patch.object(state_store, "save_states", _save):
        assert await state_store.persist_state(st, owner_id="o", thread_id="t") is True
    assert calls == [], "无改动却去写库 ⇒ 每个请求白写一次"


def test_owner_id_is_part_of_the_query_condition():
    """★★★ `owner_id` 必须进 `where`，不是返回值里的一件装饰品。

    只按 `thread_id` 查 = 「谁拿到会话键谁就能读」；同一条也适用于**删除**
    （否则越权方能把别人的槽位删掉）。这里用 AST 钉住，不看源码字符串。
    """
    tree = _tree(STORE_PY)
    for fn_name in ("load_states", "save_states"):
        fns = _funcdefs(tree, fn_name)
        assert len(fns) == 1, f"{fn_name} 定义数不为 1（{len(fns)}）"
        operands = _cmp_operands(fns[0])
        assert "AgentSessionStateRecord.owner_id" in operands, (
            f"{fn_name} 里没有 `AgentSessionStateRecord.owner_id == ...` 的比较 "
            f"⇒ 归属没有参与过滤（实际取到 {sorted(operands)}）"
        )


def test_upsert_constraint_name_matches_the_model():
    """★ upsert 的冲突目标必须**真的**是表上的约束名。

    写成常量本是为了「改名时只有一处」，但常量与模型之间仍可能脱节 ——
    那时第一次落盘会抛「没有匹配的约束」，而那时离改名已经很久了。
    """
    from modules.conversation import state_store
    from modules.conversation.db_model import AgentSessionStateRecord

    names = {c.name for c in AgentSessionStateRecord.__table__.constraints}
    assert state_store._UPSERT_CONSTRAINT in names, (
        f"upsert 冲突目标 `{state_store._UPSERT_CONSTRAINT}` 不是表上的约束"
        f"（实际有 {sorted(n for n in names if n)}）"
    )
    assert "uq_agent_session_state_thread_key" in names


def test_json_safe_round_trips_to_native_json_types():
    """`payload` 直接进 `JSON` 列 ⇒ 必须**一定能**被序列化。

    若某个值是 datetime / numpy 标量，序列化会在**落盘时**抛 ——
    而落盘在出口，那里抛等于把一次成功的回答换成 500。
    """
    from modules.conversation.state_store import _json_safe

    class _Odd:
        def __str__(self):  # noqa: D105
            return "ODD"

    out = _json_safe(
        {
            "t": datetime(2026, 9, 18, 1, 2, 3),
            "odd": _Odd(),
            "n": 1,
            "f": 1.5,
            "b": True,
            "z": None,
            "l": [1, "a"],
            "d": {"k": "v"},
        }
    )
    assert type(out["t"]) is str and "2026-09-18" in out["t"]
    assert out["odd"] == "ODD", "不认识的类型必须降级成 str 而不是抛"
    # 往返一次才是「纯 JSON 类型」——只 dumps 的话仍可能是 numpy 标量
    assert json.loads(json.dumps(out)) == out
    assert out["b"] is True and out["z"] is None and out["n"] == 1


def test_facade_exports_resolve_to_the_state_store_functions():
    """跨模块只能从门面取；门面里那两个名字必须**就是**真源函数。

    （「名字在 `__all__` 里」由 `test_module_facades.py` 通用门禁负责，
    本条只钉「指的是不是真源」——判据不同，不是重复。）
    """
    import modules.conversation as pkg
    from modules.conversation import state_store

    assert {"hydrate_state", "persist_state"} <= set(pkg.__all__)
    assert pkg.hydrate_state is state_store.hydrate_state
    assert pkg.persist_state is state_store.persist_state


# ============================================ C 组 · 接线形态门禁（AST）
def test_session_state_attribute_is_gone_and_registry_is_in():
    """旧属性 `self._session_state`（无界 dict）必须消失，换成注册表。

    ★ 必须用 AST 而不是 grep：文件里**注释**多处提到这个名字（迁移说明），
    字符串搜索会把它们算成"还在用" ⇒ 探针自己假红。
    """
    tree = _tree(AGENT_PY)
    attrs = [
        n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)
    ]
    assert attrs.count("_session_state") == 0, (
        "仍有 `self._session_state` 属性访问 —— 无界 dict 回来了"
    )
    assert attrs.count("_session_states") >= 1, "注册表属性不见了"


def test_entry_and_impl_each_defined_exactly_once():
    """★ 入口 / 实现体各恰定义 **1** 次。

    这条是**事故驱动**的：改造脚本的幂等守卫写成「`old` 是否还在」，
    而追加块的 `new` 以 `old` 为前缀 ⇒ 守卫恒假 ⇒ 第二次运行把
    `invoke` / `_invoke_impl` 各插了一遍（文件涨到 124842 B）。
    重复定义不会报错（后一个覆盖前一个），只会让「入口包了一层」的
    那层静默消失 —— 于是 hydrate/flush 全都不执行。
    """
    tree = _tree(AGENT_PY)
    for name in (
        "invoke",
        "_invoke_impl",
        "stream_chat",
        "_stream_chat_impl",
        "_state_scope",
        "_state_key",
        "_session",
        "_hydrate_state",
        "_flush_state",
        "_bind_context",
    ):
        assert len(_funcdefs(tree, name)) == 1, (
            f"{name} 定义了 {len(_funcdefs(tree, name))} 次 —— 入口/实现体被重复插入"
        )


def test_resolve_thread_id_has_exactly_one_call_site_in_business_code():
    """★★★ 作用域口径**唯一**：业务侧只有 `_state_scope` 能调 `resolve_thread_id`。

    两处各算一份键 ⇒ 状态与 checkpoint 描述"同一个会话"却键不同 ⇒
    「历史还在、槽位没了」，两边都不报错。第 138 轮的 `X-Shop-ID` 事故
    正是"同一概念两套 ID 空间"。

    ★ 用 AST：`base_agent.py` 里对它的**注释**、`test_agent_session_memory.py`
    里对它的调用都不在 `modules/` 下，不会误伤。
    """
    hits: list[tuple[str, str, int]] = []
    for f in _module_files(MODULES):
        tree = _tree(f)
        for fn_name, call in _enclosing_calls(tree):
            if isinstance(call.func, ast.Attribute) and call.func.attr == "resolve_thread_id":
                hits.append((f.relative_to(BACKEND).as_posix(), fn_name, call.lineno))

    assert len(hits) == 1, (
        f"业务侧 `resolve_thread_id` 调用点应恰有 1 处，实际 {len(hits)} 处：{hits}"
    )
    assert hits[0][1] == "_state_scope", (
        f"唯一调用点不在 `_state_scope` 里，而在 `{hits[0][1]}` —— 作用域有两份口径"
    )


def test_state_key_derives_from_state_scope_only():
    """★★★ 「算作用域」只允许发生在 `_state_scope`。

    `_state_key`（落盘键）与 `_session`（取容器）都必须经 `_state_scope`；
    `_hydrate_state` / `_flush_state` 必须经 `_state_key`。
    ⇒ 四处**不可能**分叉。
    """
    tree = _tree(AGENT_PY)

    for name in ("_session", "_state_key"):
        fn = _funcdefs(tree, name)[0]
        assert _attr_calls(fn, "_state_scope"), (
            f"{name} 没有经 `_state_scope()` 取作用域 —— 自己拼了一份键"
        )

    for name in ("_hydrate_state", "_flush_state"):
        fn = _funcdefs(tree, name)[0]
        assert _attr_calls(fn, "_state_key"), f"{name} 没有经 `_state_key()` 取键"
        assert not _attr_calls(fn, "_state_scope"), (
            f"{name} 绕过 `_state_key` 直接取作用域 ⇒ 落盘键与内存作用域可能不同源"
        )


def test_state_scope_takes_no_user_id_argument():
    """★★★ `_state_scope` **只读 ContextVar**，不接受 `user_id` 入参。

    入参（本方法的）与 ContextVar 是**两个真源**：测试把 `_bind_context` 换掉、
    或某条路径漏调时，两者就会分叉（hydrate 读 A、业务写 B）——
    而那种错**不报错、只丢状态**。
    """
    tree = _tree(AGENT_PY)
    for name in ("_state_scope", "_state_key", "_session"):
        fn = _funcdefs(tree, name)[0]
        args = [a.arg for a in list(fn.args.args) + list(fn.args.kwonlyargs)]
        assert "user_id" not in args, (
            f"{name} 接了 `user_id` 形参 ⇒ 作用域有两个真源（入参 / ContextVar）"
        )

    names = {n.id for n in ast.walk(_funcdefs(tree, "_state_scope")[0]) if isinstance(n, ast.Name)}
    assert "_current_user_id" in names, "`_state_scope` 没读那个唯一的身份 ContextVar"


def test_invoke_is_bind_hydrate_try_finally_flush():
    """★ 入口形态：绑上下文 → 入口 hydrate → `try/finally` flush → 委托实现体。

    ★ 为什么必须是 `try/finally` 而不是在实现体每个 return 前补一行：
      实现体里有 5 个 return，逐个补等于给自己留一个
      「以后新增 return 就忘了 flush」的坑。
    """
    tree = _tree(AGENT_PY)
    fn = _funcdefs(tree, "invoke")[0]

    binds = _attr_calls(fn, "_bind_context")
    hydrates = _attr_calls(fn, "_hydrate_state")
    assert binds and hydrates, "入口缺 `_bind_context` 或 `_hydrate_state`"
    assert binds[0].lineno < hydrates[0].lineno, "必须先绑上下文再 hydrate（否则身份读不到）"

    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert len(tries) == 1, f"入口的 try 语句应有 1 个，实际 {len(tries)}"
    t = tries[0]
    assert t.lineno > hydrates[0].lineno, "try 必须在 hydrate 之后才开（hydrate 失败也该正常报错）"
    assert _attr_calls(t, "_flush_state"), "`finally` 里没有 flush ⇒ 出口落盘被漏掉"
    assert _attr_calls(t, "_invoke_impl"), "try 体内没有委托 `_invoke_impl`"
    assert _attr_calls(ast.Module(body=t.finalbody, type_ignores=[]), "_flush_state"), (
        "flush 不在 `finally` 段里 ⇒ 有 return 的路径会漏"
    )


def test_stream_chat_is_bind_hydrate_try_finally_flush():
    """流式入口与同步入口**同一形态** —— 流式与否只是输出形式，不是两套生命周期。"""
    tree = _tree(AGENT_PY)
    fn = _funcdefs(tree, "stream_chat")[0]

    assert _attr_calls(fn, "_bind_context"), "流式入口没绑上下文"
    hydrates = _attr_calls(fn, "_hydrate_state")
    assert hydrates, "流式入口没 hydrate"
    tries = [n for n in ast.walk(fn) if isinstance(n, ast.Try)]
    assert len(tries) == 1
    t = tries[0]
    assert _attr_calls(t, "_stream_chat_impl"), "try 体内没有委托 `_stream_chat_impl`"
    assert _attr_calls(ast.Module(body=t.finalbody, type_ignores=[]), "_flush_state"), (
        "流式入口的 flush 不在 `finally` 里 ⇒ 消费者中途断开时状态不落盘"
    )


def test_impl_bodies_do_not_rebind_context():
    """★ 实现体里**不得**再 `_bind_context`。

    重复绑定一旦少传一个参数，就会把 ContextVar 覆盖成 `None`
    （作用域随之漂移，而症状只是「槽位又不见了」）。
    """
    tree = _tree(AGENT_PY)
    for name in ("_invoke_impl", "_stream_chat_impl"):
        fn = _funcdefs(tree, name)[0]
        assert not _attr_calls(fn, "_bind_context"), (
            f"{name} 里又绑了一次上下文 —— 少传参数就会把 ContextVar 覆盖成 None"
        )


def test_hydrate_flushes_before_reading():
    """★ 入口「先补写、再读」的顺序由 AST 钉住。

    hydrate 对脏容器不覆盖 ⇒ 若不先补写，这次请求就一直拿着内存那份，
    库里那份（更早的）永远回不来，而那笔改动也永远不出门。
    """
    tree = _tree(AGENT_PY)
    fn = _funcdefs(tree, "_hydrate_state")[0]
    flush_calls = _attr_calls(fn, "_flush_state")
    read_calls = [
        n
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "_hydrate_session_state"
    ]
    assert flush_calls and read_calls, "入口缺少补写或读取"
    assert flush_calls[0].lineno < read_calls[0].lineno, (
        "入口先读后补写 ⇒ 内存里的改动被库里的旧值盖掉（hydrate 不覆盖脏容器，"
        "但库那一份仍然读不进来）"
    )
    # 补写必须是**有条件**的（不脏就别写库）
    ifs = [n for n in ast.walk(fn) if isinstance(n, ast.If)]
    guarded = any(_attr_uses(i.test, "is_dirty") for i in ifs)
    assert guarded, "补写没有 `is_dirty` 守卫 ⇒ 每个请求都白写一次库"


def test_bind_context_writes_all_three_contextvars():
    """`_bind_context` 必须写满三个 ContextVar（含身份）。

    漏传 `user_id` 的后果不是「少记一点」，而是状态落到**另一个作用域**下。
    """
    tree = _tree(AGENT_PY)
    fn = _funcdefs(tree, "_bind_context")[0]
    used = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    for var in ("_current_context_id", "_current_shop_id", "_current_user_id"):
        assert var in used, f"`_bind_context` 没有写 {var}"
    args = [a.arg for a in fn.args.args]
    assert args == ["context_id", "shop_id", "user_id"], (
        f"`_bind_context` 形参变了：{args} —— 调用点按位置传参，顺序即契约"
    )


def test_resume_approval_rebinds_identity_and_hydrates():
    """★ 续跑审批前必须重新绑定**身份**并 hydrate。

    被中断的工具会**重新执行**，而它靠 ContextVar 拿会话与归属。
    漏 `user_id` ⇒ 它在另一个作用域里找会话状态（「第 1 个」解析不出来）。
    """
    tree = _tree(AGENT_PY)
    fn = _funcdefs(tree, "resume_approval")[0]

    binds = _attr_calls(fn, "_bind_context")
    assert binds, "`resume_approval` 没有重新绑定上下文 ⇒ 被中断的工具拿不到归属"
    call = binds[0]
    passed = [getattr(a, "id", None) for a in call.args] + [
        kw.arg for kw in call.keywords
    ]
    assert len(passed) == 3 and "user_id" in passed, (
        f"`_bind_context` 的实参不完整：{passed} —— 必须带上身份"
    )
    assert _attr_calls(fn, "_hydrate_state"), "`resume_approval` 没有 hydrate 会话状态"


def test_state_module_line_endings_stay_lf():
    """`ai_infra/` 全仓 LF-only 口径（该目录是机制层，跨平台共用）。"""
    assert STATE_PY.exists(), "会话状态机制层文件不见了"
    assert STATE_PY.read_bytes().count(b"\r\n") == 0, "ai_infra 的 LF-only 口径被破坏"


# ============================================ D 组 · 行为（打桩存储层）
def test_state_scope_has_three_tiers():
    """★ `_state_scope` 三档：有身份 ⇒ thread_id 口径；只会话 ⇒ 裸 session_id；
    无会话 ⇒ 默认作用域。

    ★ 期望值不手写：第二档直接与 `resolve_thread_id()` 比对（那才是真源）。
    """
    a = _agent()
    with _as_user(None):
        assert a._state_scope(None) == "_default"
        assert a._state_scope("") == "_default"
        assert a._state_scope("s1") == "s1", "只有会话时不得伪造身份段"
    with _as_user("u1"):
        assert a._state_scope("s1") == a.resolve_thread_id("s1", "u1"), (
            "有身份时没走 `resolve_thread_id` ⇒ 状态与 checkpoint 键不同源"
        )
        assert "u1" in a._state_scope("s1") and a._state_scope("s1").endswith("s1")


def test_state_key_marks_what_is_persistable():
    """落盘键为 `None` ⇔ 本次**不该**落库（无身份 / 无会话）。"""
    a = _agent()
    with _as_user("u1"):
        scope, thread = a._state_key("s1")
        assert scope == a._state_scope("s1") and thread == scope, "落盘键与内存作用域不同源"
        assert a._state_key(None)[1] is None, "无会话却给了落盘键"
    with _as_user(None):
        assert a._state_key("s1")[1] is None, "无身份却给了落盘键"


async def test_hydrate_and_persist_share_the_business_container():
    """★★★ hydrate / persist 拿到的必须是**业务写入的那一个容器**。

    这是「作用域无分叉」的最终判据：若 hydrate 用入参算键、`_session()` 用
    ContextVar 算键，两者就会拿到两个容器 —— 而**不报错**，
    表现为 hydrate 读完什么也没变、flush 写完什么也没写。
    """
    a = _agent()
    seen: dict = {}

    async def _hydrate(state, *, owner_id, thread_id):
        seen["hydrate"] = (state, owner_id, thread_id)
        return False

    async def _persist(state, *, owner_id, thread_id, session_id=None):
        seen["persist"] = (state, owner_id, thread_id, session_id)
        return True

    with _as_user("u1"), _patch_store(hydrate=_hydrate, persist=_persist):
        business = a._session("s-1")
        await a._hydrate_state("s-1")
        business["last_blue_ocean"] = {"products": [{"title": "X"}]}
        await a._flush_state("s-1")

    assert seen["hydrate"][0] is business, "hydrate 拿到的不是业务那个容器"
    assert seen["persist"][0] is business, "persist 拿到的不是业务那个容器"
    assert seen["hydrate"][0] is seen["persist"][0]
    assert seen["hydrate"][1] == "u1" and seen["persist"][1] == "u1", "身份没传下去"
    assert seen["persist"][3] == "s-1", "session_id 没传下去（排查/清理时定位不到）"


async def test_no_identity_means_no_write_on_exit():
    """★ 无身份 ⇒ 出口零写。"""
    a = _agent()
    writes: list = []

    async def _persist(*a_, **kw):
        writes.append(kw)
        return True

    async def _hydrate(state, *, owner_id, thread_id):
        assert thread_id is None, "无身份却算出了落盘键 ⇒ 真实实现会去查库"
        return False

    with _as_user(None), _patch_store(hydrate=_hydrate, persist=_persist):
        a._session("s-1")["k"] = 1
        await a._hydrate_state("s-1")
        await a._flush_state("s-1")
    assert writes == [], "无身份却去落库"


async def test_same_session_id_under_two_identities_are_two_states():
    """★ 同一 `session_id` 在两个身份下必须是**两份**状态。

    否则「把第 1 个加进选品库」可能拿别人的上一轮结果去解析指代。
    """
    a = _agent()
    with _as_user("uA"):
        a._session("shared")["marker"] = "A"
    with _as_user("uB"):
        assert a._session("shared").get("marker") is None, (
            "两个身份共用了同一份状态 ⇒ 指代解析会串人"
        )
        a._session("shared")["marker"] = "B"
    with _as_user("uA"):
        assert a._session("shared")["marker"] == "A"


async def test_entry_flushes_then_hydrates_and_skips_write_when_clean():
    """★★★ 入口两条行为，缺一不可：
      ① 脏 ⇒ **先补写再读**（否则那笔改动永远出不了门）；
      ② 不脏 ⇒ **零多余写库**（否则每个请求白写一次）。
    """
    a = _agent()
    order: list[str] = []

    async def _persist(state, *, owner_id, thread_id, session_id=None):
        keys = sorted(state.pending_writes())
        order.append("persist:" + ",".join(keys))
        state.mark_persisted(keys=keys, deleted=state.deleted_keys)
        return True

    async def _hydrate(state, *, owner_id, thread_id):
        order.append("hydrate")
        return True

    with _as_user("u1"), _patch_store(hydrate=_hydrate, persist=_persist):
        a._session("s-1")["pending_save"] = {"kind": "save"}
        await a._hydrate_state("s-1")
        assert order == ["persist:pending_save", "hydrate"], (
            f"入口没有先补写再读：{order}"
        )

        order.clear()
        await a._hydrate_state("s-1")
        assert order == ["hydrate"], f"容器已干净却仍写库：{order}"


async def test_stream_chat_flushes_on_exit():
    """★ 流式出口也落盘（`finally` 真的生效）。

    用真 `stream_chat` 走一遍，实现体换成桩 —— 判据是「flush 被调到、
    且带上本轮改动」，不是「实现体做了什么」。
    """
    from modules.product_research import agent_product_research as mod

    a = _agent()
    flushed: list = []

    async def _persist(state, *, owner_id, thread_id, session_id=None):
        flushed.append(dict(state.pending_writes()))
        state.mark_persisted(keys=list(state.pending_writes()))
        return True

    async def _hydrate(state, *, owner_id, thread_id):
        return False

    async def _impl(*args, **kwargs):
        a._session("s-1")["last_blue_ocean"] = {"products": [{"title": "X"}]}
        yield "chunk"

    with _as_user("u1"), _patch_store(hydrate=_hydrate, persist=_persist):
        with patch.object(mod.ProductResearchAgent, "_stream_chat_impl", _impl):
            out = [c async for c in a.stream_chat("q", "s-1", None, "u1")]

    assert out == ["chunk"], "流式输出被改造破坏"
    assert flushed == [{"last_blue_ocean": {"products": [{"title": "X"}]}}], (
        f"流式出口没有落盘 / 落盘内容不对：{flushed}"
    )


async def test_invoke_flushes_even_when_impl_raises():
    """★ 实现体抛异常时也必须落盘（`finally` 的语义），且异常照常向上抛。

    这正是「不能在每个 return 前补一行 flush」的理由。
    """
    from modules.product_research import agent_product_research as mod

    a = _agent()
    flushed: list = []

    async def _persist(state, *, owner_id, thread_id, session_id=None):
        flushed.append(dict(state.pending_writes()))
        state.mark_persisted(keys=list(state.pending_writes()))
        return True

    async def _hydrate(state, *, owner_id, thread_id):
        return False

    async def _impl(*args, **kwargs):
        a._session("s-1")["pending_save"] = {"kind": "save"}
        raise RuntimeError("boom")

    with _as_user("u1"), _patch_store(hydrate=_hydrate, persist=_persist):
        with patch.object(mod.ProductResearchAgent, "_invoke_impl", _impl):
            with pytest.raises(RuntimeError):
                await a.invoke("q", "s-1", None, "u1")

    assert flushed == [{"pending_save": {"kind": "save"}}], (
        f"异常路径漏了落盘：{flushed}"
    )


async def test_flush_swallows_generator_close_errors():
    """★ 出口再包一层 try/except：生成器被关闭时 `finally` 里的 await
    可能抛 `RuntimeError`（事件循环正在关）。

    那不该从 `finally` 里冒出来把一次**已经生成完**的回答变成错误页。
    """
    from modules.product_research import agent_product_research as mod

    a = _agent()

    async def _boom(*args, **kwargs):
        raise RuntimeError("Event loop is closed")

    with _as_user("u1"), patch.object(mod, "_persist_session_state", _boom):
        a._session("s-1")["k"] = 1
        await a._flush_state("s-1")  # 不得抛


def test_state_module_has_no_business_keys():
    """机制层不得认识业务键名（反过来它就该跟业务一起改了）。

    ★ 用 AST 判**字符串字面量**：文档里提到 `pending_save` 是为了说明用途，
    不算耦合；真正耦合的是代码里出现 `"pending_save"` 这样的字面量。
    """
    tree = _tree(STATE_PY)
    lits = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    leaked = {s for s in lits if s in {"last_blue_ocean", "pending_save"}}
    assert not leaked, f"机制层出现了业务键名：{sorted(leaked)}"


# ============================================ E 组 · 端到端（真 PG）
async def test_real_pg_roundtrip_upsert_delete_and_ownership():
    """★★★ 端到端（真 PG）：往返 / upsert 幂等 / 删除 / **归属隔离**。

    上面那些都只证明「参数传对了」，证明不了 SQL 真的按预期跑。这里必须真跑。

    其中两条是**越权**判据（反向注入删掉 `where` 里的 `owner_id` 立刻转红）：
      · 另一个 owner 读同一个 `thread_id` ⇒ 必须读不到；
      · 另一个 owner 删同一个键 ⇒ 必须删不掉。
    """
    from sqlalchemy import text

    from core.database import get_async_session
    from modules.conversation import state_store

    tag = uuid.uuid4().hex[:10]
    owner_a = f"pytest-sst-a-{tag}"
    owner_b = f"pytest-sst-b-{tag}"
    thread_a = f"pytest-sst:{owner_a}:{tag}"
    thread_b = f"pytest-sst:{owner_b}:{tag}"
    owners = [owner_a, owner_b]

    async def _purge():
        async with get_async_session() as db:
            await db.execute(
                text(f"DELETE FROM {_TABLE} WHERE owner_id = ANY(:ids)"), {"ids": owners}
            )

    await _purge()
    try:
        # ① 往返
        st = SessionState(scope_id=thread_a)
        st["k"] = {"v": 1}
        st["other"] = "lo"
        assert await state_store.persist_state(
            st, owner_id=owner_a, thread_id=thread_a, session_id="sess-1"
        ) is True
        assert not st.is_dirty, "落盘成功后脏标记没清 ⇒ 下次会重复写"

        got = await state_store.load_states(owner_id=owner_a, thread_id=thread_a)
        assert got == {"k": {"v": 1}, "other": "lo"}, f"往返不一致: {got}"

        # ② upsert 幂等（同键再写 ⇒ 仍只有一行，值是后者）
        st["k"] = {"v": 2}
        assert await state_store.persist_state(
            st, owner_id=owner_a, thread_id=thread_a, session_id="sess-1"
        ) is True
        async with get_async_session() as db:
            rows = (
                await db.execute(
                    text(
                        f"SELECT state_key, payload, updated_at FROM {_TABLE}"
                        " WHERE owner_id = :o AND thread_id = :t"
                    ),
                    {"o": owner_a, "t": thread_a},
                )
            ).all()
        by_key = {r[0]: r[1] for r in rows}
        assert len(rows) == 2, f"upsert 没去重，出现重复行: {rows}"
        assert by_key["k"] == {"v": 2}, f"upsert 没有更新 payload: {by_key}"
        # ★ `updated_at` 没有 server_default，靠 Python 端 default ——
        #   Core insert 若不带上它，这里会因为 NOT NULL 直接失败。
        assert all(r[2] is not None for r in rows), "updated_at 为空 ⇒ 默认值没被应用"

        # ③ 归属隔离（读）：另一个 owner 用同一 thread_id 必须读不到
        await state_store.save_states(
            owner_id=owner_b,
            thread_id=thread_b,
            session_id="sess-2",
            writes={"k": {"v": "B"}},
        )
        assert await state_store.load_states(owner_id=owner_b, thread_id=thread_a) == {}, (
            "另一个 owner 读到了别人的会话状态 ⇒ `where` 里没有 owner_id"
        )
        assert await state_store.load_states(owner_id=owner_a, thread_id=thread_b) == {}

        # ④ 归属隔离（删）：另一个 owner 删不掉别人的键
        #   ★ 必须用**同一个 thread_id**（`thread_a`）而**不是** `thread_b`：
        #     若用 thread_b，删不掉只是因为 thread 不匹配，与 owner 过滤毫无关系
        #     —— 这条判据会恒真。反向注入 RI-07 实测：第一版就是这么写的，
        #     把 owner 过滤整个去掉**照样绿**。
        await state_store.save_states(
            owner_id=owner_b,
            thread_id=thread_a,
            session_id="sess-2",
            writes={},
            deletes=["k"],
        )
        assert (
            await state_store.load_states(owner_id=owner_a, thread_id=thread_a)
        ).get("k") == {"v": 2}, "另一个 owner 把别人的键删了 ⇒ delete 的 where 缺 owner_id"

        # ⑤ 删除生效（自己的键）
        del st["k"]
        assert await state_store.persist_state(
            st, owner_id=owner_a, thread_id=thread_a, session_id="sess-1"
        ) is True
        assert not st.is_dirty
        left = await state_store.load_states(owner_id=owner_a, thread_id=thread_a)
        assert left == {"other": "lo"}, f"删除没有生效: {left}"
    finally:
        await _purge()


async def test_table_shape_matches_the_contract():
    """表结构（真库）：列齐、`owner_id` NOT NULL、唯一约束在、**刻意无 shop_id**。

    ★ 为什么连「没有 shop_id」也断言：`test_schema_parity.py` 的不变量是
      「凡有 `shop_id` 列的表，必须有指向 `stores_store` 的外键」。本表按会话
      （thread）分片，店铺维度不参与判据 —— 不带该列，因此不落入那条约束。
      把这句话钉成断言，免得后人误以为漏建了外键、或反过来"顺手补一个"。
    """
    from sqlalchemy import text

    from core.database import get_async_session

    async with get_async_session() as db:
        cols = (
            await db.execute(
                text(
                    "SELECT column_name, is_nullable FROM information_schema.columns"
                    " WHERE table_schema='public' AND table_name=:t"
                ),
                {"t": _TABLE},
            )
        ).all()
        assert cols, f"{_TABLE} 表不存在 —— 迁移没跑或模型没注册"

        shape = {name: nullable for name, nullable in cols}
        assert set(shape) == {
            "id",
            "owner_id",
            "thread_id",
            "session_id",
            "state_key",
            "payload",
            "updated_at",
        }, f"列集合与契约不符: {sorted(shape)}"
        assert shape["owner_id"] == "NO", "owner_id 可空 ⇒ 归属可能缺失"
        assert "shop_id" not in shape, (
            "本表刻意不带 shop_id（按 thread 分片）；若真要加，须同时补 "
            "shop_id -> stores_store 外键，否则 test_schema_parity 会红"
        )

        cons = (
            await db.execute(
                text(
                    "SELECT contype, conname, pg_get_constraintdef(oid)"
                    " FROM pg_constraint WHERE conrelid = to_regclass(:t)"
                ),
                {"t": _TABLE},
            )
        ).all()
        defs = {name: definition for _kind, name, definition in cons}
        uq = {n: d for n, d in defs.items() if "UNIQUE" in d.upper()}
        assert "uq_agent_session_state_thread_key" in uq, f"唯一约束不见了: {sorted(defs)}"
        target = uq["uq_agent_session_state_thread_key"]
        assert "thread_id" in target and "state_key" in target, (
            f"唯一约束的列不对（它就是 upsert 的冲突目标）: {target}"
        )
