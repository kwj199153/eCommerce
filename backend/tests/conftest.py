"""
pytest 公共夹具

约定：
- 所有测试针对真实本地 PostgreSQL（tests 会创建并清理自己的临时用户）
- 需要鉴权的用例用 `auth_on` 夹具打开生产模式开关
- 不发起真实 LLM 请求：由下方的 `_no_real_llm` 自动夹具**强制兜底**，见其注释
"""

import uuid

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport

from core.config import config


# ====== 真实 LLM 出网总闸（autouse） ======
#
# 背景（实测）：本后端存在**两套彼此独立的 LLM 栈**——
#   栈 A：`ai_infra.base_agent.BaseAgent._llm_with_tools()` → LangChain `ChatOpenAI`
#         （走 OpenAI 兼容端点，工具路由/多轮 ReAct 用）
#   栈 B：`ai_infra.base_agent.BaseAgent.llm_stream/llm_chat()`
#         → `ai_infra.llm.dashscope_client.DashScopeLLM`（原生 httpx 流式，正文生成用）
#         （两栈现已同属唯一基类 BaseAgent：原 LLMEnabledAgent 已并入）
#
# 原先的 `fake_llm` 夹具**只补丁了栈 B 的 `DashScopeLLM.chat`**，于是：
#   - 栈 A 从未被拦截 → 真实调用 DashScope
#   - 栈 B 的 `chat_stream` 也没被补丁（只补了 `chat`）→ 真实流式调用
# 后果：大量「看起来已打桩」的用例实际在打真实 API，单个用例耗时 10~36s，
# 全量 488 项要 6 分 33 秒，且**结果依赖网络/额度/限流，不稳定**（同输入耗时 16.8s~36s 波动）。
#
# 修复思路：不去逐个补丁具体实现（新增一条调用路径就会漏），
# 而是在**网络出口**兜底——把 `httpx` 指向未配置的主机，任何真实出网都会
# 立刻 `ConnectError` 并走各 Agent 既有的降级分支（不再静默等待数十秒）。
# 这样新增 LLM 栈/新增端点也不会再悄悄打真 API。
#
# 需要真实 LLM 的用例（如 tests/test_llm_rag_integration.py）请显式声明
# `@pytest.mark.allow_real_llm` 放行。

_DASHSCOPE_HOST_MARKERS = ("dashscope.aliyuncs.com", "aliyuncs.com")


