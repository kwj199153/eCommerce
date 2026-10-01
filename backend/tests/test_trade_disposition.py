"""第 287 轮 P0-2：`review_dispositions` 必须有**出口**（写入路径 + 状态机 + 端点）。

改造前这张表是三无表：
  · 全库 0 行 —— 全仓 `ReviewDispositionRecord(...)` 构造次数为 **0**（无写入路径）；
  · 后端无端点 —— `modules/trade` 连 `router.py` 都没有；
  · 前端零消费 —— `frontend/src` grep `disposition` 零命中。
结果是有状态机（proposed→approved→issued）、有双语回复、有补偿金额的模型，
却没有任何一条数据能证明它被用过 —— 「承诺型资产」。

★ 本文件钉三件事：
    ① **真的有写入路径**（`propose_disposition` 会落一行，且内容是现算的）；
    ② **状态机是硬约束**（未批准不能发放、已发放不可覆盖）；
    ③ **批准人/发放人只能服务端注入**（请求体里没有这两个字段）。

★ 全部 monkeypatch，**不连共享库**（本仓 `tests/` 连的是共享生产库，
  依赖 seed 数据的用例不可复现）。形态照抄 `test_cs_faq_real_source.py`。
"""

import pytest

from modules.trade import service as svc
from modules.trade.db_model import (
    CompensationRuleRecord, CustomerReviewRecord, OrderRecord,
    ReviewAttributionRecord, ReviewDispositionRecord, ShipmentRecord,
)

SHOP = "store_unit_test"
OTHER = "store_other"
REVIEW_ID = "crev-amazon-R1DEMO0001"


# ============================================================ 假会话

class _Res:
    """同时支持 `.scalars().all()/.first()` 与 `.all()/.first()/.scalar_one()`。

    ★ 为什么不实现 where 语义：那等于把 SQLAlchemy 重抄一遍，抄错会得到一份
      「看起来很真的假结果」。过滤是否发生，改由**语句文本**形态判据去查。
    """

    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self):
        return self.first()

    def scalar_one(self):
        if not self._rows:
            raise RuntimeError("no rows")
        return self._rows[0]


class _FakeSession:
    """按「查询的主体实体」分派的假会话。"""

    executed: list = []

    def __init__(self, *, entities=None, tuples=None, count=0):
        self._entities = entities or {}
        self._tuples = tuples if tuples is not None else []
        self._count = count
        self.added: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        return None

    async def commit(self):
        return None

    async def execute(self, stmt):
        _FakeSession.executed.append(stmt)
        ents = [
            d.get("entity") for d in getattr(stmt, "column_descriptions", []) or []
        ]
        ents = [e for e in ents if e is not None]
        if not ents:                      # func.count() 一类
            return _Res([self._count])
        if len(ents) > 1:                 # join 出来的多元组
            return _Res(self._tuples)
        return _Res(self._entities.get(ents[0], []))


def _session(monkeypatch=None, **kw):
    """造一个假会话。session 是**显式入参**，不需要 monkeypatch 工厂。

    ★ 与客服那轮不同：本模块的 service 函数一律 `session` 显式传入
      （路由/工具/脚本各自开会话），所以这里不需要动 `async_session_factory`。
    """
    _FakeSession.executed = []
    return _FakeSession(**kw)


def _review(shop_id=SHOP, **kw):
    base = dict(
        id=REVIEW_ID, shop_id=shop_id, external_review_id="R1DEMO0001",
        order_id="ord-1", sku="SKU-KC-002", asin="B0DEMO0001",
        product_title="Demo Kettle", rating=2, title="Arrived late",
        body="Took 12 days longer than promised.", language="en",
        review_at="2026-01-05", verified_purchase=True, buyer_name="Alice",
        status="new", source="mock_seed",
    )
    base.update(kw)
    return CustomerReviewRecord(**base)


def _attribution(cause="logistics_delay", **kw):
    base = dict(
        id="attr-1", shop_id=SHOP, review_id=REVIEW_ID, order_id="ord-1",
        sku="SKU-KC-002", rating=2, primary_cause=cause, causes=[cause],
        confidence=0.9, evidence=[], method="rule", rule_version="v1",
        attributed_at="2026-01-05T00:00:00",
    )
    base.update(kw)
    return ReviewAttributionRecord(**base)


def _shipment(**kw):
    base = dict(
        id="ship-1", shop_id=SHOP, order_id="ord-1", carrier="UPS",
        tracking_no="1Z999", ship_status="delivered", shipped_at="2026-01-01",
        promised_at="2026-01-05", delivered_at="2026-01-12", transit_days=11,
        delay_days=7, last_event_at="2026-01-12", last_location="San Jose",
        last_event_text="Delivered", events=[], source="mock_seed",
    )
    base.update(kw)
    return ShipmentRecord(**base)


def _order(**kw):
    base = dict(
        id="ord-1", shop_id=SHOP, platform="amazon", marketplace="US",
        external_order_id="AMZN123456789", buyer_id="B1", buyer_name="Alice",
        order_status="delivered", fulfillment_channel="FBA",
        ship_country="US", ship_state="CA", ship_city="San Jose",
        currency="USD", order_total=39.9, purchase_at="2025-12-28",
        promised_at="2026-01-05", shipped_at="2026-01-01",
        delivered_at="2026-01-12", transit_days=11, delay_days=7,
        source="mock_seed", fetched_at="2026-01-12",
    )
    base.update(kw)
    return OrderRecord(**base)


