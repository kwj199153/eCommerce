"""
复盘库（「资料库 → 复盘库」，第 251 轮）契约 + 归属 + 幂等门禁。

背景
----
第 251 轮给运营复盘师加了**第 7 个资料库**：老板点「归档到复盘库」才入库
（`POST /review/reports`），列表走 `GET /review/reports`，详情走
`GET /review/reports/{id}`，Agent 侧多一个只读工具 `list_reviews`。

它**不是**第 7 项复盘能力 —— 那 6 项是「**算**」（`weekly_report` … `profit_audit`），
算完不落库；复盘库是「**存 + 读**」。存在理由是老板那句
「**下一期复盘自动读到上期做对比**」：只有历史复盘落了库，下一期才读得到。

本文件钉住的六件事（与 `test_review_analyst_api.py` 同族，但对象是**存**不是**算**）
-------------------------------------------------------------------------------
1. **缺 / 空 `X-Shop-ID`**：写口（POST）⇒ 400；读口（GET）⇒ 空列表而非报错
   （读方法保持本仓既有契约，见 `get_current_shop_id` 的 docstring）。
2. ★★★ **归属只能服务端注入**：快照（`data`）由前端原样回传 ⇒ 里面的
   `store_id` 天然可被改成别家；`service.save_report` 必须**覆盖**它。
   判据不是「400」，而是「照发不报错、但落库/回显的仍是请求头那家」。
3. **幂等**：同 `(店铺, 类型, 周期长度, 周期末日)` 只允许一行 ——
   连发两次 `created` 先 `true` 后 `false`，库里仍 1 行。
   ★ 为什么幂等键要带 `period_days`：8 月与 9 月的月报 `period_end` 不同、
   但同为 30 天；若只按 (类型, 周期末日) 去重，两份月报会互相覆盖，
   「上期」就永远不存在。
4. **写口取值校验唯一实现**（`service.validate_save_payload`）：
   `report_type` 值域外 / `period_days` 越界 / `data` 非 dict ⇒ **422**。
5. **「不存在」与「不属于你」同一句 404**：否则可以拿 id 逐位枚举别家报告。
6. **签名 / 形态层判据（静态 AST，不连库）**：
   · router 端点清单**集合相等**（不是子序列 —— 那会漏掉「端点被删」）；
   · `save_report` **从不读** `payload["store_id"]`（只读 data / report_type / period_days）；
   · `list_reviews` 工具是**只读**（`TOOL_CATALOG.effect == read_only` 且
     运行时 `has_side_effects() is False`）。

所有用例针对真实本地 PostgreSQL，用**测试专属 shop_id** 隔离
（`ensure_shop` 会在用例结束按外键拓扑倒序清掉该店铺名下的全部业务数据）。
"""

import ast
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio

pytestmark = pytest.mark.tenant_identity


BACKEND = Path(__file__).resolve().parents[1]
REPORTS = "/api/v1/review/reports"


# ====== 夹具 ======

@pytest_asyncio.fixture
async def shop(ensure_shop):
    """只属于本次测试的店铺 id（`ensure_shop` 用例结束自动清理）。

    ★ 为什么每条用例都要自己的店，而不是复用 `store_test`：
      `save_report` 按 (店, 类型, 长度, 周期末日) 幂等 —— 复用同一个店会让
      「第一次归档必返回 created=True」这条判据在**同一会话的第二次跑批**里变红
      （上一轮留下的行还在 ⇒ 变成 UPDATE）。每例一店让「空 → 有」是真的空。
    """
    return await ensure_shop(f"store_revlib_{uuid.uuid4().hex[:8]}")


def _headers(shop_id: str) -> dict:
    return {"X-Shop-ID": shop_id}


