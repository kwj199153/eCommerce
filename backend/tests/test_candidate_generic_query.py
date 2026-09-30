"""候选选品库 —— 「通用查询」门禁（第 216 轮）。

动因是老板的追问：
    「换成真正的数据源的数据，也能很好地工作吗？是否具有通用性？
     （或者说我换个问题问，而不是预估销量前 3，而是售价前 5、
     评审状态通过的产品等等，对这个数据的查询能否正常）」

改前实测（`.workbuddy/probes/216b_generic_query_probe.py` + `216b_contract_probe.py`）
暴露**三处结构性不通用** —— 小库看不出来，换真数据源立刻爆发：

  ① **截断口径 ≠ 排序口径**：「销量前 3」拿到的不是销量前 3。`limit` 一个人
     兼表分页与 Top-N，SQL 先按 `updated_at` 截断，真前 3 **从未进入候选集**
     （实测手牌 `[009(560), 009(560), 007(750)]` vs 真前 3
      `[006(3200), 004(2100), 005(1800)]`，交集为空）；「售价前 5」同型复现。
  ② **`total` 撒谎**：它等于 `LIMIT` **之后**的长度 ⇒ 答「评审通过有几个」时
     给的是被截断的数（本库 11 条时 `list_candidates(limit=1)` 报 `total=1`）。
  ③ **过滤值域只写在 docstring 里**（`args_schema` 没有 `enum`）⇒ 传「通过」
     「APPROVED」静默回**空列表**，「真的没有」与「你传错了」被压成同一个结果。

本文件把「修好了」钉成可执行判据。每条判据的**反向注入**（证明它真会转红）
记在文件末尾。
"""

import ast
import asyncio
import inspect
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import text

from core.database import async_session_factory
from modules.candidates import (
    CANDIDATE_SORT_FIELDS,
    CANDIDATE_SORT_KEYS,
    CandidateQueryError,
    count_candidates,
    create_candidate,
    list_candidates,
)
from modules.candidates.db_model import CandidateRecord
from modules.library.tools import build_library_tools

#: 专用合成店铺 —— 已登记在 `conftest.SYNTHETIC_TEST_SHOP_IDS`
#: （外键前提；会话结束由会话级夹具按 shop_id 清理业务数据）。
#: ★ 用**专用**店铺而不是 `store_test`：后者被另外几个用例共用，
#:   本文件要按「绝对条数」断言，共用一个店铺会变成
#:   「全量跑绿、单跑也绿、换个顺序就红」那种顺序依赖。
_SHOP = "store_r216_q"

_BACKEND = Path(__file__).resolve().parents[1]
_AGENT_FILE = _BACKEND / "modules" / "product_research" / "agent_product_research.py"


# ============================================================== 夹具 / 助手

async def _wipe() -> None:
    async with async_session_factory() as s:
        await s.execute(text("DELETE FROM candidates WHERE shop_id = :s"), {"s": _SHOP})
        await s.commit()


@pytest_asyncio.fixture(autouse=True)
async def _isolated_shop():
    """每个用例前后都清空本店铺的候选 ⇒ 条数断言可复现（顺序无关）。"""
    await _wipe()
    yield
    await _wipe()


async def _seed(specs: list) -> list:
    """按 spec 顺序落库（用真写入口，不绕过 service）。

    每行显式给 `id`：`build_candidate_record` 缺省用**毫秒时间戳**造 id，
    同一毫秒内连写两行会撞主键（PK）—— 那是用例自身的坑，不是被测行为。
    """
    out = []
    for i, s in enumerate(specs):
        out.append(await create_candidate(
            {
                "id": s.get("id") or f"cand-r216-{i}",
                "asin": s.get("asin", ""),
                "title": s.get("title") or f"种子商品{i}",
                "price": s.get("price", 0),
                "estimated_monthly_sales": s.get("sales", 0),
                "review_status": s.get("status", "pending"),
            },
            shop_id=_SHOP,
            on_duplicate="allow",
        ))
    return out


def _tool():
    """Agent 真正拿到手的那个工具（不是 REST 端点）。"""
    tools = build_library_tools(shop_id=_SHOP)
    return next(t for t in tools if t.name == "list_candidates")


async def _call_tool(**kw) -> dict:
    return json.loads(await _tool().coroutine(**kw))


# ============================================== A. 排序白名单（形态判据）