@pytest.fixture(autouse=True)
def _no_real_llm(request, monkeypatch):
    """
    自动夹具：默认阻断一切真实 LLM 出网（除非用例标记 allow_real_llm）。

    不改变业务代码：仅在做网络调用时抛 ConnectError，让 Agent 走既有降级分支。
    """
    if request.node.get_closest_marker("allow_real_llm"):
        yield
        return

    import httpx as _httpx

    real_send = _httpx.AsyncClient.send

    async def guarded_send(self, request, *args, **kwargs):
        url = str(getattr(request, "url", ""))
        if any(m in url for m in _DASHSCOPE_HOST_MARKERS):
            raise _httpx.ConnectError(
                "测试环境禁止真实 LLM 出网（conftest._no_real_llm）。"
                "如需真实调用请加 @pytest.mark.allow_real_llm",
                request=request,
            )
        return await real_send(self, request, *args, **kwargs)

    monkeypatch.setattr(_httpx.AsyncClient, "send", guarded_send)

    # 栈 A 走 LangChain `ChatOpenAI`，它有**自己的** httpx 客户端与传输层，
    # 上面的 `AsyncClient.send` 拦不到（实测：`/listing/chat` 仍耗时 9.5s）。
    # 这里直接把 BaseAgent 取 LLM 的入口换成离线桩，从源头断掉出网。
    #
    # ⚠️ 桩必须**照常上报 `usage_metadata`**。原因：
    # `/listing/chat` 这类端点的正文完全由本栈产出，真实 `ChatOpenAI` 会在
    # `AIMessage.usage_metadata` 里带回 token 数，`BaseAgent._llm_call_node`
    # 读到后经 `record_llm_usage` 落到订阅表。桩只需**如实上报 token 数**，
    # **不要自己记账** —— 那会与节点记账双计。
    from langchain_core.messages import AIMessage

    from ai_infra import base_agent as _ba

    _STUB_TEXT = "[测试桩] LLM 已离线，本响应由桩生成。"

    def _stub_message() -> AIMessage:
        # 只上报 token，**不记账**：记账由 `BaseAgent._llm_call_node` 统一负责。
        # （改造前该节点没有记账逻辑，桩是临时替代品；两者并存会双计。）
        input_tokens, output_tokens = 120, 80
        return AIMessage(
            content=_STUB_TEXT,
            usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
        )

    class _OfflineChat:
        """离线桩：不打网络，回固定文本并上报用量。"""

        def bind_tools(self, tools, **kwargs):
            return self

        async def ainvoke(self, messages, **kwargs):
            return _stub_message()

        async def astream(self, messages, **kwargs):
            yield _stub_message()

        def stream(self, messages, **kwargs):
            yield _stub_message()

        def invoke(self, messages, **kwargs):
            return _stub_message()

    monkeypatch.setattr(
        _ba.BaseAgent, "_get_default_llm", lambda self: _OfflineChat(), raising=False
    )
    monkeypatch.setattr(
        _ba.BaseAgent, "_llm_with_tools", lambda self: _OfflineChat(), raising=False
    )

    # 栈 B：`BaseAgent.llm_chat/llm_stream` → `DashScopeLLM.chat/chat_stream`。
    # 这里补丁**最底层的客户端方法**（而不是上层 wrapper），好处：
    #   1. `llm_chat` 的返回组装、`_update_stats` 的**计量上报**全都保持真实，
    #      `test_billing_metering` 的「LLM token/成本落库」断言依然有效；
    #   2. 新增调用路径只要最终落到 `DashScopeLLM` 就自动被拦住。
    # 注意必须**同时**补丁 `chat_stream`——原 `fake_llm` 只补了 `chat`，
    # 这是流式用例仍在打真 API 的原因之一。
    from ai_infra.llm import dashscope_client as _dc

    def _stub_response(self, *args, **kwargs):
        return _dc.LLMResponse(
            content="[测试桩] LLM 已离线，本响应由桩生成。",
            model="qwen-max",
            input_tokens=120,
            output_tokens=80,
            total_tokens=200,
            cost=0.0036,
            latency_ms=1,
            finish_reason="stop",
            raw_response={},
        )

    async def _stub_chat(self, messages, system_prompt=None, **kwargs):
        resp = _stub_response(self, messages, system_prompt, **kwargs)
        # 走真实统计/计量钩子，确保「LLM 消耗 → 计费」链路仍被覆盖
        self._update_stats(resp)
        return resp

    async def _stub_chat_stream(self, messages, system_prompt=None, **kwargs):
        for chunk in ("[测试桩] ", "LLM 已离线。"):
            yield chunk
        resp = _stub_response(self, messages, system_prompt, **kwargs)
        self._update_stats(resp)

    monkeypatch.setattr(_dc.DashScopeLLM, "chat", _stub_chat, raising=False)
    monkeypatch.setattr(_dc.DashScopeLLM, "chat_stream", _stub_chat_stream, raising=False)

    yield


# ====== 鉴权开关 ======

@pytest.fixture
def auth_on():
    """打开生产模式鉴权（要求 Bearer Token）"""
    prev = config.auth_required
    config.auth_required = True
    yield
    config.auth_required = prev


@pytest.fixture
def auth_off():
    """演示模式（匿名放行）"""
    prev = config.auth_required
    config.auth_required = False
    yield
    config.auth_required = prev


# ====== HTTP 客户端 ======

@pytest_asyncio.fixture
async def client():
    """基于 ASGI 的内存 HTTP 客户端（不经过网络）"""
    from main import app

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ====== 临时用户（含订阅） ======