def _payload(report_type: str = "weekly_report", days: int = 7, **over) -> dict:
    """一份「后端刚返回、前端原样回传」的复盘快照。

    ★ `data.store_id` 故意填一个**不该被采纳**的值：归属必须由服务端覆盖。
    """
    data = {
        "report_type": report_type,
        "period_days": days,
        "store_id": "store_should_be_overridden",
        "summary": "本周 GMV $1,234.00，环比 +5.2%，ACoS 18.4%。",
        "metrics": {"revenue": 1234.0, "orders": 42, "acos": 18.4},
        "details": {"top_sku": "SKU-1", "risk_count": 2},
    }
    data.update(over.pop("data", {}))
    return {"report_type": report_type, "period_days": days, "data": data, **over}


# ============================================================
# 1. 归属守卫：写口缺头 400 / 读口缺头空列表
# ============================================================

async def test_save_without_shop_header_is_400(client):
    """写口（POST）缺 `X-Shop-ID` ⇒ 400，且原因可读。

    ★ 为什么不是「落库 shop_id=""」：那样会被外键
      `fk_review_reports_shop_id_stores_store` 拒 ⇒ 500 + 把约束名回给客户端
      （信息泄露）。守卫必须在依赖解析阶段就拦下，零数据库往返。
    """
    r = await client.post(REPORTS, json=_payload(), headers={})
    assert r.status_code == 400, f"期望 400，实际 {r.status_code} {r.text[:200]}"
    assert "店铺" in r.json().get("detail", "")


async def test_list_without_shop_header_is_empty_not_error(client):
    """读口（GET）缺 `X-Shop-ID` ⇒ 200 + 空列表（本仓读方法既有契约）。

    ★ 与写口分开是**有意**的：读方法不带头是「还没选店铺」，前端照旧要能渲染
      空态；返回 400 会让前端把「未选店铺」显示成一次错误。
    ★ 但**绝不能**返回全库 —— 内核 `query_library` 对空 `shop_id` 直接短路 `[]`
      （安全失败方向：宁可查不到，不可查全部）。这条正是钉住那个方向的。
    """
    r = await client.get(REPORTS, headers={})
    assert r.status_code == 200, r.text[:200]
    body = r.json()
    assert body["items"] == [], f"缺归属竟然读到了数据：{body}"
    assert body["total"] == 0


async def test_detail_without_shop_header_is_404(client, shop):
    """读口（GET 单条）缺 `X-Shop-ID` ⇒ 404（不是 200、不是 500）。

    `scoped(..., None)` 在 SQL 里是 `shop_id IS NULL` ⇒ 匹配不到任何行。
    这条钉的是「缺归属不得命中任何一条别人已归档的报告」。
    """
    saved = (await client.post(REPORTS, json=_payload(), headers=_headers(shop))).json()
    rid = saved["item"]["id"]

    r = await client.get(f"{REPORTS}/{rid}", headers={})
    assert r.status_code == 404, (
        f"缺归属竟然读到了报告 {rid}：{r.status_code} {r.text[:200]}"
    )


# ============================================================
# 2. ★★★ 核心门禁：快照里的 store_id 必须被服务端覆盖
# ============================================================

async def test_snapshot_store_id_cannot_override_header(client, shop):
    """`data.store_id` 塞别家 ⇒ 落库/回显的仍是**请求头**那家。

    ★ 判据为什么不是「400」：写口的请求体是**裸 dict**（校验在 service），
      老客户端/前端回传的快照里本来就带 `store_id`，照发不报错才叫兼容。
      真正要断言的是**那个值没有被采纳**（只断言 200 的写法会漏掉
      「采纳了 body」的实现 —— 假绿）。

    ★ 为什么必须走「详情」端点验证：列表出参（`report_to_dict`）**不含**
      `store_id`，所以「回显」只能从详情端点的 `data` 快照里读。
    """
    hacked = "store_hacked_via_body"
    payload = _payload(data={"store_id": hacked})

    r = await client.post(REPORTS, json=payload, headers=_headers(shop))
    assert r.status_code == 200, r.text[:200]
    rid = r.json()["item"]["id"]

    detail = await client.get(f"{REPORTS}/{rid}", headers=_headers(shop))
    assert detail.status_code == 200, detail.text[:200]
    got = detail.json()["data"]["store_id"]
    assert got == shop, (
        f"落库时采纳了请求体里的 store_id：data.store_id={got!r}，"
        f"期望 {shop!r}（body 里发的是 {hacked!r}）"
    )
    assert got != hacked


