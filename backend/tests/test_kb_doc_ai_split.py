"""
第 288 轮：`knowledge_docs` 的出口 —— 文档 → 话术草稿 → 人工发布 → 进检索

守的四件事：
  ① 拆出来的条目**恒为草稿**（LLM 说 active 也不认）—— 人工确认前不进检索；
  ② 发布**只转 draft**，不复活 archived；「不存在」与「不属于你」同一响应；
  ③ 文档没有正文 / LLM 不可用时**明确降级**，绝不编造条目；
  ④ 那条「RAG 切片检索的输入源」的假注释已经改掉（它曾把本轮引向一条不存在的路）。

★ 假会话不执行 where：它返回预先放好的 `visible` 行。
  「作用域与条件对不对」改用**语句文本形态判据**断言 —— 重抄 SQL 语义只会
  把实现再写一遍，改了实现两边一起绿（假绿）。
"""

import pytest

from modules.knowledge_base import ai_split_faq as asp
from modules.knowledge_base import service as svc
from modules.knowledge_base.db_model import (
    KnowledgeDocRecord,
    KnowledgeFaqRecord,
)

SHOP = "store_test"
KB = "kb-default-store_test"


# ====== 假会话 ======

class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """只支持本文件用到的两条查询形态：实体 select 与单列 select。"""

    def __init__(self, visible=None):
        self.visible = list(visible or [])
        self.added = []
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        self.executed.append(str(stmt))
        cd = stmt.column_descriptions
        # ★ 先判「取的是哪一列」：`select(KnowledgeFaqRecord.question)` 的
        #   column_descriptions 也带 `entity`（它是实体属性），只看 entity
        #   会把单列查询当成实体查询 ⇒ `row[0]` 对 ORM 对象取下标 ⇒ TypeError。
        name = (cd[0].get("name") if cd else None)
        if name == "question":
            return _Result([(getattr(f, "question"),) for f in self.visible])
        return _Result(list(self.visible))

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        return None

    async def refresh(self, row):
        return None


def _session(monkeypatch, visible=None):
    sess = _FakeSession(visible)
    monkeypatch.setattr(svc, "async_session_factory", lambda: sess)
    return sess


def _faq(**kw):
    base = dict(
        id=kw.pop("id", "faq-1"), shop_id=SHOP, kb_id=KB,
        question="默认问题", answer="默认答案", category="other",
        keywords=[], priority="medium", status="draft", usage_count=0,
        created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
    )
    base.update(kw)
    return KnowledgeFaqRecord(**base)


def _doc(**kw):
    base = dict(
        id="kdoc-1", shop_id=SHOP, kb_id=KB,
        filename="退货政策.md", file_type="md", size=100,
        uploaded_at="2026-01-01T00:00:00", description="", content="正文",
    )
    base.update(kw)
    return KnowledgeDocRecord(**base)


def _run(coro):
    import asyncio
    return asyncio.get_event_loop().run_until_complete(coro)


# ====== ① 拆出来的条目恒为草稿 ======

@pytest.mark.parametrize("llm_status", ["active", "ACTIVE", "archived", "published", ""])
def test_status_is_always_draft_even_if_llm_says_otherwise(llm_status):
    """★ 核心判据：LLM 给的 status 一律不采纳，落库必是 draft。

    理由不是流程洁癖：LLM 会把文档里的内部口径（成本价、供应商、
    只对某站点生效的承诺）写进 answer。草稿不进检索（`load_faq_items`
    只查 active）⇒ 人工确认前这些内容**不可能**被发给买家。
    """
    out = asp.normalize_llm_faqs(
        [{"question": "多久发货？", "answer": "48 小时内。", "status": llm_status}],
        _doc(),
    )
    assert len(out) == 1
    assert out[0]["status"] == "draft", (
        f"LLM 返回 status={llm_status!r} 时被采纳了 ⇒ 拆出的条目可能绕过人工确认直接进检索"
    )


