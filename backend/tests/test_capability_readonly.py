# -*- coding: utf-8 -*-
"""能力层（P1-1 · A 档只读三原语）的门禁。

## 这一层最容易"看起来对、其实是洞"的三个地方

① **暴露面**：只读靠的是"只收 GET"这条**结构性**判据，不是猜语义。
   判据一旦松（比如允许 POST），`/agents/{agent}/approval/resume` 这类
   推进图的端点就会变成一次普通工具调用。
② **身份**：内部调用会**重新走一遍**鉴权与租户依赖 —— 于是"谁能冒充谁"
   完全由转发头白名单决定。`x-user-id` 之类自报头一旦进了名单，
   能力层就成了"以任意身份读任意租户"的开关，而它长成一次普通工具调用。
③ **`sent` 语义**：本地拦下（缺身份/参数不认识）与"服务端拒绝"必须可区分 ——
   合成一个"失败"，模型会反复重试同一个注定失败的调用。

## 反向注入

`r400m_inject_capability.py`：
  · 把 `BLOCKED_METHODS` 清空 ⇒ 判据 1 红
  · 把 `x-user-id` 加进 `FORWARD_HEADER_ALLOW` ⇒ 判据 6 红
  · 把 `quote(..., safe="")` 改成 `str()` ⇒ 判据 4 红（路径会被值改掉）
  · 把 `no_identity` 检查删掉 ⇒ 判据 5 红（会以匿名身份发请求）
"""
from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, HTTPException

from ai_infra.capability import (
    BLOCKED_METHODS,
    BLOCKED_PREFIXES,
    bind_app,
    build_capability_tools,
    build_catalog,
    call_read,
    catalog,
    find,
    get_capability,
    is_exposed,
    stats,
)
from ai_infra.capability.invoke import _resolve_params
from core.observability.context import (
    FORWARD_HEADER_ALLOW,
    clear_request_context,
    current_forward_headers,
    set_forward_headers,
)

#: 一个**足够像**的假 spec（形状取自 `app.openapi()`，但完全可控）
FAKE_SPEC = {
    "paths": {
        "/api/v1/stores": {
            "get": {
                "operationId": "list_stores",
                "summary": "List Stores",
                "tags": ["stores"],
                "parameters": [
                    {"name": "page", "in": "query", "schema": {"type": "integer"}},
                ],
            },
            "post": {"operationId": "create_store", "summary": "Create Store"},
        },
        "/api/v1/stores/{store_id}": {
            "get": {
                "operationId": "get_store",
                "summary": "Get Store",
                "parameters": [
                    {"name": "store_id", "in": "path", "required": True, "schema": {"type": "string"}},
                ],
            },
            "delete": {"operationId": "delete_store", "summary": "Delete Store"},
        },
        # 下面三条都必须**进不来**
        "/api/v1/orchestrator/chat": {"get": {"operationId": "self_chat", "summary": "Self"}},
        "/api/v1/auth/me": {"get": {"operationId": "me", "summary": "Me"}},
        "/health": {"get": {"operationId": "health", "summary": "Health"}},
        # 没有 operationId 的 op：无法按名字调用 ⇒ 跳过（而不是编一个名字）
        "/api/v1/noop": {"get": {"summary": "No operationId"}},
        # 多方法混排：只收 get
        "/api/v1/mixed": {
            "get": {"operationId": "mixed_get", "summary": "Mixed Get"},
            "put": {"operationId": "mixed_put", "summary": "Mixed Put"},
        },
    }
}


@pytest.fixture()
def fake_binding():
    """临时把全局目录换成 `FAKE_SPEC`，用例结束**必须**恢复成真实应用。"""
    from ai_infra.capability import registry

    saved = dict(registry.catalog())
    saved_app = registry.app_of()
    try:
        bind_app(_FakeApp(FAKE_SPEC))
        yield
    finally:
        registry._catalog = saved          # noqa: SLF001 —— 测试夹具，刻意直接还原
        registry._app = saved_app          # noqa: SLF001


class _FakeApp:
    """只满足 `bind_app()` 需要的两个成员（真实调用走另一个 mini app）。"""

    def __init__(self, spec):
        self._spec = spec

    def openapi(self):
        return self._spec


# ============================================================
# 1. 暴露面：只收 GET + 前缀拒绝
# ============================================================


def test_catalog_is_get_only_and_blocks_prefixes():
    cap = build_catalog(FAKE_SPEC)
    assert set(cap) == {"list_stores", "get_store", "mixed_get"}
    for c in cap.values():
        assert c.method == "GET"
    # 前缀拒绝 + 无 operationId 跳过
    assert "self_chat" not in cap and "me" not in cap and "health" not in cap
    assert "create_store" not in cap and "delete_store" not in cap and "mixed_put" not in cap