async def test_two_shops_do_not_see_each_other(client, ensure_shop):
    """A 店归档的报告，B 店既列不到、也拿不到（归属真的生效，不是靠 Mock 过滤）。"""
    a = await ensure_shop(f"store_revlib_a_{uuid.uuid4().hex[:6]}")
    b = await ensure_shop(f"store_revlib_b_{uuid.uuid4().hex[:6]}")

    rid = (
        await client.post(REPORTS, json=_payload(), headers=_headers(a))
    ).json()["item"]["id"]

    # B 店的列表里不能出现 A 店那条（用同一个 store_id 分区才发现得了）
    listing = (await client.get(REPORTS, headers=_headers(b))).json()
    assert all(it["id"] != rid for it in listing["items"]), listing
    assert listing["total"] == 0, f"B 店看到了 A 店的归档：{listing}"

    # B 店直接按 id 取 A 店那条 ⇒ 404（与「不存在」同一响应，见下一节）
    r = await client.get(f"{REPORTS}/{rid}", headers=_headers(b))
    assert r.status_code == 404, r.text[:200]


# ============================================================
# 3. 幂等：同 (类型, 长度, 周期末日) 只留一行
# ============================================================

async def test_save_is_idempotent_on_same_scope(client, shop):
    """连发两次同一份 ⇒ `created` 先 `true` 后 `false`，库里仍 **1** 行。

    ★ 为什么把 `created` 回给前端：**「新增了一条」与「覆盖了今天那条」对老板
      是两件事**，用同一句「已归档」会让他以为库里堆了两份。
    """
    first = await client.post(REPORTS, json=_payload(), headers=_headers(shop))
    assert first.status_code == 200, first.text[:200]
    assert first.json()["created"] is True
    first_id = first.json()["item"]["id"]

    # 第二份覆盖同一幂等键，但快照内容不同（模拟老板重算后再归档一次）
    second = await client.post(
        REPORTS,
        json=_payload(data={"summary": "重算后：GMV $1,300.00，ACoS 17.1%。"}),
        headers=_headers(shop),
    )
    assert second.status_code == 200, second.text[:200]
    assert second.json()["created"] is False, "同一幂等键的第二次归档被当成了新增"
    second_id = second.json()["item"]["id"]

    assert second_id == first_id, "覆盖时应更新原行，而不是插了一条新的"

    listing = (await client.get(REPORTS, headers=_headers(shop))).json()
    assert listing["total"] == 1, f"重复归档留下了多行：{listing}"

    # 覆盖后的快照是**后一份**
    detail = (await client.get(f"{REPORTS}/{first_id}", headers=_headers(shop))).json()
    assert "重算后" in detail["summary"], detail


async def test_different_period_days_are_separate_rows(client, shop):
    """**同类型、同周期末日**，仅 `period_days` 不同 ⇒ **两行**。

    ★ 这条钉的是幂等键的**维度数**。8 月月报与 9 月月报 `period_end` 不同，
      不会互相撞；真正危险的是「同一类型的 7 天复盘」与「14 天复盘」在同一天
      归档 —— 若幂等键只到 (店铺, 类型, 周期末日) 三维，第二份会**覆盖**第一份，
      `list_reviews` 就永远读不到「上期」，复盘师的对比动作直接失效。
      ⇒ 所以这里刻意用**同一个 `report_type`**，只让 `period_days` 不同。
    """
    await client.post(REPORTS, json=_payload("weekly_report", 7), headers=_headers(shop))
    await client.post(REPORTS, json=_payload("weekly_report", 14), headers=_headers(shop))

    listing = (await client.get(REPORTS, headers=_headers(shop))).json()
    assert listing["total"] == 2, f"不同 period_days 被压成一行（「上期」会消失）：{listing}"
    assert {it["period_days"] for it in listing["items"]} == {7, 14}