def test_sort_whitelist_points_at_real_columns():
    """白名单的每个 value[0] 必须是 `CandidateRecord` 上**真实存在的列**。

    ★ 按**属性名相等**核对，不做源码字符串包含 —— 后者会被同族更长的标识符
      顶掉（`enabled` ⊂ `enabled_agents`）。
    """
    cols = set(CandidateRecord.__table__.columns.keys())
    for key, spec in CANDIDATE_SORT_FIELDS.items():
        attr, direction = spec
        assert attr in cols, f"排序维度 {key!r} 指向的列 {attr!r} 在 CandidateRecord 上不存在"
        assert direction in ("asc", "desc"), f"{key!r} 的方向非法：{direction!r}"
    assert set(CANDIDATE_SORT_FIELDS) == set(CANDIDATE_SORT_KEYS)
    assert len(CANDIDATE_SORT_KEYS) >= 5, "排序维度太少 ⇒ 大概率漏了前端已有的排序项"


def test_rest_endpoint_exposes_the_same_three_knobs():
    """REST 端点也必须能表达排序 —— 否则「换个问法」在 HTTP 侧仍不可达。"""
    from modules.candidates.router import list_candidates as endpoint

    params = set(inspect.signature(endpoint).parameters)
    assert {"order_by", "limit", "review_status"} <= params, params


# ============================================ B. 工具出参 / 描述的契约

def test_tool_exposes_order_by_and_lists_every_sort_key():
    """工具必须**暴露** `order_by`，且描述里列全可用值。

    ★ 只暴露 `limit` 时，模型问「销量前 3」唯一能表达「3」的地方就是 `limit`
      ⇒ SQL 先按 `updated_at` 截断 ⇒ 真前 3 从未进入候选集。
      「工具参数面缺一个维度」这件事在运行期**不报错**，只会静默答错。
    """
    tool = _tool()
    props = (tool.args_schema.model_json_schema().get("properties") or {})
    assert "order_by" in props, f"工具没暴露 order_by，实有参数 = {sorted(props)}"
    missing = [k for k in CANDIDATE_SORT_KEYS if k not in (tool.description or "")]
    assert not missing, f"工具描述没告诉模型这些排序维度可用：{missing}"


async def test_tool_reports_invalid_argument_not_read_failure():
    """参数写错 ⇒ `invalid_argument`（可自我纠正），不是 `library_read_failed`。

    ★ 两者处置完全不同：前者「换个值再试」，后者「读不到，别指望了」。
      合成一个 type ⇒ 模型会把「你 order_by 写错了」转述成「资料库读不出来」，
      老板就去查一个不存在的问题。
    """
    d = await _call_tool(order_by="销量")
    assert d["type"] == "invalid_argument", d
    assert "order_by" not in d["type"]
    assert "销量" in (d.get("error") or "")
    assert d["type"] != "library_read_failed"


# ================================================ C. 「换个问法」真能答对

async def test_sales_top3_is_ordered_by_sql_not_by_client():
    """「预估销量前 3」必须由 **SQL** 给出真前 3（本轮的核心判据）。

    种子按 sales 升序写入、且写入顺序与 sales 顺序**一致** ——
    这样「按 updated_at 倒序」得到的恰好是 sales 的**反序** ⇒
    排序若被忽略，断言必红（不会因为两种口径碰巧一致而假绿）。
    """
    await _seed([
        {"id": "cand-r216-s1", "asin": "B0R216S1", "sales": 100},
        {"id": "cand-r216-s2", "asin": "B0R216S2", "sales": 500},
        {"id": "cand-r216-s3", "asin": "B0R216S3", "sales": 300},
        {"id": "cand-r216-s4", "asin": "B0R216S4", "sales": 900},
        {"id": "cand-r216-s5", "asin": "B0R216S5", "sales": 200},
    ])
    rows = await list_candidates(_SHOP, limit=3, order_by="sales")
    assert [r["asin"] for r in rows] == ["B0R216S4", "B0R216S2", "B0R216S3"], (
        [r["asin"] for r in rows]
    )
    d = await _call_tool(limit=3, order_by="sales")
    assert [i["asin"] for i in d["items"]] == ["B0R216S4", "B0R216S2", "B0R216S3"]
    assert d["total"] == 5, "total 是真实总数（5），不是 returned（3）"


async def test_price_top5_is_ordered_by_sql():
    """「售价前 5」—— 老板举的第二个例子，同型判据，防止只修了销量那一条。"""
    await _seed([
        {"asin": "B0R216P1", "price": 9.99},
        {"asin": "B0R216P2", "price": 49.99},
        {"asin": "B0R216P3", "price": 29.99},
    ])
    d = await _call_tool(limit=5, order_by="price")
    assert [i["asin"] for i in d["items"]] == ["B0R216P2", "B0R216P3", "B0R216P1"]