def _rule(**kw):
    base = dict(
        id="rule-1", shop_id=SHOP, code="delay-7d", name="迟到 7 天以上",
        cause="logistics_delay", enabled=True, priority=10,
        conditions={"min_delay_days": 5},
        action={"type": "coupon", "amount": 8.0, "currency": "USD"},
        budget_cap=0, notes="",
    )
    base.update(kw)
    return CompensationRuleRecord(**base)


def _full_entities(review=None, attribution=None, rules=None, shipment=None,
                   disposition=None, shop_id=SHOP):
    """★ `rules` 显式传列表：`None` = 默认一条可用规则，`[]` = 一条都没有。

    为什么不用 `rule=None` 表达「没有规则」：那样 `rule if rule is not None
    else _rule()` 永远填回默认规则 ⇒ 「没有规则」这条分支**测不到**，
    而它正是「给不出草稿」的三种原因之一。
    """
    if rules is None:
        rules = [_rule()]
    return {
        CustomerReviewRecord: [review if review is not None else _review(shop_id)],
        ReviewAttributionRecord: [attribution if attribution is not None
                                  else _attribution()],
        # ★ 必须给 OrderRecord：`get_review_context` 只在**订单存在**时才查物流，
        #   少了它 ⇒ shipment=None ⇒ delay_days=None ⇒ 补偿规则里的
        #   `min_delay_days` 判不通过 ⇒ 草稿给不出来（假红，且看不出是夹具的锅）
        OrderRecord: [_order()],
        ShipmentRecord: [shipment if shipment is not None else _shipment()],
        CompensationRuleRecord: rules,
        ReviewDispositionRecord: [disposition] if disposition is not None else [],
    }


# ============================================================ ① 写入路径真的存在

def test_propose_persists_a_row_with_generated_draft(monkeypatch):
    """`propose_disposition` 必须**真的落一行**，且内容来自现算的草稿。"""
    sess = _session(monkeypatch, entities=_full_entities())

    out = _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))

    assert out["status"] == "proposed"
    assert out["created"] is True
    assert out["draft_filled"] is True, "没给内容字段时应该由草稿器现算填上"
    assert "coupon" in out["channels"], f"通道应含 coupon：{out['channels']}"
    assert out["compensation"]["amount"] == 8.0
    assert out["reply_draft_zh"] and out["reply_draft_en"], "双语草稿不能为空"
    assert len(sess.added) == 1, f"应该只落一行，实际 {len(sess.added)}"
    assert sess.added[0].id == f"disp-{REVIEW_ID}"


def test_propose_is_the_only_construction_site():
    """★ 形态判据：`ReviewDispositionRecord(...)` 的**真**构造点只在 service 里。

    ★ 0 行的根因就是「没有构造点」。这条红 ⇒ 要么写入路径被删了，
      要么有人绕过 `propose_disposition` 另开了一个写入口。

    ★★ 为什么走 AST 而不是 grep 字符串：本轮几处**注释与 docstring**里
      都写了 `ReviewDispositionRecord(...)`（「此前构造次数为 0」这类说明），
      按字符串数会把注释当成构造点 ⇒ 判据恒真（空跑）。本仓铁律：
      形态判据走 AST，判据的 needle 必须先在文件里实测存在。
    """
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "modules"
    hits = []
    for f in root.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "ReviewDispositionRecord"
            ):
                hits.append(f"{f.relative_to(root).as_posix()}:{node.lineno}")

    assert hits, (
        "全仓找不到 `ReviewDispositionRecord(...)` 的构造点 ⇒ 回到「0 行」的原状。"
        f"扫描目录 {root}"
    )
    # ★ 第 355 轮：service.py 已拆成包 ⇒ 构造点的相对路径是
    #   `trade/service/disposition.py`。判据放宽到**包前缀**——
    #   仍然只允许落在 trade 服务层内，不许外泄到别处。
    assert all(h.startswith("trade/service") for h in hits), (
        f"写入路径泄漏到 service 之外（同一写入两份实现）：{hits}"
    )
    assert len(hits) == 1, (
        f"构造点有 {len(hits)} 处（{hits}）—— 写入路径应当唯一，"
        f"否则「已发放不可覆盖」这类约束有一处没守住就没人知道。"
    )


# ============================================================ ② 状态机是硬约束

def test_issue_requires_approved(monkeypatch):
    """「未批准就发放」必须被拒绝 —— 否则 HITL 被架空。"""
    sess = _session(monkeypatch, entities=_full_entities())
    _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))

    # 重新构造会话，让「已存在的行」是 proposed 状态
    proposed = sess.added[0]
    sess2 = _session(monkeypatch, entities=_full_entities(disposition=proposed))
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.issue_disposition(sess2, SHOP, REVIEW_ID, actor="boss@x.com"))
    assert "不允许的状态转移" in str(e.value)
    assert proposed.status == "proposed", "被拒后状态不该变"


def test_happy_path_mints_coupon_on_issue(monkeypatch):
    """proposed → approved → issued，且只有发放这一步生成券码。"""
    sess = _session(monkeypatch, entities=_full_entities())
    _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))
    row = sess.added[0]
    # ★ 未 flush 的 ORM 行，带 default 的列读到的是 None（`""` 要等 INSERT）
    assert not row.coupon_code, f"草稿阶段不该有券码：{row.coupon_code!r}"

    sess2 = _session(monkeypatch, entities=_full_entities(disposition=row))
    approved = _run(svc.approve_disposition(sess2, SHOP, REVIEW_ID,
                                            approver="boss@x.com"))
    assert approved["status"] == "approved"
    assert approved["approved_by"] == "boss@x.com"

    sess3 = _session(monkeypatch, entities=_full_entities(disposition=row))
    issued = _run(svc.issue_disposition(sess3, SHOP, REVIEW_ID, actor="ops@x.com"))
    assert issued["status"] == "issued"
    assert issued["coupon_code"].startswith("CP-"), f"券码形态不对：{issued['coupon_code']}"
    assert issued["issued_at"], "发放时间必须落下来"


