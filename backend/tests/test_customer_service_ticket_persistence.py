"""
客服工单落库 + 归属注入门禁（第 143 轮 A4 建立）。

背景 —— 修复前的两处缺陷（同一条链上的两个断点）
------------------------------------------------
**断点 1：工单根本没落库。** `CustomerServiceService.create_ticket` 只造一个
`TicketInfo` 就返回：工单号 `TKT-YYYYMMDD-NNNNN` 是 `random.randint` 现编的，
响应写着「工单 XXX 创建成功！」，而那个号**指向不了任何记录** —— 刷新即消失，
事后无处可查。这是「伪成功」：`success=True` + 可读文案 + 不可追溯的 ID。

**断点 2：端点连租户都不取。** `create_ticket_endpoint` 的签名里没有
`X-Shop-ID` 依赖 ⇒ 即便有表，`shop_id` 也无从落 —— 而 `cs_tickets.shop_id`
有指向 `stores_store` 的外键，空值会被数据库直接拒绝（用户看到 500，且
报错里带着约束名）。

本文件钉住的六件事
------------------
1. **缺 / 空 / 纯空白 `X-Shop-ID` ⇒ 400**，且**零写入**（
   `test_ticket_without_shop_header_is_400_and_writes_nothing`）。
2. ★★★ **body 里的 `store_id` 无效**（`test_body_store_id_cannot_override_header`）：
   归属只能服务端注入。判据不是「400」（`TicketCreateRequest` 里没这个字段，
   pydantic `extra="ignore"` ⇒ 照发不 422），而是**那个值没有被采纳** ——
   落库行的 `shop_id` 必须等于请求头那个、且不等于 body 里那个。
3. **返回的 `ticket_id` 必须指向一条真实记录**
   （`test_returned_ticket_id_points_to_a_real_row`）—— 这是"伪成功"的正面判据：
   修复前每个返回的号在库里都查不到。
4. **字段原样落库**（`test_ticket_fields_roundtrip`）：标题/描述/分类/附件等
   回读一致（否则"落库了"只是写了个空行）。
5. **工单号冲突换后缀重试，而不是 500、更不是谎报成功**
   （`test_id_conflict_retries_with_suffix`）。Agent 生成的号是同一天内随机 5 位，
   **并非唯一**；直接 insert 撞主键若没人处理就是一个 500。
6. **签名层门禁**（静态 AST）：`service.create_ticket` 与
   `tools._create_ticket_tool` 的 `store_id` 都**无默认值** —— 修复前工具连
   这个参数都没有，服务端注入的值没有入口。
"""

import ast
import uuid
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
URL = "/api/v1/customer-service/ticket/create"

BODY = {
    "subject": "包裹显示已签收但没收到",
    "description": "订单显示 3 天前已签收，但我和邻居都没收到包裹，需要核实。",
    "category": "物流",
    "order_id": "112-3456789-1234567",
    "attachments": ["https://example.com/a.jpg"],
}


async def _count_tickets() -> int:
    from core.database import async_session_factory

    async with async_session_factory() as db:
        return (await db.execute(text("SELECT count(*) FROM cs_tickets"))).scalar()


async def _rows_for(shop_id: str) -> list[dict]:
    from core.database import async_session_factory

    async with async_session_factory() as db:
        res = await db.execute(
            text(
                "SELECT id, shop_id, subject, description, category, priority, status, "
                "customer_id, order_id, created_at, sla_deadline, estimated_response_time, "
                "tags, attachments, auto_replies "
                "FROM cs_tickets WHERE shop_id = :sid ORDER BY created_at"
            ),
            {"sid": shop_id},
        )
        return [dict(r._mapping) for r in res]


# ============================================================
# 1. 归属守卫：缺 / 空 / 纯空白 ⇒ 400 且零写入
# ============================================================

@pytest.mark.parametrize("headers,label", [
    ({}, "不带头"), ({"X-Shop-ID": ""}, "空串"), ({"X-Shop-ID": "   "}, "纯空白"),
])
async def test_ticket_without_shop_header_is_400_and_writes_nothing(client, headers, label):
    """写端点三类空值都必须 400，且**一行都不能落**。

    只看状态码不够 —— 一个"先写库再报错"的实现同样返回 400，脏数据已经在了。
    所以这里同时直查 `cs_tickets` 的行数。
    """
    before = await _count_tickets()
    r = await client.post(URL, json=BODY, headers=headers)
    assert r.status_code == 400, f"[{label}] 期望 400，实际 {r.status_code} {r.text[:200]}"
    assert "店铺" in r.json().get("detail", ""), f"[{label}] 400 原因不可读: {r.text[:200]}"
    after = await _count_tickets()
    assert after == before, f"[{label}] 400 之后竟新增了 {after - before} 行工单"