# ============================================================
# 4. 写口取值校验（唯一实现：service.validate_save_payload ⇒ 422）
# ============================================================

async def test_unknown_report_type_is_422(client, shop):
    """`report_type` 值域外 ⇒ 422（不是静默入库）。

    ★ 静默入库的后果：库里会出现一个**没有任何读口能筛到**、
      前端 `ReviewReportCard.TITLES` 也翻译不了的类型（退化成「运营复盘」，
      看起来像正常数据）。失败必须能归因。
    """
    r = await client.post(
        REPORTS, json=_payload("not_a_real_type"), headers=_headers(shop)
    )
    assert r.status_code == 422, f"期望 422，实际 {r.status_code} {r.text[:200]}"
    assert "report_type" in r.json().get("detail", "")


@pytest.mark.parametrize("days", [0, 91, -1, "abc"], ids=["zero", "over90", "neg", "text"])
async def test_bad_period_days_is_422(client, shop, days):
    """`period_days` 越界 / 非整数 ⇒ 422（与 6 项能力 `Field(ge=1, le=90)` 同一值域）。"""
    r = await client.post(
        REPORTS, json=_payload(days=days), headers=_headers(shop)
    )
    assert r.status_code == 422, f"days={days!r} 期望 422，实际 {r.status_code} {r.text[:200]}"


@pytest.mark.parametrize("bad", [[], "不是对象", 42, None], ids=["list", "str", "int", "none"])
async def test_non_dict_data_is_422(client, shop, bad):
    """`data` 非 dict ⇒ 422（快照必须是后端 `ReviewReport` 那个对象）。"""
    r = await client.post(
        REPORTS,
        json={"report_type": "weekly_report", "period_days": 7, "data": bad},
        headers=_headers(shop),
    )
    assert r.status_code == 422, f"data={bad!r} 期望 422，实际 {r.status_code} {r.text[:200]}"


# ============================================================
# 5. 「不存在」与「不属于你」同一句 404（防 id 枚举）
# ============================================================

async def test_missing_and_foreign_report_share_the_same_404(client, ensure_shop):
    """两种情形的 404 **逐字相同** —— 否则可区分 ⇒ 可枚举别人的报告 id。"""
    a = await ensure_shop(f"store_revlib_oa_{uuid.uuid4().hex[:6]}")
    b = await ensure_shop(f"store_revlib_ob_{uuid.uuid4().hex[:6]}")

    foreign_id = (
        await client.post(REPORTS, json=_payload(), headers=_headers(a))
    ).json()["item"]["id"]

    foreign = await client.get(f"{REPORTS}/{foreign_id}", headers=_headers(b))
    missing = await client.get(f"{REPORTS}/rpt-does-not-exist-000", headers=_headers(b))

    assert foreign.status_code == missing.status_code == 404
    assert foreign.json()["detail"] == missing.json()["detail"], (
        "「不属于你」与「不存在」的 404 文案不一致 —— 可以拿它逐位枚举别家报告 id"
    )


# ============================================================
# 6. 读口：列表形状 / 排序白名单
# ============================================================

async def test_list_shape_never_leaks_snapshot(client, shop):
    """列表出参**不含** `data` 快照（一份 details 可挂 35 行 SKU 明细）。

    ★ 为什么值得单独一条：列表进模型上下文（`list_reviews` 工具直接消费本函数），
      一份报告十几 KB × 20 条会把上下文塞满，且都是模型用不上的明细。
      「列表回不回快照」是**契约**，得有人钉。
    """
    await client.post(REPORTS, json=_payload(), headers=_headers(shop))

    body = (await client.get(REPORTS, headers=_headers(shop))).json()
    assert body["total"] == 1
    item = body["items"][0]
    for key in ("id", "report_type", "period_days", "period_end", "summary",
                "created_at", "updated_at"):
        assert key in item, f"列表出参缺 {key}：{sorted(item)}"
    assert "data" not in item, "列表回了快照 —— 会把十几 KB 的 JSON 塞进模型上下文"


