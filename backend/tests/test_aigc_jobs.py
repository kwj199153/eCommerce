"""AIGC 异步任务（P1-5）测试。

覆盖三类风险，每一类都对应一个「会真出事」的场景：

A. **钱**：连点两次 / 并发双击 ⇒ 只能出一次图（出图按张计费，≈¥0.14/张）
B. **权**：任务状态端点按归属过滤 ⇒ 拿到 job_id 也读不到别人的素材链接（P0-1 同类）
C. **假排队**：执行器不可用时必须显式失败 ⇒ 绝不留一条永远 pending 的任务

外加两条针对本项目**已踩过**的坑：
  - async SQLAlchemy 的 ``MissingGreenlet``（rollback 后再读库）
  - Celery worker 里 ``asyncio.run`` 反复新建 event loop 导致的连接跨 loop 复用
    （现象是「第一个任务成功、第二个任务必挂」，只跑一次验证会全绿放行）
"""

import asyncio
import uuid

import pytest
import pytest_asyncio

from modules.aigc_media import job_service
from modules.aigc_media.db_model import (
    INFLIGHT_STATUSES,
    AIGCJobRecord,
    is_terminal,
)


# ============================================================
# 夹具
# ============================================================

@pytest_asyncio.fixture
async def job_user(client):
    """注册一个临时用户；结束时清掉它名下的任务与账号。"""
    email = f"aigcjob-{uuid.uuid4().hex[:10]}@example.com"
    password = "pytest123456"

    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "aigc job user"},
    )
    assert r.status_code in (200, 201), f"注册失败: {r.status_code} {r.text}"

    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, f"登录失败: {lr.status_code} {lr.text}"
    token = lr.json()["access_token"]

    from sqlalchemy import select, text

    from core.database import get_async_session
    from core.identity.models import User

    async with get_async_session() as db:
        uid = (
            await db.execute(select(User.id).where(User.email == email))
        ).scalar_one()

    # ★ 在该用户名下建一个真实店铺，并把 id 放进 X-Shop-ID 头。两个原因：
    #   ① 迁移 d5e6f7a8b9c0 后 aigc_jobs.shop_id 有指向 stores_store 的外键；
    #      不带头时 shop_id 落成空串 "" ⇒ 写入被数据库直接拒绝
    #   ② 生产模式（auth_on）下 get_current_shop_id 会校验
    #      stores_store.owner_id == 当前用户 ⇒ 店铺必须属于这个测试用户
    from core.stores import StoreRecord
    shop_id = f"store_aigc_{uuid.uuid4().hex[:8]}"
    async with get_async_session() as db:
        db.add(StoreRecord(id=shop_id, name=f"[test] {shop_id}", platform="amazon_us",
                           tenant_id="default_tenant", owner_id=uid))
        await db.commit()

    payload = {
        "email": email, "token": token, "user_id": uid, "shop_id": shop_id,
        "headers": {"Authorization": f"Bearer {token}", "X-Shop-ID": shop_id},
    }

    yield payload

    async with get_async_session() as db:
        # 先删任务行（子），再删店铺（父）—— 外键是 RESTRICT，反序删不掉
        await db.execute(text("DELETE FROM aigc_jobs WHERE user_id = :u"), {"u": uid})
        await db.execute(text("DELETE FROM stores_store WHERE id = :s"), {"s": shop_id})
        await db.execute(text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": uid})
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await db.commit()


@pytest.fixture
def no_broker(monkeypatch):
    """把投递换成「什么都不做」，让 API 测试不必依赖真实 Redis/Celery。

    ★ 只是**记录**投递调用，不改变任何状态流转 —— 被测的状态逻辑仍然真实执行。
    """
    calls: list[tuple[str, dict]] = []

    def _fake_enqueue(job_id: str, ctx=None):
        calls.append((job_id, ctx or {}))
        return f"fake-task-{job_id}"

    monkeypatch.setattr(job_service, "enqueue", _fake_enqueue)
    return calls


#: 一份「便宜」的合法入参（真正出图会被下面的 task 夹具打桩，不会花钱）
def _asset_params() -> dict:
    return {
        "product_name": "测试用保温杯",
        "image_types": ["spu-main"],
        "count_per_type": 1,
    }


async def _submit(client, headers, *, kind="asset_generate", params=None):
    return await client.post(
        "/api/v1/aigc/jobs",
        json={"kind": kind, "params": params if params is not None else _asset_params()},
        headers=headers,
    )


# ============================================================
# A. 提交：落库 / 去重 / 校验
# ============================================================

@pytest.mark.asyncio
async def test_submit_job_creates_pending_row(client, job_user, no_broker, auth_on):
    """提交返回 202、落库为 pending、归属与 request_id 都写进去了。"""
    r = await _submit(client, job_user["headers"])
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["deduplicated"] is False
    job = body["job"]
    assert job["status"] == "pending"
    assert job["is_terminal"] is False
    assert job["kind_label"] == "静态素材批量出图"

    from core.database import get_async_session

    async with get_async_session() as db:
        row = await db.get(AIGCJobRecord, job["id"])
        assert row is not None
        assert row.status == "pending"
        assert row.user_id == job_user["user_id"]
        assert row.dedupe_key, "去重指纹不能为空，否则并发去重失效"
        assert row.payload["product_name"] == "测试用保温杯"
    assert len(no_broker) == 1, "提交成功后必须且只投递一次"
    assert no_broker[0][0] == job["id"]


@pytest.mark.asyncio
async def test_double_submit_is_deduplicated(client, job_user, no_broker, auth_on):
    """★ 连点两次 ⇒ 只有一条任务、只投递一次（不重复出图、不重复计费）。"""
    r1 = await _submit(client, job_user["headers"])
    r2 = await _submit(client, job_user["headers"])
    assert r1.status_code == 202 and r2.status_code == 202

    b1, b2 = r1.json(), r2.json()
    assert b2["deduplicated"] is True, "第二次提交必须被去重"
    assert b1["job"]["id"] == b2["job"]["id"], "去重后必须返回同一条任务"
    assert b1["message"] != b2["message"] or b2["deduplicated"] is True

    from core.database import get_async_session
    from sqlalchemy import func, select

    async with get_async_session() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(AIGCJobRecord)
                .where(AIGCJobRecord.user_id == job_user["user_id"])
            )
        ).scalar_one()
    assert count == 1, f"连点两次应只落库 1 条，实际 {count} 条"
    assert len(no_broker) == 1, "去重的那次不应再投递"