def test_issued_is_terminal(monkeypatch):
    """已发放是终态：批准 / 驳回 / 重新提议都不许再动它（券已发出，不能把历史改没）。"""
    row = ReviewDispositionRecord(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply", "coupon"], compensation={"type": "coupon", "amount": 8.0},
        coupon_code="CP-X1", status="issued", issued_at="2026-01-06T00:00:00",
    )
    for fn, kw in (
        (svc.approve_disposition, {"approver": "a@b.com"}),
        (svc.reject_disposition, {}),
        (svc.issue_disposition, {"actor": "a@b.com"}),
    ):
        sess = _session(monkeypatch, entities=_full_entities(disposition=row))
        with pytest.raises(svc.DispositionError):
            _run(fn(sess, SHOP, REVIEW_ID, **kw))
    assert row.status == "issued"


def test_propose_refuses_to_overwrite_approved(monkeypatch):
    """已批准/已发放的记录不许被草稿覆盖 —— 重跑归因不该改写既成事实。"""
    for status in ("approved", "issued"):
        row = ReviewDispositionRecord(
            id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
            channels=["reply"], compensation={}, status=status,
        )
        sess = _session(monkeypatch, entities=_full_entities(disposition=row))
        with pytest.raises(svc.DispositionError) as e:
            _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))
        assert status in str(e.value)
        assert row.status == status


def test_rejected_can_be_reproposed(monkeypatch):
    """驳回不应该是死路 —— 改完方案要能重新提议。"""
    row = ReviewDispositionRecord(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply"], compensation={}, status="rejected",
    )
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    out = _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))
    assert out["status"] == "proposed"
    assert out["created"] is False, "是在既有行上更新，不是新建"


def test_approve_requires_approver(monkeypatch):
    """处置是可追责动作 —— 「谁批的」不能为空。"""
    row = ReviewDispositionRecord(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply"], compensation={}, status="proposed",
    )
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.approve_disposition(sess, SHOP, REVIEW_ID, approver="   "))
    assert "批准人不能为空" in str(e.value)


# ============================================================ ③ 归属：跨店查不到

def test_other_shops_review_is_not_found(monkeypatch):
    """别家的评价 ⇒ `DispositionNotFound`（与「不存在」同一句，防枚举）。"""
    sess = _session(monkeypatch, entities={CustomerReviewRecord: []})
    with pytest.raises(svc.DispositionNotFound):
        _run(svc.propose_disposition(sess, OTHER, REVIEW_ID))


def test_list_query_is_scoped_by_shop(monkeypatch):
    """★ 形态判据：列表查询的语句必须带 `shop_id` 条件（不是查全表）。"""
    sess = _session(monkeypatch, entities=_full_entities(), tuples=[])
    _run(svc.list_dispositions(sess, SHOP))
    sql = " ".join(str(s) for s in _FakeSession.executed)
    assert "review_dispositions" in sql
    assert "shop_id" in sql, f"列表查询没有店铺作用域条件：{sql}"


def test_list_rejects_unknown_status(monkeypatch):
    """非法 status ⇒ 抛错，不静默退化成「看全部」。"""
    sess = _session(monkeypatch, entities=_full_entities())
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.list_dispositions(sess, SHOP, status="done"))
    assert "未知处置状态" in str(e.value)


# ============================================================ ④ 草稿：三种「给不出」必须分开

def test_draft_not_ready_without_attribution(monkeypatch):
    sess = _session(monkeypatch, entities=_full_entities(attribution=_attribution(
        cause="unknown")))
    out = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert out["ready"] is False
    assert "归因" in out["reason"], f"原因要指到归因：{out['reason']}"


def test_draft_not_ready_without_rule(monkeypatch):
    sess = _session(monkeypatch, entities=_full_entities(rules=[]))
    out = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert out["ready"] is False
    assert "规则" in out["reason"]


def test_draft_over_budget_is_reported(monkeypatch):
    """超预算要**报出来**，不许悄悄按上限赔。"""
    sess = _session(monkeypatch, entities=_full_entities(rules=[_rule(
        action={"type": "coupon", "amount": 50.0, "currency": "USD"},
        budget_cap=10.0)]))
    out = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert out["ready"] is False
    assert out["over_budget"] is True
    assert "上限" in out["reason"]


def test_draft_reply_is_deterministic(monkeypatch):
    """同样输入 ⇒ 同样草稿。LLM 现场写会每次不同，无法对账。"""
    sess = _session(monkeypatch, entities=_full_entities())
    a = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    sess2 = _session(monkeypatch, entities=_full_entities())
    b = _run(svc.build_disposition_draft(sess2, SHOP, REVIEW_ID))
    assert a["reply_draft_zh"] == b["reply_draft_zh"]
    assert a["reply_draft_en"] == b["reply_draft_en"]
    # 迟到天数必须是真从物流里取的（7 天），不是编的
    assert "7 天" in a["reply_draft_zh"], a["reply_draft_zh"]


