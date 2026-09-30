"""第 289 轮：产品 ↔ 差评 **软关联** 的出口与口径门禁。

背景（为什么要单独一文件盯着）
--------------------------------
差评的 `asin` / `sku` **没有外键**指向 `skus`（平台侧标识符，不能因为本地
产品库少一行就让差评插不进来）。没有外键兜 ⇒ join 可能一行都匹配不上，
而「匹配不上」有两种语义完全不同的"空"：

    A. 这个产品确实没有差评            —— 正常结论
    B. 差评和产品**没能对上**（数据缺口）—— 把 B 显示成 A ＝ 把缺口伪装成清白

于是本文件钉四件事：

    ① **两个空态必须字面不同** —— `no_reviews` 与 `no_asin_binding` / `no_sku`
       不得被合并（面板上要分开播报，见 `ProductLibrary.vue`）；
    ② **SPU 内必须去重** —— 同一个 ASIN 会挂在多个 SKU 上（真库实测
       `B0CXXXX009` → 4 SKU / 4 SPU），不去重则同一批差评被重复计数；
    ③ **店铺作用域两处都要收窄** —— `skus` 表没有 `shop_id`，产品归属只能经
       `spus.shop_id`；差评自己另有一份 `shop_id`，两条都得挂；
    ④ **孤儿必须有出口** —— 关联不上的差评不会出现在任何产品的差评 tab 里，
       没有兜底列表它们只是静默消失。

★ 与 `test_trade_disposition.py` 同形态：**全部 monkeypatch，不连共享库**
  （本仓 `tests/` 连的是共享生产库，依赖 seed 数据的用例不可复现）。

反向注入（本门禁不是空跑的实证，逐条跑过）
--------------------------------
  · 删掉 `list_reviews_for_spu` 里的 `.distinct()`            ⇒ ② 红
  · 去掉 `scope_condition(SpuRecord, shop_id)` 那一处          ⇒ ③ 红
  · 把 `no_asin_binding` 改成 `no_reviews`                     ⇒ ① 红
  · 把 `_not_bound_to_sku` 的 `.correlate(CustomerReviewRecord)` 去掉 ⇒ ③/孤儿红
"""

from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.trade import service as svc
from modules.trade.db_model import CustomerReviewRecord

BACKEND = Path(__file__).resolve().parents[1]
SERVICE_SRC = (
    (BACKEND / "modules" / "trade" / "service.py")
    .read_bytes().decode("utf-8").replace("\r\n", "\n")
)
ROUTER_SRC = (
    (BACKEND / "modules" / "trade" / "router.py")
    .read_bytes().decode("utf-8").replace("\r\n", "\n")
)

SHOP = "store_unit_test"
SPU = "prod-unit-001"


# ============================================================ 源码形态探针

def _func_src(name: str) -> str:
    """取出某个函数/协程的源码片段（变量名共享 ⇒ 只按名字足以定位）。"""
    tree = ast.parse(SERVICE_SRC)
    hits = [
        ast.get_source_segment(SERVICE_SRC, n) or ""
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    ]
    assert hits, f"service 里找不到函数 {name}（改名后本门禁须同步）"
    return hits[0]


def _string_literals_in(name: str) -> set[str]:
    """取出函数体里的**字符串常量**（**剥掉 docstring**）。

    ★ 为什么不能用 `'"x" in ast.get_source_segment(...)`：
      ① docstring / 注释里写了同一串 ⇒ 真代码删了照样恒绿（已实测假绿一次）；
      ② 反过来，注释里的描述也会让「 newValue 不存在」的判据失效。
      AST 不收录注释，且这里显式跳过函数体第一条 str 表达式（docstring）。
    """
    tree = ast.parse(SERVICE_SRC)
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if fn.name != name:
            continue
        body = list(fn.body)
        if body:
            first = body[0]
            is_doc = (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            )
            if is_doc:
                body = body[1:]
        return {
            c.value
            for node in body
            for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        }
    raise AssertionError(f"service 里找不到函数 {name}")


def _router_paths() -> set[str]:
    """router 上登记的路径集合 —— 端点是「出口」，不能被任意改名。"""
    tree = ast.parse(ROUTER_SRC)
    paths = set()
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in n.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if isinstance(f, ast.Attribute) and f.attr in {"get", "post", "put", "patch", "delete"}:
                if dec.args and isinstance(dec.args[0], ast.Constant):
                    paths.add(str(dec.args[0].value))
    return paths