# ============================================================
# 2. ★★★ 核心门禁：body 里的 store_id 必须无效
# ============================================================

async def test_body_store_id_cannot_override_header(client, ensure_shop):
    """body 里塞 `store_id` 不得改变归属 —— 归属只能服务端注入。

    判据为什么不是「400」：`TicketCreateRequest` 里**没有**这个字段，
    pydantic 默认 `extra="ignore"` ⇒ 老客户端照发不会 422、接口照常 200。
    真正要断言的是**那个值没有被采纳**：落库行的 `shop_id` 必须是请求头那个。
    """
    shop = await ensure_shop(f"store_cs_guard_{uuid.uuid4().hex[:8]}")
    hacked = f"store_cs_hacked_{uuid.uuid4().hex[:8]}"

    r = await client.post(URL, json={**BODY, "store_id": hacked},
                          headers={"X-Shop-ID": shop})
    assert r.status_code == 200, r.text[:300]
    rows = await _rows_for(shop)
    assert len(rows) == 1, f"期望该店铺名下有 1 行工单，实际 {len(rows)}"
    assert rows[0]["shop_id"] == shop
    assert rows[0]["shop_id"] != hacked
    assert await _rows_for(hacked) == [], "工单被落到了 body 指定的店铺分区"


# ============================================================
# 3. 正向：真落库、字段对得上、返回号可追溯
# ============================================================

async def test_ticket_fields_roundtrip(client, ensure_shop):
    """字段原样落库（否则"落库了"只是往表里写了个空行）。"""
    shop = await ensure_shop(f"store_cs_rt_{uuid.uuid4().hex[:8]}")
    r = await client.post(URL, json=BODY, headers={"X-Shop-ID": shop})
    assert r.status_code == 200, r.text[:400]
    payload = r.json()
    assert payload["success"] is True, payload
    assert payload["ticket"]["ticket_id"]

    rows = await _rows_for(shop)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == payload["ticket"]["ticket_id"], "返回的号与落库的号不一致"
    assert row["subject"] == BODY["subject"]
    assert row["description"] == BODY["description"]
    assert row["category"] == BODY["category"]
    assert row["order_id"] == BODY["order_id"]
    assert row["attachments"] == BODY["attachments"]
    # 派生字段要真被算出来（不能是空串/空数组）
    assert row["priority"] in ("low", "medium", "high", "urgent"), row["priority"]
    assert row["status"] == "open"
    assert row["estimated_response_time"], "预计响应时间没落库"
    assert row["sla_deadline"], "SLA 截止时间没落库"


async def test_returned_ticket_id_points_to_a_real_row(client, ensure_shop):
    """★ 「伪成功」的正面判据：每一个返回的工单号在库里都查得到。

    修复前这条必红 —— 号是 `random.randint` 现编的，库里没有对应行，
    刷新页面工单就"消失"了。
    """
    shop = await ensure_shop(f"store_cs_trace_{uuid.uuid4().hex[:8]}")
    for i in range(3):
        r = await client.post(URL, json={**BODY, "subject": f"可追溯性校验 {i}"},
                              headers={"X-Shop-ID": shop})
        assert r.status_code == 200, r.text[:300]
        tid = r.json()["ticket"]["ticket_id"]
        rows = [x for x in await _rows_for(shop) if x["id"] == tid]
        assert rows, f"第 {i} 个工单号 {tid} 在库里查不到（伪成功回归）"

    rows = await _rows_for(shop)
    assert len(rows) == 3
    assert len({x["id"] for x in rows}) == 3, "三次创建竟然落成同一个号"