def test_is_exposed_rejects_every_write_method():
    """★ 写方法一条都不能露面（这是 A 档的全部安全保证）。"""
    for m in ("post", "put", "patch", "delete"):
        assert m in BLOCKED_METHODS
        assert is_exposed("/api/v1/stores", m) is False
    assert is_exposed("/api/v1/stores", "get") is True


def test_real_app_catalog_is_non_vacuous():
    """真实应用装好后目录必须非空，且**没有一条**落在拒绝前缀里。"""
    import main  # noqa: F401 —— 触发装配 + bind_app

    st = stats()
    assert st["bound"] is True, "能力层没绑定 —— 启动期 bind_app 没跑或抛了"
    assert st["operations"] >= 50, f"只读能力只有 {st['operations']} 条，明显不对"
    for c in catalog().values():
        assert c.method == "GET"
        assert not any(c.path == p or c.path.startswith(p + "/") for p in BLOCKED_PREFIXES), c.path


def test_catalog_params_are_extracted():
    cap = build_catalog(FAKE_SPEC)
    store = cap["get_store"]
    assert [p.name for p in store.params] == ["store_id"]
    assert store.params[0].location == "path" and store.params[0].required is True
    assert cap["list_stores"].params[0].location == "query"


# ============================================================
# 2. schema 预算（每个工具的描述都是逐轮成本）
# ============================================================


def test_tool_schema_budget_under_4000_chars():
    tools = build_capability_tools()
    total = sum(
        len(json.dumps(t.args, ensure_ascii=False)) + len(t.description or "") for t in tools
    )
    assert total < 4000, f"三个工具 schema+描述合计 {total} 字符（要求 < 4000）"


def test_capability_tools_are_read_only_metadata():
    """查数据不该过审批闸门（B 档的写能力才会，且必须另起工具名）。"""
    from ai_infra.tools.side_effects import derive_hitl_tools

    tools = build_capability_tools()
    assert not derive_hitl_tools(tools), "只读能力被算成了需审批 —— 查一次数据弹一次卡"


# ============================================================
# 3. 检索：'没匹配' 与 '没装' 必须能分开
# ============================================================


def test_find_distinguishes_not_bound_from_not_matched(fake_binding):
    rows, bound = find("stores")
    assert bound is True and rows, "绑定了却检索不到（关键词在 tag / path 里都该命中）"

    rows, bound = find("绝对不存在的业务词xyz")
    assert rows == [] and bound is True, "'没匹配' 不能表现成 '没装'"

    # 真·未绑定：清空目录
    from ai_infra.capability import registry

    registry._catalog = {}                 # noqa: SLF001
    rows, bound = find("stores")
    assert rows == [] and bound is False


def test_find_respects_limit_and_empty_query(fake_binding):
    rows, _ = find("", 2)
    assert len(rows) == 2
    assert all(r.name for r in rows)


# ============================================================
# 4. 参数拼装：路径参数必须转义（否则值会改掉最终路径）
# ============================================================


def test_path_params_with_separators_are_refused():
    """★ 路径参数含 `/` `?` `#` 必须**本地拒**，不能"转义后发出去"。

    实测：`a%2Fb` 打到 Starlette 会在路由匹配前被解码回 `a/b` ⇒ 路径被切成
    两段 ⇒ 404。于是"转义"只能换来一个 404，而 404 会被读成
    "这个能力不存在" —— 归因错方向，模型会去换能力而不是改参数。
    """
    cap = build_catalog(FAKE_SPEC)["get_store"]
    for bad in ("../../api/v1/auth/me", "a/b", "a?x=1", "a#f", "a\\b"):
        _, _, err = _resolve_params(cap, {"store_id": bad})
        assert err and err["error"] == "path_param_has_separator", bad
        assert err["param"] == "store_id"


def test_path_params_are_percent_encoded_for_safe_chars():
    """空格 / 中文这类**安全字符**仍然要转义（路径不能出现裸空格）。"""
    cap = build_catalog(FAKE_SPEC)["get_store"]
    path, _, err = _resolve_params(cap, {"store_id": "a b"})
    assert err is None
    assert "{store_id}" not in path
    assert path.endswith("%20b") or "%20" in path


def test_unknown_param_is_refused_locally():
    cap = build_catalog(FAKE_SPEC)["list_stores"]
    _, _, err = _resolve_params(cap, {"page": 1, "evil": 2})
    assert err and err["error"] == "unrecognized_params"
    assert err["unknown"] == ["evil"] and "page" in err["allowed"]


def test_missing_path_param_is_refused_locally():
    cap = build_catalog(FAKE_SPEC)["get_store"]
    _, _, err = _resolve_params(cap, {})
    assert err and err["error"] == "missing_path_params"
    assert err["missing"] == ["store_id"]