async def test_every_whitelisted_sort_key_actually_orders():
    """白名单里**每一个**键都要真的能排 —— 防止「白名单登记了但代码没实现」。"""
    await _seed([
        {"id": "cand-r216-w1", "asin": "B0R216W1", "price": 1, "sales": 1,
         "rating": 1.0, "blue_ocean_score": 1, "roi": 1},
        {"id": "cand-r216-w2", "asin": "B0R216W2", "price": 2, "sales": 2,
         "rating": 2.0, "blue_ocean_score": 2, "roi": 2},
    ])
    for key in CANDIDATE_SORT_KEYS:
        rows = await list_candidates(_SHOP, order_by=key)
        assert len(rows) == 2, f"{key} 查询失败"
        if key == "updated_at":
            continue
        first = rows[0]
        second = rows[1]
        attr = dict(
            price="price", sales="estimated_monthly_sales", rating="rating",
            blue_ocean_score="blue_ocean_score", roi="roi_estimated",
        )[key]
        assert first[attr] >= second[attr], (
            f"{key} 没有真的按 {attr} 倒序：{first[attr]} -> {second[attr]}"
        )


async def test_review_status_filter_works_and_lists_its_value_domain():
    """「评审状态通过的产品」现在就能答对；非法值从「静默空列表」改为报错。"""
    await _seed([
        {"asin": "B0R216R1", "status": "approved"},
        {"asin": "B0R216R2", "status": "approved"},
        {"asin": "B0R216R3", "status": "pending"},
    ])
    rows = await list_candidates(_SHOP, review_status="approved")
    assert {r["asin"] for r in rows} == {"B0R216R1", "B0R216R2"}
    for bad in ("通过", "APPROVED", "pass"):
        with pytest.raises(CandidateQueryError) as ei:
            await list_candidates(_SHOP, review_status=bad)
        assert "approved" in str(ei.value), "报错必须列出可选值，模型才能自我纠正"


@pytest.mark.parametrize("bad", ["bogus", "estimated_monthly_sales", "Sales", "销量"])
async def test_invalid_order_by_raises_instead_of_silently_degrading(bad):
    """非法排序必须报错 —— 静默退化成默认排序会让「按售价排」与
    「按更新时间排」在模型看来长得一样（归因错方向）。"""
    with pytest.raises(CandidateQueryError) as ei:
        await list_candidates(_SHOP, order_by=bad)
    msg = str(ei.value)
    assert bad in msg
    for k in CANDIDATE_SORT_KEYS:
        assert k in msg, f"报错没列出可选值 {k}"


@pytest.mark.parametrize("blank", [None, "", "   "])
async def test_blank_order_by_means_default(blank):
    """空串 / 纯空白 = **不指定**（有意选的边），不是错误。

    理由：空串在 URL（`?order_by=`）与 LLM 出参里都是「没填」的自然表达。
    """
    await _seed([{"asin": "B0R216B1"}, {"asin": "B0R216B2"}])
    a = await list_candidates(_SHOP, order_by=blank)
    b = await list_candidates(_SHOP, order_by="updated_at")
    assert [r["id"] for r in a] == [r["id"] for r in b]


async def test_default_sort_is_still_newest_first():
    """不传 `order_by` ⇒ 与改前「最新更新在前」**逐字一致**（不静默变样）。"""
    await _seed([{"id": "cand-r216-d1", "asin": "B0R216D1"}])
    await asyncio.sleep(0.01)
    await _seed([{"id": "cand-r216-d2", "asin": "B0R216D2"}])
    rows = await list_candidates(_SHOP)
    assert [r["asin"] for r in rows] == ["B0R216D2", "B0R216D1"]


# ==================================================== D. 去重 / total 口径

async def test_read_dedupes_by_asin_keeping_the_newest():
    """同店同 ASIN 只留 `updated_at` 最新的那条（老板原话「其实是同一个产品」）。"""
    await _seed([{"id": "cand-r216-dup1", "asin": "B0R216DUP", "price": 10.0}])
    await asyncio.sleep(0.01)
    await _seed([{"id": "cand-r216-dup2", "asin": "B0R216DUP", "price": 20.0}])
    rows = [r for r in await list_candidates(_SHOP) if r["asin"] == "B0R216DUP"]
    assert len(rows) == 1, "同 ASIN 必须只留一条"
    assert rows[0]["price"] == 20.0, "留下的必须是更新的那条"
    async with async_session_factory() as s:
        raw = (await s.execute(
            text("SELECT count(*) FROM candidates WHERE shop_id = :s"), {"s": _SHOP}
        )).scalar()
    assert raw == 2, "去重只发生在**读口**，不许顺手删库里的行"


