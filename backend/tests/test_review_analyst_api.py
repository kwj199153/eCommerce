"""
运营复盘师 REST 契约 + 归属模型门禁（第 143 轮 A4 建立）。

背景
----
A4 开工前，`modules/review_analyst/` 只有 `__init__.py` / `schemas.py` / `service.py` /
`tools.py` —— **没有 router、也没挂到 main.py**，六大复盘能力在后端零 HTTP 入口
（前端「运营复盘师」看板吃 `src/mock/reviewDashboard.ts` 的 282 行假数据）。

但**照原样补 router 会一次新增 6 个越权端点**，所以本批次的正题是先把归属模型
修对再补入口：

    修复前：`ReviewRequest.store_id: int = Field(1)`
            ⇒ **客户端可控**（body 里带什么就是什么）+ **有默认值**（不传就静默读
              1 号店）；service 直接拿它去数据源取数 ⇒ 改一下 body 就能读任意
              店铺的复盘数据（OWASP API Security #1，BOLA）。
    修复后：`ReviewRequest` **没有** store_id 字段；归属只能由 router 的
            `Depends(get_current_shop_id)`（strict 版）注入；类型统一为 `str`
            （真源是 `stores_store.id`，形态 `store_xxx`，与 X-Shop-ID 同一 ID 空间）。

本文件钉住的六件事
------------------
1. **缺 / 空 / 纯空白 `X-Shop-ID` ⇒ 400**（6 个端点全覆盖），且原因可读
   （`test_missing_shop_header_*`）。
2. ★★★ **body 里的 `store_id` 必须无效**（`test_body_store_id_cannot_override_header`）
   —— 这是本批次的核心门禁。注意判据不是「400」，而是「照发不报错、但**不被采纳**」
   （pydantic `extra="ignore"` ⇒ 不 422），这比 400 更容易被写成假绿：
   只断言 `status == 200` 的话，一个"采纳了 body"的实现照样绿。
   ⇒ 所以断言的是 `data["store_id"] == 请求头那个`，且**不等于** body 里那个。
3. **body 单独带 store_id 也换不来数据**（`test_body_store_id_alone_is_not_enough`）：
   不带头 ⇒ 仍然 400。若某天有人把守卫改成 optional，这条会红。
4. **服务端注入的值被原样回显**（`test_injected_store_id_is_echoed`）：两个不同店铺
   各拿各的 `data["store_id"]` —— 证明归属真的由服务端决定。
5. **信封与 payload 同一声音**（`test_envelope_message_matches_payload_summary`）：
   `message` 必须等于 `data["summary"]`。A3 的教训：固定文案在「另一种形态」和
   「失败」下都会撒谎（`competitor_intel` 曾出现 message 写「成功获取 0 个竞品」
   而 data 里明明有完整数据）。
6. **签名层门禁（静态，不连库）**：
   · `service` 的 6 个能力必须显式接收 `store_id: str` 且**无默认值**
     （`test_service_requires_store_id_param`）—— 忘传就该 `TypeError`；
   · `tools.py` 的 6 个工具同理，`store_id` 必须**无默认值**
     （`test_tools_store_id_has_no_default`）—— 修复前是 `store_id: int = 1`，
     忘传静默复盘 1 号店，错得完全没有声音。

⚠️ 已知的**诚实边界**（刻意不写成"通过"，避免假绿）
--------------------------------------------------
`MockAmazonDataSource` 的 `fetch_daily_sales` / `fetch_ad_metrics` / `fetch_inventory`
/ `fetch_listings` **不按 store_id 过滤**（实测：`store_test` / 未知店铺 / 空串 /
`None` / 整数 1 返回**同一批 35 行**，store_id 只是被打进行里做标签）。
⇒ 本文件因此**不断言**「A 店铺看不到 B 店铺的数据」（Mock 档下这句话无法证伪）。
  真正被钉住的是**契约层**：归属只从服务端来、非法值被拒、值被原样回显。
  按店铺真实分区只能由真实档（SP-API 凭据）保证，属数据源侧责任。
"""

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]

SHOP = "store_test"
OTHER_SHOP = "store_review_other"

# (路径, 请求体, 能力名) —— 6 个端点的完整清单
ENDPOINTS = [
    ("/api/v1/review/weekly-report", {"days": 7}, "weekly_report"),
    ("/api/v1/review/monthly-review", {"days": 30}, "monthly_review"),
    ("/api/v1/review/ad-review", {"days": 7}, "ad_review"),
    ("/api/v1/review/product-performance", {"days": 7}, "product_performance"),
    ("/api/v1/review/inventory-health", {"days": 7}, "inventory_health"),
    ("/api/v1/review/profit-audit", {"days": 30}, "profit_audit"),
]
IDS = [e[2] for e in ENDPOINTS]