async def test_list_bad_order_by_is_400(client, shop):
    """排序维度值域外 ⇒ **400**（不是静默退化成默认排序）。

    ★ 为什么必须分开：静默退化会让「按创建时间排」与「你参数写错了」
      在调用方看来长得一样（第 216 轮 ③ 实测的归因错方向）。
    """
    r = await client.get(REPORTS, params={"order_by": "no_such_dim"}, headers=_headers(shop))
    assert r.status_code == 400, f"期望 400，实际 {r.status_code} {r.text[:200]}"


async def test_list_bad_report_type_filter_is_400(client, shop):
    """过滤值域外 ⇒ 400（值域直接取 `db_model.REVIEW_REPORT_TYPES`，不抄第二份）。"""
    r = await client.get(REPORTS, params={"report_type": "nope"}, headers=_headers(shop))
    assert r.status_code == 400, f"期望 400，实际 {r.status_code} {r.text[:200]}"


async def test_list_total_is_not_truncated_by_limit(client, shop):
    """`total` 是**真实条数**，不受 `limit` 截断（前端要显示「共 N 份」）。"""
    for rt, days in (("weekly_report", 7), ("monthly_review", 30), ("ad_review", 7)):
        await client.post(REPORTS, json=_payload(rt, days), headers=_headers(shop))

    body = (await client.get(REPORTS, params={"limit": 1}, headers=_headers(shop))).json()
    assert len(body["items"]) == 1, body
    assert body["total"] == 3, f"total 被 limit 截断了：{body}"


async def test_detail_includes_full_snapshot(client, shop):
    """详情端点**含**完整快照（唯一需要 `data` 的入口）。"""
    rid = (
        await client.post(REPORTS, json=_payload(), headers=_headers(shop))
    ).json()["item"]["id"]

    body = (await client.get(f"{REPORTS}/{rid}", headers=_headers(shop))).json()
    assert "data" in body, body
    assert body["data"]["metrics"]["orders"] == 42
    assert body["data"]["details"]["top_sku"] == "SKU-1"


# ============================================================
# 7. Agent 工具：list_reviews（只读，读复盘库）
# ============================================================

def _set_shop(value):
    """写 / 还原 Agent 的归属 ContextVar（唯一写入点是 `agent.invoke()`）。"""
    from modules.review_analyst.agent import _current_shop_id

    prev = _current_shop_id.get()
    _current_shop_id.set(value)
    return prev


async def test_list_reviews_tool_refuses_without_shop_context(client, shop):
    """没归属 ⇒ `type=library_read_failed` + `reason=missing_shop_context`。

    ★ 为什么**不回** `items: []`：回空列表会让「没有店铺归属」与「复盘库确实
      是空的」在模型看来一模一样 —— 前者该让老板去选店铺，后者该让他先去归档
      （处置完全不同）。本仓：空状态不得与失败态混同。
    """
    from modules.review_analyst import tools as ra_tools

    # 造一条真数据：证明「拒绝」不是因为没有数据，而是因为**没有归属**
    await client.post(REPORTS, json=_payload(), headers=_headers(shop))

    prev = _set_shop(None)
    try:
        data = json.loads(await ra_tools._list_reviews_tool())
    finally:
        _set_shop(prev)

    assert data.get("type") == "library_read_failed", data
    assert data.get("reason") == "missing_shop_context"
    assert "店铺" in (data.get("error") or ""), "拒绝文案要可行动（说清怎么办）"
    assert "items" not in data, "拒绝了却还回空 items —— 会把失败态说成空状态"