async def test_blank_asin_rows_are_never_collapsed():
    """空 ASIN 不参与去重 —— 按 ASIN 归并会把一堆手填候选塌成一条（丢数据）。"""
    await _seed([
        {"id": "cand-r216-b1", "asin": "", "title": "手填甲"},
        {"id": "cand-r216-b2", "asin": "", "title": "手填乙"},
    ])
    rows = await list_candidates(_SHOP)
    assert len(rows) == 2, f"空 ASIN 被误归并了：{[r['title'] for r in rows]}"


async def test_total_is_the_real_count_and_returned_is_the_page():
    """`total` = 真实总数；`returned` = 本次返回条数。两者不再共用一句话。"""
    await _seed([{"asin": f"B0R216T{i}"} for i in range(5)])
    assert await count_candidates(_SHOP) == 5
    assert len(await list_candidates(_SHOP, limit=1)) == 1
    d = await _call_tool(limit=1)
    assert d["total"] == 5, "total 必须是真实总数（改前这里是 LIMIT 后的长度 1）"
    assert d["returned"] == 1


async def test_counts_are_consistent_with_the_list_and_sum_to_total():
    """各状态条数之和 == total，且「列表长度 == 计数」逐个状态成立。

    ★ 这条防的是**先筛后归并**：过滤若被塞进去重子查询里，同一 ASIN 会在
      pending 视图里留 pending 那条、在 approved 视图里留 approved 那条
      ⇒ 各状态条数之和大于 total（实测：approved=5 + pending=5 > total=9）。
    """
    await _seed([
        {"asin": "B0R216C1", "status": "approved"},
        {"asin": "B0R216C2", "status": "approved"},
        {"asin": "B0R216C3", "status": "pending"},
        {"asin": "B0R216C4", "status": "rejected"},
    ])
    total = await count_candidates(_SHOP)
    assert total == 4
    per = {}
    for st in ("pending", "under_review", "approved", "rejected"):
        n_list = len(await list_candidates(_SHOP, review_status=st))
        n_cnt = await count_candidates(_SHOP, st)
        assert n_list == n_cnt, f"{st}: 列表 {n_list} 条但计数说 {n_cnt} 条"
        per[st] = n_cnt
    assert per == {"pending": 1, "under_review": 0, "approved": 2, "rejected": 1}
    assert sum(per.values()) == total, "各状态之和必须等于总数"


async def test_no_shop_contract_is_unchanged():
    assert await list_candidates(None) == []
    assert await count_candidates(None) == 0


# ======================================== E. 判重收口（写入口唯一实现）

async def test_skip_policy_dedupes_and_says_so():
    first = await create_candidate(
        {"id": "cand-r216-sk1", "asin": "B0R216SKIP", "title": "甲", "price": 10},
        shop_id=_SHOP, on_duplicate="skip",
    )
    assert first["deduped"] is False
    second = await create_candidate(
        {"id": "cand-r216-sk2", "asin": "B0R216SKIP", "title": "乙", "price": 99},
        shop_id=_SHOP, on_duplicate="skip",
    )
    assert second["deduped"] is True, "已存在必须回 deduped=True"
    assert second["id"] == first["id"], "回的是库里那条，不是新 payload 造出来的"
    assert await count_candidates(_SHOP) == 1


async def test_allow_policy_preserves_the_rest_contract():
    """REST 默认档必须**照旧插入** —— 面板是人工显式录入，替用户判重是越权。"""
    await create_candidate({"id": "cand-r216-al1", "asin": "B0R216ALOW"}, shop_id=_SHOP)
    await create_candidate({"id": "cand-r216-al2", "asin": "B0R216ALOW"}, shop_id=_SHOP)
    async with async_session_factory() as s:
        raw = (await s.execute(
            text("SELECT count(*) FROM candidates WHERE shop_id = :s"), {"s": _SHOP}
        )).scalar()
    assert raw == 2, "allow 档（REST 默认）必须保持「总是插入」的既有契约"
    assert await count_candidates(_SHOP) == 1, "但读口要收敛成一条"


async def test_unknown_duplicate_policy_raises():
    with pytest.raises(CandidateQueryError) as ei:
        await create_candidate({"asin": "B0R216X"}, shop_id=_SHOP, on_duplicate="maybe")
    assert "maybe" in str(ei.value)


def _calls_in(func_node):
    """函数体内所有 Call 的被调名（Name 或 Attribute.attr）。"""
    out = []
    for n in ast.walk(func_node):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name):
                out.append(n.func.id)
            elif isinstance(n.func, ast.Attribute):
                out.append(n.func.attr)
    return out