def _shop(shop_id: str = SHOP) -> dict:
    return {"X-Shop-ID": shop_id}


# ============================================================
# 1. 缺 / 空 / 纯空白 X-Shop-ID ⇒ 400
# ============================================================

@pytest.mark.parametrize("path,body,name", ENDPOINTS, ids=IDS)
async def test_missing_shop_header_is_400(client, path, body, name):
    """不带 X-Shop-ID 的复盘请求必须 400，且原因可读（不是 500 / 不是空结果）。

    为什么断言精确 400 而不是 `!= 500`：501/502 之类的中间态同样说明守卫没生效，
    用 `not in (200, 500)` 会把它们放过去。
    """
    r = await client.post(path, json=body, headers={})
    assert r.status_code == 400, f"{name} 期望 400，实际 {r.status_code} {r.text[:200]}"
    detail = r.json().get("detail", "")
    assert "店铺" in detail, f"{name} 的 400 原因不可读: {detail!r}"


@pytest.mark.parametrize("blank", ["", "   "], ids=["empty", "spaces"])
async def test_blank_shop_header_is_400(client, blank):
    """空串 / 纯空白与「不带头」一视同仁（`.strip()` 后为空即拒）。"""
    r = await client.post(
        "/api/v1/review/weekly-report", json={"days": 7}, headers={"X-Shop-ID": blank}
    )
    assert r.status_code == 400, r.text[:200]
    assert "店铺" in r.json().get("detail", "")


# ============================================================
# 2. ★★★ 核心门禁：body 里的 store_id 必须无效
# ============================================================

@pytest.mark.parametrize("path,body,name", ENDPOINTS, ids=IDS)
async def test_body_store_id_cannot_override_header(client, path, body, name):
    """body 里塞 `store_id` 不得改变归属 —— 归属只能服务端注入。

    ★ 判据为什么不是「400」：`ReviewRequest` 里**没有**这个字段，pydantic 默认
      `extra="ignore"` ⇒ 老客户端照发不会 422、接口照常 200。
      也就是说「接口返回 400」在这里反而是**错的期望**（会把兼容性改坏），
      真正要断言的是**那个值没有被采纳**：

          请求头 = store_test
          body   = store_id: store_hacked
          ⇒ data["store_id"] 必须是 store_test，且**不是** store_hacked

      只断言 `status == 200` 的写法会漏掉「采纳了 body」的实现（假绿）。
    """
    hacked = "store_hacked_via_body"
    r = await client.post(path, json={**body, "store_id": hacked}, headers=_shop())
    assert r.status_code == 200, f"{name} 期望 200，实际 {r.status_code} {r.text[:200]}"
    payload = r.json()
    assert payload.get("success") is True, payload
    got = payload["data"]["store_id"]
    assert got == SHOP, (
        f"{name} 把请求体里的 store_id 采纳了：data.store_id={got!r}，"
        f"期望 {SHOP!r}（body 里发的是 {hacked!r}）"
    )
    assert got != hacked


async def test_body_store_id_alone_is_not_enough(client):
    """只带 body 的 store_id、不带请求头 ⇒ 仍然 400（body 不是归属通道）。

    这条专门盯「把守卫改成 optional / 或在 handler 里 `request.store_id or 头`」的
    退化 —— 那种实现会让上面那条依旧绿，而这条红。
    """
    r = await client.post(
        "/api/v1/review/weekly-report",
        json={"days": 7, "store_id": SHOP},
        headers={},
    )
    assert r.status_code == 400, (
        f"body 里的 store_id 竟然被当成了归属通道：{r.status_code} {r.text[:200]}"
    )


# ============================================================
# 3. 正向契约：200 的形状 + 服务端注入的值被回显
# ============================================================

@pytest.mark.parametrize("path,body,name", ENDPOINTS, ids=IDS)
async def test_endpoint_returns_report_shape(client, path, body, name):
    """6 个端点在正常条件下都要 200，且返回可消费的报告结构。"""
    r = await client.post(path, json=body, headers=_shop())
    assert r.status_code == 200, f"{name} {r.status_code} {r.text[:300]}"
    payload = r.json()
    assert payload["success"] is True
    data = payload["data"]
    for key in ("report_type", "period_days", "store_id", "summary",
                "metrics", "details"):
        assert key in data, f"{name} 的 data 缺 {key}：{sorted(data)}"
    assert data["report_type"] == name, f"{name} 的 report_type 不符：{data['report_type']}"
    assert data["period_days"] == body["days"]
    assert data["store_id"] == SHOP
    assert data["summary"], f"{name} 的 summary 为空"
    assert data["metrics"], f"{name} 的 metrics 为空"


