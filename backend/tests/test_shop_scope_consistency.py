"""店秘书店铺工具的作用域一致性门禁（第 239 轮）

==============================================================================
钉住什么
==============================================================================
一条判据：**LLM 工具链（`_list_shops`）与列表端点（`/api/v1/stores`）
必须是同一份归属口径**。

为什么需要独立门禁（而不是靠 `test_stores.py` 那条顺序测试）：
那条测试此前写着「两边可能因 owner 过滤差异而子集不同」，用
`set(api_ids) <= set(tool_ids)` 把差异绕过去 —— 而「工具读全表」时
该断言**恒真**。缺陷因此躺了一整轮：UI 显示 4 家店、对话回答 9 家，
模型还在为这个错误输入编了一段「演示模式只有 1–2 家可用」的幻觉。

==============================================================================
三层判据（缺一层就有一类缺陷测不到）
==============================================================================
① 行为层：同一身份下两边**集合相等**（不是子集、不是包含）。
② 隔离层：**两个主体**互不可见 —— 单个主体证明不了隔离
   （「库恰好只有你的店」也能让断言为真 ⇒ 没有反例的断言 = 没有断言）。
③ 形态层：`_list_shops` 函数体内**真的调用了** `filter_accessible_stores`。
   ★ 走 AST，**不碰源码字符串**：该函数体的注释里就写着这个名字，
     字符串包含判据会假绿（本仓已踩过：docstring 骗过源码串断言）。
"""

import ast
import inspect
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

pytestmark = pytest.mark.tenant_identity


# ====== 夹具 ======

@pytest_asyncio.fixture
async def owned():
    """建店登记 + teardown 清理（内存读缓存与 PG 权威行都要清）。"""
    ids: list[str] = []
    yield ids
    if not ids:
        return
    from core.database import async_session_factory
    from core.stores import StoreRecord
    from modules.stores.router import _store_db

    async with async_session_factory() as session:
        for sid in ids:
            _store_db.pop(sid, None)
            await session.execute(delete(StoreRecord).where(StoreRecord.id == sid))
        await session.commit()