@pytest_asyncio.fixture
async def user(client):
    """
    注册一个临时用户并返回其凭据。

    /register 会自动创建默认订阅，因此返回对象里带 subscription 信息。
    测试结束后删除该用户及其订阅。
    """
    email = f"pytest-{uuid.uuid4().hex[:10]}@example.com"
    password = "pytest123456"

    r = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "pytest user"},
    )
    assert r.status_code in (200, 201), f"注册失败: {r.status_code} {r.text}"

    lr = await client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert lr.status_code == 200, f"登录失败: {lr.status_code} {lr.text}"
    token = lr.json()["access_token"]

    # 查 user_id / subscription_id 供 DB 断言与清理
    from sqlalchemy import select, text
    from core.database import get_async_session
    from modules.user_subscription.models import User, Subscription

    async with get_async_session() as db:
        u = (await db.execute(select(User).where(User.email == email))).scalar_one()
        sub = (
            await db.execute(select(Subscription).where(Subscription.user_id == u.id))
        ).scalar_one_or_none()
        payload = {
            "email": email,
            "password": password,
            "token": token,
            "user_id": u.id,
            "subscription_id": sub.id if sub else None,
        }

    yield payload

    async with get_async_session() as db:
        await db.execute(
            text("DELETE FROM invoices WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(
            text("DELETE FROM payment_methods WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(
            text("DELETE FROM subscriptions WHERE user_id = :u"), {"u": payload["user_id"]}
        )
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": payload["user_id"]})
        await db.commit()


@pytest.fixture
def auth_headers(user):
    """带 Bearer Token 的请求头"""
    return {"Authorization": f"Bearer {user['token']}"}


# ====== LLM 打桩 ======

@pytest.fixture
def fake_llm(monkeypatch):
    """
    把 DashScopeLLM 的 chat / chat_stream 换成固定桩，避免真实调用与花费。

    仍会走 `_update_stats` / 计量钩子，因此能覆盖「LLM 消耗 → 计费」链路。
    """
    from ai_infra.llm import dashscope_client as dc

    def _make_response(input_tokens=120, output_tokens=80, cost=0.0036):
        return dc.LLMResponse(
            content="这是一段模拟的 LLM 回答。",
            model="qwen-max",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost=cost,
            latency_ms=5,
            finish_reason="stop",
            raw_response={},
        )

    async def fake_chat(self, messages, system_prompt=None, **kwargs):
        resp = _make_response()
        self._update_stats(resp)
        return resp

    async def fake_chat_stream(self, messages, system_prompt=None, **kwargs):
        for chunk in ["这是", "一段", "模拟的", "流式回答。"]:
            yield chunk
        dc.record_llm_usage(input_tokens=120, output_tokens=80, cost=0.0036, model="qwen-max")

    monkeypatch.setattr(dc.DashScopeLLM, "chat", fake_chat)
    monkeypatch.setattr(dc.DashScopeLLM, "chat_stream", fake_chat_stream)
    return {"response": _make_response}


# ====== 业务店铺上下文（需要 X-Shop-ID 的端点测试共用） ======
#
# 背景：spus / skus / assets / candidates / monitors / knowledge_* / *_groups …
# 全部按 shop_id 过滤（`get_current_shop_id` 从 `X-Shop-ID` 头取）。
# 所以凡是要写业务数据的端点测试，都得先有一个"当前店铺"，
# 且用例结束后必须把它连同其下数据一起清掉，否则开发库里会堆测试垃圾。

_TABLES_WITH_SHOP_ID_SQL = """
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN pg_class t ON t.relname = c.table_name
    JOIN pg_namespace n ON n.oid = t.relnamespace AND n.nspname = 'public'
    WHERE c.column_name = 'shop_id' AND c.table_schema = 'public'
"""

_FK_EDGES_SQL = """
    SELECT src.relname AS child, ref.relname AS parent
    FROM pg_constraint con
    JOIN pg_class src ON src.oid = con.conrelid
    JOIN pg_class ref ON ref.oid = con.confrelid
    WHERE con.contype = 'f'
"""


async def _shop_scoped_delete_order(session):
    """
    返回「带 shop_id 的表」的删除顺序：**先子表、后父表**。

    不硬编码表名：从 information_schema 取表，从 pg_constraint 取外键边，
    再拓扑排序。将来新增带 shop_id 的表（以及新的外键）会自动纳入。

    为什么不能随便顺序删：`skus.spu_id -> spus.id` 这类外键真实存在，
    先删 spus 会被数据库拒绝（子行还在），清理就失败了。
    """
    from sqlalchemy import text

    tables = set((await session.execute(text(_TABLES_WITH_SHOP_ID_SQL))).scalars().all())
    edges = (await session.execute(text(_FK_EDGES_SQL))).all()

    parents_of = {t: set() for t in tables}
    for child, parent in edges:
        if child in tables and parent in tables:
            parents_of[child].add(parent)

    order, remaining = [], set(tables)
    while remaining:
        # 「被其它剩余表引用」的表要往后放；先删没有被引用的
        referenced = {p for t in remaining for p in parents_of[t] if p in remaining}
        ready = sorted(remaining - referenced)
        if not ready:  # 出现环（正常 schema 不该有）→ 兜底，交给事务整体回滚
            ready = sorted(remaining)
        order.extend(ready)
        remaining -= set(ready)
    return order


# ====== 合成测试店铺（外键前提） ======
#
# 测试套件长期用「合成 shop_id」做分区隔离，例如 test_platform_rules.py 里
# `build_rule_record({"title": "T"}, shop_id="s1")`。这些 id 只是分区键，
# 过去不需要真实存在。
#
# 但迁移 d5e6f7a8b9c0（2026-09-15）给 16 张业务表加了 shop_id -> stores_store
# 外键后，合成 id 不再是"合法"值：写入会被数据库拒绝。
# 实测一次性打破 49 个用例 / 709 处外键违例。
#
# 这里在会话开始时为这些 id 建出真实店铺行，结束时清掉。
# 保留原有隔离语义（每个文件仍用自己的 id 分区），只是补上"必须真实存在"这一前提。
#
# ★ 新增合成 shop_id 时必须登记到下面这张表，否则那条用例会以外键违例失败。
#   （p9b_enum_shop_ids.py 可以机械枚举出全部字面量）
SYNTHETIC_TEST_SHOP_IDS = (
    "s1",                          # test_knowledge_base / test_platform_rules / test_auth_and_tenant
    "s2",                          # test_auth_and_tenant
    "store_1",                     # test_secretary_intent_shortcut
    "store_test",                  # test_aigc_jobs
    "store_x",                     # test_monitors
    "store_unittest_delprobe",     # test_voice_clone_isolation
    "store_unittest_enrollguard",
    "store_unittest_forceprobe",
    "store_unittest_novoice",
    "store_unittest_speak",
    "store_unittest_speakclip",
    "store_unittest_speakempty",
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _synthetic_test_shops():
    """
    为 `SYNTHETIC_TEST_SHOP_IDS` 建出真实店铺行（会话级，自动生效）。

    只写 PG、不写内存 `_store_db`：
    这些是"租户上下文"，不是用户看得见的店铺；写进内存会让
    `GET /api/v1/stores`（读内存）凭空多出 12 家店。
    需要它们的用例都走 `X-Shop-ID` 头，命中点只在 PG 侧。
    """
    from sqlalchemy import text
    from core.database import async_session_factory
    from modules.stores.db_model import StoreRecord

    async with async_session_factory() as session:
        existing = set((await session.execute(
            text("SELECT id FROM stores_store WHERE id = ANY(:ids)"),
            {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
        )).scalars().all())
        for sid in SYNTHETIC_TEST_SHOP_IDS:
            if sid in existing:
                continue
            session.add(StoreRecord(
                id=sid,
                name=f"[test] {sid}",
                platform="amazon_us",
                tenant_id="default_tenant",
            ))
        await session.commit()

    yield

    # 结束清理：先清这些 id 名下的业务数据（外键 RESTRICT 会拦住直接删店铺），
    # 复用 _shop_scoped_delete_order 的拓扑排序，保证「先子表后父表」。
    async with async_session_factory() as session:
        for table in await _shop_scoped_delete_order(session):
            await session.execute(
                text('DELETE FROM "%s" WHERE shop_id = ANY(:ids)' % table),
                {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
            )
        await session.execute(
            text("DELETE FROM stores_store WHERE id = ANY(:ids)"),
            {"ids": list(SYNTHETIC_TEST_SHOP_IDS)},
        )
        await session.commit()


@pytest_asyncio.fixture
async def ensure_shop():
    """
    合成 shop_id 的「真实化」工厂：`sid = await ensure_shop(sid)`。

    为什么需要
    ----------
    迁移 d5e6f7a8b9c0 给 16 张业务表加了 `shop_id -> stores_store` 外键。
    而测试里常见写法是先造一个分区键、再塞进 X-Shop-ID 头：

        sid = f"store_pytest_kb_{uuid.uuid4().hex[:8]}"
        yield {"X-Shop-ID": sid}

    这个 id 只是分区键，`stores_store` 里并没有对应行 ⇒ 写入被外键拒绝
    （实测一次性打破 49 个用例）。

    把生成表达式包一层 `await ensure_shop(...)` 即可：它在 PG 里为该 id
    建出真实店铺行（幂等），用例结束后按外键依赖倒序清掉。

    注意
    ----
    只写 PG、不写内存 `_store_db`：这些是"租户上下文"，不是用户可见的店铺，
    进内存会让 `GET /api/v1/stores`（读内存）凭空多出店铺。

    需要"店铺属于某个用户"的场景（生产模式下 `get_current_shop_id` 会校验
    `stores_store.owner_id`）不适用本夹具 —— 那种情况请直接插入带 owner_id
    的 StoreRecord，例如 test_aigc_jobs.py 的 `job_user`。
    """
    from sqlalchemy import text
    from core.database import async_session_factory
    from modules.stores.db_model import StoreRecord

    created: list = []

    async def _ensure(sid: str) -> str:
        if not sid or sid in created:
            return sid
        async with async_session_factory() as session:
            exists = (await session.execute(
                text("SELECT 1 FROM stores_store WHERE id = :sid"), {"sid": sid}
            )).scalar()
            if not exists:
                session.add(StoreRecord(
                    id=sid, name=f"[test] {sid}",
                    platform="amazon_us", tenant_id="default_tenant",
                ))
                await session.commit()
        created.append(sid)
        return sid

    yield _ensure

    if not created:
        return
    async with async_session_factory() as session:
        for table in await _shop_scoped_delete_order(session):
            await session.execute(
                text('DELETE FROM "%s" WHERE shop_id = ANY(:ids)' % table),
                {"ids": created},
            )
        await session.execute(
            text("DELETE FROM stores_store WHERE id = ANY(:ids)"), {"ids": created}
        )
        await session.commit()