@pytest.mark.parametrize("shop_id", [SHOP, OTHER_SHOP])
async def test_injected_store_id_is_echoed(client, shop_id):
    """服务端注入谁，报告就回显谁（两个不同店铺各拿各的）。"""
    r = await client.post(
        "/api/v1/review/profit-audit", json={"days": 7}, headers=_shop(shop_id)
    )
    assert r.status_code == 200, r.text[:200]
    assert r.json()["data"]["store_id"] == shop_id


async def test_envelope_message_matches_payload_summary(client):
    """信封 `message` 与 `data.summary` 必须是同一句话 —— 两处各写一份就必然分叉。

    起因（A3 / `competitor_intel` 的实测教训）：service 里 9 个方法各写
    `result.get("message") or <写死成功文案>`，固定文案在「另一种形态」和「失败」
    下都会撒谎（`data` 里明明是完整数据，`message` 却写「成功获取 0 个竞品」）。
    """
    r = await client.post(
        "/api/v1/review/weekly-report", json={"days": 7}, headers=_shop()
    )
    assert r.status_code == 200, r.text[:200]
    payload = r.json()
    assert payload["message"] == payload["data"]["summary"]
    assert payload["message"]


@pytest.mark.parametrize("days", [0, 91, -1], ids=["zero", "over90", "negative"])
async def test_days_out_of_range_is_422(client, days):
    """`days` 的边界（1..90）由请求模型管 —— 越界 422，不是静默截断。"""
    r = await client.post(
        "/api/v1/review/weekly-report", json={"days": days}, headers=_shop()
    )
    assert r.status_code == 422, f"days={days} 期望 422，实际 {r.status_code} {r.text[:200]}"


# ============================================================
# 4. 签名层门禁（静态 AST，不连库、不 import 数据源）
# ============================================================

def _func_args(rel: str) -> dict[str, ast.arguments]:
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8", errors="replace"))
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out[node.name] = node.args
    return out


def _param_default(args: ast.arguments, name: str):
    """返回该参数的默认值表达式；无默认值返回 `None`（位置对齐全靠 offsets）。"""
    pos = [a.arg for a in args.posonlyargs] + [a.arg for a in args.args]
    if name in pos:
        idx = pos.index(name)
        n_def = len(args.defaults)
        first = len(pos) - n_def          # 第一个「有默认值」的位置参数下标
        return args.defaults[idx - first] if idx >= first else None
    for a, d in zip(args.kwonlyargs, args.kw_defaults):
        if a.arg == name:
            return d
    raise AssertionError(f"参数 {name} 不存在")


SERVICE_CAPS = [
    "weekly_report", "monthly_review", "ad_review",
    "product_performance", "inventory_health", "profit_audit",
]
TOOL_FUNCS = [
    "_weekly_report_tool", "_monthly_review_tool", "_ad_review_tool",
    "_product_performance_tool", "_inventory_health_tool", "_profit_audit_tool",
]


@pytest.mark.parametrize("fname", SERVICE_CAPS)
def test_service_requires_store_id_param(fname):
    """service 的每个能力都必须**必填**接收 `store_id: str`（无默认值）。

    为什么这条值得单独一个用例：`store_id` 一旦有默认值，「忘传」就退化成
    **静默复盘某家店**（旧形态是硬编码 1 号店）—— 错得完全没有声音。
    `TypeError` 才是我们要的失败形态（本仓「签名即门禁」）。
    """
    args = _func_args("modules/review_analyst/service.py")[fname]
    assert "store_id" in [a.arg for a in args.args], (
        f"{fname} 没有 store_id 形参 ⇒ 归属无处注入"
    )
    assert _param_default(args, "store_id") is None, (
        f"{fname} 的 store_id 带了默认值 —— 忘传会静默取默认店铺，必须是必填"
    )
    ann = next(a.annotation for a in args.args if a.arg == "store_id")
    assert ast.unparse(ann) == "str", (
        f"{fname} 的 store_id 注解是 {ast.unparse(ann)!r}，"
        "真源 stores_store.id 是字符串（store_xxx），必须统一为 str"
    )


@pytest.mark.parametrize("fname", TOOL_FUNCS)
def test_tools_store_id_has_no_default(fname):
    """工具函数的 `store_id` 同样必须无默认值（修复前的形态是 `int = 1`）。

    ★ 本注册表当前全仓零消费点（悬空，由
      `test_tool_registry_guard.py::test_orphan_registry_ratchet` 钉着），
      所以本条**不是**在说"线上安全"，而是把「接线时不许再退化成静默默认店」
      这条要求提前固化 —— 否则接线那一刻谁都想不起来。
    """
    args = _func_args("modules/review_analyst/tools.py")[fname]
    try:
        default = _param_default(args, "store_id")
    except AssertionError as e:
        raise AssertionError(f"{fname} 缺 store_id 形参：{e}")
    assert default is None, (
        f"{fname} 的 store_id 又有默认值了（{ast.unparse(default)!r}）—— "
        "忘传会静默复盘那家店，而不是 TypeError"
    )


