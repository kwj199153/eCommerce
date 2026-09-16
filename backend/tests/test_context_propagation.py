"""
统一 Context 贯通回归（P0-2，2026-09-16）

★ 本文件钉住的**核心事实**（修复前）
    `observability/context.py` 里有 `_user_id_var`、导出了 `current_user_id()`，
    但 `set_request_context` **全项目只有一个调用点**（请求日志中间件），
    而它只传 `request_id` + `shop_id`：
        ⇒ `current_user_id()` 恒为空串 —— 那个 ContextVar 是**装饰品**；
        ⇒ `account_id` / `client_ip` 两个字段当时**根本不存在**。

    所以本文件断言的不是"函数存在"，而是**"真的被写进去了"** +
    **"写入点只有那几个"**。第二点同样重要：多一个写入点，就可能把
    一个**未经校验**的身份写进上下文 —— 那是越权通道的形态
    （见 `core/tenant/middleware.py` docstring 里记录的 P0 事故）。
"""

import pathlib

import pytest
from starlette.requests import Request

from core.observability.context import (
    CONTEXT_FIELDS,
    clear_request_context,
    current_account_id,
    current_client_ip,
    current_request_id,
    current_shop_id,
    current_user_id,
    set_request_context,
    snapshot,
)

#: 统一 Context 的**封闭**写入点集合（多一个都要在评审里说清楚为什么）
_ALLOWED_WRITERS = {
    "core/observability/context.py",    # 定义处（自身 5 个字段的 set）
    "core/middleware/request_log.py",   # request_id / shop_id / client_ip
    "core/auth/dependencies.py",        # user_id
    "core/tenant/middleware.py",        # account_id
}

_BACKEND = pathlib.Path(__file__).resolve().parent.parent


def _make_request(headers=None, client=("198.51.100.7", 4444)) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/stores",
        "query_string": b"",
        "headers": headers or [],
    }
    if client:
        scope["client"] = client
    return Request(scope)


@pytest.fixture(autouse=True)
def _clean_context():
    """每条用例前后都清干净，避免 keep-alive 式残留（ContextVar 在同 task 内会串）。"""
    clear_request_context()
    yield
    clear_request_context()


# ====== 1. 五字段：可写、可读、进快照 ======

_SAMPLE = {
    "request_id": "req-abc",
    "user_id": "user-1",
    "account_id": "acct-1",
    "shop_id": "store_x",
    "client_ip": "203.0.113.9",
}
_READERS = {
    "request_id": current_request_id,
    "user_id": current_user_id,
    "account_id": current_account_id,
    "shop_id": current_shop_id,
    "client_ip": current_client_ip,
}


def test_context_fields_is_the_closed_set():
    assert set(CONTEXT_FIELDS) == set(_SAMPLE), (
        "CONTEXT_FIELDS 与实际字段不一致 —— 新增字段时四处都要同步："
        "set_request_context / current_* / snapshot / logger patcher"
    )


def test_every_field_is_writable_readable_and_snapshotted():
    """
    ★ 这一条就是针对"字段定义了但没人写"的形态。
      每个字段都必须同时满足：能写（set 参数）、能读（current_*）、进快照。
    """
    set_request_context(**_SAMPLE)
    for name in CONTEXT_FIELDS:
        assert _READERS[name]() == _SAMPLE[name], f"{name} 读了但没拿到值"
    assert snapshot() == _SAMPLE


def test_none_means_skip_not_clobber():
    """`None` = 本次不改这一项（多阶段写入互不冲掉的契约基础）。"""
    set_request_context(request_id="req-1", client_ip="1.1.1.1")
    set_request_context(user_id="user-1", account_id=None, client_ip=None)
    assert current_request_id() == "req-1"
    assert current_client_ip() == "1.1.1.1"
    assert current_user_id() == "user-1"


def test_clear_empties_everything():
    set_request_context(**_SAMPLE)
    clear_request_context()
    assert all(_READERS[n]() == "" for n in CONTEXT_FIELDS)
    assert set(snapshot().values()) == {"-"}, "空上下文应统一渲染成 '-'"


