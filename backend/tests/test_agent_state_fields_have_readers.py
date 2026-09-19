# -*- coding: utf-8 -*-
"""`AgentState` 每个字段都必须有**读它的地方**（第 159 轮 · 批 D3）。

为什么需要这条门禁
==================
`AgentState.metadata` 曾是一个**只写不读**的死字段，而护航它的那条门禁
（原 `test_agent_state_metadata_is_free_form_dict`）只钉
「它是不是自由字典、有没有预置业务键」—— **钉的是形式**。
形式合规 ⇒ 它通过 ⇒ 字段合规地死了下去（全仓 0 处读 `state["metadata"]`）。

同一个病还有第二例：`structured_response` 的生产代码读点长期为 0，
而它携带的 `status`（`completed` / `budget_truncated`）正是 C5 要传给
调用方的结论 ⇒ **调用方拿到的仍然是「看起来成功」的结果**。

⇒ 判据从「形式」改成「**性质**」：字段名（或它的常量别名）必须在
`ai_infra/` + `modules/` 的**生产代码**里被读过。

形态判据一律走 **AST** —— 注释/docstring 会让「源码字符串包含」判据假绿
（本仓已踩多次；并且**本门禁的第一版复核脚本就踩了同一个坑**）。
"""
import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SRC_ROOTS = [BACKEND / "ai_infra", BACKEND / "modules"]

#: 通过常量间接读写 state 的字段：字段名 -> 常量名（常量定义处见 `ai_infra/plan.py`）
INDIRECT = {"todos": "TODOS_STATE_KEY"}


def _state_fields():
    """从 `AgentState` 类体取字段名（不含继承来的 `messages`）。"""
    src = (BACKEND / "ai_infra" / "base_agent.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == "AgentState":
            return sorted(
                st.target.id
                for st in n.body
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name)
            )
    raise AssertionError("未找到 AgentState")


def _readers(field):
    """返回读 `state[field]` / `state.get(field)` 的生产代码位置。"""
    alias = INDIRECT.get(field)
    keys = {field} | ({alias} if alias else set())
    hits = []
    for root in SRC_ROOTS:
        for p in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for n in ast.walk(tree):
                # 形态一：state["x"]
                if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name):
                    sl = n.slice
                    if isinstance(sl, ast.Constant) and sl.value in keys:
                        hits.append((p, n.lineno))
                # 形态二：state.get("x") / state.get(常量)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                        and n.func.attr == "get" and isinstance(n.func.value, ast.Name):
                    for a in n.args:
                        if isinstance(a, ast.Constant) and a.value in keys:
                            hits.append((p, n.lineno))
                        if isinstance(a, ast.Name) and a.id in keys:
                            hits.append((p, n.lineno))
    return hits


def test_agent_state_fields_all_have_readers():
    """每个 `AgentState` 字段都至少有一个读点（否则就是死重量）。"""
    fields = _state_fields()
    print("\n[门禁] AgentState 字段: %s" % fields)
    dead = []
    for f in fields:
        rs = _readers(f)
        print("   %-20s 读点 %2d  %s" % (f, len(rs), rs[:3]))
        if not rs:
            dead.append(f)
    assert not dead, (
        "AgentState 有字段**从没被读过** = 死重量：%s\n"
        "  字段写进 state 却没人读，等于让调用方以为「有这份数据」而实际拿不到。\n"
        "  ⇒ 要么给它接上真消费者（读它并据此改变行为），要么把它删掉。\n"
        "  先例：`AgentState.metadata` 就是这样死掉的（第 159 轮批 D3 已删）。" % dead
    )


def test_budget_truncation_reaches_a_non_infra_consumer():
    """`budget.truncated` 的结论必须传到一个**基础设施层之外**的消费者。

    `_respond_node` 把它写进 `structured_response["status"]`，但那只是「生产」。
    必须有业务侧真的读它 —— 否则 C5 的承诺
    （「把『这次是被预算截断的』变成**调用方读得到**的状态」）只做了一半：
    状态写进去了，调用方却看不到。
    """
    hits = [ln for (p, ln) in _readers("structured_response")
            if "ai_infra" not in p.parts]
    print("\n[门禁] structured_response 的业务侧读点: %s" % hits)
    assert hits, (
        "`structured_response` 在生产代码里**没有业务侧读点** ——\n"
        "  `_respond_node` 写进去的 `status`（是否被预算截断）没有任何调用方读，\n"
        "  于是「被截断」与「正常答完」在调用方看来完全一样。\n"
        "  ⇒ 至少要在业务侧读一次（本轮接的是 secretary 的 `route()`）。"
    )