def test_write_path_defers_dedupe_to_the_write_entry():
    """形态判据：`_write_candidates` **不得**自己判重，且必须要求写入口判重。

    ★ 为什么走 AST 而不是「源码里有没有 `candidate_exists`」：
      docstring / 注释里提到它是**有价值**的（保留历史），
      拿字符串包含判会既骗过注释又误伤文档。
    """
    tree = ast.parse(_AGENT_FILE.read_text(encoding="utf-8"))
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_write_candidates"
    )
    called = _calls_in(fn)
    assert "candidate_exists" not in called, (
        "判重又漂回调用侧了 —— 收口目标是写入口 create_candidate"
    )
    assert "create_candidate" in called, "找不到对写入口的调用"
    kws = [
        k.arg
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "create_candidate"
        for k in n.keywords
    ]
    assert "on_duplicate" in kws, (
        "调用写入口时必须**显式交代**判重策略（on_duplicate='skip'）"
    )
    vals = {
        getattr(k.value, "value", None)
        for n in ast.walk(fn)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "create_candidate"
        for k in n.keywords if k.arg == "on_duplicate"
    }
    assert vals == {"skip"}, f"判重策略必须是 skip，实测 {vals}"


def test_dedupe_query_has_exactly_one_call_site_in_the_whole_backend():
    """形态判据：判重查询**只允许有一个调用点**，且在 `candidates/service.py`。

    ★ 「同一判定两份实现 ⇒ 至少一份永远测不到」。改前这里是「一份实现挂错
      地方」：`candidate_exists` 只在选品 Agent 那条写路径上被调用，
      REST 那条路完全不判重 ⇒ 重复行继续长。
    """
    hits = []
    for p in (_BACKEND / "modules").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            nm = None
            if isinstance(n.func, ast.Name):
                nm = n.func.id
            elif isinstance(n.func, ast.Attribute):
                nm = n.func.attr
            if nm in ("candidate_exists", "find_candidate_by_asin"):
                hits.append((p.relative_to(_BACKEND).as_posix(), nm))

    assert hits, "连唯一实现都找不到了？判重收口不该把实现也删掉"
    bad = [h for h in hits if h[0] != "modules/candidates/service.py"]
    assert not bad, f"这些地方自己查了一遍判重（应收口进写入口）：{bad}"
    n_query = [nm for _, nm in hits].count("find_candidate_by_asin")
    assert n_query == 1, f"判重查询的调用点必须恰好 1 处，实测 {n_query}"


# ============================================================================
# 反向注入记录（每条判据都实测过「注进去会转红」，否则它只是装饰）
# ============================================================================
#
# · test_sales_top3_is_ordered_by_sql_not_by_client
#     注入：把 `list_candidates` 里的 `order_by(sort_clause, ...)` 改回
#           `order_by(CandidateRecord.updated_at.desc())`
#     → 红（实测拿到 S5/S4/S3 = updated_at 倒序，而不是 S4/S2/S3）。
# · test_total_is_the_real_count_and_returned_is_the_page
#     注入：把工具层 `_rows_to_candidates` 的 `total` 改回 `len(items)`
#     → 红（total 变 1）。
# · test_invalid_order_by_raises_instead_of_silently_degrading
#     注入：删掉 `_sort_clause` 里的白名单校验（改成 `key = DEFAULT_SORT_FIELD`）
#     → 红（不再抛 CandidateQueryError）。
# · test_invalid_review_status / invalid_argument
#     注入：删掉 `_review_filter` 里的值域校验 → 红。
# · test_read_dedupes_by_asin_keeping_the_newest
#     注入：去掉 `_deduped_rows_subquery`（直接 select 全表）→ 红（2 条）。
# · test_blank_asin_rows_are_never_collapsed
#     注入：把去重键的 `CASE WHEN asin = '' THEN id ELSE asin END` 简化为
#           `CandidateRecord.asin` → 红（2 行塌成 1 行）。
# · test_counts_are_consistent_with_the_list_and_sum_to_total
#     注入：把 review_status 过滤挪回 `_deduped_rows_subquery` 内（先筛后归并）
#     → 红（approved + pending > total）。
# · test_write_path_defers_dedupe_to_the_write_entry
#     注入：在 `_write_candidates` 里重新加一行 `await candidate_exists(...)`
#     → 红。
# · test_dedupe_query_has_exactly_one_call_site_in_the_whole_backend
#     注入：在 REST handler 或工具层加一处 `find_candidate_by_asin(...)` → 红。
# · test_tool_exposes_order_by_and_lists_every_sort_key
#     注入：把工具描述里的排序维度清单删掉 → 红。
