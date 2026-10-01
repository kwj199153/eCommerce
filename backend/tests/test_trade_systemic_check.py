# -*- coding: utf-8 -*-
"""第 294 轮 B 档：把「个案 vs 系统性」判定搬进 HTTP 面。

老板原话
--------
「在【差评处理】中已经全流程走完了，那么【差评应对】用不上啊」——
查下来这个推论不成立，但**指到了一个真缺口**：面板的 11 个端点里没有一个
能回答「这是不是重复问题」。`count_repeat_issues` 全仓唯一消费点是
`modules/trade/tools.py` 那个 Agent 工具 ⇒ **只有对话通道**拿得到它；
面板结构上给不出第 3 步，而且漏得毫无提示。按 B 档把它搬进面板：
后端补 2 个端点（本文件钉的就是它们）。

本文件钉五件事（缺一不可）
--------------------------
  A. **判定四个分支**逐条钉死（unknown / isolated / repeat / systemic）——
     只测「能返回结论」等于没测；每一条都要有**只靠它才会红**的用例；
  B. **阈值只有一份**：`service.REPEAT_ISSUE_THRESHOLD` == 技能正文写的那个数。
     技能写 3、代码写 5 ⇒ 两条通道结论不同，而用户只会看到其中一个；
  C. **边界**：count=2 不算重复；count=3 但无下行趋势只算 `repeat`（不升格）；
  D. **端点在场** —— 问**运行时路由表**（`scripts/route_inventory`），不是 grep
     源码：`@router.get(...)` 写了但 `include_router` 没挂，grep 一样命中；
  E. **唯一真源**：健康分查询只在 `service` 有一处，`tools.py` 里已无第二份
     （本轮把它搬下去就是为了这个）。

★ 全部 monkeypatch `service` 的模块属性，**不连共享库**（本仓 `tests/` 连的是
  共享生产库，依赖 seed 数据的用例不可复现）。假会话形态照抄
  `tests/test_trade_disposition.py`。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from modules.trade import service as svc

BACKEND = Path(__file__).resolve().parents[1]

# ★ 第 355 轮拆包：本文件要读 trade **服务层整包**的源码（唯一读取点在
#   `tests/trade_service_src.py`）。
from trade_service_src import read_service_source  # noqa: E402
SHOP = "store_unit_test"
REVIEW_ID = "crev-amazon-R1DEMO0001"
SKU = "SKU-KC-002"
CAUSE = "logistics_delay"


# ============================================================ 假会话（只为 count 查询）

class _Res:
    """支持 `.scalar_one()`（`select(func.count())` 那条路走它）。"""

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
            raise RuntimeError("no rows")
        return self._rows[0]

    def scalar_one_or_none(self):
        return self.first()


class _CountSession:
    """`count_repeat_issues` 只发一条 `select(func.count())` ⇒ 喂一个数就够。

    ★ 刻意**不实现 where 语义**：那等于把 SQLAlchemy 重抄一遍，抄错会得到一份
      「看起来很真的假结果」。这里要钉的是**判定合成**，不是计数实现本身。
    """

    def __init__(self, count: int):
        self.count = count

    async def execute(self, stmt):
        return _Res([self.count])


def _stub(monkeypatch, *, cause=CAUSE, count=1, health=None) -> _CountSession:
    """把三个上游都换成受控输入：ctx / 计数 / 健康分。"""

    async def _ctx(session, shop_id, review_id):
        return {
            "found": True,
            "review": {"id": REVIEW_ID, "sku": SKU},
            "attribution": ({"primary_cause": cause} if cause is not None else None),
            "data_source": "mock_seed",
        }

    async def _health(session, shop_id, sku):
        if health is None:
            return {"found": False, "sku": sku, "error": "该 SKU 还没算过健康分"}
        return {"found": True, "sku": sku, **health}

    # ★ 拆包后打桩必须打在**调用点所在子模块** `systemic` 上（不是包门面）。
    monkeypatch.setattr(svc.systemic, "get_review_context", _ctx)
    monkeypatch.setattr(svc.systemic, "get_sku_health_score", _health)
    return _CountSession(count)


#: 正常健康分（无下行趋势、中差评占比低）
HEALTHY = {"health_score": 88.0, "previous_score": 87.3, "delta": 0.7,
           "negative_rate": 0.08, "review_count": 40, "top_cause": CAUSE}
#: 环比为负
DROPPING = {**HEALTHY, "delta": -0.7, "previous_score": 88.7, "health_score": 88.0}
#: 占比偏高（环比不为负 —— 单独钉「占比」这一支）
HIGH_NEG = {**HEALTHY, "delta": 0.0, "negative_rate": 0.42}


# ============================================================ A. 四个分支

async def test_unknown_when_attribution_missing(monkeypatch):
    """没有归因 ⇒ 判不出，且**不硬判**（本仓 fail-closed：拿不到就报 unknown）。"""
    session = _stub(monkeypatch, cause=None)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["ready"] is False
    assert out["verdict"] == "unknown"
    assert out["recommend_escalate"] is False
    assert out["reason"], "缺归因时必须给得出可读原因（否则界面只能说『失败了』）"


async def test_unknown_when_cause_is_unknown_code(monkeypatch):
    """归因码本身是 `unknown` ⇒ 与「没有归因」同样处理，不许当成个案放过去。"""
    session = _stub(monkeypatch, cause="unknown")
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["ready"] is False
    assert out["verdict"] == "unknown"
    assert out["recommend_escalate"] is False


async def test_isolated(monkeypatch):
    """同因只出现 1 次、SKU 无下行 ⇒ 个案。"""
    session = _stub(monkeypatch, count=1, health=HEALTHY)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["ready"] is True
    assert out["verdict"] == "isolated"
    assert out["verdict_label"] == svc.VERDICT_LABELS["isolated"]
    assert out["recommend_escalate"] is False
    assert out["is_repeat_issue"] is False


async def test_repeat_when_threshold_hit_without_downtrend(monkeypatch):
    """同因 3 次但 SKU 没变坏 ⇒ `repeat`（建议升级），**不**升格为系统性。"""
    session = _stub(monkeypatch, count=svc.REPEAT_ISSUE_THRESHOLD, health=HEALTHY)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["verdict"] == "repeat"
    assert out["recommend_escalate"] is True
    assert out["is_repeat_issue"] is True
    assert out["historical_count"] == svc.REPEAT_ISSUE_THRESHOLD


@pytest.mark.parametrize("health,label", [
    (DROPPING, "环比为负"),
    (HIGH_NEG, "中差评占比偏高"),
])
async def test_systemic_when_repeat_plus_trend(monkeypatch, health, label):
    """重复 + 趋势（环比负 / 占比高）⇒ 系统性风险。两个趋势支各钉一条。"""
    session = _stub(monkeypatch, count=svc.REPEAT_ISSUE_THRESHOLD, health=health)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["verdict"] == "systemic", f"{label} 这一支没生效"
    assert out["recommend_escalate"] is True
    assert out["reason"], "系统性结论必须带依据（否则和个案长得一样）"


# ============================================================ C. 边界

@pytest.mark.parametrize("health,expect_in,expect_not_in", [
    (HIGH_NEG, "中差评占比", "下降"),
    (DROPPING, "下降", "中差评占比"),
])
async def test_systemic_reason_names_the_actual_trigger(
    monkeypatch, health, expect_in, expect_not_in,
):
    """★ 文案必须点名**真正命中的那一支**（第 294 轮真机读数抓出来的缺陷）。

    真机的组合是 `delta=+14`（环比**上升**）+ `negative_rate=0.5`（占比偏高）：
    判 `systemic` 是对的（占比那一支命中），但 reason 当时写成
    「SKU 趋势向下（环比 14.0）」—— **字面为真、暗示为假**，
    用户会照着它去查一个并不存在的下降。

    ★ 两个方向都钉：命中占比时不许说「下降」；命中下降时不许说「占比」。
      只钉一边的话，另一边的错文案照样能过。
    """
    session = _stub(monkeypatch, count=svc.REPEAT_ISSUE_THRESHOLD, health=health)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["verdict"] == "systemic"
    assert expect_in in out["reason"], out["reason"]
    assert expect_not_in not in out["reason"], (
        f"文案提到了并没命中的那一支「{expect_not_in}」：{out['reason']}"
    )


async def test_count_two_is_not_repeat(monkeypatch):
    """★ 边界：2 次不算重复 —— 钉的是「阈值确实是 3」，不是「≥1 就算」。"""
    session = _stub(monkeypatch, count=svc.REPEAT_ISSUE_THRESHOLD - 1, health=DROPPING)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["is_repeat_issue"] is False
    assert out["verdict"] == "isolated", "没到阈值就不该因为趋势而升格"


async def test_missing_health_does_not_upgrade_or_crash(monkeypatch):
    """拿不到健康分 ⇒ 结论停在 `repeat`，**不因缺数据而放大**成系统性。

    ★ 这是安全方向的选择（本仓 fail-closed 的一贯口径）：缺证据时既不升级结论、
      也不悄悄降级成「个案」—— 停在证据支持得住的那一档。
    """
    session = _stub(monkeypatch, count=svc.REPEAT_ISSUE_THRESHOLD, health=None)
    out = await svc.analyze_review_systemic(session, SHOP, REVIEW_ID)
    assert out["verdict"] == "repeat"
    assert out["health"]["found"] is False


# ============================================================ B/D/E. 口径同步 · 端点 · 唯一真源

def _skill_content() -> str:
    """把 `seed.py` 里技能卡 `cs-negative-review-triage` 的正文取出来（AST）。"""
    src = (BACKEND / "modules" / "skills" / "seed.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        flat = {}
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                flat[k.value] = v
        if flat.get("name") and getattr(flat["name"], "value", None) == "cs-negative-review-triage":
            content = flat.get("content")
            assert isinstance(content, ast.Constant), "技能卡的 content 不是字符串字面量"
            return content.value
    raise AssertionError("未在 seed.py 里找到 cs-negative-review-triage 技能卡")


def test_threshold_matches_skill_text():
    """阈值**只有一份**：代码常量 == 技能正文写的那个数。

    ★ 为什么这条必须存在：两条通道（面板 / 技能）都会向用户报「是不是重复问题」，
      它们各有一个 3。代码里改成 5 而技能正文没改 ⇒ 同一诉求两个结论，
      且**谁都不会报错**。这条判据让「改一处」变成不可能。
    """
    text = _skill_content()
    nums = [int(m) for m in re.findall(r"≥\s*(\d+)\s*次", text)]
    assert nums, "技能正文里找不到「≥N 次」这个阈值表述（判据会空跑）"
    assert svc.REPEAT_ISSUE_THRESHOLD in nums, (
        f"技能正文里的阈值 {sorted(set(nums))} 与 service.REPEAT_ISSUE_THRESHOLD="
        f"{svc.REPEAT_ISSUE_THRESHOLD} 对不上"
    )


def test_verdict_labels_cover_every_verdict():
    """`VERDICT_LABELS` 必须覆盖代码里可能赋的每个 verdict（防空跑/防 KeyError）。"""
    assert set(svc.VERDICT_LABELS) == {"isolated", "repeat", "systemic", "unknown"}


async def test_endpoints_registered_in_runtime_route_table():
    """D. 两个端点在**运行时路由表**里 —— 不是 grep 源码。"""
    from main import app
    from scripts.route_inventory import route_paths

    paths = route_paths(app)
    assert len(paths) > 100, f"路由表只盘到 {len(paths)} 条 ⇒ 盘点失明，判据无效"
    for p in (
        "/api/v1/trade/reviews/{review_id}/systemic-check",
        "/api/v1/trade/skus/{sku}/health",
    ):
        assert p in paths, f"{p} 没挂进 app（写了但没挂 ⇒ 前端永远 404）"


@pytest.mark.parametrize("path", [
    "/api/v1/trade/reviews/crev-x/systemic-check",
    "/api/v1/trade/skus/SKU-X/health",
])
async def test_endpoints_require_shop_context(client, path):
    """缺 `X-Shop-ID` ⇒ 400（不是 200 空对象）。

    ★ 为什么不能放宽成「返回空」：本模块的数据全是租户隔离的，
      「还没选店铺」与「这条差评是个案」是两件不同的事 ——
      混成同一个空结果，用户会得出「没问题」的错误结论（本仓：失败必须能归因）。
    """
    r = await client.get(path, headers={})
    assert r.status_code == 400, f"{path} 期望 400，实际 {r.status_code} {r.text[:200]}"
    assert "店铺" in r.json().get("detail", ""), "400 的原因不可读"


def _name_hits(tree: ast.AST, name: str) -> list[str]:
    """某个名字在**任何形态**下出现的位置。

    ★★ 为什么必须同时查「导入点」（第 294 轮反向注入实测）：
      本判据第一版只查 `ast.Name` / `ast.Attribute`（使用点）。注入
      `from modules.trade.db_model import SkuHealthScoreRecord as _X` 时
      **一条都没红** —— 而「又 import 了这张表」正是第二份查询的**起点**。
      只查使用点的判据会被「先 import、还没用」这种形态整个绕过去。
    """
    hits: list[str] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and n.id == name:
            hits.append(f"Name@{n.lineno}")
        elif isinstance(n, ast.Attribute) and n.attr == name:
            hits.append(f"Attribute@{n.lineno}")
        elif isinstance(n, ast.alias) and (n.name == name or (n.asname or "") == name):
            hits.append(f"alias@{n.lineno}")      # import / import ... as ...
    return hits


def test_health_query_has_single_source():
    """E. `tools.py` 里不得再有第二份健康分查询（唯一真源在 service）。

    ★ 判据走 AST，不用「源码字符串包含」：注释 / docstring 里提到表名会让
      字符串判据**恒真**（本仓铁律：docstring 会骗过字符串判据）。
    """
    src = (BACKEND / "modules" / "trade" / "tools.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert "get_sku_health_score" in src, "工具不再调 service ⇒ 判据会空跑"
    for name in ("SkuHealthScoreRecord", "scope_condition"):
        hits = _name_hits(tree, name)
        assert not hits, (
            f"tools.py 里又出现了 {name}（{hits}）—— 健康分查询出现了第二份实现；"
            f"端点与工具必须共用 service.get_sku_health_score"
        )


def test_threshold_has_single_definition():
    """阈值在 service 里**只有一处定义**，且 `count_repeat_issues` 引用的就是它。

    ★ 这条是反向注入逼出来的（见 patch-294e）：`count_repeat_issues` 原先写死
      `>= 3`，把常量改成 5 时**判定用例不红** —— 真判据走的是那个硬编码。
      所以判据要钉的不只是「有常量」，而是「**没有第二个数**」。
    """
    src = read_service_source()
    assert src.count("REPEAT_ISSUE_THRESHOLD = ") == 1, "阈值出现了多处定义"
    tree = ast.parse(src)
    # `count_repeat_issues` 函数体里不得再有裸的数字比较
    target = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "count_repeat_issues"
    )
    literals = [
        n.value for n in ast.walk(target)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, int) and not isinstance(n.value, bool)
        and n.value != 0          # 0 是「未知归因码时计数为 0」的正常值，不是阈值
    ]
    assert literals == [], (
        f"`count_repeat_issues` 里还有写死的数字 {literals} —— 阈值必须只有常量一处"
    )

