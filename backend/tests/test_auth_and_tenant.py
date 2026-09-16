"""
鉴权 & 多租户隔离回归测试

覆盖此前几轮修复的闭环：
1. 业务接口在演示模式放行、生产模式要求 Bearer Token
2. 租户中间件已注册，且**只做可观测性**（不得持有/写入任何租户上下文）
3. P0 修复回归（2026-09-16）：跨租户写入必 403 / refresh token 必须真的
   校验过期时间
4. P1-c 收拢回归（2026-09-16）：账户侧 `tenant_context` 家族已整体删除，
   不得复活（见 `test_tenant_context_family_is_gone`）

★ 店铺归属校验的端到端用例现在住在
  `tests/test_account_store_hierarchy.py`（账户成员共享 / 角色矩阵 /
  陌生人 403），本文件不再重复一遍 —— 同一判据只在**一处**实现，
  否则两边会各自漂移。
"""

import pytest

from core.config import config
from core.identity.router import hash_password, verify_password


# ====== 鉴权开关 ======

async def test_health_is_open(client):
    """
    健康检查必须免鉴权。

    ★ 2026-09-15 语义更新：/health 由「恒返回 ok」改为**真实探活依赖**，
      因此 status 只保证落在三个合法值里（ok / degraded / unhealthy）。
      本测试的意图是「这条路径不需要 Token」，不是「服务一定全健康」——
      测试环境通常没有 Redis，degraded 才是正确结果。
      （修复前的写法 `== "ok"` 会让「Redis 挂了」这种真实状态把测试跑红，
        而它跟本测试要验证的鉴权无关。）
    """
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded", "unhealthy")


async def test_health_detail_exposes_dependencies(client):
    """?detail=true 时返回各依赖探活结果（不含敏感信息）"""
    r = await client.get("/health?detail=true")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded", "unhealthy")
    deps = body["dependencies"]
    # postgres 是必需依赖，测试环境应可用
    assert deps["postgres"]["up"] is True
    assert "latency_ms" in deps["postgres"]
    # redis / llm 只校验结构，不假设环境状态
    assert "up" in deps["redis"]
    assert "up" in deps["llm"]


async def test_metrics_endpoint_available(client):
    """
    /metrics 暴露 Prometheus 文本格式，且不消耗限流额度。

    这是「可观测性从 0 到 1」的回归保护：一旦有人把该路由删掉或改坏格式，
    监控采集会静默断流（比报错更难发现）。
    """
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "process_uptime_seconds" in body
    assert "http_requests_total" in body
    # 路径标签必须是归一化后的模板，不能出现原始 UUID
    assert "http_request_duration_ms_bucket" in body


async def test_metrics_requires_token_once_configured(client, monkeypatch):
    """
    配了 METRICS_TOKEN 之后：无 token / 错 token ⇒ 401；对 token ⇒ 200。

    ★ P1-d 的分工说明（别在这里补一条「没配 token」的用例）：
      「token 压根没配」由**启动护栏**拦住
      （core/config.py::_enforce_production_safety ⇒ 生产环境拒绝启动），
      本端点只负责「配了但请求带错」这一种。同一判据不在两处实现，
      否则两边会各自漂移。
    """
    monkeypatch.setattr(config, "metrics_token", "s3cr3t-metrics-token")

    r0 = await client.get("/metrics")
    assert r0.status_code == 401, f"无 token 应 401，实际 {r0.status_code}"

    r1 = await client.get("/metrics", headers={"Authorization": "Bearer wrong-token"})
    assert r1.status_code == 401, f"错 token 应 401，实际 {r1.status_code}"

    r2 = await client.get(
        "/metrics", headers={"Authorization": "Bearer s3cr3t-metrics-token"}
    )
    assert r2.status_code == 200, f"正确 token 应 200，实际 {r2.status_code}"
    assert "http_requests_total" in r2.text


async def test_request_id_is_returned_and_propagated(client):
    """
    每个响应都带 X-Request-ID；上游透传的 ID 必须被原样沿用。

    ★ 透传（而不是每次新生成）是链路追踪的前提：网关/前端已经生成了 ID，
      服务端再换一个就会把链路切断。
    """
    r = await client.get("/health")
    assert r.headers.get("X-Request-ID")

    r2 = await client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert r2.headers["X-Request-ID"] == "trace-abc-123"


async def test_business_endpoint_401_without_token(client, auth_on):
    r = await client.post("/api/v1/listing/chat", json={"message": "优化标题"})
    assert r.status_code == 401, r.text