async def test_list_reviews_tool_returns_archived_items(client, shop):
    """有归属 ⇒ `type=review_list` + 真实 total + 不含快照的 items。"""
    from modules.review_analyst import tools as ra_tools

    await client.post(REPORTS, json=_payload("monthly_review", 30), headers=_headers(shop))

    prev = _set_shop(shop)
    try:
        data = json.loads(await ra_tools._list_reviews_tool(limit=5))
    finally:
        _set_shop(prev)

    assert data.get("type") == "review_list", data
    assert data["total"] == 1, data
    assert data["returned"] == 1, data
    assert data["items"][0]["report_type"] == "monthly_review"
    assert "data" not in data["items"][0], "工具出参带了快照 —— 会撑爆模型上下文"


async def test_list_reviews_tool_bad_order_by_is_invalid_argument(client, shop):
    """排序维度值域外 ⇒ `type=invalid_argument`（让模型**改参数重试**）。

    ★ 与 `library_read_failed` 分开是必须的：把它说成「读不出来」，
      模型就不会去改 `order_by`，只会转述成「复盘库读不到」，老板拿不到可行动信息。
    """
    from modules.review_analyst import tools as ra_tools

    prev = _set_shop(shop)
    try:
        data = json.loads(await ra_tools._list_reviews_tool(order_by="no_such_dim"))
    finally:
        _set_shop(prev)

    assert data.get("type") == "invalid_argument", data
    assert data.get("error"), "invalid_argument 必须说明哪里不合法"


async def test_list_reviews_tool_caps_limit(client, shop):
    """`limit` 被夹到 1..MAX_LIST_ITEMS（模型可能传 9999）。"""
    from modules.review_analyst import tools as ra_tools

    prev = _set_shop(shop)
    try:
        data = json.loads(await ra_tools._list_reviews_tool(limit=9999))
    finally:
        _set_shop(prev)

    assert data.get("type") == "review_list", data
    assert data["returned"] <= ra_tools.MAX_LIST_ITEMS


# ============================================================
# 8. 静态判据（AST，不连库）
# ============================================================