def test_every_normalized_item_is_draft():
    """覆盖式：不管输入长什么样，输出里**不允许**出现非 draft 的条目"""
    data = [
        {"question": "q1", "answer": "a1"},
        {"question": "q2", "answer": "a2", "status": "active"},
        {"question": "q3", "answer": "a3", "status": None},
    ]
    out = asp.normalize_llm_faqs(data, _doc())
    assert out and all(it["status"] == "draft" for it in out)


def test_dropped_when_question_or_answer_missing():
    """缺一半的条目直接丢，不补空壳（空条目在列表里是一行看不懂的空白）"""
    out = asp.normalize_llm_faqs(
        [
            {"question": "只有问题"},
            {"answer": "只有答案"},
            {"question": "  ", "answer": "空白问题"},
            {"question": "完整的", "answer": "答案"},
        ],
        _doc(),
    )
    assert len(out) == 1
    assert out[0]["question"] == "完整的"


def test_kb_id_comes_from_doc_not_from_llm():
    """归属由文档决定，LLM 无权改（否则条目会落到别的库里，在任何视图都不可见）"""
    out = asp.normalize_llm_faqs(
        [{"question": "q", "answer": "a", "kb_id": "kb-别人的库"}],
        _doc(kb_id=KB),
    )
    assert out[0]["kb_id"] == KB


# ====== ② 分类口径 ======

def test_category_is_normalized_to_canonical_codes():
    cases = [
        ("shipping", "shipping"), ("SHIPPING", "shipping"),
        ("物流", "shipping"), ("配送", "shipping"),
        ("退货", "return"), ("退款", "return"),
        ("质保", "aftersale"), ("保修", "aftersale"),
        ("尺码", "product"),
        ("发票", "payment"),
        ("不存在的分类", "other"), ("", "other"), (None, "other"),
    ]
    for raw, expect in cases:
        assert asp.normalize_category(raw) == expect, f"{raw!r} → {asp.normalize_category(raw)!r}"


def test_category_codes_match_customer_service():
    """★ 防漂移：`knowledge_faqs.category` 的取值集合在本模块与客服侧各写了一份
    （两边都是 PLUGIN，不能互相 import，见 `ai_split_faq.FAQ_CATEGORY_CODES` 注释）。

    ⇒ 由本用例断言两边**恒等**。改任一侧都必须同步另一侧，否则会出现
    「拆出来的分类客服侧不认识」这种两边都绿、中间断链的缺陷。
    """
    from modules.customer_service.faq_source import CATEGORY_LABELS

    assert set(asp.FAQ_CATEGORY_CODES) == set(CATEGORY_LABELS), (
        "分类口径漂移：ai_split_faq 与 faq_source 各写了一份，必须同步。\n"
        f"  仅 ai_split_faq 有：{set(asp.FAQ_CATEGORY_CODES) - set(CATEGORY_LABELS)}\n"
        f"  仅 faq_source 有：{set(CATEGORY_LABELS) - set(asp.FAQ_CATEGORY_CODES)}"
    )


def test_priority_is_normalized():
    assert asp.normalize_priority("high") == "high"
    assert asp.normalize_priority("HIGH") == "high"
    assert asp.normalize_priority("瞎写的") == "medium"
    assert asp.normalize_priority(None) == "medium"


# ====== ③ 降级方向：不编造 ======

@pytest.mark.asyncio
async def test_no_content_degrades_with_reason():
    res = await asp.split_faqs_from_doc(_doc(content=""))
    assert res["degraded"] is True
    assert res["faqs"] == []
    assert "正文" in res["reason"], f"原因要能指导用户下一步：{res['reason']!r}"


@pytest.mark.asyncio
async def test_llm_unavailable_degrades(monkeypatch):
    monkeypatch.setattr(asp, "LLM_AVAILABLE", False)
    res = await asp.split_faqs_from_doc(_doc())
    assert res["degraded"] is True and res["faqs"] == []
    assert "AI" in res["reason"]