def test_reply_does_not_invent_delay_when_unknown():
    """拿不到迟到天数 ⇒ 说「一段时间」，不许编数字。"""
    zh, en = svc._render_reply_drafts("logistics_delay", delay_days=None)
    assert "一段时间" in zh
    assert "7" not in zh
    assert "day(s)" not in en


# ============================================================ ⑤ 批量补生成（让表不再 0 行）

def test_backfill_creates_and_skips(monkeypatch):
    """有归因无处置 ⇒ 生成；已有处置 ⇒ 跳过（幂等）。"""
    reviews = [_review(), _review()]
    sess = _session(monkeypatch, entities={
        CustomerReviewRecord: reviews,
        ReviewDispositionRecord: [],
        CompensationRuleRecord: [_rule()],
        ReviewAttributionRecord: [_attribution()],
        ShipmentRecord: [_shipment()],
        OrderRecord: [_order()],   # ★ 少了它 ⇒ delay_days=None ⇒ 规则判不过 ⇒ 假红
    })
    out = _run(svc.backfill_dispositions(sess, SHOP))
    # ★ 假会话按实体返回**同一批行**，所以这里钉的是「真的落了行 + 真的计入了」
    assert out["scanned"] >= 1
    assert out["created"] >= 1, f"一个都没生成 ⇒ 表还是 0 行：{out}"
    assert len(sess.added) >= 1


# ============================================================ ⑥ 批准人只能服务端注入

def test_request_body_has_no_approver_field():
    """★ 请求体里**没有** `approver` / `actor` —— 否则「我是谁批的」可伪造。"""
    from modules.trade import router as trade_router

    fields = set(trade_router.ProposeDispositionBody.model_fields)
    assert "approver" not in fields
    assert "actor" not in fields
    assert "store_id" not in fields, "归属不许由请求体指定"
    assert "review_id" in fields


def test_approval_endpoints_inject_actor_from_server():
    """★ 形态判据：审批/发放端点的依赖里必须有 `require_acting_user`。"""
    import inspect

    from modules.trade import router as trade_router

    src = inspect.getsource(trade_router)
    for name in ("approve_disposition", "reject_disposition", "issue_disposition"):
        fn = getattr(trade_router, name)
        sig = inspect.signature(fn)
        assert "user" in sig.parameters, f"{name} 没有注入行动者依赖"
        assert "approver" not in sig.parameters and "actor" not in sig.parameters
    assert "require_acting_user" in src


def test_status_machine_covers_every_status():
    """状态机不留「没定义转移规则」的状态（那种会被 `_assert_transition` 静默放行）。"""
    assert set(svc.DISPOSITION_TRANSITIONS) == set(svc.DISPOSITION_STATUSES)


# ============================================================ ⑦ 反向注入：证明判据不是空跑

def test_judge_is_not_vacuous(monkeypatch):
    """把状态机放宽成「什么都能转」⇒ 上面那些断言必须**转红**。

    做法：临时把 `DISPOSITION_TRANSITIONS` 改成全通，再跑一次
    「未批准就发放」，此刻**不该**抛错 —— 说明原判据确实咬的是状态机，
    而不是别的什么东西。
    """
    row = ReviewDispositionRecord(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply", "coupon"], compensation={"type": "coupon", "amount": 8},
        status="proposed",
    )
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    # ★ 拆包后 `_assert_transition` 读的是 `disposition` 子模块的全局。
    monkeypatch.setattr(
        svc.disposition, "DISPOSITION_TRANSITIONS",
        {s: tuple(svc.DISPOSITION_STATUSES) for s in svc.DISPOSITION_STATUSES},
    )
    out = _run(svc.issue_disposition(sess, SHOP, REVIEW_ID, actor="x@y.com"))
    assert out["status"] == "issued", "放宽后应该能发 —— 否则说明原断言咬的不是状态机"


def _run(coro):
    """同步跑一个协程。本文件的用例都是**同步**函数 ⇒ 没有在跑的循环，`run` 安全。"""
    import asyncio

    return asyncio.run(coro)


# ============================================================ ⑧ 第 292 轮 P0：时态 + 券码

def test_draft_stage_must_not_claim_the_coupon_is_already_issued():
    """★ P0 时态门禁：处置还停在 `proposed`（待批准）时，回复草稿**不许**写成
    既成事实。

    原文 `We've issued a USD 8 coupon for you`（现在完成时 = 已经发了）会诱导
    客服直接发给买家；而这条处置随后可能被驳回 ⇒ 对买家的承诺落空。
    同一条口径中文也不能写「已为您…」。
    """
    zh, en = svc._render_reply_drafts(
        "logistics_delay", delay_days=7,
        compensation={"type": "coupon", "amount": 8.0, "currency": "USD"},
        coupon_code="CP-ABC123-260101",
        issued=False,
    )
    assert "We've issued" not in en, f"草稿阶段不该用完成时：{en}"
    assert "已为您发放" not in zh and "已为您申请" not in zh, f"中文同样不许写成既成事实：{zh}"
    # 反面：必须给出「正在办理」的口径（否则只是把内容删掉，等于没说补偿）
    assert "arranging" in en, en
    assert "正在为您申请" in zh, zh


