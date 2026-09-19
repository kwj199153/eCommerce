"""
shop_id 空值守卫回归测试（多租户隔离闭环的最后一环）。

背景：修复前实测（探针 `r51-before-write-no-shop`）
---------------------------------------------------
写端点不带 `X-Shop-ID` 时，库层会把 `shop_id` 落成空串 `""`；而 16 张业务表
都有 `shop_id -> stores_store.id` 外键，空串不是合法父键 ⇒ PG 抛
`ForeignKeyViolationError`。实测四个场景：

    A 完全不带头   POST /api/v1/spus -> 500
    B 头是空串     POST /api/v1/spus -> 500
    C 头是纯空白   POST /api/v1/spus -> 500
    D 头是真实店铺 POST /api/v1/spus -> 201

两个副作用让这件事必须修：
  1. **信息泄露**：500 响应体把 SQLAlchemy 报错与约束名原样返回给客户端。
  2. **归因错误**：用户看到的是"服务器内部错误"，而不是"你没选店铺"。

修复后
------
`get_current_shop_id` 增加按 method 分流的空值守卫：
写方法 + 缺失/空白 `X-Shop-ID` ⇒ 400（零数据库往返）；读方法保持原契约
（返回 `None` → 端点回空列表）。

本文件钉住的四件事
------------------
1. 三类空值（无头 / 空串 / 纯空白）在写端点上都必须 400，且**真的没有入库**。
2. 读端点的「未选店铺 → 空列表」契约不能被这次改动破坏。
3. 对话入口 `POST /orchestrator/chat` 必须豁免（否则新用户没人能救）。
4. **防后门**：豁免依赖 `get_current_shop_id_optional` 的使用面必须锁死在
   一张白名单上；严格依赖也不许从既有 8 个业务模块里消失。
   —— 这两条是 AST 级断言，防的是"未来某次改动顺手绕开守卫"。
5. **对话入口「不落数据」必须是可执行的**：白名单里允许豁免的形态只有两种 ——
   「不落业务数据」或「写路径自身在缺店铺上下文时硬拒绝」。后者不能只写在
   注释里，所以第 5 节用真实请求 + 直查表行数把它钉住
   （P0 修复 2026-09-16：product_research 对话入口曾用未校验的请求头当写库归属）。
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text

from core.database import async_session_factory

BACKEND = Path(__file__).resolve().parents[1]
MODULES = BACKEND / "modules"

STRICT = "get_current_shop_id"
OPTIONAL = "get_current_shop_id_optional"

# ★ 豁免白名单：只有这些函数允许使用 `get_current_shop_id_optional`。
#   新增一条必须先回答两个问题：
#     ① 它会落业务数据吗？
#     ② 若会 —— 它的**写路径**在缺店铺上下文时是否硬拒绝？
#        会落 且 写路径不拒绝 → 不许加（那才是真的开后门）。
#   现有四条（含第 131 轮新增的 resume_approval）的成立理由（每条都有测试背书，不是自述）：
#     · secretary/router.py::secretary_chat  —— ① 不会（纯对话/导航；工具层拿不到
#       shop_id 时只回「产品库为空」）。
#     · product_research/router.py::chat / chat_stream —— ① 会（候选入库），
#       ② 写路径 `agent_product_research._write_candidates` 在 shop_id 缺失时
#       直接返回失败、**零数据库往返**（见本文件第 5 节两条用例）。
#       为什么不用严格版：该端点同时服务只读意图（蓝海/利润/痛点/能力），
#       严格版对**所有写方法**强制要求 X-Shop-ID，会把"还没选店铺"的用户
#       整个挡在门外（400）—— 属零收益的体验损伤。
#       ⇒ 门禁放在"写"这一层，而不是"入口"这一层。
ALLOWED_OPTIONAL = {
    ("modules/secretary/router.py", "secretary_chat"),
    ("modules/product_research/router.py", "chat"),
    ("modules/product_research/router.py", "chat_stream"),
    # ★ 第 131 轮新增。与 chat / chat_stream **完全同构**：
    #   ① 会落业务数据（恢复被中断的图 ⇒ 执行 save_candidate）；
    #   ② 缺店铺时写路径硬拒绝（`_write_candidates` 零 DB 往返），
    #      且第 131 轮起 `_route_gated_intent` 在**入口**就拦了（零写入）。
    #   为什么不用严格版：审批的 reject / response 两档**不需要** shop_id
    #      （thread_id 由 (命名空间, 用户, 会话) 重算，不含 shop_id）。
    #      用严格版会让「想拒绝但没选店铺」的用户连拒绝都点不动（400）。
    ("modules/product_research/router.py", "resume_approval"),
}

# 严格依赖的使用方（8 个业务模块）。少一个都意味着某个模块的租户过滤被摘掉了。
EXPECTED_STRICT_MODULES = {
    "modules/aigc_media/router.py",
    "modules/assets/router.py",
    "modules/candidates/router.py",
    "modules/knowledge_base/router.py",
    "modules/monitors/router.py",
    "modules/platform_rules/router.py",
    "modules/products/router.py",
    "modules/voice_clone/router.py",
}


def _depends_usage() -> tuple[set[tuple[str, str]], set[str]]:
    """扫 modules/ 下所有 router.py，返回（豁免依赖使用点, 严格依赖所在模块）。"""
    optional_hits: set[tuple[str, str]] = set()
    strict_modules: set[str] = set()

    for py in sorted(MODULES.rglob("router.py")):
        rel = py.relative_to(BACKEND).as_posix()
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                f = node.func
                # ★ `Depends(...)` 里的 Depends 是 **ast.Name**（id 属性），
                #   只有 `fastapi.Depends(...)` 才是 ast.Attribute（attr 属性）。
                #   只判其中一种会**静默扫出空集**——本文件第一版就栽在这里：
                #   断言报"实际 = []"，看起来像被测代码没了依赖，其实是我扫错了。
                is_depends = (
                    (isinstance(f, ast.Name) and f.id == "Depends")
                    or (isinstance(f, ast.Attribute) and f.attr == "Depends")
                )
                if not is_depends:
                    continue
                arg = node.args[0]
                if not isinstance(arg, ast.Name):
                    continue
                if arg.id == OPTIONAL:
                    optional_hits.add((rel, fn.name))
                elif arg.id == STRICT:
                    strict_modules.add(rel)
    return optional_hits, strict_modules


# ====== 1. 写端点：三类空值必须 400 ======

@pytest.mark.parametrize(
    "label,headers",
    [
        ("完全不带头", {}),
        ("头是空串", {"X-Shop-ID": ""}),
        ("头是纯空白", {"X-Shop-ID": "   "}),
    ],
)
async def test_write_endpoint_rejects_blank_shop_id(client, label, headers):
    """
    写端点三类空值都必须 400，而不是 500。

    这里刻意断言 `!= 500` 之外的**精确状态码 400**：501/502 之类的中间态
    同样说明守卫没生效，用 `not in (200, 500)` 会把它们放过去。
    """
    r = await client.post("/api/v1/spus", json={"title": "guard-probe"}, headers=headers)
    assert r.status_code == 400, f"[{label}] 期望 400，实际 {r.status_code} {r.text[:200]}"
    body = r.json()
    assert "店铺" in body.get("detail", ""), f"[{label}] 400 原因不可读: {body}"


async def test_blank_shop_id_write_never_reaches_database(client):
    """
    「禁止入库」的字面验证：400 之后库里不能多出空 shop_id 的行。

    只看状态码是不够的 —— 一个"先写入再报错"的实现同样返回 400，
    但脏数据已经落库了。所以这里直查 DB 的空分区行数。
    """
    async with async_session_factory() as db:
        before = (await db.execute(
            text("SELECT count(*) FROM spus WHERE shop_id = ''")
        )).scalar()

    r = await client.post("/api/v1/spus", json={"title": "guard-probe-2"}, headers={})
    assert r.status_code == 400, r.text

    async with async_session_factory() as db:
        after = (await db.execute(
            text("SELECT count(*) FROM spus WHERE shop_id = ''")
        )).scalar()

    assert after == before, f"空 shop_id 竟被写入：{before} -> {after}"


@pytest.mark.parametrize(
    "method,path",
    [
        ("put", "/api/v1/spus/spu-guard-not-exist"),
        ("delete", "/api/v1/spus/spu-guard-not-exist"),
        ("put", "/api/v1/assets/asset-guard-not-exist"),
        ("delete", "/api/v1/monitors/mon-guard-not-exist"),
        ("patch", "/api/v1/skus/sku-guard-not-exist/listing"),
    ],
)
async def test_all_write_methods_are_guarded(client, method, path):
    """
    PUT / DELETE / PATCH 与 POST 一视同仁。

    守卫依赖在 FastAPI 里先于路径参数校验解析，所以这里故意传不存在的资源 id：
    期望拿到的是守卫的 400，而不是处理器里的 404。
    （若拿到 404，说明守卫被排到了路径校验之后 —— 这也是回归信号。）
    """
    # ★ 用统一入口 `client.request(...)`：`AsyncClient.delete()` 不接受 `json=`
    #   关键字（httpx 的便捷方法签名里没有它），逐个 getattr 调用会 TypeError。
    r = await client.request(method.upper(), path, json={})
    assert r.status_code == 400, (
        f"{method.upper()} {path} 期望 400（守卫先于路径校验），"
        f"实际 {r.status_code} {r.text[:200]}"
    )


async def test_write_with_real_shop_still_succeeds(client, ensure_shop):
    """守卫不能误伤正常调用：带真实店铺头的写入必须照旧 201 且落对 shop_id。"""
    sid = await ensure_shop(f"store_guard_{uuid.uuid4().hex[:8]}")
    r = await client.post("/api/v1/spus", json={"title": "guard-ok"},
                          headers={"X-Shop-ID": sid})
    assert r.status_code == 201, r.text

    async with async_session_factory() as db:
        got = (await db.execute(
            text("SELECT shop_id FROM spus WHERE id = :i"), {"i": r.json()["id"]}
        )).scalar()
    assert got == sid, f"落库 shop_id 应为 {sid}，实际 {got!r}"


async def test_shop_id_is_stripped_before_use(client, ensure_shop):
    """`X-Shop-ID: '  store_x  '` 应被规整后正常放行（头解析不管空白）。"""
    sid = await ensure_shop(f"store_guard_{uuid.uuid4().hex[:8]}")
    r = await client.post("/api/v1/spus", json={"title": "guard-space"},
                          headers={"X-Shop-ID": f"  {sid}  "})
    assert r.status_code == 201, r.text

    async with async_session_factory() as db:
        got = (await db.execute(
            text("SELECT shop_id FROM spus WHERE id = :i"), {"i": r.json()["id"]}
        )).scalar()
    assert got == sid, f"期望规整为 {sid}，实际 {got!r}"


# ====== 2. 读端点：契约不变 ======

async def test_read_endpoint_keeps_empty_list_contract(client):
    """
    GET 不带头仍是 200 + 空列表 —— 这是 `Workspace.vue` 明确注释依赖的契约
    （「未选店铺时列表为空」）。守卫只该管写，管到读就是把功能改坏。
    """
    r = await client.get("/api/v1/spus")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"items": [], "total": 0}, body


async def test_read_endpoint_still_200_with_blank_header(client):
    r = await client.get("/api/v1/monitors", headers={"X-Shop-ID": "   "})
    assert r.status_code == 200, r.text
    assert r.json()["items"] == []


# ====== 3. 对话入口豁免 ======

async def test_secretary_chat_allowed_without_shop(client):
    """
    店秘书是 POST，但属对话入口，必须能在「一家店铺都没有」时工作。

    否则新注册用户（shops 为空、前端不发 X-Shop-ID）一开口就 400，
    「帮我创建第一个店铺」这个唯一能自救的路径被自己堵死。
    """
    r = await client.post("/api/v1/orchestrator/chat", json={"message": "你好"}, headers={})
    assert r.status_code == 200, f"店秘书不应被写守卫拦截: {r.status_code} {r.text[:200]}"
    assert r.json().get("reply")


# ====== 4. 防后门（AST 级） ======

def test_optional_variant_usage_is_locked_to_allowlist():
    """
    豁免依赖的使用面必须与 `ALLOWED_OPTIONAL` 完全一致。

    这条测试防的是最危险的后续改动形态：某个**会落业务数据**的新端点
    顺手 import 了 `get_current_shop_id_optional`，于是守卫对它形同不存在
    —— 代码能跑、单测能过、评审容易漏。用集合相等（而非包含）断言，
    所以「多加一处」和「少一处」都会红。
    """
    optional_hits, _ = _depends_usage()
    assert optional_hits == ALLOWED_OPTIONAL, (
        f"豁免依赖使用点与白名单不一致：\n"
        f"  实际 = {sorted(optional_hits)}\n"
        f"  期望 = {sorted(ALLOWED_OPTIONAL)}\n"
        f"新增豁免前先回答白名单注释里的两个问题："
        f"① 它会落业务数据吗？② 若会，写路径在缺店铺时硬拒绝吗？"
        f"（「会落数据且写路径硬拒绝」是允许的形态之一 —— 门禁放在写那一层，"
        f"而不是入口那一层；chat / chat_stream / resume_approval 都属此类。）"
    )


def test_strict_variant_still_used_by_all_business_modules():
    """
    严格依赖不许从既有业务模块里消失（被替换成豁免版、或被整段删掉都会红）。
    """
    _, strict_modules = _depends_usage()
    assert strict_modules == EXPECTED_STRICT_MODULES, (
        f"严格依赖所在模块与预期不一致：\n"
        f"  缺失 = {sorted(EXPECTED_STRICT_MODULES - strict_modules)}\n"
        f"  多出 = {sorted(strict_modules - EXPECTED_STRICT_MODULES)}"
    )


# ====== 5. 对话入口「不落数据」的可执行证明 ======

async def test_optional_dependent_endpoint_cannot_write_without_shop(client):
    """
    用豁免依赖的对话入口，缺店铺上下文时**不得**落业务数据。

    这是 `ALLOWED_OPTIONAL` 判据的可执行版本：白名单允许豁免的形态之一是
    「写路径自身硬拒绝」，那就必须有测试证明它真的拒绝 ——
    否则白名单条目只是一句注释，下一个人照着加一条也不会有人拦。

    ★ 断言分两半，缺一不可：
      · **可读原因**含「店铺」—— 这一半才有鉴别力。修复前缺店铺时仍然会去调
        `create_candidate(shop_id=None)`，落成 `shop_id=""` 撞外键 → 回的是
        "写入选品库失败（数据库不可用）"：**归因错误**，用户去查数据库，
        而真因是他没选店铺。
      · **表行数不变** —— 只看状态码/文案不够，"先写入再报错"同样能通过。
    """
    from sqlalchemy import text
    from core.database import async_session_factory

    async with async_session_factory() as db:
        before = (await db.execute(text("SELECT count(*) FROM candidates"))).scalar()

    r = await client.post(
        "/api/v1/product-research/chat",
        json={
            # 显式给 ASIN：目标解析必然命中 ⇒ 一定走到写库那一步
            # （若只给"这个品"，会在解析阶段就转成追问，测不到写守卫）
            "message": "把 B0CGLKP2R1 加入选品库",
            "context_id": "guard-no-shop-probe",
        },
        headers={},
    )
    assert r.status_code == 200, r.text
    assert "店铺" in r.text, (
        f"缺店铺时必须回一句指向店铺的可读原因（而不是「数据库不可用」）：{r.text[:300]}"
    )

    async with async_session_factory() as db:
        after = (await db.execute(text("SELECT count(*) FROM candidates"))).scalar()
    assert after == before, f"缺店铺上下文时竟写了候选：{before} -> {after}"


async def test_write_candidates_hard_refuses_without_shop_id(monkeypatch):
    """
    `_write_candidates` 缺 shop_id 时**硬拒绝**，且**零数据库往返**。

    反向保护：这条防的是"以后有人图省事，把 shop_id 默认成 '' 或从某个全局
    上下文兜底取" —— 那样跨租户写入会以另一种形式复活（P0 事故就是"兜底取值"
    的形态：直读中间件塞进上下文的原始请求头）。

    ★ 用「写入口被触达就抛错」的探针证明"零往返"，而不是只看返回值：
      返回值可能是"失败"，但失败发生在数据库拒绝之后（已经晚了一步）。
    """
    # ★ 第 140 轮修正：必须打桩在**门面**上。打在 `service` 子模块上时
    #   桩永不生效 —— 本用例会因「生产的硬拒绝恰好也回一句含『店铺』的
    #   文案」而**通过**，于是「零数据库往返」这条断言其实一次都没被验证。
    import modules.candidates as candidates_service
    from modules.product_research.agent_product_research import ProductResearchAgent

    touched: list = []

    async def _boom(*args, **kwargs):
        touched.append(args)
        raise AssertionError("缺 shop_id 时不该触达 candidates/service")

    monkeypatch.setattr(candidates_service, "candidate_exists", _boom)
    monkeypatch.setattr(candidates_service, "create_candidate", _boom)

    result = await ProductResearchAgent()._write_candidates(
        [{"asin": "B0PROBE001", "title": "no-shop probe"}], None, None
    )

    assert result["type"] == "candidate_save_failed", result
    assert "店铺" in result.get("error", ""), f"失败原因须指向店铺：{result}"
    assert touched == [], "必须在触达数据库之前就拦下"
