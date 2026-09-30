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
5. ★★ **信封 `message` 是短回执、不是结论**（`test_envelope_message_is_receipt_not_conclusion`
   —— 第 268 轮 B 档改判据方向）：`message` 只能是「<能力>已生成」式短句，
   结论一律留在 `data.summary`。
   · 旧判据（`test_envelope_message_matches_payload_summary`）钉的是
     `message == data["summary"]` —— 它把「结论被当成回执用」写成了契约，
     于是任何按 `message` 弹提示的实现都会把一屏结论飘到顶部
     （第 266 轮老板报障的链1：点一下运营复盘师就弹字）。
   · 反向也有坑：**只**断言「message 不等于 summary」的话，「谁把 summary 删了」
     照样绿 ⇒ 本条一并发断言 `data.summary` 仍在且非空（改判据方向必须成对）。
6. **签名层门禁（静态，不连库）**：
   · `service` 的 6 个能力必须显式接收 `store_id: str` 且**无默认值**
     （`test_service_requires_store_id_param`）—— 忘传就该 `TypeError`；
   · `tools.py` 的 6 个工具同理，`store_id` 必须**无默认值**
     （`test_tools_store_id_has_no_default`）—— 修复前是 `store_id: int = 1`，
     忘传静默复盘 1 号店，错得完全没有声音。
7. **信封 `message` 的形态（静态 AST，不连库）**
   （`test_envelope_message_has_no_payload_ref`）：`ReviewResponse` /
   `ReviewChatResponse` 的 `message=` 实参**不得**引用 `summary` / `reply`
   —— 回执不是结论。第 5 条运行时用例只打了一个端点，本形态用例管住**所有**
   信封构造点（含以后新增的），且锚点失效（构造点少到 0）时**先 FAIL**。

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
pytestmark = pytest.mark.tenant_identity


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


#: 回执**规格表**：每个端点的 `message` 期望值。
#: ★ 改文案要同步改这里（它就是回执的规格）；这**不是**重复实现 ——
#:   它是判据侧的期望值，生产侧的真源是 `router._report` 的 `label` 实参。
RECEIPTS = {
    "/api/v1/review/weekly-report": "周报已生成",
    "/api/v1/review/monthly-review": "月度复盘已生成",
    "/api/v1/review/ad-review": "广告归因已生成",
    "/api/v1/review/product-performance": "商品表现已生成",
    "/api/v1/review/inventory-health": "库存健康已生成",
    "/api/v1/review/profit-audit": "利润审计已生成",
}