def test_issued_stage_uses_completed_tense_and_carries_the_code():
    """发放之后才可以用完成时 —— 与上一条互为反向，证明 `issued` 真的在起作用。"""
    zh, en = svc._render_reply_drafts(
        "logistics_delay", delay_days=7,
        compensation={"type": "coupon", "amount": 8.0, "currency": "USD"},
        coupon_code="CP-ABC123-260101",
        issued=True,
    )
    assert "We've issued" in en and "code CP-ABC123-260101" in en, en
    assert "已为您发放" in zh and "券码 CP-ABC123-260101" in zh, zh


def test_issue_writes_the_coupon_code_into_the_reply_draft(monkeypatch):
    """★ P0：券码**必须进回复**。

    原实现 `_render_reply_drafts` 的 `coupon_code` 是个**死参数** —— 唯一调用点
    不传它，`issue_disposition` 生成券码后也不重渲染 ⇒ 券发了，而给买家的那段话
    里永远没有券码（买家拿着一个「已发券」的通知却兑换不了）。
    """
    sess = _session(monkeypatch, entities=_full_entities())
    _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))
    row = sess.added[0]
    assert not row.coupon_code, "草稿阶段不该有券码"
    # 草稿阶段正文里也不该出现券码（提前把券号许出去）
    assert "CP-" not in (row.reply_draft_en or ""), row.reply_draft_en

    sess2 = _session(monkeypatch, entities=_full_entities(disposition=row))
    _run(svc.approve_disposition(sess2, SHOP, REVIEW_ID, approver="boss@x.com"))

    sess3 = _session(monkeypatch, entities=_full_entities(disposition=row))
    issued = _run(svc.issue_disposition(sess3, SHOP, REVIEW_ID, actor="ops@x.com"))

    code = issued["coupon_code"]
    assert code.startswith("CP-"), code
    assert code in issued["reply_draft_en"], (
        f"发放后券码没写进英文回复：{issued['reply_draft_en']}"
    )
    assert code in issued["reply_draft_zh"], (
        f"发放后券码没写进中文回复：{issued['reply_draft_zh']}"
    )
    assert "We've issued" in issued["reply_draft_en"], issued["reply_draft_en"]
    # ★ 与 `row` 是同一个对象 ⇒ 断言的是**落库那一行**，不是返回值里的副本
    assert row.reply_draft_en == issued["reply_draft_en"]


def test_issue_never_clobbers_a_human_edited_draft(monkeypatch):
    """人工改过措辞的草稿，发放时**一行都不许被覆盖** —— 但要记账。

    ★ 为什么宁可让券码缺席：券码是不可逆的既成事实，措辞是客服按买家语境写的。
      两者冲突时不能悄悄二选一，必须把「没重写」这件事写进 `notes` 让人看见。
    """
    row = ReviewDispositionRecord(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply", "coupon"],
        compensation={"type": "coupon", "amount": 8.0, "currency": "USD"},
        reply_draft_en="Hi Alice, our team wrote this for you.",
        reply_draft_zh="客服手工写的措辞。",
        status="approved",
    )
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    issued = _run(svc.issue_disposition(sess, SHOP, REVIEW_ID, actor="ops@x.com"))

    assert issued["reply_draft_en"] == "Hi Alice, our team wrote this for you."
    assert issued["reply_draft_zh"] == "客服手工写的措辞。"
    assert issued["coupon_code"].startswith("CP-"), "券码本身还是要生成"
    assert "未自动重写" in (issued["notes"] or ""), (
        f"没重写就必须记账，否则界面上看不出来：{issued['notes']!r}"
    )


def test_reply_drafts_are_deterministic_under_the_issued_flag():
    """同一输入 ⇒ 同一输出（`issued` 也当输入看待），否则发放那一步无法对账。"""
    kw = dict(delay_days=7,
              compensation={"type": "coupon", "amount": 8.0, "currency": "USD"},
              coupon_code="CP-X-1")
    assert svc._render_reply_drafts("logistics_delay", issued=False, **kw) == \
        svc._render_reply_drafts("logistics_delay", issued=False, **kw)
    assert svc._render_reply_drafts("logistics_delay", issued=True, **kw) == \
        svc._render_reply_drafts("logistics_delay", issued=True, **kw)
    assert svc._render_reply_drafts("logistics_delay", issued=False, **kw) != \
        svc._render_reply_drafts("logistics_delay", issued=True, **kw)


# ============================================================ ⑨ 第 304 轮 P0·A：`issued` ≠ 平台上已执行
#
# ★ 这一节钉的是「语义欺诈」的正面修法：`issue_disposition` **零出站调用**
#   （本模块没有任何 HTTP 客户端，平台适配层清一色是只读的 `fetch_*`），
#   所以 `issued` 只等于「本地已核准」。此前库里没有任何字段能回答
#   「平台上做没做」⇒ 界面的「已发放 / 退回货款」是字面为真、暗示为假。
#   修法不是去接平台 API（那是 B/C 档），而是**先把两个语义在数据层拆开**：
#   `issued`（已核准）→ `executed`（已执行，且有回执）。

def _disp(status="issued", **kw):
    """造一条处置行。**五列显式给空串** —— 见下方注释。"""
    base = dict(
        id=f"disp-{REVIEW_ID}", shop_id=SHOP, review_id=REVIEW_ID,
        channels=["reply", "coupon"],
        compensation={"type": "coupon", "amount": 8.0, "currency": "USD"},
        coupon_code="CP-DEMO01-260101", issued_at="2026-01-06T00:00:00",
        status=status,
        # ★★ 为什么必须显式写：ORM 的 `default=""` 只在 **INSERT** 时生效，
        #    测试里手工构造的对象读到的是 `None`。不显式给 ⇒ 「空串契约」
        #    根本判不出来（None 与 "" 都是 falsy，判据会静默变松）。
        execution_mode="", platform_ref="", executed_by="", executed_at="",
        receipt_note="",
    )
    base.update(kw)
    return ReviewDispositionRecord(**base)


