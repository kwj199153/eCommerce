# -*- coding: utf-8 -*-
"""运营复盘师 —— 工具层「成功路径」补测 + 四处真分支守卫（第 355 轮）。

## 为什么要补（先给证据，再给用例）

第 355 轮用 `sys.monitoring`（PEP 669）对**现有 3 个测试文件**
（`test_review_analyst_api.py` / `test_review_analyst_agent.py` / `test_review_library.py`）
现测了 `modules/review_analyst/` 的运行时**函数体**覆盖：

    service.py   316 / 347  ≈ 91.1%
    tools.py      40 /  66  ≈ 60.6%
    router.py     29 /  49  ≈ 59.2%
    agent.py      55 / 166  ≈ 33.1%

★★★ 口径更正（重要）：仓库里的 `backend/coverage.xml` 时间戳是 **2026-09-18**，
早于 `router.py` 与上述三个测试文件落地。那份读数里
「`service.py` / `tools.py` / `schemas.py` = 0.0%」是**陈旧读数**，
不能用于判断现状 —— 本仓铁律：读数必须与磁盘现状对账后才可下结论。

在「已覆盖」的数字之下，仍有**四处需要特定输入才会走到的真实分支**
（不是行覆盖口径的假象）：

1. ★★★ **5 个复盘工具的「正文」从未被执行过**。
   现有 `test_tools_refuse_without_server_side_shop_context` 只走了
   「缺归属 ⇒ 显式拒绝」这一条；工具**拿到归属之后**的三行
   （构造 Request → 调 service → 序列化）从没跑过。
   ⇒ 若 `ReviewAnalystService` 的方法签名变了、或 `_dump` 坏了，
     **现有全部测试仍然全绿**，而线上工具一调就炸。**这是本文件的主靶**。
2. `_dump` 的两条非 dict 分支：`model_dump()` 通道与 `str()` 兜底。
3. `_list_reviews_tool` 的 `except (TypeError, ValueError)` 分支
   —— 取值域外由 `LibraryQueryError` 覆盖（在 `test_review_library.py`），
   参数**类型**错走的是另一条。
4. `service.py` 的两处：
   · `validate_save_payload` 的**快照超限守卫**（`MAX_SNAPSHOT_CHARS`）。
     它防的不是安全而是可用性：一份几 MB 的 JSON 写进 `review_reports.data`
     之后，每次列表查询都要把它读出来。现有用例只测了「data 不是 dict」。
   · `ad_review` 的 **C 级 campaign 分支**（`acos > 32`）。
   同族的**三目运算符**分支（`_sum_ad` 的 `sales=0 ⇒ acos=100.0` 等）
   行覆盖天然看不见（整个三目写在一行）⇒ 一并按**分支**补齐。

## 本文件的纪律
- **不连库、不出网、不 import 数据源实现**：数据源一律用桩替换
  （`service._source` 是模块级函数，monkeypatch 它即可，不需要真 SP-API/Mock）。
  因此本文件与共享 PG 无关 —— 单跑必绿，不受库状态影响。
- 每条断言都能回答「哪一处改动能把它打红」；不写无可观测判据的用例。
"""

import json

import pytest

from core.tenant.middleware import MissingShopContext
from modules.review_analyst import service as ra_service
from modules.review_analyst import tools as ra_tools
from modules.review_analyst.schemas import MetricSummary

#: 本文件用的合成店铺 ID（形态与真实 `stores_store.id` 一致）。
#: ★ 不会落库（本文件全程不碰 DB），它只是「服务端注入的归属」这个值。
SHOP = "store_pytest_r355_toolpaths"


# ============================================================
# 1. 工具层：5 条成功路径（本文件主靶）
# ============================================================

class _RecordingService:
    """`ReviewAnalystService` 的替身：记录调用三元组并按方法名回一个可识别 dict。

    ★ 为什么不 patch `service.weekly_report` 而是 patch `tools._service`：
      `tools.py` 顶部有 `_service = ReviewAnalystService()`，工具走的是
      **这个实例**的方法。patch 类属性对已构造的实例无效（绑定在实例上），
      而 patch 模块级 service 函数又拦不住类内已绑定的 staticmethod
      —— 这是本仓「门面 re-export 复制绑定」那条陷阱的同族。
      打在**调用点真正读的那个对象**上，桩才生效。
    """

    def __init__(self):
        self.calls = []

    async def _record(self, name, req, shop):
        self.calls.append((name, req, shop))
        return {"report_type": name, "period_days": req.days, "store_id": shop}

    async def weekly_report(self, req, shop):
        return await self._record("weekly_report", req, shop)

    async def monthly_review(self, req, shop):
        return await self._record("monthly_review", req, shop)

    async def product_performance(self, req, shop):
        return await self._record("product_performance", req, shop)

    async def inventory_health(self, req, shop):
        return await self._record("inventory_health", req, shop)

    async def profit_audit(self, req, shop):
        return await self._record("profit_audit", req, shop)


