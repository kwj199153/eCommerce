"""P0-5 通用审计日志的门禁（形态 + 行为 + 反向注入自检）。

================================ 这道门禁守什么 ================================
审计是一个**旁路能力**，它的失效几乎全部是静默的：
  · 忘挂权限 ⇒ 「审计日志被所有人读得到」（信息泄露，接口全绿）；
  · 多一处 `AuditLog(...)` 构造 ⇒ 绕过 `record_audit` 的统一口径（时间/截断/
    指标全丢），而两处都能正常写库，没有任何报错；
  · 动作名写成裸字符串 ⇒ 改名时历史被静默撕裂（见 actions.py 文件头）；
  · 写失败被吞 ⇒ 审计悄悄停了，而业务一切正常。

⇒ 所以本文件把四件事分别钉住（A 组形态 / B 组行为 / C 组自检）：

  A1 读口**每条**路由必须挂平台超管门禁（`Depends(get_admin_user)`）
  A2 `AuditLog(...)` 构造只允许出现在 `core/audit/service.py`（唯一写入路径）
  A3 接入点的 `record_audit(action=...)` 实参必须是**常量**，禁裸字符串
  A4 `record_audit` 的失败分支必须同时有 `logger.error` 与指标（禁静默）
  B1 写入 → 从读口按过滤条件读回（端到端闭环）
  B2 匿名 401 / 普通用户 403 / 平台超管 200（★ 401 与 403 必须分开）
  B3 写失败 ⇒ 返回 False、不抛、指标 +1（★ 计数取增量，不写成恒真）
  B4 **主体不存在的审计仍能写入** —— 「actor_id 不建外键」的行为证明
  C1/C2 反向注入自检：A1 / A2 的判据必须能报出违规样本
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, text

from core.audit import (
    ACTION_LOGIN_SUCCESS,
    ACTION_STORE_DELETE,
    TARGET_STORE,
    TARGET_USER,
    AuditLog,
    record_audit,
)

BACKEND = Path(__file__).resolve().parents[1]
AUDIT_ROUTER = BACKEND / "core" / "audit" / "router.py"
AUDIT_SERVICE = BACKEND / "core" / "audit" / "service.py"

#: 允许出现 `AuditLog(...)` 构造的**唯一**文件（唯一写入路径）
AUDIT_WRITE_PATH = AUDIT_SERVICE

#: 接入点：会出现 `record_audit(action=...)` 的文件
INGEST_FILES = (
    BACKEND / "core" / "identity" / "router.py",
    BACKEND / "modules" / "stores" / "router.py",
    BACKEND / "core" / "auth" / "accounts_router.py",
)

ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}


def _src(path: Path) -> str:
    return path.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


# ============================ A 组：形态（AST） ============================


def _uses_admin_dep(fn: ast.AST) -> bool:
    """函数（含参数默认值）里是否有 `Depends(get_admin_user)`。"""
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Depends"
        ):
            for a in node.args:
                if isinstance(a, ast.Name) and a.id == "get_admin_user":
                    return True
    return False


def _routes_missing_admin_dep(source: str) -> list[str]:
    """返回**缺平台超管门禁**的路由函数名（空 = 合规）。"""
    bad: list[str] = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        is_route = False
        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and isinstance(dec.func.value, ast.Name)
                and dec.func.value.id == "router"
                and dec.func.attr in ROUTE_METHODS
            ):
                is_route = True
        if is_route and not _uses_admin_dep(node):
            bad.append(node.name)
    return bad


def _audit_log_constructions(source: str, rel: str) -> list[str]:
    """返回 `AuditLog(...)` 构造的位置（空 = 该文件没有直接构造）。"""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if name == "AuditLog":
                out.append(f"{rel}:{node.lineno}")
    return out


def _literal_action_calls(source: str) -> list[str]:
    """返回 `record_audit(action="字面量")` 的位置（空 = 全部走常量）。"""
    out: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "record_audit"
        ):
            continue
        for kw in node.keywords:
            if (
                kw.arg == "action"
                and isinstance(kw.value, ast.Constant)
                and isinstance(kw.value.value, str)
            ):
                out.append(f"line {kw.value.lineno}: {kw.value.value!r}")
    return out


def _record_audit_failure_is_visible(source: str) -> tuple[int, int]:
    """在 `record_audit` 的 except 分支里数 `logger.error` 与 `*.inc(` 的调用数。"""
    n_log = n_inc = 0
    for fn in ast.walk(ast.parse(source)):
        if not (isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.name == "record_audit"):
            continue
        for t in ast.walk(fn):
            if not isinstance(t, ast.Try):
                continue
            for h in t.handlers:
                for sub in ast.walk(h):
                    if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                        if sub.func.attr == "error" and isinstance(sub.func.value, ast.Name) and sub.func.value.id == "logger":
                            n_log += 1
                        if sub.func.attr == "inc":
                            n_inc += 1
    return n_log, n_inc


def test_read_endpoints_all_require_platform_admin():
    """A1：读口每条路由都必须挂 `Depends(get_admin_user)`。"""
    bad = _routes_missing_admin_dep(_src(AUDIT_ROUTER))
    assert not bad, (
        "以下审计读口路由没有平台超管门禁 —— 审计是**跨账户**的全局视图，"
        f"任何登录用户可读都是信息泄露：{bad}"
    )


def test_read_endpoints_actually_exist():
    """A1 的前提：判据不能空跑（扫到 0 条路由 ⇒ 恒绿）。"""
    src = _src(AUDIT_ROUTER)
    tree = ast.parse(src)
    routes = [
        n.name
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and getattr(d.func.value, "id", "") == "router"
            for d in n.decorator_list
        )
    ]
    assert len(routes) >= 2, f"只扫到 {len(routes)} 条审计路由，判据可能失效：{routes}"


def test_audit_log_is_constructed_only_in_service():
    """A2：`AuditLog(...)` 只允许出现在 service.py（唯一写入路径）。"""
    offenders: list[str] = []
    roots = ("core", "modules", "ai_infra", "platforms")
    for root in roots:
        d = BACKEND / root
        if not d.is_dir():
            continue
        for f in d.rglob("*.py"):
            if "__pycache__" in f.parts or f == AUDIT_WRITE_PATH:
                continue
            offenders += _audit_log_constructions(_src(f), str(f.relative_to(BACKEND)))
    assert not offenders, (
        "在 core/audit/service.py 之外出现了 `AuditLog(...)` 构造 —— 那会绕过"
        "`record_audit()` 的统一口径（截断 / 指标 / 失败处理），"
        f"而两处都能正常写库、没有任何报错：{offenders}"
    )


def test_ingest_points_use_action_constants():
    """A3：接入点的动作名必须来自常量，禁裸字符串（否则改名会静默撕裂历史）。"""
    offenders: list[str] = []
    for f in INGEST_FILES:
        offenders += [f"{f.name} {x}" for x in _literal_action_calls(_src(f))]
    assert not offenders, (
        "以下 `record_audit(action=...)` 用了**字符串字面量** —— 改名后老记录查不到、"
        f"新记录筛不出，且没有任何报错。请改用 core/audit/actions.py 里的常量：{offenders}"
    )


def test_ingest_points_actually_call_record_audit():
    """A3 的前提：接入点必须真的调用 `record_audit`（防「判据空跑」）。"""
    counts = {f.name: _src(f).count("await record_audit(") for f in INGEST_FILES}
    assert all(c >= 1 for c in counts.values()), f"有接入点没有调用 record_audit：{counts}"


def test_record_audit_failure_is_never_silent():
    """A4：写失败分支必须同时有 `logger.error` 与指标 inc。"""
    n_log, n_inc = _record_audit_failure_is_visible(_src(AUDIT_SERVICE))
    assert n_log >= 1, "record_audit 的失败分支没有 logger.error —— 失败会被静默吞掉"
    assert n_inc >= 1, (
        "record_audit 的失败分支没有指标 inc —— 「审计悄悄停了」这件事"
        "将没有任何可告警的出口"
    )


# ============================ B 组：行为（真库） ============================


async def _promote_to_admin(user_id: str) -> None:
    """把用户提成平台超管。

    ★ 原生 SQL 里的 enum 字面量是 **name**（`ADMIN`）而不是 `.value`（`admin`）：
      SQLAlchemy 的 `Enum(UserRole)` 按 name 落库。写小写会直接
      `InvalidTextRepresentationError`。这里从枚举取名字，不手抄字面量。
    """
    from core.database import get_async_session
    from core.identity.models import UserRole

    async with get_async_session() as db:
        await db.execute(
            text("UPDATE users SET role = :r WHERE id = :u"),
            {"r": UserRole.ADMIN.name, "u": user_id},
        )
        await db.commit()


async def _purge_audit(target_id: str) -> None:
    """清掉本文件用例写下的审计行（只按 target_id 精确删，不碰其它数据）。"""
    from core.database import get_async_session

    async with get_async_session() as db:
        await db.execute(delete(AuditLog).where(AuditLog.target_id == target_id))
        await db.commit()


@pytest.mark.asyncio
async def test_write_then_read_back_via_endpoint(client, make_user):
    """B1：写入 → 从读口按过滤条件读回（端到端闭环）。"""
    u = await make_user("audit_e2e")
    tag = f"e2e-{uuid.uuid4().hex[:10]}"
    try:
        ok = await record_audit(
            action=ACTION_STORE_DELETE,
            actor=SimpleNamespace(id=u["user_id"], email="e2e@example.com"),
            target_type=TARGET_STORE,
            target_id=tag,
            summary=f"端到端审计写入 {tag}",
            detail={"probe": True},
        )
        assert ok is True, "审计写入返回 False"

        await _promote_to_admin(u["user_id"])
        r = await client.get(
            "/api/v1/audit/logs", params={"target_id": tag}, headers=u["headers"]
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 1, f"写入成功但读口查不到：{body}"
        hit = [it for it in body["items"] if it["target_id"] == tag]
        assert hit, f"过滤条件没有命中刚写入的行：{body['items']}"
        assert hit[0]["action"] == ACTION_STORE_DELETE
        assert hit[0]["detail"] == {"probe": True}
        assert hit[0]["summary"] == f"端到端审计写入 {tag}"
        assert hit[0]["created_at"], "created_at 未序列化（应走 utc_iso 口径）"
    finally:
        await _purge_audit(tag)


@pytest.mark.asyncio
async def test_actions_catalog_is_served(client, make_user):
    """读口 `/actions` 返回动作目录（前端筛选框的真源）。"""
    u = await make_user("audit_catalog")
    await _promote_to_admin(u["user_id"])
    r = await client.get("/api/v1/audit/actions", headers=u["headers"])
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    got = {it["action"] for it in items}
    assert ACTION_STORE_DELETE in got and ACTION_LOGIN_SUCCESS in got
    assert all(it.get("label") and it.get("target_type") for it in items), (
        "动作目录缺 label / target_type —— 前端筛选框无法渲染"
    )


@pytest.mark.asyncio
async def test_audit_read_is_admin_only(client, make_user):
    """B2：匿名 401 / 普通用户 403 / 平台超管 200 —— 三者必须分得开。"""
    # ① 匿名（无 token）⇒ 401（「该去登录」）
    r = await client.get("/api/v1/audit/logs")
    assert r.status_code == 401, f"匿名读审计应 401，实际 {r.status_code}：{r.text}"

    u = await make_user("audit_nonadmin")
    # ② 已登录但非平台超管 ⇒ 403（「登录了也没用」）
    r = await client.get("/api/v1/audit/logs", headers=u["headers"])
    assert r.status_code == 403, f"普通用户读审计应 403，实际 {r.status_code}：{r.text}"

    # ③ 平台超管 ⇒ 200
    await _promote_to_admin(u["user_id"])
    r = await client.get("/api/v1/audit/logs", headers=u["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body and "limit" in body and "offset" in body


@pytest.mark.asyncio
async def test_audit_write_failure_is_visible_but_not_fatal(monkeypatch):
    """B3：写失败 ⇒ 返回 False、**不抛**、指标增量 > 0（禁静默）。"""
    import core.audit.service as svc
    from core.observability import metrics as M

    def _boom():
        raise RuntimeError("audit db down（本用例刻意注入）")

    key = (ACTION_STORE_DELETE,)
    before = M.AUDIT_WRITE_ERRORS._values.get(key, 0)  # noqa: SLF001
    monkeypatch.setattr(svc, "async_session_factory", _boom)

    ok = await svc.record_audit(
        action=ACTION_STORE_DELETE, target_type=TARGET_STORE, target_id="probe-down"
    )

    after = M.AUDIT_WRITE_ERRORS._values.get(key, 0)  # noqa: SLF001
    assert ok is False, "写失败时应当返回 False（调用方要能知道），且不得外抛"
    assert after > before, (
        f"写失败没有留下指标（{before} -> {after}）—— 「审计悄悄停了」将无人知道。"
        "★ 用增量而不是 >=1：后者会被历史计数顶住，成为恒真的死判据。"
    )


@pytest.mark.asyncio
async def test_audit_survives_actor_that_does_not_exist():
    """B4：**主体不存在**时审计仍必须写得进去 —— 「actor_id 不建外键」的行为证明。

    这正是设计要保的性质：用户被删之后，「当时是谁干的」仍要答得出来。
    若有人给 `actor_id` 加了 FK，这一条会立刻变红（而行不会被静默丢弃 ——
    它会以 `IntegrityError` 的形式让 record_audit 返回 False）。
    """
    ghost = f"ghost-{uuid.uuid4().hex[:10]}"
    try:
        ok = await record_audit(
            action=ACTION_LOGIN_SUCCESS,
            actor=SimpleNamespace(id=ghost, email="ghost@example.com"),
            target_type=TARGET_USER,
            target_id=ghost,
            summary=f"主体不存在的审计 {ghost}",
        )
        assert ok is True, (
            "主体不存在时审计写不进去 —— 说明 actor_id 挂了外键；"
            "那会让「删号」变成「清痕迹」的入口"
        )
        from core.database import get_async_session
        from sqlalchemy import select

        async with get_async_session() as db:
            row = (
                await db.execute(select(AuditLog).where(AuditLog.target_id == ghost))
            ).scalars().first()
        assert row is not None and row.actor_id == ghost, "审计行没有保留孤儿 actor_id"
    finally:
        await _purge_audit(ghost)


# ============================ C 组：反向注入自检 ============================


def test_admin_gate_predicate_detects_missing_dep():
    """C1：A1 的判据必须**能报出**缺门禁的路由，且放过合规形态。"""
    bad = (
        "@router.get('/x')\n"
        "async def x(_a: User = Depends(get_current_user)):\n"
        "    return {}\n"
    )
    assert _routes_missing_admin_dep(bad) == ["x"], "判据没能报出缺平台超管门禁的路由"

    good = (
        "@router.get('/x')\n"
        "async def y(_a: User = Depends(get_admin_user)):\n"
        "    return {}\n"
    )
    assert _routes_missing_admin_dep(good) == [], "判据把合规形态误报成违规"


def test_construction_predicate_detects_second_write_site():
    """C2：A2 的判据必须能报出「第二处构造」。"""
    src = "row = AuditLog(id='x')\n"
    hits = _audit_log_constructions(src, "modules/foo/bar.py")
    assert hits and "modules/foo/bar.py" in hits[0], "判据没能报出第二处 AuditLog 构造"
    assert _audit_log_constructions("x = 1\n", "a.py") == [], "判据在无构造时误报"


def test_literal_action_predicate_detects_bare_string():
    """C2'：A3 的判据必须能报出裸字符串动作名。"""
    src = "await record_audit(action='store.delete')\n"
    assert _literal_action_calls(src), "判据没能报出裸字符串动作名"
    assert _literal_action_calls("await record_audit(action=ACTION_STORE_DELETE)\n") == []