def test_issue_only_approves_locally_it_does_not_execute_on_the_platform(monkeypatch):
    """★ 发放 = 本地核准，**不等于**平台上已经执行。

    这条是本轮的核心判据：若 `issue_disposition` 顺手把状态推到 `executed`，
    界面上的「已执行」就又是**一次无据可查的宣称** —— 与本轮要治的病一模一样。
    """
    row = _disp("approved")
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    out = _run(svc.issue_disposition(sess, SHOP, REVIEW_ID, actor="ops@x.com"))

    assert out["status"] == "issued", out["status"]
    assert out["issued_at"], "本地核准要留时间戳"
    # ★ 五列必须**全空**：空 = 还没登记回执 = 平台上还没执行
    assert out["executed_at"] == "", f"发放 ≠ 平台上已执行：{out['executed_at']!r}"
    assert out["execution_mode"] == "", out["execution_mode"]
    assert out["platform_ref"] == "", out["platform_ref"]
    assert out["executed_by"] == "", out["executed_by"]


def test_receipt_moves_issued_to_executed_and_stamps_the_registrant(monkeypatch):
    """登记回执 ⇒ 终态，且「谁登记的」落在服务端注入的字段上。"""
    row = _disp("issued")
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    out = _run(svc.record_execution_receipt(
        sess, SHOP, REVIEW_ID, platform_ref="REFUND-9911",
        executed_by="ops@x.com", receipt_note="在卖家后台做了部分退款"))

    assert out["status"] == "executed", out["status"]
    assert out["execution_mode"] == "manual", out["execution_mode"]
    assert out["platform_ref"] == "REFUND-9911"
    assert out["executed_by"] == "ops@x.com"
    assert out["executed_at"], "登记回执必须留时间"
    assert "部分退款" in (out["receipt_note"] or "")
    # ★ 回执**不改写**「核准」那一段：两个语义各记各的
    assert out["issued_at"] == "2026-01-06T00:00:00", out["issued_at"]
    assert out["coupon_code"] == "CP-DEMO01-260101"


def test_receipt_refuses_to_fake_a_system_execution(monkeypatch):
    """★ 值域只有 `manual`：填 `mode="api"` 冒充「系统已调用平台」必须被拒。

    今天本模块没有任何出站 HTTP 客户端，系统**没有能力**自动执行。开放 `api`
    就等于允许「填个 mode 冒充系统已调用平台」—— 那是把回执做成另一种自我声明。
    """
    row = _disp("issued")
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.record_execution_receipt(
            sess, SHOP, REVIEW_ID, execution_mode="api", executed_by="ops@x.com"))
    assert "manual" in str(e.value), str(e.value)
    assert row.status == "issued", "被拒之后状态不许动"


def test_receipt_requires_a_named_registrant(monkeypatch):
    """「平台上已经执行」是可追责断言 ⇒ 登记人不能为空（与 approver / actor 同口径）。"""
    row = _disp("issued")
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.record_execution_receipt(sess, SHOP, REVIEW_ID, executed_by="   "))
    assert "登记人" in str(e.value), str(e.value)


def test_receipt_requires_issued_first(monkeypatch):
    """没核准就登记回执 ⇒ 拒绝（`proposed` / `approved` / `rejected` 都不是 issued）。"""
    for st in ("proposed", "approved", "rejected"):
        row = _disp(st)
        sess = _session(monkeypatch, entities=_full_entities(disposition=row))
        with pytest.raises(svc.DispositionError):
            _run(svc.record_execution_receipt(
                sess, SHOP, REVIEW_ID, executed_by="ops@x.com"))


def test_executed_is_terminal_and_nothing_can_rewrite_it(monkeypatch):
    """★ 终态之后：不能批准、不能驳回、不能重复登记，也不能被草稿覆盖。

    ★ 为什么不能退回：券码已经生成并写进了给买家的回复，把历史改没只会让
      台账与对话对不上账（要调整只能另开一笔）。
    """
    row = _disp("executed", executed_at="2026-01-07T00:00:00",
                executed_by="ops@x.com", execution_mode="manual")

    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError):
        _run(svc.approve_disposition(sess, SHOP, REVIEW_ID, approver="boss@x.com"))

    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError):
        _run(svc.reject_disposition(sess, SHOP, REVIEW_ID, notes="想反悔"))

    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError):
        _run(svc.record_execution_receipt(sess, SHOP, REVIEW_ID, executed_by="ops@x.com"))

    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    with pytest.raises(svc.DispositionError) as e:
        _run(svc.propose_disposition(sess, SHOP, REVIEW_ID))
    assert "不允许被草稿覆盖" in str(e.value), str(e.value)


def test_issued_has_exactly_one_exit_and_it_is_executed():
    """状态机形态：`issued` 的唯一出口是 `executed`，`executed` 是终态。"""
    assert "executed" in svc.DISPOSITION_STATUSES
    assert svc.DISPOSITION_TRANSITIONS["issued"] == ("executed",), (
        "issued 只能走向「登记回执」—— 退回 proposed/approved 会让已发出的券码对不上账")
    assert svc.DISPOSITION_TRANSITIONS["executed"] == ()
    assert svc.DISPOSITION_EXECUTION_MODES == ("manual",), (
        "系统没有出站客户端之前，值域不许出现 api")