@pytest.mark.parametrize("path,body,name", ENDPOINTS, ids=IDS)
async def test_envelope_message_is_receipt_not_conclusion(client, path, body, name):
    """信封 `message` 必须是**短回执**，结论一律在 `data.summary`（第 268 轮 B 档）。

    这条判据的前身是 `test_envelope_message_matches_payload_summary`（它钉的是
    `message == data["summary"]`）—— 那不是契约，那是把**病**写成了契约：
    前端按 `message` 弹成功提示时，点一下「运营复盘师」就会有一整段报告结论
    飘在屏幕顶部（第 266 轮老板报障的链1）。

    改判据方向必须**成对**做，否则会把「删掉结论」放过去：
      ① 结论**还在**（`data.summary` 非空）；
      ② `message` 是回执规格里那一句；
      ③ `message` **不等于**结论（三条里这条最直白地钉住病根）。
    """
    r = await client.post(path, json=body, headers=_shop())
    assert r.status_code == 200, f"{name} {r.status_code} {r.text[:300]}"
    payload = r.json()
    data = payload["data"]

    # ① 结论没有丢：它只是搬到了 data 里（这一半防「谁把 summary 删了也绿」）
    assert data.get("summary"), f"{name} 的 data.summary 丢了或为空 —— 结论没地方去了"
    # ② message 是规格表里那句短回执
    assert payload["message"] == RECEIPTS[path], (
        f"{name} 的 message 是 {payload['message']!r}，"
        f"期望短回执 {RECEIPTS[path]!r}（改文案请同步本文件的 RECEIPTS）"
    )
    # ③ 回执不是结论 —— 这条直指第 266 轮报障：整段结论被当提示弹上屏
    assert payload["message"] != data["summary"], (
        f"{name} 又把结论塞回 message 了（{payload['message']!r}）—— "
        "前端会把整段结论当成功提示弹到屏幕顶部"
    )


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
    "_weekly_report_tool", "_monthly_review_tool",
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
def test_tools_do_not_expose_store_id_to_the_llm(fname):
    """★ 工具函数的入参里**不得出现** `store_id` / `shop_id`。

    ★ 本条是「门禁的墓志铭」的现场 —— 需求变了，旧断言从资产变成负资产：
      它原来钉的是「`store_id` 必须有形参、且**不得有默认值**」，防的是
      「忘传 ⇒ 静默复盘 1 号店」。
      接线时（第 166 轮 · `#726` 第 2 条）才看清：问题**不在默认值**，
      而在**这个参数根本不该给 LLM 看见** —— 工具入参是模型自己填的，
      它会照着自己编一个 `store_id`，而编出来的值可能正好**是别人的店铺**
      （BOLA 的 LLM 版本，比「忘传落到 1 号店」更难发现：它看起来一切正常）。

      ⇒ 要求从「无默认值」升级为「**不存在**」：
        · 归属只能经 ContextVar 由服务端入口（`agent.invoke()`）注入，
          范式同 `modules/product_research/agent_product_research.py::_current_shop_id`；
        · 缺归属时必须**硬拒绝**（见下一条运行期用例）。

      旧断言在新形态下必然红，而**这条说明就是它红的价值**：逼改动者来读，
      而不是把形参悄悄留着当第二份真源。
    """
    args = _func_args("modules/review_analyst/tools.py")[fname]
    names = [a.arg for a in args.args] + [a.arg for a in args.kwonlyargs]
    assert "store_id" not in names, (
        f"{fname} 的入参里又出现了 store_id —— 工具入参**是给 LLM 看的**，"
        "模型会自己编一个值（可能正好是别人的店铺）。"
        "归属必须经 ContextVar 由服务端入口注入。"
    )
    assert "shop_id" not in names, f"{fname} 的入参里出现了 shop_id（同上）"


async def test_tools_refuse_without_server_side_shop_context():
    """运行期印证：没有服务端注入的店铺归属时，工具**显式拒绝**，不兜默认店。

    ★ 为什么必须是「拒绝」而不是「用个默认店铺」：
      数据源（尤其 Mock 档）对**任意** store_id 都返回同一批数据 ⇒ 兜一个默认值
      等于给出一份「看起来正常、其实不知属于谁」的报表。那是**归因错误**，
      比一句可行动的「请先选店铺」糟得多。
    """
    import json as _json

    from modules.review_analyst import tools as ra_tools
    from modules.review_analyst.agent import _current_shop_id

    # 确保没有残留（ContextVar 是模块级全局，别的用例可能写过）
    assert _current_shop_id.get() is None, "上一条用例没还原 ContextVar，先修夹具"

    for fn in (
        ra_tools._weekly_report_tool,
        ra_tools._monthly_review_tool,
        ra_tools._product_performance_tool,
        ra_tools._inventory_health_tool,
        ra_tools._profit_audit_tool,
    ):
        raw = await fn()
        data = _json.loads(raw)
        assert data.get("found") is False, (
            f"{fn.__name__} 在没有店铺归属时没有显式拒绝：{data}"
        )
        assert data.get("reason") == "missing_shop_context"
        assert "店铺" in (data.get("error") or ""), "拒绝文案要可行动（说清怎么办）"


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


# ============================================================
# 5. 信封语义层门禁（静态 AST，不连库、不 import 数据源）
# ============================================================

#: 响应信封模型 —— 它们的 `message=` 只承载短回执。
ENVELOPE_MODELS = {"ReviewResponse", "ReviewChatResponse"}

#: 出现在 `message=` 表达式里就说明「结论/正文又被当成回执用了」的符号名。
MESSAGE_FORBIDDEN = {"summary", "reply"}


def _symbolic_names(expr: ast.expr) -> set[str]:
    """收集表达式引用到的**符号名**：属性名 + 变量名 + 字符串字面量的值。

    例：`data.get("summary") or f"{label}已生成"` ⇒ `{"data", "get", "summary", "label"}`；
        `"复盘完成"` ⇒ `{"复盘完成"}`。
    """
    out: set[str] = set()
    for node in ast.walk(expr):
        if isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            out.add(node.value)
    return out