@pytest.mark.asyncio
async def test_llm_returns_nothing_degrades(monkeypatch):
    """LLM 通了但什么都没提取到 ⇒ 同样降级，不返回空数组假装成功"""
    class _LLM:
        async def structured_chat(self, **kw):
            return []

    monkeypatch.setattr(asp, "LLM_AVAILABLE", True)
    monkeypatch.setattr(asp, "get_llm", lambda: _LLM())
    res = await asp.split_faqs_from_doc(_doc())
    assert res["degraded"] is True and res["faqs"] == []
    assert res["reason"]


def test_parse_failed_is_empty_not_guess(monkeypatch):
    """结构化解析失败 ⇒ 空结果（判定走唯一真源，不自写 `"raw_text" in data`）"""
    monkeypatch.setattr(asp, "is_llm_parse_failed", lambda d: True)
    assert asp.normalize_llm_faqs({"raw_text": "{不是 JSON"}, _doc()) == []


# ====== ④ 落库：草稿 + 去重 ======

def test_create_faq_drafts_forces_draft_and_dedupes(monkeypatch):
    """两条同 question（一条撞库里已有、一条撞本批内）⇒ 各记一次 duplicated"""
    existing = _faq(id="faq-old", question="退款多久能到账？", status="active")
    sess = _session(monkeypatch, visible=[existing])

    out = _run(svc.create_faq_drafts([
        {"kb_id": KB, "question": "退款多久能到账？", "answer": "3 个工作日", "status": "active"},
        {"kb_id": KB, "question": "质保多久？", "answer": "整机 12 个月"},
        {"kb_id": KB, "question": "质保多久？", "answer": "整机 12 个月（本批内重复）"},
        {"kb_id": KB, "question": "缺答案的", "answer": "  "},
    ], shop_id=SHOP))

    assert out["added"] == 1, out
    assert out["duplicated"] == 2, out
    assert out["dropped"] == 1, out
    # ★ 落库的行必须是 draft（前端传了 active 也不认）
    assert sess.added and all(r.status == "draft" for r in sess.added)


def test_create_faq_drafts_query_is_tenant_scoped(monkeypatch):
    """★ 形态判据：查重必须带店铺作用域。

    不写这条时，「去掉 scoped」这个改动会让全仓用例照旧全绿 —— 而后果是
    A 店铺的拆词会撞上 B 店铺的同名话术，凭空少拆一批（静默）。
    """
    sess = _session(monkeypatch, visible=[])
    _run(svc.create_faq_drafts(
        [{"kb_id": KB, "question": "q", "answer": "a"}], shop_id=SHOP))
    assert sess.executed, "没发出任何查询 ⇒ 判据空跑"
    joined = " ".join(sess.executed)
    assert "knowledge_faqs" in joined
    # ★ 店铺值是绑定参数（`:shop_id_1`），**不在**语句文本里 ⇒ 只能判
    #   「作用域条件这一列被写进了 WHERE」。去掉 `scoped` 时这串就消失了。
    assert "knowledge_faqs.shop_id =" in joined, (
        f"查重查询丢了店铺作用域（那会撞上别家店铺的同名话术）：{joined}"
    )


# ====== ⑤ 发布：只转草稿 ======

def test_publish_only_drafts_and_reports_each_class(monkeypatch):
    """draft → active；archived **不复活**；不存在的进 not_found（与越权同响应）"""
    draft = _faq(id="faq-d", question="草稿问题", status="draft")
    archived = _faq(id="faq-a", question="归档问题", status="archived")
    active = _faq(id="faq-x", question="已发布", status="active")
    sess = _session(monkeypatch, visible=[draft, archived, active])

    out = _run(svc.publish_draft_faqs(["faq-d", "faq-a", "faq-x", "faq-ghost"], shop_id=SHOP))

    assert out["published"] == 1 and out["ids"] == ["faq-d"]
    assert draft.status == "active"
    assert archived.status == "archived", "归档被'发布'顺手复活了 —— 那是另一个意图"
    assert [s["id"] for s in out["skipped"]] == ["faq-a", "faq-x"]
    # ★ 「不存在」与「不属于本租户」都落在这里，不区分
    assert out["not_found"] == ["faq-ghost"]