#: (工具属性名, 期望调到的 service 方法, 期望的 Request 类型, 工具入参, 期望落在 Request 上的字段)
REPORT_TOOL_CASES = [
    ("_weekly_report_tool", "weekly_report", "WeeklyReportRequest",
     {"days": 7}, {"days": 7}),
    ("_monthly_review_tool", "monthly_review", "MonthlyReviewRequest",
     {"days": 30}, {"days": 30}),
    ("_product_performance_tool", "product_performance", "ProductPerformanceRequest",
     {"days": 7, "asins": ["B0PYTEST01"]}, {"days": 7, "asins": ["B0PYTEST01"]}),
    ("_inventory_health_tool", "inventory_health", "InventoryHealthRequest",
     {"days": 7}, {"days": 7}),
    ("_profit_audit_tool", "profit_audit", "ProfitAuditRequest",
     {"days": 30}, {"days": 30}),
]


@pytest.mark.parametrize(
    "tool_name,svc_name,req_cls_name,kwargs,expect",
    REPORT_TOOL_CASES,
    ids=[c[0] for c in REPORT_TOOL_CASES],
)
async def test_report_tool_success_path(monkeypatch, tool_name, svc_name,
                                        req_cls_name, kwargs, expect):
    """★ 主靶：有店铺归属时，工具必须真的取数、按模型构造请求、并回 JSON 字符串。"""
    fake = _RecordingService()
    monkeypatch.setattr(ra_tools, "_service", fake)
    monkeypatch.setattr(ra_tools, "_store_id", lambda: SHOP)

    raw = await getattr(ra_tools, tool_name)(**kwargs)

    # ① 出参必须是**可解析的 JSON 字符串**（工具出参直接进模型上下文，不许是对象 repr）
    data = json.loads(raw)
    assert data["report_type"] == svc_name
    assert data["store_id"] == SHOP, "工具回显的归属不是服务端注入的那家"

    # ② 真的调到了对应的 service 方法，且恰好一次（多调一次＝重复取数）
    assert len(fake.calls) == 1, f"应恰好取数一次，实际 {len(fake.calls)} 次：{fake.calls}"
    name, req, shop = fake.calls[0]
    assert name == svc_name
    assert shop == SHOP, "service 拿到的 store_id 不是服务端注入值（归属被污染）"

    # ③ 工具自己构造 Request（扁平入参 → Pydantic 模型），字段逐项对账
    req_cls = getattr(ra_service, req_cls_name)
    assert isinstance(req, req_cls), f"期望 {req_cls_name}，实际 {type(req).__name__}"
    for field, want in expect.items():
        got = getattr(req, field)
        assert got == want, f"{field}={got!r}，期望 {want!r}"


async def test_product_performance_tool_keeps_asins_none_when_omitted(monkeypatch):
    """不传 `asins` 时必须是 `None`（＝分析全部），**不许兜成 `[]`**。

    ★ 为什么这不是吹毛求疵：`asins` 最终会传给数据源的
      `fetch_daily_sales(..., asins=request.asins)`。`None` 与 `[]` 在
      过滤语义上是两件事（`[]` 是「过滤后一个都不剩」）。兜成空列表会让
      老板看到一份「0 个 SKU」的报告，而真实原因是他没指定 ASIN。
    """
    fake = _RecordingService()
    monkeypatch.setattr(ra_tools, "_service", fake)
    monkeypatch.setattr(ra_tools, "_store_id", lambda: SHOP)

    await ra_tools._product_performance_tool()

    _name, req, _shop = fake.calls[0]
    assert req.asins is None, f"未指定 asins 时被兜成了 {req.asins!r}（应为 None＝全部）"


# ============================================================
# 2. 工具层：`_dump` 的三条通道
# ============================================================