async def _mk_store(client, ids: list[str], headers: dict) -> dict:
    """建一家店挂在 `headers` 对应的身份下，并登记 id 供清理。"""
    payload = {"name": f"scope-{uuid.uuid4().hex[:6]}", "platform": "amazon_us"}
    r = await client.post("/api/v1/stores", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    ids.append(r.json()["id"])
    return r.json()


async def _tool_ids_under(user_id: str) -> list[str]:
    """在**指定身份**下调用 LLM 侧工具，返回店铺 id 序列。

    ★ 身份只能这样注入（服务端上下文），工具签名里**没有**身份入参 ——
      这是设计约束，不是遗漏：入参可被提示注入伪造。
    """
    from core.observability.context import clear_request_context, set_request_context
    from modules.secretary.shop_tools import _list_shops

    set_request_context(user_id=user_id)
    try:
        shops = await _list_shops()
    finally:
        # ★ 必须清：ContextVar 会跨用例残留（keep-alive 污染）
        clear_request_context()
    return [s["id"] for s in shops]


# ====== ① + ② 行为层 / 隔离层 ======

async def test_tool_scope_equals_api_scope_and_isolates_tenants(
    client, auth_off, make_user, owned
):
    """★ 核心门禁：同一身份下工具==端点；**两个主体**互相看不见。

    这是「修好了」的判据：不是看源码里有没有那行过滤，
    而是看**输出**在两个不同身份下是否真的分叉。
    """
    a = await make_user("scope-a")
    b = await make_user("scope-b")
    assert a["user_id"] != b["user_id"]

    for _ in range(2):
        await _mk_store(client, owned, a["headers"])
    b_store = await _mk_store(client, owned, b["headers"])

    # A 的端点视角
    ra = await client.get("/api/v1/stores", headers=a["headers"])
    assert ra.status_code == 200, ra.text
    api_a = [s["id"] for s in ra.json()["stores"]]

    # B 的端点视角
    rb = await client.get("/api/v1/stores", headers=b["headers"])
    assert rb.status_code == 200, rb.text
    api_b = [s["id"] for s in rb.json()["stores"]]

    # 两个主体各自恰好 2 / 1 家（防「空集合使下面的相等断言真空通过」）
    assert len(api_a) == 2, f"A 的端点视角应恰好 2 家，实得 {api_a}"
    assert len(api_b) == 1, f"B 的端点视角应恰好 1 家，实得 {api_b}"

    tool_a = await _tool_ids_under(a["user_id"])
    tool_b = await _tool_ids_under(b["user_id"])

    # ① 同一身份下：工具与端点必须给出**同一个集合**（而不是子集）
    assert set(tool_a) == set(api_a), (
        "A 身份下工具与端点的店铺集合不一致 —— 归属口径分叉\n"
        "  api  多出 = %s\n  tool 多出 = %s"
        % (sorted(set(api_a) - set(tool_a)), sorted(set(tool_a) - set(api_a)))
    )
    assert set(tool_b) == set(api_b), (
        "B 身份下工具与端点的店铺集合不一致 —— 归属口径分叉\n"
        "  api  多出 = %s\n  tool 多出 = %s"
        % (sorted(set(api_b) - set(tool_b)), sorted(set(tool_b) - set(api_b)))
    )

    # ② 隔离：两个主体的可见集必须**不相交**（这条才是反例断言 ——
    #    若工具读全表，A 会在 tool 里看到 B 的店，立刻红）
    assert not (set(tool_a) & set(tool_b)), (
        "两个身份的工具可见集出现交集 —— 跨租户店铺泄漏进 LLM 上下文\n"
        "  交集 = %s" % sorted(set(tool_a) & set(tool_b))
    )
    assert b_store["id"] not in tool_a, "B 的店铺出现在了 A 的工具输出里"
    assert not any(i in api_a for i in (b_store["id"],)), "B 的店铺出现在了 A 的端点输出里"


async def test_tool_scope_denies_other_tenant_store(client, auth_off, make_user, owned):
    """最小反例：B 建店、A 调工具 —— A 必须**看不到**它。

    与上一条的区别：这里 A 自己**一家店都没有**，
    于是「A 的输出为空」是唯一正确结果，任何泄漏都逃不掉。
    """
    a = await make_user("scope-empty")
    b = await make_user("scope-has-one")
    s = await _mk_store(client, owned, b["headers"])

    tool_a = await _tool_ids_under(a["user_id"])
    assert s["id"] not in tool_a, (
        "A（无任何店铺）竟然看到了 B 的店铺 —— 工具未按归属过滤\n"
        "  A 看到 = %s" % tool_a
    )


async def test_tool_scope_without_identity_only_sees_demo_stores(auth_off):
    """无身份（演示档）时走**演示窄口**：只见 `is_demo` 行，真实店铺仍不可见。

    ★ 这条钉的是「安全失败方向」：上下文里的 user_id 缺失/失效时，
      工具**不能**退回读全表。判据与 `filter_accessible_stores` 同源 ——
      这里独立算一遍，防的正是「哪天有人给 `_list_shops` 加个 `if not uid: 读全表`」。
    """
    from core.auth.accounts import filter_accessible_stores
    from core.database import async_session_factory
    from core.observability.context import clear_request_context
    from core.stores import StoreRecord, SHOP_ORDER_BY
    from sqlalchemy import select as _select
    from modules.secretary.shop_tools import _list_shops

    clear_request_context()
    tool_ids = [s["id"] for s in await _list_shops()]
    clear_request_context()

    async with async_session_factory() as db:
        order = [getattr(StoreRecord, k) for k in SHOP_ORDER_BY]
        rows = (await db.execute(_select(StoreRecord).order_by(*order))).scalars().all()
        expect = [s.id for s in await filter_accessible_stores(db, None, list(rows))]

    assert tool_ids == expect, (
        "无身份时工具的可见集与 `filter_accessible_stores(user=None)` 不一致\n"
        "  tool   = %s\n  expect = %s" % (tool_ids, expect)
    )
    leaked = [s.id for s in rows if (not getattr(s, "is_demo", False)) and s.id in tool_ids]
    assert not leaked, "无身份时看到了**非演示**店铺 —— 演示窄口被绕过：%s" % leaked


# ====== ③ 形态层（AST，剥注释）======

def _fn_node(module, name: str):
    """从模块源码解析出指定函数节点。

    ★ 走 `ast.parse`：注释**不在 AST 里** ⇒ 天然免疫
      「注释/docstring 里写了函数名、代码里没调」这类假绿。
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"模块里找不到函数 {name!r}（被改名或删除了？）")


def _calls(fn_node) -> list[tuple[str, int]]:
    """函数体内所有调用的 (被调名, 行号)。属性调用取属性名（`x.filter_...` 也认）。"""
    out: list[tuple[str, int]] = []
    for node in ast.walk(fn_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.append((f.id, node.lineno))
            elif isinstance(f, ast.Attribute):
                out.append((f.attr, node.lineno))
    return out


def test_list_shops_calls_the_shared_scope_filter():
    """★ 接线判据：`_list_shops` **函数体内**真的调用了那份共享过滤。

    ⚠️ 为什么必须钉在**函数体**而不是「文件里出现过」：
      同文件其他地方也能出现这个标识符（import 行！）——
      只判文件级会出现「只是 import 了却没调用」的假绿。
    """
    from modules.secretary import shop_tools

    fn = _fn_node(shop_tools, "_list_shops")
    calls = _calls(fn)
    names = [c[0] for c in calls]

    assert "filter_accessible_stores" in names, (
        "`_list_shops` 函数体内没有调用 `filter_accessible_stores` —— "
        "归属过滤被摘掉了（这会直接把别家店铺喂给 LLM）。调用点：%s" % names
    )
    assert "_resolve_current_user" in names, (
        "`_list_shops` 没有解析请求身份 —— 身份从哪来？"
    )

    # 接线顺序：必须**先选出行、再过滤**（写反 = 过滤了个寂寞）
    sel = [ln for n, ln in calls if n == "select"]
    flt = [ln for n, ln in calls if n == "filter_accessible_stores"]
    assert sel and flt, f"select/filter 调用缺失：select={sel} filter={flt}"
    assert min(sel) < min(flt), (
        "过滤发生在 `select` **之前** —— 说明过滤的对象不是查出来的行："
        "select=%s filter=%s" % (sel, flt)
    )


def test_list_shops_does_not_read_the_table_unfiltered():
    """反向形态判据：`_list_shops` 里**只允许一条**读取路径。

    为什么用「`select` 调用恰好 1 次」这个形态：读全表本身不是缺陷
    （过滤前必须先把它查出来），缺陷是**多出一条**「查了却没过滤」的旁路。
    每多一处 `select` 就多一个需要人工确认的口子，所以把它钉成 1。
    """
    from modules.secretary import shop_tools

    fn = _fn_node(shop_tools, "_list_shops")
    calls = _calls(fn)
    sel_calls = [c for c in calls if c[0] == "select"]
    assert len(sel_calls) == 1, (
        "`_list_shops` 里出现了 %d 处 `select` 调用（期望 1 处）—— "
        "多出来的读取路径需要人工确认是否也过了归属过滤：%s" % (len(sel_calls), sel_calls)
    )