@pytest.mark.asyncio
async def test_concurrent_double_click_deduplicated(client, job_user, no_broker, auth_on):
    """★★ 并发双击（4 个同时提交）⇒ 仍然只有 1 条任务。

    这是「先查再插」挡不住的场景：4 个请求都会读到「当前无进行中任务」。
    靠的是 DB 的部分唯一索引 + ``INSERT ... ON CONFLICT DO NOTHING``。
    """
    responses = await asyncio.gather(
        *[_submit(client, job_user["headers"]) for _ in range(4)]
    )
    codes = [r.status_code for r in responses]
    assert codes == [202] * 4, codes

    ids = {r.json()["job"]["id"] for r in responses}
    assert len(ids) == 1, f"并发双击后应只剩一个 job_id，实际 {ids}"

    from core.database import get_async_session
    from sqlalchemy import func, select

    async with get_async_session() as db:
        count = (
            await db.execute(
                select(func.count())
                .select_from(AIGCJobRecord)
                .where(AIGCJobRecord.user_id == job_user["user_id"])
            )
        ).scalar_one()
    assert count == 1, f"并发双击应只落库 1 条，实际 {count} 条"
    assert len(no_broker) == 1, "只应投递一次"


@pytest.mark.asyncio
async def test_different_params_not_deduplicated(client, job_user, no_broker, auth_on):
    """反向用例：入参不同 ⇒ 必须各自成任务。

    防止去重写成「同一用户只允许一条任务」（那会让用户永远只能生成一次）。
    """
    p2 = _asset_params()
    p2["image_types"] = ["scene"]
    r1 = await _submit(client, job_user["headers"])
    r2 = await _submit(client, job_user["headers"], params=p2)
    assert r1.json()["job"]["id"] != r2.json()["job"]["id"]
    assert r2.json()["deduplicated"] is False


@pytest.mark.asyncio
async def test_dedupe_key_stable_under_dict_order():
    """去重指纹必须与 dict 键顺序无关（否则同一次点击的两个请求算不出同一个键）。"""
    a = job_service.build_dedupe_key("asset_generate", {"x": 1, "y": "测试"})
    b = job_service.build_dedupe_key("asset_generate", {"y": "测试", "x": 1})
    assert a == b
    c = job_service.build_dedupe_key("asset_generate", {"x": 2, "y": "测试"})
    assert a != c
    # 不同 kind 不能撞键
    assert job_service.build_dedupe_key("image_generate", {"x": 1}) != a