def test_dump_serializes_pydantic_model_via_model_dump():
    """`model_dump()` 通道：service 若改回返回 Pydantic 模型，工具仍能序列化。"""
    out = ra_tools._dump(MetricSummary(label="GMV", value=1.5, unit="USD"))
    data = json.loads(out)
    assert data["label"] == "GMV"
    assert data["value"] == 1.5
    assert data["unit"] == "USD"


def test_dump_falls_back_to_str_for_unknown_types():
    """`str()` 兜底：既不是 dict 也没有 `model_dump` ⇒ 退化成字符串，不抛。"""
    class _Weird:
        def __str__(self):
            return "weird-obj"

    assert ra_tools._dump(_Weird()) == "weird-obj"


def test_dump_does_not_escape_chinese():
    """中文不得被转义成 `\\uXXXX` —— 出参是给模型直接读的（`ensure_ascii=False`）。"""
    out = ra_tools._dump({"summary": "近 7 天 GMV 与 ACoS"})
    assert "近 7 天" in out
    assert "\\u" not in out, f"中文被转义了：{out}"


# ============================================================
# 3. 工具层：`list_reviews` 的参数**类型**错分支
# ============================================================

async def test_list_reviews_tool_maps_type_error_to_invalid_argument(monkeypatch):
    """参数**类型**错 ⇒ `invalid_argument`（让模型改参数重试），不是崩掉。

    ★ 与「取值域外 ⇒ `LibraryQueryError`」是**两条**不同的分支
      （后者已由 `test_review_library.py` 覆盖）。合并成一条会让
      「类型错」这条静默退化成「读取失败」，模型就不知道该改参数。
    """
    class _Boom:
        async def list_saved_reports(self, *a, **k):
            raise TypeError("limit 需要整数")

        async def count_saved_reports(self, *a, **k):
            raise TypeError("limit 需要整数")

    monkeypatch.setattr(ra_tools, "_service", _Boom())
    monkeypatch.setattr(ra_tools, "_store_id", lambda: SHOP)

    data = json.loads(await ra_tools._list_reviews_tool())
    assert data["type"] == "invalid_argument", f"期望 invalid_argument，实际 {data}"
    assert "参数类型" in data["error"]


# ============================================================
# 4. service.py：快照超限守卫
# ============================================================

def test_validate_save_payload_rejects_oversized_snapshot():
    """★ 快照超过 `MAX_SNAPSHOT_CHARS` 必须**硬拒绝**（不许写进库）。

    这条守卫防的是可用性事故：`data` 由前端原样回传，一份几 MB 的 JSON
    落进 `review_reports.data` 后，每次列表查询都要把它读出来。
    """
    oversized = {"blob": "x" * (ra_service.MAX_SNAPSHOT_CHARS + 1024)}
    with pytest.raises(ra_service.ReviewLibraryError) as ei:
        ra_service.validate_save_payload({
            "report_type": "weekly_report", "period_days": 7, "data": oversized,
        })
    assert "过大" in str(ei.value), f"拒绝文案没说清原因：{ei.value}"


def test_validate_save_payload_accepts_snapshot_just_under_the_cap():
    """边界对侧：刚好在上限**之内**必须放行。

    ★ 少了这一半，守卫可以「一律拒绝」而仍然全绿 —— 那是把正常报告也拒了。
      这是本仓「门禁须成对」那条：只测拒绝不测放行，等于测了个恒真的东西。
    """
    ok = {"blob": "x" * (ra_service.MAX_SNAPSHOT_CHARS - 2048)}
    # 不抛即通过（返回 None）
    ra_service.validate_save_payload({
        "report_type": "weekly_report", "period_days": 7, "data": ok,
    })


# ============================================================
# 5. service.py：归属归一化（空白串必须与空串同罪）
# ============================================================

def test_require_store_strips_and_rejects_whitespace_only():
    """`_require_store` 走唯一真源 `require_shop_context`：strip 后判空。

    ★ 为什么要单独钉「纯空白」：这正是 `require_shop_context` docstring 里
      记录的漂移形态 —— 一处 strip、另一处不 strip，会让 `"   "` 在某个模块
      被当成合法店铺 ID 拿去查库。本用例把它钉在「与空串同罪」这一侧。
    """
    assert ra_service._require_store("  store_x  ") == "store_x"
    with pytest.raises(MissingShopContext):
        ra_service._require_store("   ")


# ============================================================
# 6. service.py：`ad_review` 的三档评级 + `_sum_ad` 的三目分支
# ============================================================