async def test_business_endpoint_ok_with_token(client, auth_on, user, auth_headers):
    r = await client.post(
        "/api/v1/listing/chat",
        json={"message": "生成一款便携咖啡研磨器的标题"},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text


async def test_demo_mode_allows_anonymous(client, auth_off):
    r = await client.post("/api/v1/listing/chat", json={"message": "生成标题"})
    assert r.status_code == 200, r.text


# ====== 账户侧租户上下文：已删除，不得复活（P1-c 收拢 2026-09-16）======
#
# 收拢前这里有三条用例，验证 `tenant_context`（ContextVar + 替换式写入代理）
# 的并发隔离与只读语义。那套设施已随账户侧实体（`shops` 表 / `shop_router.py`）
# 一并删除 —— 因为它是 P0 事故（BOLA 跨租户写入）的**载体**：
#
#   `TenantMiddleware` 往里写**未校验**的原始 `X-Shop-ID`，
#   而 `modules/product_research/agent_product_research.py::_write_candidates`
#   直读它当作写库归属 ⇒「带自己的 token + 改一下请求头」就能把候选写进别人的
#   选品库（探针 r84d 实测：有校验的端点 403，本路径 200 且落库对齐受害店铺）。
#
# ⇒ 与其继续验证"这个容器并发安全"，正确做法是**验证它不存在**：
#   一个不存在的通道不可能被写错。

def test_tenant_context_family_is_gone():
    """
    账户侧租户上下文设施必须**一个都不在**（防止有人"顺手加回来"）。

    ★ 为什么删掉旧用例、换成这条：旧用例的前提是"这个容器要存在且并发安全"。
      真实结论是"这个容器本身就不该存在" —— 留着旧用例等于替一个已废除的
      设计背书，还会让人以为 `tenant_context` 仍是被支持的 API。
    ★ 为什么逐个点名每一个符号：只断言 `tenant_context` 不存在挡不住
      "换个名字再写一个同类通道"；逐个列出等于把**设计决定**写成可执行判据。
    ★ 补充：AST 级的同类守卫见
      `tests/test_tenant_id_spaces.py::test_deleted_shops_side_symbols_do_not_come_back`。
    """
    import core.tenant.middleware as tmw

    gone = [
        "TenantContext", "_tenant_context_var", "_read_context", "_update_context",
        "_TenantContextProxy", "tenant_context", "get_tenant_context",
        "_require_owned", "get_tenant_from_header", "get_optional_tenant",
        "get_tenant_from_query", "require_shop_owner",
    ]
    leaked = [n for n in gone if hasattr(tmw, n)]
    assert not leaked, (
        f"core/tenant/middleware.py 里又出现了已废除的账户侧租户上下文符号：{leaked}。"
        f"它们是 P0 跨租户写入事故的载体（未校验的 X-Shop-ID 被存进请求级上下文，"
        f"供任意读取方当写库归属用）。要拿店铺 ID 请用 `get_current_shop_id*`。"
    )


def test_tenant_middleware_registered():
    """TenantMiddleware 必须真正挂在 app 上（历史 bug：定义了但没注册）"""
    from main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "TenantMiddleware" in names


# ====== 店铺归属校验 ======
#
# ★ P1-c（2026-09-16）迁移说明：本文件原先有一条 `test_shop_ownership_enforced`，
#   打的是**账户侧** `GET /api/v1/shops/{uuid}`（`shops` 表 / UUID 主键）。
#   该端点已随账户侧实体整体删除（实测生产 0 调用点），用例随之删除。
#
#   业务侧的归属校验现在由 `tests/test_account_store_hierarchy.py` 完整覆盖：
#     陌生人 403 / owner 放行 / 账户成员可读可写但不可删 / viewer 只读 /
#     成员被移除后立刻失去访问。
#   ⇒ 刻意**不**在本文件保留一份更弱的副本：同一判据在两处实现必然漂移，
#     而漂移掉的那一份永远测不到。


# ====== 口令哈希轮数：开关接线 + 默认值守护 ======
#
# 背景（2026-09-16 实测）：bcrypt rounds=12 ⇒ 单次 hash 209ms / verify 207ms。
# `user` 夹具每条用例都要 register+login 一次 ⇒ 每例白花 416ms；
# 全量 627 项里 25 项依赖该夹具 ⇒ 合计 17.73s，其中 bcrypt ≈10.4s。
# 于是把轮数做成配置项（默认 12 不动），由 tests/conftest.py 降到 4。
# 下面三条用例保证这个「降轮」既**真的生效**、又**没有削弱生产**。


async def test_hash_password_honors_configured_rounds():
    """
    开关必须真的接线（不是摆设）：轮数变 ⇒ 哈希串里的成本因子随之变。

    ★ bcrypt 哈希自带成本因子（`$2b$<rounds>$...`），所以「有没有生效」
      可以直接从产物上看出来，不用计时 —— 计时会被机器负载干扰。
    ★ 正反两向都验：4 轮的哈希与 12 轮的哈希都要能被 verify 通过，
      证明降轮只影响**耗时**，不影响**互验兼容性**（历史数据仍可登录）。
    """
    prev = config.password_hash_rounds
    try:
        config.password_hash_rounds = 4
        h4 = hash_password("pytest123456")
        config.password_hash_rounds = 12
        h12 = hash_password("pytest123456")
    finally:
        config.password_hash_rounds = prev

    assert h4.startswith("$2b$04$"), f"轮数 4 未生效，产物={h4[:20]}"
    assert h12.startswith("$2b$12$"), f"轮数 12 未生效，产物={h12[:20]}"
    assert verify_password("pytest123456", h4), "降轮后的哈希无法自验"
    assert verify_password("pytest123456", h12), "12 轮哈希无法自验"
    assert not verify_password("wrong-password", h4), "错误口令竟通过验证"


def test_password_hash_rounds_default_stays_production_grade():
    """
    字段**默认值**必须保持 >= 12。

    ★ 为什么单独要一条：测试进程里 rounds 被 conftest 降到 4，所以
      「默认值被改成 4」这件事在测试中**看不出来**——套件照样全绿。
      而它意味着生产环境的口令哈希强度静默掉到 1/256，且没有任何报错。
      「测试里调低」与「默认值调低」必须可区分，故这里直接读字段默认值。
    """
    from core.config import Settings

    d = Settings.model_fields["password_hash_rounds"].default
    assert d >= 12, (
        f"password_hash_rounds 默认值被降到了 {d} —— 生产会静默变弱。"
        f"测试提速请改 tests/conftest.py，不要动默认值"
    )


def test_production_guard_rejects_lowered_password_rounds(prod_settings_kwargs):
    """
    生产环境配了低轮数必须**拒绝启动**；合规值必须放行（护栏别过宽）。

    ★ 与 mock 支付网关护栏同一思路：方向相反，道理相同 ——
      「静默放行」比「启动失败」危险得多。

    ★★ 合规基线已收敛到 `tests/conftest.py::prod_settings_kwargs`。
      此前本文件与 test_billing_payment.py **各自**维护一份 production
      Settings 入参，每加一条生产护栏就要两处同步补合规值，漏一处就表现为
      "正向用例被新护栏打红"（已经发生过三次：P1-d 的 METRICS_TOKEN、
      P1-b 的邮件通道与锁定阈值）。现在只有一处。
    """
    from core.config import Settings

    # 正向：合规配置不得因本项被拦（否则护栏变成「生产永远起不来」）
    Settings(**prod_settings_kwargs(password_hash_rounds=12))

    # 反向：低轮数必须被拦，且错误信息要指名道姓
    with pytest.raises(ValueError) as ei:
        Settings(**prod_settings_kwargs(password_hash_rounds=4))
    msg = str(ei.value)
    assert "PASSWORD_HASH_ROUNDS" in msg, msg
    assert "12" in msg, msg


# ====== P0 修复回归（2026-09-16）======
#
# 本轮修两个「方向错了」的缺陷：
#   A. 跨租户写入（BOLA）：`TenantMiddleware` 用**未校验**的原始 `X-Shop-ID`
#      写业务上下文，而 `product_research._write_candidates` 直读该上下文当
#      写库归属 ⇒ 带上自己的 token、改一下请求头，候选就落进别人的选品库。
#   B. refresh token 永不过期：`/auth/refresh` 用 `decode_expired_token()`
#      （内部 `verify_exp: False`）的返回值放行 ⇒ exp 校验从未发生。


async def _login_token(client, email: str, password: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert r.status_code == 200, r.text[:200]
    return r.json()["access_token"]


async def _make_store(store_id: str, owner_id) -> None:
    """在 stores_store 建一行（owner_id=None 表示"无主店铺"）。"""
    from core.database import async_session_factory
    from modules.stores.db_model import StoreRecord

    async with async_session_factory() as db:
        db.add(StoreRecord(
            id=store_id, name=f"[test] {store_id}",
            platform="amazon_us", tenant_id="default_tenant",
            owner_id=owner_id,
        ))
        await db.commit()


async def _drop_store(store_id: str) -> None:
    from sqlalchemy import text
    from core.database import async_session_factory

    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM candidates WHERE shop_id = :s"), {"s": store_id})
        await db.execute(text("DELETE FROM stores_store WHERE id = :s"), {"s": store_id})
        await db.commit()


async def _count_candidates(shop_id: str) -> int:
    from sqlalchemy import text
    from core.database import async_session_factory

    async with async_session_factory() as db:
        return (await db.execute(
            text("SELECT count(*) FROM candidates WHERE shop_id = :s"), {"s": shop_id}
        )).scalar()


def test_tenant_middleware_never_writes_business_context():
    """
    `TenantMiddleware` 只做可观测性，**不得**写 `tenant_context`（不变量守卫）。

    ★ 为什么用源码断言而不是行为断言（刻意的）
      这条缺陷的特征是「脏值在上游被写入、读取方在别处」。行为测试只能覆盖
      **我已经知道的**读取方；而本次事故之所以成立，恰恰因为读取方当时没人知道
      —— `product_research._write_candidates` 直读上下文，于是「改个请求头」
      就变成了「写进别人的选品库」（探针 r84d 实测 200 + 落库归属受害店铺）。

    ★★ 必须走 **AST**，不能对源码做字符串匹配
      本类方法的 docstring 里**逐字引用**了修复前那行代码，字符串匹配会命中
      注释/文档文本 ⇒ "代码改对了、测试反而红"（本用例第一版就栽在这里）。
      AST 只反映真实语法结构，注释与 docstring 都不进节点树。

    ★ 与本文件 `test_password_hash_rounds_default_stays_production_grade`
      同一类型：钉住一次修复，防的是"以后有人图方便又写回去"。

    ★ P1-c（2026-09-16）补充：`tenant_context` 这条通道本身**已被删除**
      （见 `core/tenant/middleware.py` 的模块 docstring），所以本断言现在
      是「恒真」的 —— 但**不能删**：它守的是「别再引入一条未校验的租户
      身份通道」，删掉它的那一刻下一个人就失去了这道提醒。
      `tests/test_tenant_id_spaces.py` 从 AST 层面兜底，两条构成双闸。
    """
    import ast
    import inspect
    import textwrap

    from core.tenant.middleware import TenantMiddleware

    tree = ast.parse(textwrap.dedent(inspect.getsource(TenantMiddleware)))

    written = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("set_shop", "set_shop_id")
    ]
    assert written == [], (
        f"TenantMiddleware 又写业务上下文了：{written} —— 它手里的 X-Shop-ID 是"
        f"**未经校验**的原始请求头，写进上下文等于恢复了一条未校验的租户身份注入"
        f"通道。该值只应放进 request.state.shop_id（日志用）。"
    )

    # 可观测性不能跟着一起丢（请求日志依赖它）—— 同样走 AST
    assigned = [
        t.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        for t in node.targets
        if isinstance(t, ast.Attribute)
    ]
    assert "shop_id" in assigned, (
        "request.state.shop_id 的赋值没了 —— 请求日志会丢掉"
        "「这条请求声称属于哪个店铺」"
    )

async def test_product_research_chat_rejects_forged_shop_header(client, auth_on, user):
    """
    对话入口必须校验店铺归属：拿**别人的/无主的**店铺 ID 当 `X-Shop-ID` → 403 + 零写入。

    修复前实测（探针 r84d 三段对照）：同一 token，同一伪造头 ——
      `/api/v1/candidates` → 403（有归属校验），
      `/product-research/chat` → 200 且候选落进受害店铺。
    """
    import uuid

    mine = f"store_p0_a_{uuid.uuid4().hex[:8]}"
    victim = f"store_p0_b_{uuid.uuid4().hex[:8]}"
    await _make_store(mine, user["user_id"])
    await _make_store(victim, None)          # 无主店铺：非 admin 一律拒绝
    try:
        r = await client.post(
            "/api/v1/product-research/chat",
            json={"message": "把 B0CGLKP2R1 加入选品库",
                  "context_id": f"ctx-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {user['token']}", "X-Shop-ID": victim},
        )
        assert r.status_code == 403, (
            f"伪造店铺头必须被拒，实际 {r.status_code} {r.text[:200]}"
        )
        assert await _count_candidates(victim) == 0, "被拒的请求不该在受害店铺留下任何数据"
    finally:
        await _drop_store(mine)
        await _drop_store(victim)


async def test_product_research_chat_writes_to_own_shop(client, auth_on, user):
    """
    反向保护（防误伤）：带**自己**店铺头的入库必须照常成功，且落在自己分区。

    守卫若把正常路径也堵死，"修好了"就只是"关掉了功能"。
    """
    import uuid

    mine = f"store_p0_own_{uuid.uuid4().hex[:8]}"
    await _make_store(mine, user["user_id"])
    try:
        assert await _count_candidates(mine) == 0, "用例前提：该店铺开始没有候选"

        r = await client.post(
            "/api/v1/product-research/chat",
            json={"message": "把 B0CGLKP2R1 加入选品库",
                  "context_id": f"ctx-{uuid.uuid4().hex[:8]}"},
            headers={"Authorization": f"Bearer {user['token']}", "X-Shop-ID": mine},
        )
        assert r.status_code == 200, r.text[:300]
        assert await _count_candidates(mine) == 1, (
            "正常入库被守卫误伤 —— 检查 shop_id 是否一路带到了 "
            f"`_write_candidates`（期望 {mine}）；响应：{r.text[:300]}"
        )
    finally:
        await _drop_store(mine)


async def test_refresh_rejects_expired_token(client, user):
    """
    过期的 refresh token 必须 401。

    修复前实测（探针 r84e）：造一个"过期 30 天"的 refresh token 打 `/auth/refresh`
    → **200**，换回全新的 access + refresh 对。根因是放行用的
    `decode_expired_token()` 内部写着 `options={"verify_exp": False}`
    ⇒ `jwt_refresh_token_expire_days = 7` 是**装饰性配置**，
    且每次刷新都续期 = 永久会话。
    """
    from datetime import timedelta
    from core.auth.jwt_handler import create_refresh_token

    expired = create_refresh_token(user["user_id"], expires_delta=timedelta(days=-1))
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": expired})
    assert r.status_code == 401, (
        f"过期 refresh token 竟被放行：{r.status_code} {r.text[:200]}"
    )
    assert "access_token" not in r.json(), "拒绝时不得下发任何 token"


async def test_refresh_accepts_valid_token_from_json_body(client, user):
    """
    有效 refresh token（**JSON body**）→ 200，换回可用的新 token 对。

    ★ 这条同时钉住"入参位置"：修复前端点是裸标量形参 `refresh_token: str`，
      FastAPI 对这种形参默认按 **query** 解析，而前端发的是
      `post('/auth/refresh', { refresh_token })`（body）⇒ 服务端永远读到 None
      ⇒ 稳定 422（日志实证 `POST /api/v1/auth/refresh -> 422`）。
      前端拦截器于是判定"刷新失败"→ `logout()` + 跳登录页：
      **access token 一到期就被踢回登录页，「自动刷新」从未生效过。**
    """
    from core.auth.jwt_handler import create_refresh_token, verify_token

    fresh = create_refresh_token(user["user_id"])
    r = await client.post("/api/v1/auth/refresh", json={"refresh_token": fresh})
    assert r.status_code == 200, f"body 传参必须被接受：{r.status_code} {r.text[:200]}"

    body = r.json()
    assert verify_token(body["access_token"], expected_type="access") is not None
    assert verify_token(body["refresh_token"], expected_type="refresh") is not None


async def test_refresh_rejects_access_token(client, user):
    """拿 access token 当 refresh 用 → 401（类型隔离绕不过去）。"""
    from core.auth.jwt_handler import create_access_token

    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": create_access_token({"sub": user["user_id"]})},
    )
    assert r.status_code == 401, r.text[:200]


async def test_refresh_token_not_accepted_via_query_string(client, user):
    """
    `?refresh_token=...` 必须**不再**被接受（防 token 进日志与浏览器历史）。

    query 里的 token 会留在 Nginx access log、浏览器历史、Referer 里；
    改成 body 后这条路径应当直接失效（缺 body 必填字段 → 422）。
    """
    from core.auth.jwt_handler import create_refresh_token

    fresh = create_refresh_token(user["user_id"])
    r = await client.post(f"/api/v1/auth/refresh?refresh_token={fresh}")
    assert r.status_code == 422, (
        f"query 传参应已失效（token 不该出现在 URL 里），实际 {r.status_code} {r.text[:200]}"
    )