def test_request_model_has_no_store_id_field():
    """★ 结构层判据：`ReviewRequest` 里不得存在 store_id 字段。

    为什么用 AST 而不是 import 后查 `model_fields`：这条是**形状**判据
    （「请求体里根本没有这个字段」），而 AST 不依赖导入顺序、不拉任何依赖。
    运行期口径由下一个用例 `test_request_model_ignores_body_store_id` 印证。
    """
    src = (BACKEND / "modules/review_analyst/schemas.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        for stmt in cls.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                assert not (cls.name == "ReviewRequest" and stmt.target.id == "store_id"), (
                    "ReviewRequest 又出现了 store_id 字段 —— 归属只能服务端注入，"
                    "从请求体删字段（而不是接收后忽略）才是本仓的收口口径"
                )


def test_request_model_ignores_body_store_id():
    """运行期印证：真构造一次请求模型，看 store_id 到底进不进得来。"""
    from modules.review_analyst.schemas import WeeklyReportRequest

    assert "store_id" not in WeeklyReportRequest.model_fields
    req = WeeklyReportRequest(days=7, store_id="store_hacked")  # type: ignore[call-arg]
    assert not hasattr(req, "store_id") or getattr(req, "store_id", None) != "store_hacked", (
        "请求模型把 body 里的 store_id 收下了 —— 那它就是客户端可控的归属通道"
    )


@pytest.mark.parametrize("fname", SERVICE_CAPS)
def test_service_calls_require_store(fname):
    """★ 每个能力都必须在函数体里**真的调用** `_require_store`（静态判据）。

    为什么运行时用例不够：`test_service_rejects_empty_store_id` 只打了
    `weekly_report` 一个能力。反向注入时实测到了这个缺口 —— 把
    `inventory_health` 里的 `_require_store(...)` 删掉，那条用例**照样绿**
    （它压根没走那个函数）。⇒ 缺口是「另一个能力**本该有而没做**」，
    这类形态运行时用例**结构性看不见**（本仓「一个状态在 N 个入口被消费 ⇒
    逐个问有没有做」那条铁律的现场）。

    判据走 AST 的 `ast.Call`：只看**是不是真的调了**，不看 docstring / 注释
    （本仓踩过「源码字符串包含」被 docstring 骗过的坑）。
    """
    src = (BACKEND / "modules/review_analyst/service.py").read_text(
        encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    target = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fname:
            target = node
    assert target is not None, f"service.py 里找不到 {fname}"

    called = [
        n for n in ast.walk(target)
        if isinstance(n, ast.Call)
        and ((isinstance(n.func, ast.Name) and n.func.id == "_require_store")
             or (isinstance(n.func, ast.Attribute) and n.func.attr == "_require_store"))
    ]
    assert called, (
        f"{fname} 没有调用 _require_store —— 空 store_id 会一路传到数据源，"
        "而数据源对任意 store_id 都返回同一批数据（实测），"
        "于是产出一份「看起来正常、却不知属于谁」的报告"
    )


async def test_service_rejects_empty_store_id():
    """service 层 fail-closed：空 store_id 必须抛错，绝不出「GMV $0」的假报告。

    为什么必须有这道（router 已经会 400 了）：`tools.py` 与测试/脚本都能直接调
    service。而数据源**不会**因为 store_id 为空就返回空表 —— 实测
    （探针 `r142_a4_source_probe.py`）：Mock 对 `store_test` / 未知店铺 / `""` /
    `None` / 整数 1 返回**同一批 35 行**。也就是说缺店铺**不会**得到空结果，
    而会得到一份看起来完全正常、却不知属于谁的报告 —— 归因错误比报错更糟。
    """
    from modules.review_analyst import service
    from modules.review_analyst.schemas import WeeklyReportRequest

    for bad in ("", "   ", None):
        with pytest.raises(service.MissingShopContext) as ei:
            await service.weekly_report(WeeklyReportRequest(days=7), bad)  # type: ignore[arg-type]
        assert "店铺" in str(ei.value), f"store_id={bad!r} 的报错不可读：{ei.value}"


def test_missing_shop_context_is_a_value_error():
    """`MissingShopContext` 必须是 `ValueError` 子类 —— router 靠它映射 400。

    钉住的是一致性：如果哪天有人把它改成 `RuntimeError`，router 的
    `except service.MissingShopContext` 仍然能抓（它按名字抓），
    但**其它**按 `ValueError` 抓的地方会静默漏掉 ⇒ 变成 500。
    """
    from modules.review_analyst import service

    assert issubclass(service.MissingShopContext, ValueError)