def test_receipt_body_has_no_registrant_field():
    """★ 请求体里**没有** `executed_by`：让客户端自报「我执行完了」= 审计字段可伪造。"""
    from modules.trade import router as trade_router

    fields = set(trade_router.ExecutionReceiptBody.model_fields)
    assert "executed_by" not in fields
    assert "executed_at" not in fields
    assert "status" not in fields
    assert "store_id" not in fields, "归属不许由请求体指定"
    assert "platform_ref" in fields


def test_receipt_endpoint_injects_the_registrant_from_the_server():
    """形态判据：端点必须挂 `require_acting_user`，且把 `_actor_name(user)` 传下去。"""
    import inspect

    from modules.trade import router as trade_router

    fn = trade_router.record_execution_receipt
    sig = inspect.signature(fn)
    assert "user" in sig.parameters, "登记回执必须注入行动者依赖"
    assert "executed_by" not in sig.parameters
    src = inspect.getsource(trade_router)
    assert "executed_by=_actor_name(user)" in src
    assert "require_acting_user" in src


def test_receipt_judges_are_not_vacuous(monkeypatch):
    """★ 反向注入：放宽状态机 / 放宽值域 ⇒ 上面那些断言必须**转红**。

    两条分别证明：
      ① 「未核准不能登记」咬的是状态机，不是别的什么；
      ② 「mode=api 被拒」咬的是值域，不是字符串比较。
    """
    # ① 状态机放宽成全通 ⇒ approved 也能登记
    row = _disp("approved")
    sess = _session(monkeypatch, entities=_full_entities(disposition=row))
    # ★ 拆包后 `_assert_transition` 读的是 `disposition` 子模块的全局。
    monkeypatch.setattr(
        svc.disposition, "DISPOSITION_TRANSITIONS",
        {s: tuple(svc.DISPOSITION_STATUSES) for s in svc.DISPOSITION_STATUSES},
    )
    out = _run(svc.record_execution_receipt(sess, SHOP, REVIEW_ID, executed_by="ops@x.com"))
    assert out["status"] == "executed", "放宽后应该能登记 —— 否则原断言咬的不是状态机"

    # ② 值域放宽出 api ⇒ mode="api" 不再被拒
    row2 = _disp("issued")
    sess2 = _session(monkeypatch, entities=_full_entities(disposition=row2))
    monkeypatch.setattr(svc.disposition, "DISPOSITION_EXECUTION_MODES", ("manual", "api"))
    out2 = _run(svc.record_execution_receipt(
        sess2, SHOP, REVIEW_ID, execution_mode="api", executed_by="ops@x.com"))
    assert out2["execution_mode"] == "api", "放宽后应该能填 api —— 否则原断言咬的不是值域"



# ============================================================ ⑩ 第 304 轮补修：两种「没规则」必须分开报

def test_draft_no_rule_reports_no_rule_code(monkeypatch):
    """该 cause **一条规则都没有** ⇒ `reason_code=no_rule`（这一类的修法是新增规则）。"""
    sess = _session(monkeypatch, entities=_full_entities(rules=[]))
    out = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert out["ready"] is False
    assert out["reason_code"] == "no_rule", out
    assert "还没有任何补偿规则" in out["reason"], out["reason"]


def test_draft_rule_conditions_unmet_is_not_reported_as_missing_rule(monkeypatch):
    """★ 本轮错案的正身：**有启用规则**、但这条差评不满足它的条件。

    旧口径把它与「压根没规则」合并成同一句「没有针对「X」的启用规则」——
    真库实测 `logistics_delay` 明明有一条启用规则（`logistics-delay-minor`，
    条件 `min_delay_days=3`）。报错了 ⇒ 人跑去「再配一条同名规则」，
    而那条新规则**永远不会命中**（同因同条件，还是过不了）。
    """
    sess = _session(monkeypatch, entities=_full_entities(
        rules=[_rule(conditions={"min_delay_days": 30})]))
    out = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert out["ready"] is False
    assert out["reason_code"] == "rule_conditions_unmet", out
    assert "没有针对" not in out["reason"], "又退回旧口径（对「有规则但条件不符」是假陈述）"
    assert "不是「没配规则」" in out["reason"], out["reason"]


def test_draft_other_failure_codes_are_reported(monkeypatch):
    """另外两种「给不出」也要带码 —— 前端才不必从文案里正则猜形状。"""
    sess = _session(monkeypatch, entities=_full_entities(
        attribution=_attribution(cause="unknown")))
    got = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert got["reason_code"] == "no_attribution", got

    sess = _session(monkeypatch, entities=_full_entities(rules=[_rule(
        action={"type": "coupon", "amount": 50.0, "currency": "USD"}, budget_cap=10.0)]))
    got = _run(svc.build_disposition_draft(sess, SHOP, REVIEW_ID))
    assert got["reason_code"] == "over_budget", got


def test_candidate_rule_lookup_has_a_single_source():
    """候选集只此一份实现：`match_compensation_rule` 必须**复用**它。

    否则「诊断」（这条为什么给不出）与「匹配」各查一遍库 ⇒ 两边过滤条件一旦漂移，
    「有规则但条件不符」就会被诊断分支误判成「没规则」—— 正是本轮的错案形态。
    """
    import inspect
    src = inspect.getsource(svc.match_compensation_rule)
    assert "list_enabled_rules_for_cause" in src, (
        "match_compensation_rule 又自己写了一份 where 条件 ⇒ 候选集有了第二份实现"
    )
    # 反向自检：把候选集函数换掉，上面的断言必须失配（证明不是恒真）
    mutated = src.replace("list_enabled_rules_for_cause", "_inline_query")
    assert "list_enabled_rules_for_cause" not in mutated, "自检空跑"


