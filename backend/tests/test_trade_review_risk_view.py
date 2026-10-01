# -*- coding: utf-8 -*-
"""第 299 轮 P1：风险识别只读视图（`service.scan_reviews_risk`）的判据。

====================================================================
★ 这个视图的三条不变量，就是本文件要钉住的东西
====================================================================
1. **排序在后端、且顺序是 风险 → 未定论 → 干净**。
   「未定论」必须在「干净」**前面**（前者要人补判）。前端不得自己重排。
2. **deep 但无凭据 ⇒ 显式 degraded + 每条 unknown**，绝不静默变成「无风险」。
   这是 fail-closed 的端点级延伸：把「没扫成」和「扫了没风险」合并，
   等于把一次失败的扫描伪装成一次通过的扫描。
3. **零写操作**。识别只产线索；写路径仍然只有 `propose_disposition` 一条。

★ 为什么全部走 monkeypatch 而不是连库：本仓 `tests/` 连的是**共享生产库**，
  连库的用例「全量红 / 单跑绿」不可复现（既有教训）。判定逻辑用桩即可，
  端点只验路由表与缺店铺 400（两者都在碰库之前）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from modules.trade import risk_scan as rs
from modules.trade import service as svc

BACKEND = Path(__file__).resolve().parents[1]
#: trade 服务层源码（第 355 轮拆包 ⇒ 读整个包）—— AST 形态判据要用（只读，不参与 import）。
from trade_service_src import read_service_source  # noqa: E402

SVC_SRC = read_service_source()


# ============================================================ 桩工具

def _res(decision: str, *, level: str | None = None, cats=(), channel="rule",
         note="") -> rs.ScanResult:
    """造一个 `ScanResult`：`decision` 显式给（三态不可由 hits 反推时尤其重要）。"""
    hits = [
        rs.RiskHit(category=c, level=level or rs.LEVEL_UNKNOWN,
                   evidence=[f"ev-{c}"], channel=channel, note=note)
        for c in cats
    ]
    return rs.ScanResult(hits=hits, channel=channel, decision=decision, note=note)


def _item(i: int, review_at: str, body: str = "body", title: str = "") -> dict:
    """一条「像 `_review_to_dict` 输出」的评价（只需被扫到的那几个字段）。"""
    return {
        "id": f"crev-{i}", "review_at": review_at, "title": title, "body": body,
        "rating": 2, "asin": "B0X", "sku": "SKU-X",
    }


def _patch_list(monkeypatch, items, seen: dict | None = None):
    """桩掉列表与计数（`scan_reviews_risk` 的两个取数入口）。"""
    async def _list(session, shop_id, **kw):
        if seen is not None:
            seen.update(kw)
        return list(items)

    async def _count(session, shop_id, **kw):
        return len(items)

    # ★ 第 355 轮拆包：**打桩必须打在调用点所在的子模块上**。
    monkeypatch.setattr(svc.review_risk, "list_recent_negative_reviews", _list)
    monkeypatch.setattr(svc.review_risk, "count_recent_negative_reviews", _count)


def _patch_scan_text(monkeypatch, table: dict[str, rs.ScanResult], calls: list | None = None):
    def _scan_text(text, channel="rule"):
        if calls is not None:
            calls.append((text, channel))
        return table.get(text, _res(rs.DECISION_CLEAN, channel=channel))

    monkeypatch.setattr(svc.risk_scan, "scan_text", _scan_text)


# ============================================================ 1. 排序

async def test_sort_is_risk_then_unknown_then_clean(monkeypatch):
    """★ 置顶口径：风险 → 未定论 → 干净；同组内按时间 新→旧。

    ★★ 为什么顺序里「未定论」必须在「干净」前：未定论 = 算法不敢定、要人补判；
      干净 = 不用人管。把两者并列排序，等于让**待办**淹在长尾里。
    """
    items = [
        _item(1, "2026-01-04"),                       # clean, 最新
        _item(2, "2026-01-01"),                       # risk, 最旧
        _item(3, "2026-01-03"),                       # unknown
        _item(4, "2026-01-02"),                       # clean, 较旧
    ]
    _patch_list(monkeypatch, items)
    _patch_scan_text(monkeypatch, {
        "body": _res(rs.DECISION_CLEAN),
        "risk": _res(rs.DECISION_RISK, level=rs.LEVEL_HIGH, cats=("r1",)),
        "unknown": _res(rs.DECISION_UNKNOWN, cats=("r5",), note="拿不准"),
    })
    # 让每条的文本区分开（同名文本会共用同一判定）
    for it, key in zip(items, ["clean", "risk", "unknown", "clean"]):
        it["body"] = key

    out = await svc.scan_reviews_risk(None, "shop-1")  # type: ignore[arg-type]
    order = [(x["id"], x["risk"]["decision"]) for x in out["items"]]
    assert order == [
        ("crev-2", "risk"),        # 风险置顶
        ("crev-3", "unknown"),     # 未定论居中
        ("crev-1", "clean"),       # 组内新→旧
        ("crev-4", "clean"),
    ], f"排序口径错误：{order}"
    assert (out["risk_count"], out["unknown_count"], out["clean_count"]) == (1, 1, 2)


async def test_sort_does_not_reorder_within_group(monkeypatch):
    """同组内必须保持「新→旧」—— 两段排序若写成一段会把组内序打乱。"""
    items = [_item(i, f"2026-01-0{i}") for i in range(1, 5)]   # 全 clean
    _patch_list(monkeypatch, items)
    _patch_scan_text(monkeypatch, {})
    out = await svc.scan_reviews_risk(None, "shop-1")  # type: ignore[arg-type]
    assert [x["review_at"] for x in out["items"]] == [
        "2026-01-04", "2026-01-03", "2026-01-02", "2026-01-01",
    ]


# ============================================================ 2. fail-closed

async def test_deep_without_credentials_is_degraded_not_clean(monkeypatch):
    """★★ 核心 fail-closed：请求了语义通道却没有凭据 ⇒ 显式 degraded + 全 unknown。

    ★ 反向注入靶点：把 `degraded` 分支改成报 `clean`（或让它悄悄退回只跑规则），
      本用例必须转红。否则「这次没扫成」会被上屏成「这家店很干净」。
    """
    _patch_list(monkeypatch, [_item(i, f"2026-01-0{i}") for i in range(1, 4)])
    _patch_scan_text(monkeypatch, {})                       # 规则通道零命中
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: False)

    out = await svc.scan_reviews_risk(None, "shop-1", deep=True)  # type: ignore[arg-type]
    assert out["degraded"] is True, "缺凭据时没有报 degraded ⇒ 静默降级"
    assert out["llm_used"] is False, "缺凭据却声称用了 LLM"
    assert out["clean_count"] == 0, (
        "降级下把『没扫成』报成 clean ⇒ 失败被伪装成通过（本仓最忌讳的一类）"
    )
    assert out["unknown_count"] == 3
    for x in out["items"]:
        assert x["risk"]["decision"] == rs.DECISION_UNKNOWN
        assert "未定论" in x["risk"]["note"] or "不可用" in x["risk"]["note"], (
            "降级原因没有写进 note ⇒ 前端无从如实播报"
        )


async def test_degraded_still_reports_real_rule_hits(monkeypatch):
    """降级不等于「一律未定论」：规则通道真命中的条目照实报 risk（真信号不埋）。"""
    items = [_item(1, "2026-01-01", body="threat"), _item(2, "2026-01-02", body="plain")]
    _patch_list(monkeypatch, items)
    _patch_scan_text(monkeypatch, {
        "threat": _res(rs.DECISION_RISK, level=rs.LEVEL_HIGH, cats=("r1",)),
    })
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: False)

    out = await svc.scan_reviews_risk(None, "shop-1", deep=True)  # type: ignore[arg-type]
    by_id = {x["id"]: x["risk"] for x in out["items"]}
    assert by_id["crev-1"]["decision"] == rs.DECISION_RISK
    assert by_id["crev-1"]["is_risk"] is True
    assert by_id["crev-2"]["decision"] == rs.DECISION_UNKNOWN
    assert out["degraded"] is True
    # ★ 真命中必须置顶（它 decision=risk）
    assert out["items"][0]["id"] == "crev-1"


async def test_shallow_never_touches_llm(monkeypatch):
    """`deep=False` ⇒ 一个模型实例都不造（这是「零成本」那一档的全部含义）。"""
    _patch_list(monkeypatch, [_item(1, "2026-01-01")])
    _patch_scan_text(monkeypatch, {})

    def _boom(*a, **kw):  # pragma: no cover - 被调用即失败
        raise AssertionError("浅层扫描不该构造 LLM")

    monkeypatch.setattr("ai_infra.llm.get_llm", _boom)
    out = await svc.scan_reviews_risk(None, "shop-1", deep=False)  # type: ignore[arg-type]
    assert out["llm_used"] is False and out["degraded"] is False


async def test_deep_uses_one_batch_call_and_reads_it_back(monkeypatch):
    """有凭据 + deep ⇒ 语义通道是**一次批量调用**，结果按序号回填到各条。

    ★ 反向注入靶点：把 `scan_llm_batch` 换回「逐条 `scan_llm`」⇒ 本用例的
      `len(seen) == 1` 立刻转红。这一条钉的就是「批量」这件事本身 ——
      逐条串行 20 条的实测是 43.4 s，那正是老板这轮指出的问题。
    """
    items = [_item(1, "2026-01-01", body="semantic"), _item(2, "2026-01-02", body="other")]
    _patch_list(monkeypatch, items)
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: True)
    monkeypatch.setattr("ai_infra.llm.get_llm", lambda **kw: "LLM-INSTANCE")

    seen: list[dict] = []

    async def _batch(texts, llm=None):  # noqa: ANN001
        seen.append({"texts": list(texts), "llm": llm})
        return [
            rs.ScanResult(
                hits=[rs.RiskHit(category="r2", level="medium",
                                 evidence=["refund or I will report"], channel="llm")],
                channel="llm",
            ) if t == "semantic" else rs.ScanResult(
                hits=[], channel="llm", decision=rs.DECISION_CLEAN)
            for t in texts
        ]

    monkeypatch.setattr(svc.risk_scan, "scan_llm_batch", _batch)
    out = await svc.scan_reviews_risk(None, "shop-1", deep=True)  # type: ignore[arg-type]

    assert len(seen) == 1, f"语义通道不是一次批量调用（发了 {len(seen)} 次）"
    assert seen[0]["texts"] == ["semantic", "other"]
    assert seen[0]["llm"] == "LLM-INSTANCE", "没把 llm 实例传进批量通道"
    assert out["degraded"] is False and out["llm_used"] is True
    blk = {x["id"]: x["risk"] for x in out["items"]}["crev-1"]
    assert blk["decision"] == "risk" and blk["level"] == "medium"
    assert blk["level_label"] == rs.LEVEL_LABELS["medium"], "等级中文名没走后端真源"
    assert blk["is_risk"] is True and blk["risk_categories"] == ["r2"]
    assert blk["suggested_action"] == rs.SUGGESTED_ACTION["medium"]
    assert blk["channel"] == "fuse", "走语义的块必须经过 fuse（通道名不能是 rule/llm）"


async def test_empty_body_is_unknown_not_clean(monkeypatch):
    """没有正文可判 ⇒ `unknown`（不是 `clean`）。三态不可压成两态。"""
    _patch_list(monkeypatch, [_item(1, "2026-01-01", body="", title="")])
    _patch_scan_text(monkeypatch, {})
    out = await svc.scan_reviews_risk(None, "shop-1")  # type: ignore[arg-type]
    assert out["items"][0]["risk"]["decision"] == rs.DECISION_UNKNOWN
    assert "无正文" in out["items"][0]["risk"]["note"]


# ============================================================ 3. 标签 / 上限 / 分页

async def test_labels_are_served_by_backend(monkeypatch):
    """中文名由后端下发 —— 前端不得自写一份（两份实现改了这边忘那边）。"""
    _patch_list(monkeypatch, [])
    _patch_scan_text(monkeypatch, {})
    out = await svc.scan_reviews_risk(None, "shop-1")  # type: ignore[arg-type]
    assert out["category_labels"] == dict(rs.CATEGORY_LABELS)
    assert out["level_labels"] == dict(rs.LEVEL_LABELS)
    assert out["categories"] == list(rs.RISK_CATEGORIES)


@pytest.mark.parametrize("deep,expect_cap", [
    (False, svc.RISK_SCAN_MAX_LIMIT),
    (True, svc.RISK_SCAN_MAX_LIMIT_DEEP),
])
async def test_limit_is_always_clamped_to_the_hard_cap(monkeypatch, deep, expect_cap):
    """单次上限必须真的限住取数 —— deep 每条一次模型调用，没有上限就是一个 GET 烧配额。"""
    seen: dict = {}
    _patch_list(monkeypatch, [], seen)
    _patch_scan_text(monkeypatch, {})
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: False)
    out = await svc.scan_reviews_risk(None, "shop-1", limit=999, deep=deep)  # type: ignore[arg-type]
    assert seen["limit"] == expect_cap, f"传给取数的 limit 没被限到 {expect_cap}"
    assert out["limit"] == expect_cap


async def test_capped_is_false_when_the_cap_did_not_truncate_anything(monkeypatch):
    """★ `capped` 只在**上限真的截断了数据**时为真 —— 否则界面会写一句假话。

    ★ 反向注入：把 `"capped"` 改回 `eff_limit < int(limit)` ⇒ 本用例转红。
      为什么这很重要：面板固定传 `limit=100`（deep 上限 20），
      按旧口径**无论库里几条**都会亮「已达单次上限」，界面上写成
      「本页扫描 3 / 共 3 条（已达单次上限）」—— 字面为真、暗示为假。
    """
    _patch_list(monkeypatch, [_item(i, f"2026-01-0{i}") for i in range(1, 3)])
    _patch_scan_text(monkeypatch, {})
    out = await svc.scan_reviews_risk(None, "shop-1", limit=100, deep=True)  # type: ignore[arg-type]
    assert out["scanned"] == 2 and out["total"] == 2
    assert out["capped"] is False, "库里比上限还少，却报了「已达单次上限」"


@pytest.mark.parametrize("deep,cap", [
    (False, svc.RISK_SCAN_MAX_LIMIT),
    (True, svc.RISK_SCAN_MAX_LIMIT_DEEP),
])
async def test_capped_is_true_when_the_cap_actually_hides_rows(monkeypatch, deep, cap):
    """库里条数 > 单次上限 ⇒ 确实有没扫到的，且原因是上限 ⇒ capped=True。"""
    rows = [_item(i, f"2026-01-{i:02d}") for i in range(1, cap + 6)]

    async def _list(session, shop_id, **kw):
        return rows[: kw.get("limit")]

    async def _count(session, shop_id, **kw):
        return len(rows)

    # ★ 第 355 轮拆包：**打桩必须打在调用点所在的子模块上**。
    monkeypatch.setattr(svc.review_risk, "list_recent_negative_reviews", _list)
    monkeypatch.setattr(svc.review_risk, "count_recent_negative_reviews", _count)
    _patch_scan_text(monkeypatch, {})
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: False)
    out = await svc.scan_reviews_risk(None, "shop-1", limit=999, deep=deep)  # type: ignore[arg-type]
    assert out["scanned"] == cap and out["total"] == cap + 5
    assert out["capped"] is True


async def test_total_is_not_truncated_by_limit(monkeypatch):
    """`total` 是真实条数；`scanned < total` 就是「本页只覆盖一部分」的显式信号。"""
    items = [_item(i, f"2026-01-0{i}") for i in range(1, 4)]
    async def _list(session, shop_id, **kw):
        return items[:1]
    async def _count(session, shop_id, **kw):
        return 3
    # ★ 第 355 轮拆包：**打桩必须打在调用点所在的子模块上**。
    monkeypatch.setattr(svc.review_risk, "list_recent_negative_reviews", _list)
    monkeypatch.setattr(svc.review_risk, "count_recent_negative_reviews", _count)
    _patch_scan_text(monkeypatch, {})
    out = await svc.scan_reviews_risk(None, "shop-1")  # type: ignore[arg-type]
    assert out["total"] == 3 and out["scanned"] == 1


# ============================================================ 3b. ★ 端到端：正类口径唯一

#: 两条样本（实测：前者只命中 r5，后者命中 r1）
_BODY_EMOTION_ONLY = "This is garbage and a complete waste of money. Never again."
_BODY_THREAT = (
    "I will leave a 1-star review and tell everyone about this, or I'll take this further."
)


async def _batch_says_clean(texts, llm=None):  # noqa: ANN001
    """桩掉**批量**语义通道为「明确判无风险」，让规则通道与 `fuse` 走**真实现**。

    ★ 返回必须与入参**等长同序** —— 那正是 `scan_llm_batch` 的契约。
    """
    return [rs.ScanResult(hits=[], channel="llm", decision=rs.DECISION_CLEAN)
            for _ in texts]


async def test_deep_path_counts_only_real_risk_categories(monkeypatch):
    """★★ 端点级不变量：`decision == risk` ⟺ 命中四类，且 `risk_count` 只数它们。

    ★ 走的是**真** `scan_rules` / `fuse`（只桩掉 LLM 调用），所以它钉的是判定内核，
      不是投影层自己算得对不对。
    ★ 反向注入靶点：把 `risk_scan._decide` 的正类判据改回「有任何等级已知的 hit」，
      或把 `fuse` 的守卫改回 `merged.hits` ⇒ 本用例转红。
      这正是 P0 交付时的形态 —— 当时 3 条**全负样本**的库报出 risk=2，
      而那两条 `is_risk=False`，界面上就成了「红皮置顶 + 无风险标签」。
    """
    _patch_list(monkeypatch, [
        _item(1, "2026-01-03", body=_BODY_EMOTION_ONLY),
        _item(2, "2026-01-02", body=_BODY_THREAT),
        _item(3, "2026-01-01", body="The box arrived with a small dent on the corner."),
    ])
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: True)
    monkeypatch.setattr(svc.risk_scan, "scan_llm_batch", _batch_says_clean)
    monkeypatch.setattr("ai_infra.llm.get_llm", lambda **kw: object())

    out = await svc.scan_reviews_risk(None, "shop-1", limit=10, deep=True)  # type: ignore[arg-type]
    by_id = {x["id"]: x["risk"] for x in out["items"]}

    assert by_id["crev-1"]["categories"] == [rs.CAT_EMOTION], "样本失效：高情绪那条没命中 r5"
    assert by_id["crev-1"]["decision"] != rs.DECISION_RISK, (
        "只命中 r5（高情绪）的评价被判成了 risk —— r5 按定义不是风险话术"
    )
    assert by_id["crev-2"]["decision"] == rs.DECISION_RISK
    assert by_id["crev-2"]["is_risk"] is True
    assert out["risk_count"] == 1, (
        f"risk_count={out['risk_count']}：把没有命中四类的条目算进了风险计数"
    )

    for it in out["items"]:
        blk = it["risk"]
        assert (blk["decision"] == rs.DECISION_RISK) == bool(blk["is_risk"]), (
            f"{it['id']}: decision={blk['decision']} 与 is_risk={blk['is_risk']} 分叉"
        )
        if blk["decision"] == rs.DECISION_RISK:
            assert blk["risk_categories"], "判成 risk 却没有命中任何四类类别"


# ============================================================ 4. risk 块的线上契约

#: 前端渲染 `risk` 块要消费的全部字段（**线上契约**）。
#: ★ 这条判据钉的是「**不得少**」，不是「恰好这些」—— 多一个字段是无害的，
#:   少一个才会让界面静默缺项（而静默缺项在本仓是最难查的一类 bug）。
RISK_BLOCK_REQUIRED_KEYS = frozenset({
    "decision", "level", "level_label", "suggested_action", "is_risk",
    "categories", "risk_categories", "hits", "channel", "note",
})


def _sample_scan_result() -> rs.ScanResult:
    return rs.ScanResult(
        hits=[rs.RiskHit(category="r1", level="high", evidence=["I will report"],
                         channel="fuse", note="威胁")],
        channel="fuse", decision="risk",
    )


def test_risk_block_exposes_the_documented_wire_keys():
    """`risk` 块必须含齐全前端要用的字段。

    ★ 反向注入靶点：从构造处删掉任意一个键（例如 `level_label`）⇒ 本用例转红。
      （前一版写成「两条通道产出的块相等」，那是**套话** —— `_risk_block_from_full`
      本来就委托给 `_risk_block_from_scan`，两边永远相等，加字段也测不出来。）
    """
    block = svc._risk_block_from_scan(_sample_scan_result())
    missing = RISK_BLOCK_REQUIRED_KEYS - set(block)
    assert not missing, f"risk 块缺字段 {sorted(missing)} ⇒ 前端渲染会静默缺项"
    assert block["hits"] and block["hits"][0]["label"] == rs.CATEGORY_LABELS["r1"], (
        "命中项没有走 CATEGORY_LABELS 真源"
    )


def test_fused_scan_result_keeps_wire_semantics():
    """语义路径的块由**同一构造点**产出，字段语义与规则路径一致。

    ★ 为什么不再有 `_risk_block_from_full`：它转换的是已退役的 `scan_full` 的返回，
      而 deep 分支现在走 `fuse([rule, llm_batch])` —— 留一个没人调用的转换层
      = 第二份投影实现（本仓铁律：两份实现里至少有一份永远测不到）。
      ★ 换来的等价保障：语义路径**必须**经过 `_risk_block_from_scan`，由
        `test_risk_block_has_single_construction_site` 用 AST 钉住「只有一处构造」。
    """
    rule = rs.scan_rules(_BODY_THREAT)
    llm = rs.ScanResult(
        hits=[rs.RiskHit(category="r2", level="medium",
                         evidence=["I want a full refund"], channel="llm", note="索赔")],
        channel="llm",
    )
    block = svc._risk_block_from_scan(rs.fuse([rule, llm]))
    assert RISK_BLOCK_REQUIRED_KEYS <= set(block)
    assert block["decision"] == "risk" and block["level"] == "high", (
        "融合应取四类里等级更高者（r1/high 覆盖 r2/medium）"
    )
    assert block["is_risk"] is True and set(block["risk_categories"]) == {"r1", "r2"}
    assert block["level_label"] == rs.LEVEL_LABELS["high"]
    assert block["suggested_action"] == rs.SUGGESTED_ACTION["high"]
    assert all(h["label"] for h in block["hits"]), "命中项没有走 CATEGORY_LABELS 真源"
    # 空命中 ⇒ 不得凭空造 risk
    empty = svc._risk_block_from_scan(
        rs.ScanResult(hits=[], channel="rule", decision=rs.DECISION_CLEAN))
    assert empty["is_risk"] is False and empty["hits"] == []


# ============================================================ 5. 形态门禁（AST）

def _func_tree(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    src = SVC_SRC
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == name:
            return n
    raise AssertionError(f"service.py 里找不到函数 {name}")


def _called_names(node: ast.AST) -> set[str]:
    """函数体里被调用的**名字**（含 `obj.method` 取 method 名）。"""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def _used_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def test_scan_reviews_risk_reuses_the_single_query_source():
    """★ 不得在 `scan_reviews_risk` 里另写一份差评查询（同一查询两份实现）。

    ★ 判据走 AST 而不是「源码字符串包含」：docstring / 注释里提到表名会让
      字符串判据**恒真**（本仓铁律：docstring 会骗过字符串判据）。
    """
    node = _func_tree("scan_reviews_risk")
    used = _used_names(node)
    for name in ("CustomerReviewRecord", "scope_condition"):
        assert name not in used, (
            f"`scan_reviews_risk` 里出现了 {name} ⇒ 它自己查库了；"
            f"取数必须复用 list_recent_negative_reviews（唯一口径）"
        )
    called = _called_names(node)
    for name in ("list_recent_negative_reviews", "count_recent_negative_reviews"):
        assert name in called, f"没有复用 {name} ⇒ 取数口径可能已经分叉"


def test_scan_reviews_risk_is_read_only():
    """★ 零写操作：识别函数体里不得出现任何写出口或 session 写原语。"""
    node = _func_tree("scan_reviews_risk")
    called = _called_names(node) | _used_names(node)
    banned = {
        "propose_disposition", "approve_disposition", "reject_disposition",
        "issue_disposition", "backfill_dispositions", "apply_compensation_rule",
        "attribute_review", "compute_sku_health", "upsert_review", "sync_trade",
        "add", "commit", "flush", "delete", "execute", "begin",
    }
    hit = sorted(called & banned)
    assert not hit, f"`scan_reviews_risk` 里有写/执行原语 {hit} ⇒ 它不再是只读端点"


def test_risk_block_has_single_construction_site():
    """★ 只允许**一处**把判定投影成块：多一处 ⇒ 两支形状迟早分叉。

    ★ 判据是 AST 的**结构事实**：「构造带 `decision` 键的字典」的函数只能有一个。
      「两支块相等」是套话（委托关系下永远相等，实测反向注入加字段**没红**）。
    ★ 反向注入靶点：在 `scan_reviews_risk` 里就地拼一个带 `decision` 的块 ⇒ 转红。
    """
    tree = ast.parse(SVC_SRC)
    sites: dict[str, list[int]] = {}
    for n in ast.walk(tree):
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in ast.walk(n):
            if not isinstance(d, ast.Dict):
                continue
            keyed = {k.value for k in d.keys if isinstance(k, ast.Constant)}
            if "decision" in keyed:
                sites.setdefault(n.name, []).append(d.lineno)
    assert set(sites) == {"_risk_block_from_scan"}, (
        f"风险块的构造点不止一处：{sites} ⇒ 两支形状迟早分叉"
    )
    assert SVC_SRC.count("def _risk_block_from_scan(") == 1, "投影函数有多处定义"


def test_labels_are_read_from_the_constants_not_hardcoded():
    """端点下发的中文名必须**引用常量**，不得在 service 里再写一份字面量。

    ★ 反向注入靶点：把 `dict(risk_scan.CATEGORY_LABELS)` 换成字面量 ⇒ 转红
      （从此两份真源可以各改各的，且谁都不报错）。
    """
    node = _func_tree("scan_reviews_risk")
    used = _used_names(node)
    for name in ("CATEGORY_LABELS", "LEVEL_LABELS", "RISK_CATEGORIES"):
        assert name in used, f"`scan_reviews_risk` 没有引用 risk_scan.{name}"
    for n in ast.walk(node):
        if isinstance(n, ast.Dict):
            keyed = {k.value for k in n.keys if isinstance(k, ast.Constant)}
            assert not ({"r1", "r2", "r3", "r4"} & keyed), (
                f"函数体里出现类别码字面量表（第 {n.lineno} 行）—— 第二份中文名真源"
            )


def test_decision_rank_has_single_definition():
    """排序权重只有一处定义，且端点侧（router）不得再做一次排序。"""
    src = SVC_SRC
    assert src.count("_RISK_DECISION_RANK = ") == 1, "排序权重出现了多处定义"
    router_src = (BACKEND / "modules" / "trade" / "router.py").read_text(encoding="utf-8")
    assert ".sort(" not in router_src and "sorted(" not in router_src, (
        "router 里出现了排序 ⇒ 「置顶」有了第二份实现"
    )


def test_level_labels_cover_every_level():
    """`LEVEL_LABELS` 必须覆盖代码里可能赋的每个等级（防空跑 / 防 KeyError）。"""
    assert set(rs.LEVEL_LABELS) == {
        rs.LEVEL_HIGH, rs.LEVEL_MEDIUM, rs.LEVEL_LOW, rs.LEVEL_UNKNOWN,
    }


def test_category_labels_cover_all_categories():
    """`CATEGORY_LABELS` 覆盖四类风险 + 候选池 r5 —— 少一个 ⇒ 前端标签为空串。"""
    assert set(rs.CATEGORY_LABELS) == set(rs.RISK_CATEGORIES) | {rs.CAT_EMOTION}


# ============================================================ 6. 端点

def test_endpoint_registered_in_runtime_route_table():
    """端点在**运行时路由表**里 —— 不是 grep 源码。"""
    from main import app
    from scripts.route_inventory import route_paths

    paths = route_paths(app)
    assert len(paths) > 100, f"路由表只盘到 {len(paths)} 条 ⇒ 盘点失明，判据无效"
    assert "/api/v1/trade/reviews/risk" in paths, (
        "端点没挂进 app（写了但没挂 ⇒ 前端永远 404）"
    )


async def test_endpoint_requires_shop_context(client):
    """缺 `X-Shop-ID` ⇒ 400（不是 200 空对象）。

    ★ 为什么不能放宽成「返回空」：「还没选店铺」与「这家店没有风险差评」
      是两件不同的事 —— 混成同一个空结果，用户会得出「没问题」的错误结论。
    """
    r = await client.get("/api/v1/trade/reviews/risk", headers={})
    assert r.status_code == 400, f"期望 400，实际 {r.status_code} {r.text[:200]}"
    assert "店铺" in r.json().get("detail", ""), "400 的原因不可读"


# ============================================================ 7. ★ 第 300 轮：分层（A / C / D）
#
# 老板的三个要求与落地对应：
#   A 默认浅层  → `test_shallow_is_the_default_in_both_signatures`
#   C 批量语义  → `test_deep_uses_one_batch_call_and_reads_it_back`（第 2 节）
#   D 四类命中跳过语义 → `test_deep_skips_semantics_for_items_the_rules_already_flagged`
#                        + `test_short_circuit_predicate_is_the_four_risk_categories`
#                        + `test_no_per_item_semantic_entry_point_left`


def test_shallow_is_the_default_in_both_signatures():
    """★ A：**默认档必须是浅层**。两处签名都不许把昂贵的语义通道变成默认。

    ★ 为什么值得单独钉一条：`deep` 的默认值一改，成本就从「用户按按钮才发生」
      变成「谁来调这个端点都会发生」，而接口文档、压测脚本、未来的 Agent 工具
      都不会报错 —— 只会静默地开始花钱。
    """
    import inspect

    from modules.trade import router as rtr

    for fn, label in ((svc.scan_reviews_risk, "service"), (rtr.scan_reviews_risk, "router")):
        params = inspect.signature(fn).parameters
        assert "deep" in params, f"{label}.{fn.__name__} 的 deep 参数没了"
        assert params["deep"].default is False, (
            f"{label}.{fn.__name__} 的 deep 默认不再是 False ⇒ 语义通道会变成默认档"
        )


async def test_deep_skips_semantics_for_items_the_rules_already_flagged(monkeypatch):
    """★★ D：规则已判出**四类**的条目**不再送语义**；只命中 r5 的**必须**送。

    ★ 两条方向都要对，而且代价不对称：
      - 送了四类已命中的条目 = 白花钱（`fuse()` 在那个分支提前 return、不读 LLM）；
      - 漏送只命中 r5 的条目 = **丢信号** —— 那时 `fuse()` **要**读 LLM 的结论
        （规则判 clean、LLM 可能报 risk）。实测「宽泛版」在这个方向上 3 格劣化
        （2 格漏报 + 1 格把 unknown 洗成 clean），与第 246 轮
        「关键词短路抢在技能注入之前 return」同构。

    ★ 反向注入：把筛选条件从 `r.risk_categories` 改成 `r.categories` ⇒
      本用例的 `sent[0]` 与 `semantic_skipped` 两处断言同时转红。
    """
    neutral = "The box arrived with a small dent on the corner."
    items = [
        _item(1, "2026-01-03", body=_BODY_THREAT),        # 规则命中 r1（四类）
        _item(2, "2026-01-02", body=_BODY_EMOTION_ONLY),  # 规则只命中 r5
        _item(3, "2026-01-01", body=neutral),             # 规则零命中
    ]
    _patch_list(monkeypatch, items)
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: True)
    monkeypatch.setattr("ai_infra.llm.get_llm", lambda **kw: object())

    sent: list[list[str]] = []

    async def _batch(texts, llm=None):  # noqa: ANN001
        sent.append(list(texts))
        return [rs.ScanResult(hits=[], channel="llm", decision=rs.DECISION_CLEAN)
                for _ in texts]

    monkeypatch.setattr(svc.risk_scan, "scan_llm_batch", _batch)
    out = await svc.scan_reviews_risk(None, "shop-1", deep=True)  # type: ignore[arg-type]

    assert len(sent) == 1, "语义通道不是一次批量调用"
    assert sent[0] == [_BODY_EMOTION_ONLY, neutral], (
        f"送进语义的条目不对：{sent[0]} —— 四类已命中的必须跳过，但只命中 r5 的必须送"
    )
    assert out["semantic_sent"] == 2 and out["semantic_skipped"] == 1
    assert out["llm_calls"] == 1

    by_id = {x["id"]: x["risk"] for x in out["items"]}
    assert by_id["crev-1"]["decision"] == rs.DECISION_RISK, "规则命中的四类没被报出来"
    assert by_id["crev-1"]["channel"] == "rule", (
        "被规则短路的条目没有融合过，通道名写 fuse 是假话"
    )
    assert "分层" in by_id["crev-1"]["note"], "短路这件事没写进 note ⇒ 无从解释为何没花模型钱"
    assert by_id["crev-2"]["decision"] != rs.DECISION_RISK
    assert out["risk_count"] == 1


async def test_skipping_every_item_leaves_llm_used_true_and_zero_calls(monkeypatch):
    """全部条目都被规则命中 ⇒ 一次模型调用都不发，但 `llm_used` 仍是 `True`。

    ★ 三个读数必须能解释这个组合：`llm_used=True`（语义通道**开着**）
      + `llm_calls=0`（这次**没用到**）+ `semantic_skipped=N`（全部被规则预筛）。
      少任何一个，老板都会问「那到底省了多少」而界面上答不出来。
    """
    items = [_item(i, f"2026-01-0{i}", body=_BODY_THREAT) for i in range(1, 4)]
    _patch_list(monkeypatch, items)
    monkeypatch.setattr(svc.review_risk, "_llm_configured", lambda: True)
    monkeypatch.setattr("ai_infra.llm.get_llm", lambda **kw: object())

    async def _boom(*a, **kw):  # pragma: no cover - 被调用即失败
        raise AssertionError("所有条目都被规则命中时不该发起语义调用")

    monkeypatch.setattr(svc.risk_scan, "scan_llm_batch", _boom)
    out = await svc.scan_reviews_risk(None, "shop-1", deep=True)  # type: ignore[arg-type]

    assert out["llm_used"] is True and out["degraded"] is False
    assert out["llm_calls"] == 0 and out["semantic_sent"] == 0
    assert out["semantic_skipped"] == 3
    assert out["risk_count"] == 3


def test_short_circuit_predicate_is_the_four_risk_categories():
    """★ D 的短路条件必须钉在 `risk_categories` 上 —— 不能是 `categories`。

    ★ 反向注入：把筛选推导式里的 `r.risk_categories` 改成 `r.categories` ⇒ 本用例转红。
      （只改成 `categories` 时，`semantic_skipped` 那处仍留着 `risk_categories`，
        所以判据必须**只认那一处推导式**，不能用「全函数出现过这个词」当判据 ——
        那会让门禁在反向注入下照旧绿。）

    ★ 怎么把「那一处」认出来：函数里有 4 个推导式（`texts` / `rules` / `pending` /
      `[texts[i] for i in pending]`），只有筛选送语义条目那个带 `enumerate`。
      用 `enumerate` 当锚是**变异稳定**的 —— 反向注入改的是属性名，不是过滤器形状。
    """
    node = _func_tree("scan_reviews_risk")
    comps = [
        n for n in ast.walk(node)
        if isinstance(n, ast.ListComp) and any(
            isinstance(x, ast.Call) and getattr(x.func, "id", "") == "enumerate"
            for x in ast.walk(n)
        )
    ]
    assert len(comps) == 1, f"筛选「送语义的条目」的推导式不止一处：{len(comps)}"
    attrs = {a.attr for a in ast.walk(comps[0]) if isinstance(a, ast.Attribute)}
    assert "risk_categories" in attrs, (
        "送语义的筛选条件不再看 `risk_categories`（四类）—— 改成 `categories` 会把"
        "只命中 r5 的条目一起短路掉，而 `fuse()` 那时**要**读 LLM 的结论"
    )


def test_no_per_item_semantic_entry_point_left():
    """★ deep 分支不得再出现**逐条**语义入口（`scan_llm` / 已退役的 `scan_full`）。

    ★ 那正是这一轮要消掉的 43.4 s。「留着当兜底」不算理由：两条路径对同一条
      评价给出不同耗时与不同成本，而调用方只看得到其中一个。
    """
    node = _func_tree("scan_reviews_risk")
    called = _called_names(node)
    for banned in ("scan_llm", "scan_full"):
        assert banned not in called, f"deep 分支又逐条调语义了（{banned}）—— 回到 20 条 43.4 s"
    assert "scan_llm_batch" in called, "deep 分支没有走批量语义通道"
