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
#   现有六条（含第 131 轮 resume_approval、第 155 轮 secretary_plan、第 204 轮 customer_service chat_stream）的成立理由（每条都有测试背书，不是自述）：
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
    # ★ 第 212 轮新增（店秘书 SSE 对话）：与 `secretary_chat` **完全同构** ——
    #   两者共用同一份归属解析（`router.py::_resolve_session`）、同一张图、
    #   同一个正文取口（`agent.py::_digest_graph_state`），差别只在
    #   「过程能不能边跑边看」。
    #   ① 会落业务数据吗？—— **不会**（同 `secretary_chat`：纯对话/导航；
    #      工具层拿不到 shop_id 时只回「产品库为空」）。
    #   ② 不适用（没有写路径）。
    #   为何不用严格版：它是店秘书的**主对话入口**，而店秘书是 `AGENT_LIST[0]`
    #      （打开应用默认选中）—— 严格版会让「一家店铺都还没有」的新用户
    #      一开口就被 400 挡住，而那时他恰恰只能靠店秘书去创建第一家店铺。
    ("modules/secretary/router.py", "secretary_chat_stream"),
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
    # ★ 第 325 轮补登（选品大盘 treemap：端点第 305 轮就加了，当时漏登记）。
    #   ① 会落业务数据吗？—— **不会**。纯读：`service.get_market_insight_treemap`
    #      → `core.library_query.query_library(MARKET_SNAPSHOT_SPEC, shop_id)`，
    #      内核在 `not shop_id` 时**直接 return []**（零 DB 往返），
    #      下游只做字段投影 + 拼文案，一行都不写。
    #   ② 不适用（没有写路径）。
    #   为何不用严格版：面板的契约是「没选店铺 ⇒ 200 + 空列表 + 空态文案」
    #      （`MarketInsightConfig.vue` 据此显示空态）。严格版给 400，
    #      会把「还没有店铺的新用户」在大盘页上读成「加载失败」。
    #   ★ 归属不靠这个依赖：内核 `base_select()` 无条件挂 `scoped()`
    #      （`shop_id=None` ⇒ `col IS NULL` ⇒ 查不到任何行），fail-closed。
    ("modules/product_research/router.py", "get_market_insight_treemap"),
    # ★ 第 155 轮新增（两条问答）：
    #   ① 会落业务数据吗？—— **不会**。
    #      `modules/secretary/agent.py::current_plan()` 只 `aget_state`，
    #      不推进图 / 不调 LLM / 不 `append_message`，
    #      连一条消息都不写；路由层拿到后只构造 `PlanResponse` 返回。
    #   ② 不适用（没有写路径）。
    #   为何不用严格版：刚注册、**还没有店铺**的用户同样会刷新页面，
    #     严格版给他 400，而正确语义是 `plan: null`（他本来就没计划）；
    #     400 还会被前端读成「读计划失败」，把「没有计划」错报成「出错了」。
    #   归属不靠这个依赖：`thread_id = ns:user_id:session_id`，
    #     `user_id` 只从服务端身份取 ⇒ 别人拿你的 session_id
    #     算出的是**他自己**的键，物理上读不到。
    ("modules/secretary/router.py", "secretary_plan"),
    # ★ 第 204 轮新增（客服 SSE 对话）：
    #   ① 会落业务数据吗？—— **会**（LLM 可能在这个环路里调 `create_ticket`）。
    #   ② 写路径在缺店铺上下文时硬拒绝吗？—— **是**：
    #      `modules/customer_service/tools.py::_shop_id()` 取不到 ⇒ 传 None 给
    #      `service.create_ticket` ⇒ `require_shop_context(None)` 抛
    #      `MissingShopContext` ⇒ 零数据库往返（`cs_tickets.shop_id` 有外键，
    #      不会出现「先写空行再报错」的形态）。
    #   为何不用严格版：与 product_research 的两个入口**完全同构** —— 它同时
    #      服务只读意图（FAQ 搜索 / 情感分析 / 对话摘要），且是客服的**主对话
    #      入口**。严格版会让「还没选店铺」的用户连「你们的退换货
    #      政策是什么」都问不了（400）—— 属零收益的体验损伤。
    #      ⇒ 门禁放在「写」那一层，而不是「入口」那一层。
    ("modules/customer_service/router.py", "chat_stream"),
    # ★ 第 285 轮新增（客服订单追踪）：
    #   ① 会落业务数据吗？—— **不会**。纯读路径：查自有订单库
    #      （`modules/trade.service.get_order_context`）或平台适配层，**不写库**
    #      （平台数据落库的正确落点是 `trade.sync.sync_orders_from_source`，
    #      不在查询路径里 —— 读路径写库会让「读」产生副作用）。
    #   ② 不适用（没有写路径）。
    #
    #   为何不用严格版（这条与前面六条**性质不同**，值得单独记一笔）：
    #     这里是本仓第一条「**optional 用来决定取哪个源**」的用例 ——
    #       · 拿到 shop_id ⇒ 查**租户隔离**的自有订单库（真源，信息更全）
    #       · 拿不到     ⇒ **只**能走平台适配层（本来就是店铺无关的上游接口）
    #     也就是说，缺店铺**不会**退化为「读到全店数据」：自有库那一步
    #     根本不会执行（`_fetch_order_info` 里 `if shop_id:` 是硬门槛）。
    #     用严格版反而有害：它会让「还没选店铺」的用户连一次纯查询都点不动，
    #     而那次查询即便退化也是安全的。
    ("modules/customer_service/router.py", "track_order_endpoint"),
    # ★ 第 286 轮新增四个（客服读话术的四条入口）：
    #   ① 会落业务数据吗？—— **不会**。四条全是**纯读**：
    #      · `chat_endpoint` / `quick_reply_endpoint`：读话术 + 生成回复，
    #        写路径只有 `create_ticket`，它另有 **strict** 守卫
    #        （缺店铺 ⇒ `require_shop_context` 抛错 ⇒ 零 DB 往返）；
    #      · `search_faq_endpoint` / `get_faq_categories`：查 `knowledge_faqs`。
    #   ② 不适用（这四条自身没有写路径）。
    #
    #   为何不用严格版（与 `track_order_endpoint` **同型**）：
    #     optional 在这里的作用是「**决定能不能读到本店话术**」，不是「放宽租户过滤」——
    #       · 拿到 shop_id ⇒ 查 `knowledge_faqs`（`scope_condition` 按店铺收窄）
    #       · 拿不到       ⇒ `load_faq_items` **直接抛 PermissionError**（fail-closed），
    #         回复里写明「没有店铺上下文，读不了话术」
    #     缺店铺**不会**退化成「读到全店话术」：那一步根本不执行。
    #     用严格版只会让「还没选店铺」的用户连「你们的退换货政策是什么」都问不了。
    ("modules/customer_service/router.py", "chat_endpoint"),
    ("modules/customer_service/router.py", "quick_reply_endpoint"),
    ("modules/customer_service/router.py", "search_faq_endpoint"),
    ("modules/customer_service/router.py", "get_faq_categories"),
}