# ====== 2. 门禁：写入点与 IP 实现都必须是封闭集合 ======

def test_context_writer_set_is_closed():
    """
    统一 Context 的写入点必须是**封闭集合**。新增写入点前请先回答：
    这个值**已经过校验**了吗？（未校验的用户/租户身份写进上下文 = 越权通道）
    """
    found = set()
    for p in _BACKEND.rglob("*.py"):
        rel = p.relative_to(_BACKEND).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/")) or "__pycache__" in rel:
            continue
        if "set_request_context(" in p.read_text(encoding="utf-8"):
            found.add(rel)

    assert found == _ALLOWED_WRITERS, (
        f"Context 写入点发生变化：\n"
        f"  新增 = {sorted(found - _ALLOWED_WRITERS)}\n"
        f"  消失 = {sorted(_ALLOWED_WRITERS - found)}\n"
        "确认新增点是安全的之后再更新本名单（并写清为什么）。"
    )


def test_client_ip_has_exactly_one_implementation():
    """
    客户端 IP 提取只能有**一处**读 `X-Forwarded-For` 的实现。

    本项目曾同时存在 **4 份**拷贝（request_log / rate_limit / identity.router /
    identity.security_router —— 后两者注释里甚至写着"与 rate_limit 同一套逻辑"）。
    多份漂移后，同一条请求在"访问日志 / 限流 key / 安全审计"里会指向不同来源。
    """
    hits = set()
    for p in _BACKEND.rglob("*.py"):
        rel = p.relative_to(_BACKEND).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/")) or "__pycache__" in rel:
            continue
        if 'headers.get("X-Forwarded-For"' in p.read_text(encoding="utf-8"):
            hits.add(rel)

    assert hits == {"core/middleware/client_ip.py"}, f"发现多处 XFF 实现：{sorted(hits)}"


# ====== 3. 端到端：真的鉴权路径会写入 user_id ======

async def test_get_current_user_writes_user_id_and_client_ip(client, user):
    """★ P0-2 的核心证据：真实 token + 真实 DB → 上下文里真的有 user_id。"""
    from core.auth.dependencies import get_current_user
    from core.database import async_session_factory

    req = _make_request(headers=[
        (b"authorization", f"Bearer {user['token']}".encode()),
        (b"x-forwarded-for", b"203.0.113.9, 10.0.0.1"),
    ])
    async with async_session_factory() as db:
        u = await get_current_user(request=req, token=user["token"], db=db)

    assert u.id == user["user_id"]
    assert current_user_id() == user["user_id"], "user_id 仍未写进上下文（P0-2 回归）"
    assert current_client_ip() == "203.0.113.9", "XFF 首跳未进上下文"


async def test_get_current_user_writes_nothing_on_failure(client, user):
    """
    鉴权失败**不能**在上下文里留下身份。

    否则一条 401/403 的日志看起来会像"这个用户成功访问过某接口"，
    排查越权事件时会把人往错方向带。
    """
    from fastapi import HTTPException

    from core.auth.dependencies import get_current_user
    from core.database import async_session_factory

    async with async_session_factory() as db:
        with pytest.raises(HTTPException):
            await get_current_user(
                request=_make_request(), token="not-a-real-token", db=db
            )

    assert current_user_id() == ""


async def test_require_auth_if_enabled_writes_context(client, user, auth_on):
    """HTTP 路由实际用的就是这个依赖（`BUSINESS_AUTH`），所以它也必须写。"""
    from core.auth.dependencies import require_auth_if_enabled
    from core.database import async_session_factory

    req = _make_request(headers=[
        (b"authorization", f"Bearer {user['token']}".encode())
    ])
    async with async_session_factory() as db:
        u = await require_auth_if_enabled(request=req, db=db)

    assert u is not None and u.id == user["user_id"]
    assert current_user_id() == user["user_id"]