async def test_id_conflict_retries_with_suffix(client, ensure_shop, monkeypatch):
    """工单号撞车时必须换后缀重试 —— 不是 500，更不是谎报成功。

    Agent 生成的号形如 `TKT-20260918-48213`（末 5 位 `random.randint`），
    同一天内**并非唯一**。这里把 Agent 换成一个"永远返回同一个号"的桩，
    复现冲突路径：第二次创建必须成功，且落库的号 = 第一次的号 + `-xxxx` 后缀。
    """
    from modules.customer_service import service as cs_service
    from modules.customer_service.agent_cs import TicketCreateResult, TicketInfo

    shop = await ensure_shop(f"store_cs_conflict_{uuid.uuid4().hex[:8]}")
    first = await client.post(URL, json=BODY, headers={"X-Shop-ID": shop})
    assert first.status_code == 200, first.text[:300]
    taken = first.json()["ticket"]["ticket_id"]

    class _StubAgent:
        """永远复用第一次那个号 —— 模拟极小概率的编号撞车。"""

        async def create_ticket(self, **kw):
            return TicketCreateResult(
                success=True,
                ticket=TicketInfo(
                    ticket_id=taken,
                    subject=kw["subject"],
                    description=kw["description"],
                    category=kw["category"],
                    priority="medium",
                    status="open",
                    customer_id=kw.get("customer_id", ""),
                    order_id=kw.get("order_id"),
                    created_at=datetime.now().isoformat(),
                    sla_deadline=datetime.now().isoformat(),
                    tags=[],
                ),
                estimated_response_time="24h",
                auto_replies=[],
            )

    monkeypatch.setattr(cs_service, "get_cs_agent", lambda: _StubAgent())

    second = await client.post(URL, json={**BODY, "subject": "冲突重试"}, headers={"X-Shop-ID": shop})
    assert second.status_code == 200, f"编号冲突被处理成了 {second.status_code}: {second.text[:300]}"
    payload = second.json()
    assert payload["success"] is True, payload
    new_id = payload["ticket"]["ticket_id"]
    assert new_id != taken, "撞车之后没有换号 —— 要么覆盖了旧工单，要么根本没写进去"
    assert new_id.startswith(taken), f"新号 {new_id} 不是原号 {taken} 加后缀的形态"

    rows = await _rows_for(shop)
    assert {x["id"] for x in rows} == {taken, new_id}, "两条工单没有各自落库"


# ============================================================
# 4. 签名层门禁（静态 AST，不连库）
# ============================================================

def _func_args(rel: str, name: str) -> ast.arguments:
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node.args
    raise AssertionError(f"{rel} 里找不到 {name}")


def _default_of(args: ast.arguments, name: str):
    pos = [a.arg for a in args.posonlyargs] + [a.arg for a in args.args]
    if name in pos:
        idx = pos.index(name)
        n_def = len(args.defaults)
        first = len(pos) - n_def
        return args.defaults[idx - first] if idx >= first else None
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        if a.arg == name:
            return d
    raise AssertionError(f"参数 {name} 不存在")


def test_service_create_ticket_requires_store_id():
    """`service.create_ticket` 的 `store_id` 必须**必填无默认值**。

    与 A4-1（review_analyst）同口径：有默认值 ⇒ "忘传"退化成静默落到某家店，
    而这张表的外键会把它拦下来变成一个 500（用户看不懂）。
    `TypeError` 才是我们要的失败形态（本仓「签名即门禁」）。
    """
    args = _func_args("modules/customer_service/service.py", "create_ticket")
    assert "store_id" in [a.arg for a in args.args], "create_ticket 没有 store_id 形参"
    assert _default_of(args, "store_id") is None, (
        "create_ticket 的 store_id 带了默认值 —— 忘传会静默落到默认店铺"
    )


def test_tool_create_ticket_store_id_has_no_default():
    """`tools._create_ticket_tool` 同样必须必填（修复前它**连这个参数都没有**）。"""
    args = _func_args("modules/customer_service/tools.py", "_create_ticket_tool")
    assert "store_id" in [a.arg for a in args.args], (
        "工具层没有 store_id 入口 ⇒ 服务端注入的值无从传下去，工单必然落不了库"
    )
    assert _default_of(args, "store_id") is None


async def test_service_rejects_blank_store_id():
    """service 层 fail-closed：空 store_id 必须抛错，绝不能拿它去写库。

    为什么必须有这道（router 已经会 400 了）：工具层 / 脚本 / 测试都能直接调
    service。而 `cs_tickets.shop_id` 有外键 —— 空值写入会被数据库拒绝，
    报错里带着约束名，用户看到的是"服务器内部错误"（归因错方向）。
    """
    from core.tenant.middleware import MissingShopContext
    from modules.customer_service import service as cs_service
    from modules.customer_service.schemas import TicketCreateRequest

    req = TicketCreateRequest(**BODY)
    for bad in ("", "   ", None):
        with pytest.raises(MissingShopContext) as ei:
            await cs_service.CustomerServiceService.create_ticket(req, bad)  # type: ignore[arg-type]
        assert "店铺" in str(ei.value), f"store_id={bad!r} 的报错不可读：{ei.value}"