@pytest.mark.asyncio
async def test_unknown_kind_rejected(client, job_user, no_broker, auth_on):
    r = await _submit(client, job_user["headers"], kind="not_a_real_kind")
    assert r.status_code == 400
    assert "未知任务类型" in r.json()["detail"]


@pytest.mark.asyncio
async def test_invalid_params_rejected(client, job_user, no_broker, auth_on):
    """异步端点不是「把 dict 直接丢进队列」—— 入参校验强度与同步端点一致。"""
    r = await _submit(client, job_user["headers"], params={"count_per_type": 999})
    assert r.status_code == 422, r.text

    from core.database import get_async_session
    from sqlalchemy import func, select

    async with get_async_session() as db:
        count = (
            await db.execute(select(func.count()).select_from(AIGCJobRecord))
        ).scalar_one()
    assert count == 0, "校验失败不应留下任务记录"


@pytest.mark.asyncio
async def test_inflight_limit_returns_429(client, job_user, no_broker, auth_on):
    """进行中任务超上限 ⇒ 429（别让一个用户占满整条队列）。"""
    for i in range(job_service.MAX_INFLIGHT_PER_USER):
        params = _asset_params()
        params["extra_description"] = f"批次-{i}"
        r = await _submit(client, job_user["headers"], params=params)
        assert r.status_code == 202, r.text

    params = _asset_params()
    params["extra_description"] = "超出上限那次"
    r = await _submit(client, job_user["headers"], params=params)
    assert r.status_code == 429
    assert "进行中" in r.json()["detail"]


@pytest.mark.asyncio
async def test_executor_unavailable_marks_failed_not_pending(
    client, job_user, auth_on, monkeypatch
):
    """★★ 执行器不可用 ⇒ 503 **且**任务被显式标成 failed。

    绝不能只报错不改状态：那样用户列表里会多出一条永远「排队中」的任务，
    界面上一直转圈而队列里根本没有它 —— 最难排查的一类故障。
    """
    def _boom(job_id, ctx=None):
        raise job_service.ExecutorUnavailable("无法连接 Redis broker")

    monkeypatch.setattr(job_service, "enqueue", _boom)

    r = await _submit(client, job_user["headers"])
    assert r.status_code == 503
    assert "异步执行器不可用" in r.json()["detail"]
    assert "worker" in r.json()["detail"], "报错要给出可执行的整改指引"

    from core.database import get_async_session
    from sqlalchemy import select

    async with get_async_session() as db:
        rows = (
            await db.execute(
                select(AIGCJobRecord).where(AIGCJobRecord.user_id == job_user["user_id"])
            )
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "failed", f"应显式失败，实际 {rows[0].status}"
    assert "Redis" in rows[0].error
    assert rows[0].finished_at is not None


# ============================================================
# B. 授权：按归属过滤
# ============================================================

async def _make_other_user(client):
    """再注册一个用户，用于验证跨用户读不到对方的任务。"""
    email = f"aigcjob-other-{uuid.uuid4().hex[:10]}@example.com"
    password = "pytest123456"
    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "other"},
    )
    assert r.status_code in (200, 201), r.text
    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, lr.text

    from sqlalchemy import select

    from core.database import get_async_session
    from core.identity.models import User

    async with get_async_session() as db:
        uid = (await db.execute(select(User.id).where(User.email == email))).scalar_one()
    return {"email": email, "user_id": uid, "headers": {"Authorization": f"Bearer {lr.json()['access_token']}"}}


async def _drop_user(user_id: str):
    from sqlalchemy import text

    from core.database import get_async_session

    async with get_async_session() as db:
        await db.execute(text("DELETE FROM aigc_jobs WHERE user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": user_id})
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": user_id})
        await db.commit()