def _router_routes() -> set:
    """从 `router.py` 的装饰器里取 `{("POST", "/reports"), ...}`（AST，不 import）。"""
    src = (BACKEND / "modules/review_analyst/router.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    routes = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                continue
            if dec.func.attr not in ("get", "post", "put", "patch", "delete"):
                continue
            path = dec.args[0]
            if isinstance(path, ast.Constant) and isinstance(path.value, str):
                routes.add((dec.func.attr.upper(), path.value))
    return routes


def test_router_exposes_exactly_the_expected_endpoints():
    """端点清单**集合相等**（不是子序列）。

    ★ 为什么不用 `expected ⊆ actual`：子序列断言在 `api ⊆ tool` 时恒真 ——
      它给缺陷盖章（本仓踩过：删掉一个端点、或改错路径，子序列照样绿）。
      这里要的是「**多一个不行、少一个也不行**」。
    """
    expected = {
        ("POST", "/weekly-report"),
        ("POST", "/monthly-review"),
        ("POST", "/ad-review"),
        ("POST", "/product-performance"),
        ("POST", "/inventory-health"),
        ("POST", "/profit-audit"),
        ("POST", "/chat"),
        # ★ 第 251 轮：复盘库三端点
        ("POST", "/reports"),
        ("GET", "/reports"),
        ("GET", "/reports/{report_id}"),
    }
    actual = _router_routes()
    assert actual == expected, (
        f"多出的：{sorted(actual - expected)}\n缺少的：{sorted(expected - actual)}"
    )


def test_save_report_never_reads_client_store_id_from_payload():
    """★ `save_report` 的**函数体**里不得出现 `payload["store_id"]`。

    形态判据的意义：运行期用例只打了「body 里 store_id 被覆盖」这一个值路径；
    若哪天有人加一行 `store_id = payload.get("store_id") or shop`，那行会在
    **特定取值**下才生效。这里钉的是「这个读取**根本不存在**」（形状），
    与「值对不对」互补。

    判据走 AST：找 `Subscript`，其 `value` 是名字 `payload`、`slice` 是常量
    `"store_id"`。不用「源码字符串包含」—— 那会被 docstring / 注释骗过。
    """
    src = (BACKEND / "modules/review_analyst/service.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    target = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "save_report"),
        None,
    )
    assert target is not None, "service.py 里找不到 save_report"

    offenders = [
        n for n in ast.walk(target)
        if isinstance(n, ast.Subscript)
        and isinstance(n.value, ast.Name) and n.value.id == "payload"
        and isinstance(n.slice, ast.Constant) and n.slice.value == "store_id"
    ]
    assert not offenders, (
        f"save_report 读了 payload['store_id']（第 {offenders[0].lineno} 行）—— "
        "归属只能由服务端注入，快照里的 store_id 必须被**覆盖**而不是被采纳"
    )


def test_save_report_calls_require_store_and_validator():
    """`save_report` 必须**真的调用** `_require_store` 与 `validate_save_payload`。

    ★ 只看是不是真调了（`ast.Call`），不看 docstring —— 本仓踩过
      「源码字符串包含被 docstring 骗过」的坑。
    """
    src = (BACKEND / "modules/review_analyst/service.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    target = next(
        (n for n in ast.walk(tree)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "save_report"),
        None,
    )
    assert target is not None

    called = {
        n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
        for n in ast.walk(target) if isinstance(n, ast.Call)
    }
    assert "_require_store" in called, (
        "save_report 没有校验店铺归属 —— 空 store_id 会落一行 shop_id='' 的孤儿"
    )
    assert "validate_save_payload" in called, (
        "save_report 没有走唯一的那份写口校验 —— 值域外的 report_type 会被静默入库"
    )


def test_list_reviews_tool_is_declared_read_only():
    """`list_reviews` 在**运行时**注册表与 `TOOL_CATALOG` 里都必须是只读。

    ★ 两侧都要，因为它们是两份数据：运行时 `metadata`（HITL 审批靠它）
      与目录 `effect`（管理页展示靠它）。只钉一个方向 ⇒ 另一个方向漂移没人发现
      （写错方向的代价不对称：把只读标成有副作用只是多弹一次审批；
       把有副作用的标成只读 = 用户以为不弹审批，危险方向）。
    """
    from ai_infra.tools.side_effects import has_side_effects

    from modules.review_analyst.tools import review_analyst_tools
    from modules.skills.tools_catalog import EFFECT_READ_ONLY, TOOL_CATALOG

    tool = next((t for t in review_analyst_tools if t.name == "list_reviews"), None)
    assert tool is not None, "运行时注册表里没有 list_reviews"
    assert has_side_effects(tool) is False, "list_reviews 被标成了有副作用"

    entry = next(
        (e for e in TOOL_CATALOG
         if e.get("agent") == "review_analyst" and e.get("name") == "list_reviews"),
        None,
    )
    assert entry is not None, "TOOL_CATALOG 里没有 list_reviews（管理页看不到它）"
    assert entry["effect"] == EFFECT_READ_ONLY, entry


def test_review_spec_key_matches_sidebar_contract():
    """`REVIEW_SPEC.key` 必须是 `"reviews"`，值域直接取 `db_model` 那份。

    ★ 这个 key 是**跨端**的：前端侧边栏 `<a-menu-item key="reviews">` 与
      `appActions.ts::AppView` 都用它。后端这里换名 = 前端点进去是空白页。
      （前端三处由 `frontend/scripts/check-review-library-view.cjs` 钉住。）
    """
    from modules.review_analyst.db_model import REVIEW_REPORT_TYPES
    from modules.review_analyst.spec import REVIEW_SPEC

    assert REVIEW_SPEC.key == "reviews"
    assert REVIEW_SPEC.label == "复盘库"
    # 过滤值域与写口校验**同一份**（抄第二份必然在某个取值上漂移）
    assert REVIEW_SPEC.filters["report_type"].values == REVIEW_REPORT_TYPES
    # 默认按业务周期倒序（不是归档时刻）
    assert REVIEW_SPEC.default_sort == "period_end"