def _envelope_message_exprs_in(src: str) -> list[tuple[str, ast.expr]]:
    """从**源码文本**里取出每个响应信封的 `message=` 实参表达式。

    ★ 为什么走 AST 而不是 `unparse` 之后做子串匹配（本仓铁律）：字符串判据会被
      **注释 / docstring** 骗过 —— 而注释恰好是最爱写「以前这里塞过 summary」的
      地方，于是判据变成恒真（假绿）。
    """
    tree = ast.parse(src)
    out: list[tuple[str, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            name = fn.id
        elif isinstance(fn, ast.Attribute):
            name = fn.attr
        else:
            continue
        if name not in ENVELOPE_MODELS:
            continue
        kw = next((k for k in node.keywords if k.arg == "message"), None)
        if kw is not None:
            out.append((name, kw.value))
    return out


def _envelope_message_exprs(rel: str) -> list[tuple[str, ast.expr]]:
    return _envelope_message_exprs_in(
        (BACKEND / rel).read_text(encoding="utf-8", errors="replace")
    )


def test_envelope_message_has_no_payload_ref():
    """★ 信封的 `message=` **不得**由 `summary` / `reply` 派生（第 268 轮 B 档）。

    起因（两处都实测过）：
      · `_report`：`message=data.get("summary") or f"{label}已生成"`；
      · `/review/chat`：`message=result.reply`。
    前端把非 GET 响应的 `message` 当「操作回执」弹提示 ⇒ 点一下运营复盘师，
    整段报告结论被弹到屏幕顶部（第 266 轮老板报障的链1）。

    ★ 判据是**形态**判据：逐个信封构造点取 `message=` 的实参表达式，看它引用了
      哪些符号 —— 而不是在源码里搜字符串（docstring 会把它喂饱）。

    ★ 反向注入（`.workbuddy/probes/r268_envelope_message_reverse_inject.py`，4/4）：
      把两条 message 分别改回 `data.get("summary") or …` / `result.reply` ⇒ 各自转红；
      把 `ReviewResponse` 改名 ⇒ 构造点少到 0 ⇒ 也转红（锚点失效不许静默放行）。
    """
    exprs = _envelope_message_exprs("modules/review_analyst/router.py")
    assert len(exprs) >= 2, (
        f"只找到 {len(exprs)} 个信封构造点 —— 构造点被改名/移走时，下面的循环会"
        "退化成**空集恒真**，所以这里必须先 FAIL（「拿不到清单 ≠ 清单为空」）"
    )
    for model, expr in exprs:
        bad = _symbolic_names(expr) & MESSAGE_FORBIDDEN
        assert not bad, (
            f"{model} 的 message= 引用了 {sorted(bad)} —— 回执字段只放短回执"
            f"（实测表达式：{ast.unparse(expr)}）。"
            "结论/正文必须留在 data 子字段里（data.summary / data.reply），"
            "否则前端会把整段结论当成功提示弹上屏。"
        )


@pytest.mark.parametrize("snippet,should_catch", [
    ('ReviewResponse(success=True, message=data.get("summary") or "周报已生成")', True),
    ("ReviewChatResponse(success=True, message=result.reply)", True),
    ('ReviewResponse(success=True, message=f"{label}已生成")', False),
    ('ReviewChatResponse(success=True, message="复盘未取到数据" if degraded else "复盘完成")', False),
], ids=["old-report-summary", "old-chat-reply", "new-report-receipt", "new-chat-receipt"])
def test_envelope_message_judge_selfcheck(snippet, should_catch):
    """判据自检：历史形态必须被抓到，现形态**不得**被误伤（否则绿/红都不可信）。"""
    exprs = _envelope_message_exprs_in(snippet)
    assert len(exprs) == 1, f"自检样本没被解析成恰好一个信封构造点：{snippet!r}"
    caught = bool(_symbolic_names(exprs[0][1]) & MESSAGE_FORBIDDEN)
    if should_catch:
        assert caught, f"判据瞎了：{snippet!r} 是历史病根形态，却没抓到"
    else:
        assert not caught, f"判据误伤：{snippet!r} 是合规形态（短回执），却被判红"