# ============================================================ ⑪ 第 304 轮后半：补偿规则 CRUD + 人工补归因
#
# ★ 背景（真库实测）：`compensation_rules` 有表有种子有匹配逻辑，却**没有端点也没有界面**，
#   失败提示让人「到补偿规则里配一条」⇒ 负指令（指向不存在的面板）。
#   另：风险识别命中 12 条、处置台账只有 5 条，真因是 12 条里 8 条 `primary_cause=unknown`，
#   处置链只扫有归因的那批 ⇒ 补「人工归因」入口（method=manual，自动同步不得冲掉）。

def test_rule_shape_rejects_unknown_cause():
    """unknown 不是可配的 cause：判不出成因的差评本来就不走补偿链。"""
    import pytest as _pytest
    with _pytest.raises(svc.RuleError):
        svc._validate_rule_shape(cause="unknown", conditions={}, action={},
                                 priority=1, budget_cap=0)


def test_rule_shape_rejects_unknown_condition_key():
    """未知条件键要**显式报错**：`_conditions_match` 只认三个键，
    配了别的键会静默失效（永不判到）—— 比报错更糟。"""
    import pytest as _pytest
    with _pytest.raises(svc.RuleError):
        svc._validate_rule_shape(cause="packaging_failure", conditions={"min_stars": 2},
                                 action={}, priority=1, budget_cap=0)


def test_rule_shape_rejects_negative_amount_and_bad_action():
    import pytest as _pytest
    with _pytest.raises(svc.RuleError):
        svc._validate_rule_shape(cause="price_value", conditions={},
                                 action={"type": "coupon", "amount": -1},
                                 priority=1, budget_cap=0)
    with _pytest.raises(svc.RuleError):
        svc._validate_rule_shape(cause="price_value", conditions={},
                                 action={"type": "refund_and_more"}, priority=1, budget_cap=0)


def test_create_rule_conflicts_on_same_code():
    """同店同 code ⇒ `RuleConflict`（不静默覆盖）。"""
    import pytest as _pytest
    sess = _session(entities={CompensationRuleRecord: [_rule()]})
    coro = svc.create_compensation_rule(
        sess, SHOP, code="delay-7d", name="再来一条", cause="logistics_delay",
        action={"type": "coupon", "amount": 9})
    with _pytest.raises(svc.RuleConflict):
        _run(coro)


def test_create_rule_persists_a_row(monkeypatch):
    """create 落一行且 id 与 seed 同构（`crule-<shop>-<code>`）。"""
    sess = _session(entities={CompensationRuleRecord: []})  # 无同 code 行
    out = _run(svc.create_compensation_rule(
        sess, SHOP, code="price-basic", name="价格基础", cause="price_value",
        priority=7, conditions={"max_rating": 3},
        action={"type": "coupon", "amount": 5.0}, budget_cap=20.0))
    assert out["id"] == f"crule-{SHOP}-price-basic"
    assert out["cause"] == "price_value"
    assert out["enabled"] is True
    assert sess.added and isinstance(sess.added[0], CompensationRuleRecord)


def test_update_rule_only_touches_given_fields():
    """部分更新：只改传进来的字段（enabled），name 不动。"""
    sess = _session(entities={CompensationRuleRecord: [_rule()]})
    out = _run(svc.update_compensation_rule(sess, SHOP, "rule-1", enabled=False))
    assert out["enabled"] is False
    assert out["name"] == "迟到 7 天以上", "没传 name 就不该动 name"


def test_set_attribution_requires_concrete_cause():
    """手工归因**不接受** unknown：那是自动判定判不出来的结果，不是可选项。"""
    import pytest as _pytest
    sess = _session(entities=_full_entities())
    with _pytest.raises(svc.AttributionError):
        _run(svc.set_review_attribution(sess, SHOP, REVIEW_ID, primary_cause="unknown"))


def test_set_attribution_marks_manual_and_full_confidence():
    """补标落 `method="manual"`、`confidence=1.0`（人工不表达「把握多大」）。"""
    sess = _session(entities=_full_entities(attribution=_attribution(cause="unknown")))
    out = _run(svc.set_review_attribution(
        sess, SHOP, REVIEW_ID, primary_cause="packaging_failure"))
    assert out["attribution"]["method"] == "manual"
    assert out["attribution"]["primary_cause"] == "packaging_failure"
    assert out["attribution"]["confidence"] == 1.0


def test_set_attribution_rejects_out_of_range_cause():
    import pytest as _pytest
    sess = _session(entities=_full_entities())
    with _pytest.raises(svc.AttributionError):
        _run(svc.set_review_attribution(sess, SHOP, REVIEW_ID, primary_cause="not_a_cause"))


def test_rule_crud_judges_are_not_vacuous():
    """反向自检：候选集函数改名 ⇒ 既有「唯一真源」判据必须失配（证明非恒真）。"""
    import inspect
    src = inspect.getsource(svc.match_compensation_rule)
    assert "list_enabled_rules_for_cause" in src
    mutated = src.replace("list_enabled_rules_for_cause", "_renamed")
    assert "list_enabled_rules_for_cause" not in mutated, "自检空跑"