class _StubAdSource:
    """最小数据源替身：`ad_review` 只用 `fetch_ad_metrics` 一个方法。"""

    def __init__(self, ads):
        self._ads = ads

    def fetch_ad_metrics(self, store_id, d_from, d_to):
        return self._ads


def _ad_row(name: str, spend: float, sales: float) -> dict:
    return {
        "campaign_name": name, "spend": spend, "sales": sales,
        "orders": 3, "clicks": 10, "impressions": 1000,
    }


async def test_ad_review_grades_campaigns_by_acos(monkeypatch):
    """★ 三个档位都要走到 + 两个边界取「含」。

    规格（`ad_review` 正文）：`acos <= 25` → S；`<= 32` → B；否则 C。
    此前**只有 C 档分支从未被执行**（两个边界也比较的就是它）。
    """
    ads = [
        _ad_row("s-low", spend=10.0, sales=100.0),    # acos 10.0 → S
        _ad_row("s-edge", spend=25.0, sales=100.0),   # acos 25.0 → S（边界含）
        _ad_row("b-mid", spend=30.0, sales=100.0),    # acos 30.0 → B
        _ad_row("b-edge", spend=32.0, sales=100.0),   # acos 32.0 → B（边界含）
        _ad_row("c-high", spend=50.0, sales=100.0),   # acos 50.0 → C
    ]
    monkeypatch.setattr(ra_service, "_source", lambda: _StubAdSource(ads))

    data = await ra_service.ad_review(ra_service.AdReviewRequest(days=7), SHOP)

    grades = {c["campaign"]: c["grade"] for c in data["details"]["campaigns"]}
    assert grades == {
        "s-low": "S", "s-edge": "S", "b-mid": "B", "b-edge": "B", "c-high": "C",
    }, f"评级口径不符：{grades}"


def test_sum_ad_uses_fallbacks_on_zero_denominators():
    """★ 三目分支：整句写在一行 ⇒ **行覆盖天然看不见**，只能按分支补。

    · `sales == 0` ⇒ acos 记 `100.0`（不是 ZeroDivisionError，也不是 0
      —— 「花了钱没卖出」与「ACoS 恰好为 0」是两件事）
    · `spend == 0` ⇒ roas 记 `0.0`
    · `impressions == 0` ⇒ ctr 记 `0`
    """
    out = ra_service._sum_ad([
        {"impressions": 0, "clicks": 5, "spend": 0, "orders": 0, "sales": 0},
    ])
    assert out["acos"] == 100.0
    assert out["roas"] == 0.0
    assert out["ctr"] == 0
    assert out["clicks"] == 5, "零分母不得影响其它维度求和"


def test_sum_sales_on_empty_rows_is_all_zero_not_error():
    """空销售行 ⇒ 全 0 的结构（`_sum_sales` 自身的空输入行为）。

    ★ 注意与「降级禁用全 0 兜底」那条铁律的区别：那条禁的是**取数失败**时
      用全 0 冒充数据；这里是**取数成功但确实是空集**的合法聚合结果。
      两者不能混为一谈，故本用例只钉「函数对空列表的行为」。
    """
    assert ra_service._sum_sales([]) == {
        "units": 0, "revenue": 0, "refunds": 0, "net_revenue": 0,
        "estimated_profit": 0,
    }


# ============================================================
# 7. 类入口与模块函数必须是**同一个绑定对象**
# ============================================================

def test_service_class_bindings_are_the_module_functions():
    """`tools.py` 走 `ReviewAnalystService.xxx()` 调用 ⇒ 类属性必须与模块函数同对象。

    ★ 若有人把 `staticmethod(...)` 误写成普通方法（或漏掉某个绑定），
      崩溃发生在**运行期第一次调用工具**时，而所有静态门禁照样全绿。
      这条判据把「类入口」与「模块函数」钉成同一绑定。
    """
    for name in (
        "weekly_report", "monthly_review", "ad_review",
        "product_performance", "inventory_health", "profit_audit",
        "save_report", "list_saved_reports", "count_saved_reports",
        "get_saved_report",
    ):
        bound = getattr(ra_service.ReviewAnalystService, name)
        module_fn = getattr(ra_service, name)
        assert bound is module_fn, (
            f"ReviewAnalystService.{name} 与 service.{name} 不是同一绑定 "
            f"（工具层会调到另一个实现）"
        )