def test_publish_query_is_tenant_scoped(monkeypatch):
    sess = _session(monkeypatch, visible=[])
    _run(svc.publish_draft_faqs(["faq-1"], shop_id=SHOP))
    joined = " ".join(sess.executed)
    assert "knowledge_faqs" in joined, f"不是查 knowledge_faqs？{joined}"
    assert "knowledge_faqs.shop_id =" in joined, (
        f"发布查询丢了店铺作用域 —— 那就能发布别人的话术：{joined}"
    )


def test_publish_empty_ids_is_noop(monkeypatch):
    sess = _session(monkeypatch, visible=[])
    out = _run(svc.publish_draft_faqs([], shop_id=SHOP))
    assert out["published"] == 0 and sess.executed == []


# ====== ⑥ 假注释已修 ======

def test_db_model_no_longer_claims_rag_chunking():
    """★ 形态判据 + 反向注入：`knowledge_docs.content` 曾注释为
    「智能客服 RAG 切片检索的输入源」，但全仓没有任何代码把它送进检索 ——
    第 287 轮我就是被它引着去找「RAG 那一路」，结果那一路根本不存在。

    判据取「只有改对才可能出现」的字符串（新注释里的关键词），
    而不是「旧串不在了」（删掉整段注释也会让旧串消失 ⇒ 恒真）。
    """
    from pathlib import Path

    src = Path(__file__).resolve().parent.parent / "modules" / "knowledge_base" / "db_model.py"
    text = src.read_text(encoding="utf-8")
    assert "AI 拆成话术的输入源" in text, "新注释没落盘（或措辞改了 —— 同步改本判据）"
    assert "RAG 切片检索的输入源" not in text, "假承诺又回来了"
    assert "原料" in text and "语料" in text


# ====== ⑦ 端点已挂 ======

def test_two_new_endpoints_are_registered():
    from modules.knowledge_base.router import router

    paths = {}
    for r in router.routes:
        paths.setdefault(getattr(r, "path", ""), set()).update(getattr(r, "methods", set()))

    assert "/api/v1/knowledge-base/faqs/publish" in paths
    assert "POST" in paths["/api/v1/knowledge-base/faqs/publish"]
    assert "/api/v1/knowledge-base/docs/{doc_id}/ai-split-faq" in paths
    assert "POST" in paths["/api/v1/knowledge-base/docs/{doc_id}/ai-split-faq"]


# ====== ⑧ 反向注入：证明上面的判据不是空跑 ======

def test_judge_is_not_vacuous():
    """把「恒为草稿」这条改回「信任 LLM 的 status」—— 上面的用例必须变红。

    ★ 若这条也跟着绿了，说明 ① 那组判据根本没在测它以为自己在测的东西。
    """
    source = asp.normalize_llm_faqs.__doc__ or ""
    assert "draft" in source, "docstring 里没提 draft ⇒ 改实现时没人看得到约定"

    # 正向确认：当前实现确实会覆盖
    out = asp.normalize_llm_faqs(
        [{"question": "q", "answer": "a", "status": "active"}], _doc())
    assert out[0]["status"] == "draft"

    # 反向确认：如果有人把它改成 `raw.get("status") or "draft"`，下面这个断言就会红
    assert out[0]["status"] != "active"

    # 分类判据非空：normalize_category 必须真的能归一（不是永远返回 other）
    assert asp.normalize_category("物流") == "shipping"
    assert asp.normalize_category("质保") == "aftersale"