def _service_calls_in_router() -> set[str]:
    """router 里**引用到的** `service.<name>` —— 「有函数没出口」就是这么长出来的。

    ★ 只收 `service.X(...)` 的**调用**形态会收集到**空集**：本仓 router 的实际
      写法是 `_guard(service.X, "标签", session, shop, ...)` —— 函数对象作为
      **参数**传进统一异常映射点，全部 11 个端点都是这个形态。
      ⇒ 判据必须覆盖「属性引用」，而不是「函数调用」。
    """
    tree = ast.parse(ROUTER_SRC)
    return {
        n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Attribute)
        and isinstance(n.value, ast.Name)
        and n.value.id == "service"
    }


def test_router_call_probe_is_not_empty():
    """自证：上面的探针在本文件里必须真能吃到东西（空集 ⇒ 每条断言都恒红）。"""
    calls = _service_calls_in_router()
    assert calls, "router 里一个 service.X 都没解析到 —— 探针形态错了，门禁在假红"
    assert "list_dispositions" in calls, "连既有端点都没解析到 ⇒ 探针不可信"


# ============================================================ 假会话

class _Res:
    """同时支持 `.scalars().all()/.first()` 与 `.all()/.first()/.scalar_one()`。

    ★ 为什么不实现 where 语义：那等于把 SQLAlchemy 重抄一遍，抄错会得到一份
      「看起来很真的假结果」。过滤是否发生，改由**语句文本**形态判据去查
      （照抄 `test_trade_disposition.py` 的做法）。
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one(self):
        if not self._rows:
            raise ValueError("no rows")
        return self._rows[0]


def _sku(sid: str, asin: str, code: str = "") -> SimpleNamespace:
    return SimpleNamespace(id=sid, asin=asin, sku_code=code, spec_value="黑")


def _review(rid: str, asin: str = "B0UNIT0001", sku: str = "",
            rating: int = 1) -> CustomerReviewRecord:
    return CustomerReviewRecord(
        id=rid, shop_id=SHOP, external_review_id=rid, sku=sku, asin=asin,
        product_title="单测产品", rating=rating, review_at="2026-09-01",
        source="unit",
    )


class FakeSession:
    """按语句形态分派的假会话（顺序无关，避免被测函数的实现顺序成为判据）。"""

    def __init__(self, *, spu=None, skus=None, review_ids=None, reviews=None,
                 total=0):
        self.spu = spu
        self.skus = skus if skus is not None else []
        self.review_ids = review_ids if review_ids is not None else []
        self.reviews = reviews if reviews is not None else []
        self.total = total

    async def execute(self, stmt):
        t = str(stmt)
        # ① 计数：count() select_from(customer_reviews)
        if "count(*)" in t:
            return _Res([self.total])
        # ② 孤儿主查（文本里带 `NOT (EXISTS ... FROM skus ...`）必须排在「FROM skus」
        #    之前 —— 否则子查询里的 "FROM skus" 会把明细行分派成 SKU 列表。
        if "NOT (EXISTS" in t:
            return _Res(self.reviews)
        # ③ SPU 本体
        if "FROM spus" in t:
            return _Res([self.spu] if self.spu is not None else [])
        # ③ SPU 名下的 SKU
        if "FROM skus" in t:
            return _Res(self.skus)
        # ④ 差评 id 解集（带 DISTINCT）
        if "SELECT DISTINCT" in t:
            return _Res(self.review_ids)
        # ⑤ 差评明细
        return _Res(self.reviews)


SPU_ROW = SimpleNamespace(id=SPU, title="单测产品", shop_id=SHOP)


# ============================================================ ① 两种空态必须字面不同

def test_empty_states_are_distinct_literals():
    """「确实没有差评」与「没能对上」必须是两个不同的返回值。

    ★ 为什么值得一条断言：界面只看 `empty_state`。合并成一个之后，
      代码照样跑、数量照样对，只是「SKU 没登记 ASIN」会被播报成
      「这个产品没有差评」—— 数据缺口被伪装成产品质量。
    """
    lits = _string_literals_in("list_reviews_for_spu")
    # 自证：探针必须是活的（空集会让下面每条都恒绿 —— 那就是假绿，不是绿）
    assert lits, "AST 探针没取到任何字符串常量 ⇒ 下面的断言全部恒真，门禁是假的"
    for lit in ("not_found", "no_sku", "no_asin_binding", "no_reviews"):
        assert lit in lits, (
            f"`list_reviews_for_spu` 的**返回值**里缺少空态 {lit!r} —— "
            "四种空态少任何一种，界面就少一种归因"
            "（注意：只看 docstring 里有没有这个串是抓不到改动的，已实测）"
        )


@pytest.mark.asyncio
async def test_gap_empty_state_is_not_silently_no_reviews():
    """行为层再现「数据缺口」：SKU 登记了但 ASIN 全空 ⇒ 不是 no_reviews。"""
    s = FakeSession(spu=SPU_ROW, skus=[_sku("sku-1", "", "")])
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["empty_state"] == "no_asin_binding"
    assert out["sku_count"] == 1 and out["asin_count"] == 0
    assert out["total"] == 0 and out["reviews"] == []


@pytest.mark.asyncio
async def test_no_sku_is_its_own_state():
    s = FakeSession(spu=SPU_ROW, skus=[])
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["empty_state"] == "no_sku"


@pytest.mark.asyncio
async def test_spu_outside_shop_lookup_is_not_found():
    """不属于本店的 SPU ⇒ `not_found`，而不是「存在但没差评」。"""
    s = FakeSession(spu=None)
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["found"] is False
    assert out["empty_state"] == "not_found"


@pytest.mark.asyncio
async def test_real_no_reviews_is_a_clean_conclusion():
    """关联得上、确实没有 ⇒ `no_reviews`（这是唯一允许被读成「清白」的空态）。"""
    s = FakeSession(spu=SPU_ROW, skus=[_sku("sku-1", "B0UNIT0001")], review_ids=[])
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["empty_state"] == "no_reviews"
    assert out["found"] is True


# ============================================================ ② SPU 内必须去重

def test_reviews_for_spu_dedupes():
    """同一 ASIN 挂在多个 SKU 上 ⇒ 不去重会被重复计数（真库 4 SKU / 4 SPU）。"""
    src = _func_src("list_reviews_for_spu")
    assert ".distinct()" in src, (
        "`list_reviews_for_spu` 必须先解出 **distinct 差评 id** 再取明细："
        "`B0CXXXX009` 这样的 ASIN 对应多个 SKU，直接 join 明细会把同一条差评数多遍"
    )


@pytest.mark.asyncio
async def test_total_counts_distinct_reviews_not_join_rows():
    """`total` 必须是**去重后**的差评条数。"""
    ids = ["crev-1", "crev-2", "crev-3", "crev-4"]
    rows = [_review(r) for r in ids]
    s = FakeSession(spu=SPU_ROW, skus=[_sku("sku-1", "B0UNIT0001")],
                    review_ids=ids, reviews=rows)
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["total"] == 4
    assert [r["id"] for r in out["reviews"]] == ids


@pytest.mark.asyncio
async def test_match_kind_is_reported():
    """每条差评必须说清「靠什么对上产品」—— 界面要显示「命中 ASIN / SKU 码」。"""
    s = FakeSession(
        spu=SPU_ROW, skus=[_sku("sku-1", "B0UNIT0001", "CODE-1")],
        review_ids=["crev-1"], reviews=[_review("crev-1", asin="B0UNIT0001")],
    )
    out = await svc.list_reviews_for_spu(s, SHOP, SPU)
    assert out["reviews"][0]["match_kind"] == "asin"

    s2 = FakeSession(
        spu=SPU_ROW, skus=[_sku("sku-1", "B0UNIT0001", "CODE-1")],
        review_ids=["crev-2"],
        reviews=[_review("crev-2", asin="", sku="CODE-1")],
    )
    out2 = await svc.list_reviews_for_spu(s2, SHOP, SPU)
    assert out2["reviews"][0]["match_kind"] == "sku_code"


# ============================================================ ③ 店铺作用域两处都要收窄

def test_both_shop_scopes_are_applied_in_spu_query():
    """差评的 `shop_id` 与产品的 `spus.shop_id` 都得挂 —— `skus` 没有店铺列。

    ★ 为什么 `spus` 这一侧必须判 **>= 2 处**而不是「存在」
      ----------------------------------------------------------------
      这两处守的是**不同的东西**，删掉任何一处都不该放行：
        (a) SPU 本体查询 —— 判断这个 SPU 属不属于本店；
        (b) 差评 join 查询 —— 挡住「别家店的 SKU 用同一个 ASIN 认领本店差评」。
      原先只判「存在」⇒ 删一处、留一处，测试照样绿（防御被悄悄打了折
      还没人发现）。这类漏判不会报错，只会让口子慢慢变大。
    """
    src = _func_src("list_reviews_for_spu")
    n_spu = src.count("scope_condition(SpuRecord, shop_id)")
    assert n_spu >= 2, (
        f"`list_reviews_for_spu` 里的 spus 店铺过滤只有 {n_spu} 处（应 >= 2）："
        "①SPU 本体查询 判断归属、②差评 join 查询 挡别家 SKU 认领 —— 缺一就是跨租户读"
    )
    assert "scope_condition(CustomerReviewRecord, shop_id)" in src, (
        "差评侧缺了店铺过滤：`skus` 表没有 shop_id，产品归属只能经 `spus.shop_id`，"
        "而差评自己另有一份 shop_id，两条都得挂"
    )


def test_orphan_query_scopes_skus_through_spus_and_correlates():
    """孤儿判定：`skus` 无店铺列 ⇒ 必须经 `spus.shop_id`；且子查询必须 correlate。"""
    src = _func_src("_not_bound_to_sku")
    assert "scope_condition(SpuRecord, shop_id)" in src, (
        "孤儿 exists 子查询没带 spus 的店铺过滤 ⇒ 别家店的 SKU 也能认领本店差评，"
        "孤儿数被系统性低估（看起来像「关联质量很好」）"
    )
    assert ".correlate(CustomerReviewRecord)" in src, (
        "exists 子查询没有 correlate ⇒ 条件退化成「本店是否存在任意能对上的 SKU」，"
        "结果是要么全孤儿要么全不孤儿，且不报错"
    )


def test_no_handwritten_shop_id_comparison():
    """（补充口径）本模块不得自己写 `Xxx.shop_id == ...` —— 由 test_tenant_scoping 全仓管。"""
    tree = ast.parse(SERVICE_SRC)
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare) and isinstance(n.left, ast.Attribute):
            assert n.left.attr != "shop_id", (
                f"service.py 第 {n.lineno} 行出现手写店铺过滤，"
                "店铺作用域的唯一真源是 `core.tenant.scoping`"
            )


# ============================================================ ④ 出口：孤儿 / 列表必须有 HTTP 面

@pytest.mark.parametrize("fn", [
    "list_reviews_for_spu",
    "list_orphan_reviews",
    "list_recent_negative_reviews",
    "count_recent_negative_reviews",
])
def test_service_functions_have_http_exits(fn):
    """「有函数没端点」是本仓反复出现的三无形态 —— 这里逐个钉出口。"""
    assert fn in _service_calls_in_router(), (
        f"service.{fn} 没有任何 router 调用点 ⇒ 它只能被 Agent 工具用到，"
        "前端永远拿不到（这就是一直以来 product detail / 工作台缺数据的根因形状）"
    )


def test_review_endpoints_exist():
    paths = _router_paths()
    for p in ("/reviews", "/reviews/orphans", "/reviews/by-spu/{spu_id}"):
        assert p in paths, (
            f"端点 {p} 不存在或被改名 —— 前端 api/trade.ts 里的调用会 404"
        )


@pytest.mark.asyncio
async def test_orphan_list_reports_total_and_empty_state():
    s = FakeSession(reviews=[_review("crev-x", asin="B0NOBODY")], total=1)
    out = await svc.list_orphan_reviews(s, SHOP, limit=50)
    assert out["total"] == 1
    assert out["empty_state"] is None
    assert out["items"][0]["id"] == "crev-x"

    s0 = FakeSession(reviews=[], total=0)
    out0 = await svc.list_orphan_reviews(s0, SHOP, limit=50)
    assert out0["empty_state"] == "no_orphans"


@pytest.mark.asyncio
async def test_count_orphan_matches_list_total():
    """列表 total 与独立 count 必须同源口径（界面上的「共 N 条」就靠它）。"""
    s = FakeSession(reviews=[_review("crev-x")], total=7)
    assert await svc.count_orphan_reviews(s, SHOP) == 7