# ============================================================
# 5. 身份与 sent 语义
# ============================================================


@pytest.fixture()
def mini_app(fake_binding):
    """一个真实可调的 mini ASGI 应用（验证 `sent=true` 那条路）。"""
    app = FastAPI()

    @app.get("/api/v1/ok")
    def ok():
        return {"ok": True, "shop": "s1"}

    @app.get("/api/v1/forbidden")
    def forbidden():
        raise HTTPException(status_code=403, detail="没有这个店铺的权限")

    @app.get("/api/v1/items/{item_id}")
    def item(item_id: str):
        return {"item_id": item_id}

    spec = {
        "paths": {
            "/api/v1/ok": {"get": {"operationId": "mini_ok", "summary": "OK"}},
            "/api/v1/forbidden": {"get": {"operationId": "mini_forbidden", "summary": "Denied"}},
            "/api/v1/items/{item_id}": {
                "get": {
                    "operationId": "mini_item",
                    "summary": "Item",
                    "parameters": [{"name": "item_id", "in": "path", "required": True,
                                    "schema": {"type": "string"}}],
                }
            },
        }
    }
    bind_app(app)                       # 记下 app（内部调用要用它做 ASGI transport）
    from ai_infra.capability import registry

    # ★ 目录改用**可控 spec**：`app.openapi()` 生成的 operationId 是
    #   `ok_api_v1_ok_get` 这种（函数名 + 路径派生），与本用例写的名字对不上。
    #   这样"名字 → 路径"的映射仍由 `build_catalog` 决定，只是 spec 由我们给。
    registry._catalog = build_catalog(spec)   # noqa: SLF001
    yield app
    clear_request_context()


async def test_read_without_identity_is_never_sent(mini_app):
    """★ 没有登录身份 ⇒ **本地拦下**，一个字节都不发出去。"""
    clear_request_context()
    out = await call_read("mini_ok")
    assert out["sent"] is False and out["error"] == "no_identity"

    set_forward_headers({"authorization": "Bearer x"})   # 有身份没店铺
    out = await call_read("mini_ok")
    assert out["sent"] is False and out["error"] == "no_shop"


async def test_read_success_and_server_side_rejection_are_distinguishable(mini_app):
    set_forward_headers({"authorization": "Bearer x", "x-shop-id": "s1"})

    ok = await call_read("mini_ok")
    assert ok["sent"] is True and ok["ok"] is True and ok["status"] == 200
    assert '"ok": true' in ok["data"]

    denied = await call_read("mini_forbidden")
    assert denied["sent"] is True and denied["ok"] is False and denied["status"] == 403
    assert "没有这个店铺的权限" in denied["error"], "服务端的 detail 必须顶到 error 上"


async def test_read_encodes_path_params_end_to_end(mini_app):
    set_forward_headers({"authorization": "Bearer x", "x-shop-id": "s1"})
    out = await call_read("mini_item", {"item_id": "a b"})
    assert out["sent"] is True and out["status"] == 200
    # 服务端收到的是解码后的原值（说明编码是"可往返"的，不是被吃掉）
    assert "a b" in out["data"]

    # 带分隔符的一律本地拒（见上一条用例的理由）
    bad = await call_read("mini_item", {"item_id": "a/b"})
    assert bad["sent"] is False and bad["error"] == "path_param_has_separator"


async def test_read_unknown_capability_fails_closed(mini_app):
    out = await call_read("nope_not_a_capability")
    assert out["sent"] is False and out["error"] == "unknown_capability"


# ============================================================
# 6. 转发头白名单（身份边界的唯一判据）
# ============================================================


def test_forward_headers_whitelist_excludes_impersonation():
    """★ `x-user-id` / `x-account-id` / `x-role` 一旦在名单里，能力层就成了
    "以任意身份读任意租户"的开关 —— 而它长成一次普通工具调用。"""
    assert "x-shop-id" in FORWARD_HEADER_ALLOW, "缺 x-shop-id ⇒ 读端点拿不到店铺上下文"
    assert "authorization" in FORWARD_HEADER_ALLOW
    for banned in ("x-user-id", "x-account-id", "x-role", "x-identity"):
        assert banned not in FORWARD_HEADER_ALLOW, f"{banned} 不该被转发"


def test_forward_headers_are_filtered_not_passed_through():
    clear_request_context()
    picked = set_forward_headers({
        "authorization": "Bearer t",
        "x-shop-id": "s1",
        "x-user-id": "someone-else",
        "x-account-id": "acct",
    })
    assert picked == {"authorization": "Bearer t", "x-shop-id": "s1"}
    assert "x-user-id" not in current_forward_headers()
    # 清空上下文必须包括转发头（它含 authorization）
    clear_request_context()
    assert current_forward_headers() == {}