@pytest.mark.asyncio
async def test_job_query_is_owner_scoped(client, job_user, no_broker, auth_on):
    """★★ 别人的 job_id 一律 404（BOLA/IDOR 同类防护）。

    ★ 返回 404 而不是 403：403 等于确认「这个 job_id 存在」，
    会把任务的 ID 空间泄露出去。
    """
    r = await _submit(client, job_user["headers"])
    job_id = r.json()["job"]["id"]

    other = await _make_other_user(client)
    try:
        r2 = await client.get(f"/api/v1/aigc/jobs/{job_id}", headers=other["headers"])
        assert r2.status_code == 404, (
            f"越权读到了别人的任务！status={r2.status_code} body={r2.text}"
        )

        # 自己读得到
        r3 = await client.get(f"/api/v1/aigc/jobs/{job_id}", headers=job_user["headers"])
        assert r3.status_code == 200
        assert r3.json()["job"]["id"] == job_id

        # 列表也只看得到自己的
        r4 = await client.get("/api/v1/aigc/jobs", headers=other["headers"])
        assert r4.status_code == 200
        assert r4.json()["jobs"] == [], "不应看到别人的任务"
    finally:
        await _drop_user(other["user_id"])


@pytest.mark.asyncio
async def test_job_list_returns_own_jobs_and_shapes(client, job_user, no_broker, auth_on):
    """列表返回自己的任务，且列表项**不含 result 大字段**（列表页不该传整张图的数据）。"""
    await _submit(client, job_user["headers"])
    r = await client.get("/api/v1/aigc/jobs", headers=job_user["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["jobs"][0]
    assert "result" not in item, "列表项不应带 result（避免把大对象全拉出来）"
    assert item["created_at"].endswith("Z"), "时间戳必须是带 Z 的 UTC，否则前端会早 8 小时"


@pytest.mark.asyncio
async def test_missing_job_returns_404(client, job_user, auth_on):
    r = await client.get("/api/v1/aigc/jobs/job_doesnotexist", headers=job_user["headers"])
    assert r.status_code == 404


# ============================================================
# C. 任务执行：状态机 / 幂等 / 跨 loop
# ============================================================

@pytest_asyncio.fixture
async def db_job_factory(client, job_user, auth_on):
    """直接落库一条 pending 任务（不经过 HTTP），返回 job_id 与清理函数。"""
    created: list[str] = []

    async def _create(params: dict | None = None) -> str:
        from core.database import get_async_session

        async with get_async_session() as db:
            job, _ = await job_service.submit_job(
                db,
                kind="asset_generate",
                payload=params if params is not None else _asset_params(),
                user_id=job_user["user_id"],
                shop_id="store_test",
                request_id="req-test",
            )
            await db.commit()
            created.append(job.id)
            return job.id

    yield _create

    from sqlalchemy import text

    from core.database import get_async_session

    async with get_async_session() as db:
        for jid in created:
            await db.execute(text("DELETE FROM aigc_jobs WHERE id = :i"), {"i": jid})
        await db.commit()


def _stub_assets_result(assets: int = 2):
    """构造一个与真实 service 同形状的返回值（不打网络、不花钱）。"""
    async def _fake(request):
        return {
            "success": True,
            "data": {
                "mode": "text2image",
                "model": "wanx2.1-t2i-turbo",
                "assets": [
                    {"id": f"asset_{i}", "type": "spu-main", "url": f"/static/a{i}.png"}
                    for i in range(assets)
                ],
                "failed": [],
                "degraded": False,
                "source_image_used": False,
            },
            "message": f"已生成 {assets} 张素材",
        }
    return _fake


async def _read_job(job_id: str) -> AIGCJobRecord:
    from core.database import get_async_session

    async with get_async_session() as db:
        return await db.get(AIGCJobRecord, job_id)


@pytest.mark.asyncio
async def test_task_success_path(db_job_factory, monkeypatch):
    """任务成功：pending → running → succeeded，结果与张数落库。"""
    from modules.aigc_media.service import AIGCMediaService
    from modules.aigc_media.tasks import run_aigc_job

    monkeypatch.setattr(AIGCMediaService, "generate_assets", _stub_assets_result(3))

    job_id = await db_job_factory()
    # ★ 用 to_thread：任务体内部 asyncio.run 需要「没有正在运行的 event loop」的线程
    out = await asyncio.to_thread(run_aigc_job, job_id, {"shop_id": "store_test"})

    assert out["ok"] is True, out
    row = await _read_job(job_id)
    assert row.status == "succeeded"
    assert row.assets_count == 3
    assert row.started_at is not None and row.finished_at is not None
    assert len(row.result["assets"]) == 3
    assert row.error == ""


@pytest.mark.asyncio
async def test_task_business_failure_marks_failed(db_job_factory, monkeypatch):
    """内核返回 success=False ⇒ 任务 failed，并把原因原样带出（不静默）。"""
    from modules.aigc_media.service import AIGCMediaService
    from modules.aigc_media.tasks import run_aigc_job

    async def _fail(request):
        return {"success": False, "error": "真实出图已关闭", "message": "真实出图已关闭（AIGC_IMAGE_REAL_GEN=0）", "data": {}}

    monkeypatch.setattr(AIGCMediaService, "generate_assets", _fail)

    job_id = await db_job_factory()
    out = await asyncio.to_thread(run_aigc_job, job_id, None)

    assert out["ok"] is False
    row = await _read_job(job_id)
    assert row.status == "failed"
    assert "AIGC_IMAGE_REAL_GEN" in row.error, "失败原因必须落到任务记录上"


@pytest.mark.asyncio
async def test_task_exception_is_caught_and_recorded(db_job_factory, monkeypatch):
    """内核抛异常 ⇒ 任务边界兜住，落成 failed，不冒泡成「永远 running」。"""
    from modules.aigc_media.service import AIGCMediaService
    from modules.aigc_media.tasks import run_aigc_job

    async def _boom(request):
        raise RuntimeError("出图服务 500")

    monkeypatch.setattr(AIGCMediaService, "generate_assets", _boom)

    job_id = await db_job_factory()
    out = await asyncio.to_thread(run_aigc_job, job_id, None)

    assert out["ok"] is False
    row = await _read_job(job_id)
    assert row.status == "failed"
    assert "RuntimeError" in row.error and "出图服务 500" in row.error


@pytest.mark.asyncio
async def test_task_is_idempotent_on_terminal_job(db_job_factory, monkeypatch):
    """★ 已是终态的任务被重复投递（acks_late 重投递）⇒ 直接跳过，不重复出图。

    重复出图 = 重复花钱，所以这个出口必须在**业务内核之前**。
    """
    from modules.aigc_media.service import AIGCMediaService
    from modules.aigc_media.tasks import run_aigc_job

    calls = {"n": 0}

    async def _counted(request):
        calls["n"] += 1
        return await _stub_assets_result(1)(request)

    monkeypatch.setattr(AIGCMediaService, "generate_assets", _counted)

    job_id = await db_job_factory()
    await asyncio.to_thread(run_aigc_job, job_id, None)
    assert calls["n"] == 1

    out2 = await asyncio.to_thread(run_aigc_job, job_id, None)
    assert calls["n"] == 1, "终态任务的重复投递不应再执行内核（否则重复计费）"
    assert out2.get("skipped") == "already_terminal"


@pytest.mark.asyncio
async def test_task_runs_twice_without_event_loop_conflict(db_job_factory, monkeypatch):
    """★★ 同一个 worker 进程连续跑两个任务都必须成功。

    这是本项目 async SQLAlchemy + Celery 最容易踩的坑：任务体里
    ``asyncio.run`` 每次新建 event loop，若复用模块级全局 engine，
    asyncpg 连接会跨 loop ⇒ 第二次执行报
    ``Task got Future attached to a different loop``。
    只跑一个任务的验证会**全绿放行**，所以这里必须连跑两次。
    """
    from modules.aigc_media.service import AIGCMediaService
    from modules.aigc_media.tasks import run_aigc_job

    monkeypatch.setattr(AIGCMediaService, "generate_assets", _stub_assets_result(1))

    j1 = await db_job_factory()
    out1 = await asyncio.to_thread(run_aigc_job, j1, None)
    j2 = await db_job_factory({**_asset_params(), "extra_description": "第二单"})
    out2 = await asyncio.to_thread(run_aigc_job, j2, None)

    assert out1["ok"] is True, out1
    assert out2["ok"] is True, out2
    assert (await _read_job(j1)).status == "succeeded"
    assert (await _read_job(j2)).status == "succeeded"


@pytest.mark.asyncio
async def test_task_marks_failed_when_job_missing(monkeypatch):
    """任务记录不存在时显式返回失败，不抛异常（抛异常会让 Celery 反复重试一个不存在的任务）。"""
    from modules.aigc_media.tasks import run_aigc_job

    out = await asyncio.to_thread(run_aigc_job, "job_nonexistent_x", None)
    assert out["ok"] is False
    assert "不存在" in out["error"]


@pytest.mark.asyncio
async def test_terminal_status_helpers():
    """状态机口径的唯一来源：终态判定与 inflight 集合互补。"""
    assert is_terminal("succeeded") and is_terminal("failed")
    assert not is_terminal("pending") and not is_terminal("running")
    assert set(INFLIGHT_STATUSES) == {"pending", "running"}