# 严格依赖的使用方（12 个业务模块）。少一个都意味着某个模块的租户过滤被摘掉了。
EXPECTED_STRICT_MODULES = {
    "modules/aigc_media/router.py",
    "modules/assets/router.py",
    "modules/candidates/router.py",
    "modules/knowledge_base/router.py",
    "modules/monitors/router.py",
    "modules/platform_rules/router.py",
    "modules/products/router.py",
    "modules/voice_clone/router.py",
    # ★ 第 142 轮 A2-3 新增两个。为什么必须用**严格版**而不是豁免：
    #   这两个模块（广告分析 / 竞品情报）的 service 在第 142 轮改接
    #   `amazon_sp.get_data_source()`，取数入口是 `store_id` —— 也就是说
    #   **没有店铺就取不到任何数据**，只会走显式空状态（no_data）。
    #   它们的端点全是 POST（被守卫判为写方法），strict 版自然命中。
    #   为什么不豁免成 optional：豁免在这里只会把「你没选店铺」这句
    #   可行动的提示，换成一句看起来像「AI 变笨了」的空结果（归因错误）。
    #   前端两条通道都会自动带该头（`api/request.ts:124-127`、
    #   `api/stream.ts:48-51`），所以真实用户不会被挡；
    #   这条守卫挡的是"绕过前端直接调 API"的那种请求。
    "modules/ad_analysis/router.py",
    "modules/competitor_intel/router.py",
    # ★ 第 143 轮 A4 新增。 此前**只有 service/tools、没有 router**
    #   （六大复盘能力后端零 HTTP 入口），A4 补 router 并挂 main.py 时一次性接上
    #   strict 版。理由与上面两个同构：复盘取数**必须**按 store_id（没有店铺就取不到
    #   任何数据），且它的 6 个端点全是 POST ⇒ 自然命中 strict。
    #   为什么不豁免成 optional：Mock 数据源对任意 store_id 都返回同一批数据
    #   （实测 35 行 ×4 张表），豁免会把「你没选店铺」这句**可行动**的提示，
    #   换成一份看起来正常、却不知属于谁的报告 —— 归因错误。
    "modules/review_analyst/router.py",
    # ★ 第 143 轮 A4 新增。`/customer-service/ticket/create` 在 A4 之前**连
    #   X-Shop-ID 都不取** —— 所以即便建了表也落不下租户维度（`shop_id` 为空
    #   会被外键拒绝，用户看到 500 且报错里带约束名）。A4 一边给工单建表落库、
    #   一边把 strict 守卫接到这个端点上，两件事必须同时做。
    #   为什么用 strict 而不是豁免：工单是**写业务数据**，缺店铺就该硬拒绝；
    #   而本模块的读端点（chat / faq / order track）并不带这个依赖 ⇒ 不受影响。
    "modules/customer_service/router.py",
    # ★ 第 287 轮新增。此前 trade **根本没有 router.py**（只有 db_model /
    #   service / tools），本轮补端点（`review_dispositions` 的出口）才第一次
    #   出现 HTTP 面 ⇒ 守卫是跟着端点一起长出来的，不是后来补的。
    #   为什么用 strict 而不是豁免：这张表的 shop_id 是外键（RESTRICT），
    #   空店铺写不进去（表现为 500 + 约束名）；而**读**端点若豁免，
    #   缺店铺时只能「什么都不返回」——把「没选店铺」伪装成「没有处置记录」。
    #   strict 让缺店铺在**入口**就 400，是可行动的提示。
    "modules/trade/router.py",
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


async def test_write_with_real_shop_still_succeeds(client, make_user):
    """守卫不能误伤正常调用：**车主带真实店铺头**的写入必须照旧 201 且落对 shop_id。

    ★★ 第 177 轮改前置（原前置已不成立）：
      原来这里是「`ensure_shop()` 造一家**无主**店铺 + **匿名**写入」。那条路
      能通**仅仅**因为 `core/tenant/middleware.py::_resolve_current_shop_id` 里
      写着 `if current_user is None: return shop_id` —— 归属校验整段被跳过
      （"列表紧、单店松"，体检报告 P1-5）。第 177 轮收掉该档后：
        · 匿名写真实店铺 ⇒ 403（正确行为，见 `test_demo_store.py` 第 6 节）；
        · 无主店铺对**任何**身份都不可访问 —— `_matches` 的过渡期兜底分支
          在 `owner_id` 为空时返回 False。
      ⇒ 前置改为「真用户 + 他自己的店」。用例要验证的东西**没变**：
        空白值守卫（缺头 400）不误伤正常写入。
    """
    a = await make_user("guard-ok")
    r0 = await client.post(
        "/api/v1/stores", headers=a["headers"],
        json={"name": "守卫不误伤店", "platform": "amazon"},
    )
    assert r0.status_code in (200, 201), r0.text
    sid = r0.json()["id"]

    r = await client.post("/api/v1/spus", json={"title": "guard-ok"},
                          headers={**a["headers"], "X-Shop-ID": sid})
    assert r.status_code == 201, r.text

    async with async_session_factory() as db:
        got = (await db.execute(
            text("SELECT shop_id FROM spus WHERE id = :i"), {"i": r.json()["id"]}
        )).scalar()
    assert got == sid, f"落库 shop_id 应为 {sid}，实际 {got!r}"


async def test_shop_id_is_stripped_before_use(client, make_user):
    """`X-Shop-ID: '  store_x  '` 应被规整后正常放行（头解析不管空白）。

    ★★ 第 177 轮前置同 `test_write_with_real_shop_still_succeeds` 重基
      （无主店铺 + 匿名的组合已不可写）—— 本用例验证的是**空白规整**，
      不是匿名放行。
    """
    a = await make_user("guard-space")
    r0 = await client.post(
        "/api/v1/stores", headers=a["headers"],
        json={"name": "守卫空白规整店", "platform": "amazon"},
    )
    assert r0.status_code in (200, 201), r0.text
    sid = r0.json()["id"]

    r = await client.post("/api/v1/spus", json={"title": "guard-space"},
                          headers={**a["headers"], "X-Shop-ID": f"  {sid}  "})
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


# ====== 2.5 详情读端点：缺头/跨店不得越权（第 271 轮 P0-1） ======

async def test_detail_read_never_leaks_across_shop(client, make_user):
    """
    详情读端点（GET /spus/{id} 等）缺 X-Shop-ID 或带**别家**店铺头时，
    必须 404 —— 不得返回别的租户的数据。

    背景（P0-1，2026-09-25）：四处详情端点原写 `if shop_id: q = scoped(...)`，
    缺头时 `shop_id=None` ⇒ 过滤被整个跳过 ⇒ 拿到**全库任意**记录（ID 形如
    `spu-<毫秒>` 可枚举）。而 400 空值守卫只对写方法生效（middleware.py），
    GET 缺头返回 None。修复：去掉 `if shop_id:`，无条件 `scoped()` ——
    `shop_id=None` 时 SQL 为 `col IS NULL` ⇒ 0 行 ⇒ 404。

    ★ 反向注入验证：把 `scoped(q, ...)` 改回 `if shop_id: q = scoped(...)`
      会命中下面「越权读到 A 的数据」的断言，用例转红。
    """
    a = await make_user("leak-a")
    b = await make_user("leak-b")

    # A 建店 + 建 SPU
    r0 = await client.post(
        "/api/v1/stores", headers=a["headers"],
        json={"name": "越权 A 店", "platform": "amazon"},
    )
    assert r0.status_code in (200, 201), r0.text
    sid_a = r0.json()["id"]

    r1 = await client.post("/api/v1/spus", json={"title": "A 店的 SPU"},
                           headers={**a["headers"], "X-Shop-ID": sid_a})
    assert r1.status_code == 201, r1.text
    spu_id = r1.json()["id"]

    # B 建自己的店
    r2 = await client.post(
        "/api/v1/stores", headers=b["headers"],
        json={"name": "越权 B 店", "platform": "amazon"},
    )
    assert r2.status_code in (200, 201), r2.text
    sid_b = r2.json()["id"]

    # ① B 用户带 B 店头读 A 的 SPU 详情 ⇒ 404（跨店越权防护）
    rb = await client.get(f"/api/v1/spus/{spu_id}",
                          headers={**b["headers"], "X-Shop-ID": sid_b})
    assert rb.status_code == 404, (
        f"带 B 店头读 A 店 SPU 应 404，实际 {rb.status_code} {rb.text[:200]}"
    )

    # ② B 用户**不带** X-Shop-ID 读 A 的 SPU 详情 ⇒ 404（缺头不越权）
    rn = await client.get(f"/api/v1/spus/{spu_id}", headers=b["headers"])
    assert rn.status_code == 404, (
        f"缺头读 A 店 SPU 应 404（安全失败方向），实际 {rn.status_code} {rn.text[:200]}"
    )

    # ③ A 用户带 A 店头读自己的 SPU ⇒ 200（不误伤正常读取）
    ra = await client.get(f"/api/v1/spus/{spu_id}",
                          headers={**a["headers"], "X-Shop-ID": sid_a})
    assert ra.status_code == 200, ra.text
    assert ra.json()["id"] == spu_id


# ★ 第 283 轮：此处原有一条手写**端点字典**的 AST 护栏（四处详情端点）。
#   它守住了 assets / products / monitors 三个 router，但 platform_rules /
#   knowledge_base / candidates 三个 service **从未进过名单** —— 第 283 轮
#   人工审查才发现那 5 处同形态越权。手写名单必然漂移，形态扫描不会。
#   ⇒ 该断言已升级为「全仓扫描」并迁至
#     `tests/test_tenant_scoping.py::test_no_conditional_scope_mounting`
#     （含扫描器自检），本文件不再留第二份实现。
#     下面保留的是它的**行为层**对应物：真的发请求，看会不会漏。


async def test_library_detail_reads_never_leak_across_shop(client, make_user):
    """
    三处资料库**详情读端点**缺 X-Shop-ID 时不得跨租户（第 283 轮 P0 修复）。

    ★ 与上一节 `test_detail_read_never_leaks_across_shop` 的区别：
      那一节的四处端点住在 `router.py`；这一批漏洞住在 **`service.py`**
      （`knowledge_base` 的 9 处 `scoped_if`、`candidates._load_scoped`、
      `platform_rules.get_rule_by_id` / `get_doc_by_id`）—— 所以旧的
      端点字典门禁一处都没扫到它们。

    共同形态：GET 缺 `X-Shop-ID` 时 `get_current_shop_id` 返回 **None**
    （400 空值守卫只拦写方法，GET 不在 `WRITE_METHODS` 里），而 service 写成
    `if shop_id: q = scoped(...)` ⇒ 条件整个不发 ⇒ **凭 id 可读任意租户**的
    规则源文件正文 / 业务话术源码 / 候选选品详情。

    ★ 反向注入：把 service 里的 `scoped(...)` 改回 `if shop_id: scoped(...)`
      （或把 `scoped_if` 加回来），下面「缺头 ⇒ 404」与「跨店 ⇒ 404」两组
      断言会立刻得到 200 + 正文，用例转红。
    """
    a = await make_user("lib-a")
    b = await make_user("lib-b")

    def _owned(user, sid=None):
        h = dict(user["headers"])
        if sid:
            h["X-Shop-ID"] = sid
        return h

    async def _store(user, name):
        r = await client.post(
            "/api/v1/stores", headers=_owned(user),
            json={"name": name, "platform": "amazon"},
        )
        assert r.status_code in (200, 201), r.text
        return r.json()["id"]

    sid_a = await _store(a, "资料库 A 店")
    sid_b = await _store(b, "资料库 B 店")

    # A 在自家店里放三样东西：规则源文档 / 业务话术文档 / 候选选品
    rule_doc = (await client.post(
        "/api/v1/platform-rule-docs",
        json={"filename": "A-secret-rule.pdf", "platform": "amazon", "content": "A 的内部规则正文"},
        headers=_owned(a, sid_a),
    )).json()

    kb_id = (await client.post(
        "/api/v1/knowledge-base", json={"name": "A 的私有库"}, headers=_owned(a, sid_a),
    )).json()["id"]
    kb_doc = (await client.post(
        "/api/v1/knowledge-base/docs",
        json={"kb_id": kb_id, "filename": "A-secret.md", "content": "A 的售后政策底稿"},
        headers=_owned(a, sid_a),
    )).json()

    cand = (await client.post(
        "/api/v1/candidates",
        json={"asin": "B0AAAAAAAAA", "title": "A 的秘密候选品"},
        headers=_owned(a, sid_a),
    )).json()

    targets = [
        ("平台规则源文档", f"/api/v1/platform-rule-docs/{rule_doc['id']}"),
        ("业务话术文档", f"/api/v1/knowledge-base/docs/{kb_doc['id']}"),
        ("候选选品详情", f"/api/v1/candidates/{cand['id']}"),
    ]

    for label, url in targets:
        # ① B **不带头**读 A 的资源 ⇒ 404（不是全库可读）
        rn = await client.get(url, headers=_owned(b))
        assert rn.status_code == 404, (
            f"{label}：B 缺 X-Shop-ID 应 404（安全失败方向），"
            f"实际 {rn.status_code} {rn.text[:200]}"
        )

        # ② B 带**自己店**的头读 A 的资源 ⇒ 404
        rb = await client.get(url, headers=_owned(b, sid_b))
        assert rb.status_code == 404, (
            f"{label}：B 带自己店铺头应 404，实际 {rb.status_code} {rb.text[:200]}"
        )

        # ③ A 带自己店的头读自己的资源 ⇒ 200（不误伤正常读取）
        ra = await client.get(url, headers=_owned(a, sid_a))
        assert ra.status_code == 200, (
            f"{label}：A 读自己的资源应 200，实际 {ra.status_code} {ra.text[:200]}"
        )


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

    monkeypatch.setattr(candidates_service, "create_candidate", _boom)

    result = await ProductResearchAgent()._write_candidates(
        [{"asin": "B0PROBE001", "title": "no-shop probe"}], None, None
    )

    assert result["type"] == "candidate_save_failed", result
    assert "店铺" in result.get("error", ""), f"失败原因须指向店铺：{result}"
    assert touched == [], "必须在触达数据库之前就拦下"
