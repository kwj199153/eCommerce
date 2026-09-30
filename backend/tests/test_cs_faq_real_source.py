"""第 286 轮 P0-1：客服话术的检索源必须是 `knowledge_faqs` 表，不是内存常量。

为什么必须单独钉这一条：
  · 改造前 `agent_cs.MOCK_FAQ_DB`（12 条硬编码）与 `knowledge_faqs`（库里真数据）
    是**同一业务的两种答案**，而客服只用前者。改完之后，任何一处把检索源
    换回内存、或「取不到就悄悄回退到一份默认话术」，界面上都不报错 ——
    看起来只是「答案不太对」。
  · 既有测试（工单落库 / 订单 fail-closed / 订单取数顺序）**全都看不见**这条：
    它们不碰话术。⇒ 必须另建。

★ 全部 monkeypatch，**不连共享库**（本仓 `tests/` 连的是共享生产库，
  依赖 seed 数据的用例不可复现）。喂的是构造好的行，形态照抄
  `modules/knowledge_base/db_model.py::KnowledgeFaqRecord`。

★ 与「订单三件套」的分工同构：
    order_failclosed  → 管「不能编」
    order_own_source  → 管「先问谁」
    本文件            → 管「从哪读」（真表 vs 内存）以及「读不到时怎么说」
"""

import pytest

from modules.customer_service import faq_source
from modules.customer_service.agent_cs import CustomerServiceAgent
from modules.knowledge_base.db_model import KnowledgeFaqRecord

SHOP = "store_unit_test"

# 表里的两行（分类用**英文 code**，与 knowledge_base 模块同口径）
ROWS = [
    KnowledgeFaqRecord(
        id=f"cs-faq-001-{SHOP}", shop_id=SHOP, kb_id=f"kb-default-{SHOP}",
        question="发货时间要多久？", answer="表里的答案：国内仓 1-3 个工作日发出。",
        category="shipping", keywords=["发货", "多久"], priority="high",
        status="active", usage_count=1520,
    ),
    KnowledgeFaqRecord(
        id=f"cs-faq-002-{SHOP}", shop_id=SHOP, kb_id=f"kb-default-{SHOP}",
        question="如何申请退货？", answer="表里的答案：收到商品 30 天内可申请。",
        category="return", keywords=["退货", "退款"], priority="medium",
        status="active", usage_count=980,
    ),
]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    """假会话。`executed` 记录收到的语句 —— 供「租户 / 状态过滤」的形态判据用。

    ★ 为什么不在这里实现 where 过滤：那等于把 SQLAlchemy 的语义重抄一遍，
      抄错就会得到一份**看起来很真的假结果**。过滤是否发生，改由
      `test_query_is_scoped_by_shop_and_status` 直接查语句文本。
    """

    executed: list = []

    def __init__(self, rows):
        self._rows = rows

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, stmt):
        _FakeSession.executed.append(stmt)
        return _Result(self._rows)


def _patch_table(monkeypatch, rows=None, exc=None):
    """把 `async_session_factory` 换成假会话（rows）或抛异常的会话（exc）。"""
    if exc is not None:
        class _Boom:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def execute(self, stmt):
                raise exc
    else:
        _Boom = None

    def _factory():
        return _Boom() if _Boom else _FakeSession(rows if rows is not None else ROWS)

    monkeypatch.setattr(faq_source, "async_session_factory", _factory)


@pytest.fixture
def agent():
    return CustomerServiceAgent()


# =====================================================================
# 1. 从表读：字段映射正确 + 归档条目不出现
# =====================================================================
async def test_loads_from_table_and_maps_fields(monkeypatch):
    _patch_table(monkeypatch)

    items = await faq_source.load_faq_items(SHOP)

    assert len(items) == 2
    first = items[0]
    assert first["id"] == f"cs-faq-001-{SHOP}"
    # ★ 表存英文 code，客服展示用中文 —— 翻译只发生在 `faq_source` 一处
    assert first["category"] == "物流"
    assert first["priority"] == 100, "high 应映射成数值权重（_search_faq 的加权要数值）"
    assert first["usage_count"] == 1520
    # ★ views 没有对应列 ⇒ 恒 0，不拿 usage_count 冒充实测
    assert first["views"] == 0
    # 高优先级在前
    assert items[1]["category"] == "退换货" and items[1]["priority"] == 60


# =====================================================================
# 1b. 语句里**真的**带租户过滤与 status 过滤（形态判据）
# =====================================================================
async def test_query_is_scoped_by_shop_and_status(monkeypatch):
    """★ 为什么用语句文本判据：假会话不会执行 where，若只看返回值，
       「忘了加店铺过滤」的查询照样返回构造好的行 —— 判据是空的。
       直接查语句，才能保证归档条目 / 别家店铺的话术进不来。
    """
    _FakeSession.executed = []
    _patch_table(monkeypatch)

    await faq_source.load_faq_items(SHOP)

    assert _FakeSession.executed, "一次查询都没发出"
    sql = str(_FakeSession.executed[-1]).lower()
    assert "knowledge_faqs" in sql, f"查的不是 knowledge_faqs：{sql}"
    assert "shop_id" in sql, f"缺少租户过滤 ⇒ 会读到别家店铺的话术：{sql}"
    assert "status" in sql, f"缺少 status 过滤 ⇒ 归档话术会被检索到：{sql}"


# =====================================================================
# 2. 缺店铺 ⇒ PermissionError（不是「查全部店铺」、也不是空列表）
# =====================================================================
async def test_missing_shop_is_rejected_not_silently_empty(monkeypatch):
    _patch_table(monkeypatch)

    for bad in (None, ""):
        with pytest.raises(PermissionError):
            await faq_source.load_faq_items(bad)


# =====================================================================
# 3. 数据库异常 ⇒ 原样冒泡（★ 不吞、不回退到任何默认话术）
# =====================================================================
async def test_db_failure_propagates(monkeypatch):
    _patch_table(monkeypatch, exc=RuntimeError("connection reset"))

    with pytest.raises(RuntimeError, match="connection reset"):
        await faq_source.load_faq_items(SHOP)


# =====================================================================
# 4. 表里 0 行 ⇒ 空列表（**正常业务状态**，不是故障）
# =====================================================================
async def test_empty_table_is_empty_not_error(monkeypatch):
    _patch_table(monkeypatch, rows=[])

    assert await faq_source.load_faq_items(SHOP) == []


# =====================================================================
# 5. Agent 侧：ensure_faq 的三种结局
# =====================================================================
async def test_agent_loads_table_faq_into_database(agent, monkeypatch):
    _patch_table(monkeypatch)

    err = await agent.ensure_faq(SHOP)

    assert err == ""
    assert len(agent.faq_database) == 2
    assert agent._faq_shop == SHOP
    assert agent._faq_error == ""


async def test_agent_records_reason_when_source_unavailable(agent, monkeypatch):
    """读不出来 ⇒ 记原因 + **话术清空**（留着上一批就是拿旧数据冒充新结果）。"""
    _patch_table(monkeypatch)
    await agent.ensure_faq(SHOP)
    assert len(agent.faq_database) == 2

    _patch_table(monkeypatch, exc=RuntimeError("database is down"))
    err = await agent.ensure_faq(SHOP)

    assert "database is down" in err
    assert agent.faq_database == [], "读不出来时必须清空，不能沿用上一批话术"
    assert agent._faq_shop is None


async def test_search_raises_instead_of_returning_empty_list(agent, monkeypatch):
    """★ 核心：`search_knowledge_base` 绝不把「读不出来」伪装成「没匹配」"""
    _patch_table(monkeypatch, exc=RuntimeError("database is down"))

    with pytest.raises(RuntimeError):
        await agent.search_knowledge_base("发货", shop_id=SHOP)

    monkeypatch.setattr(faq_source, "async_session_factory", lambda: _FakeSession(ROWS))
    with pytest.raises(PermissionError):
        await agent.search_knowledge_base("发货", shop_id=None)


# =====================================================================
# 6. 检索到的**内容**确实来自表（不是内存常量）
# =====================================================================
async def test_search_hits_the_table_content(agent, monkeypatch):
    _patch_table(monkeypatch)

    hits = await agent.search_knowledge_base("发货时间要多久", shop_id=SHOP)

    assert hits, "表里明明有这条话术，却没检索到"
    assert hits[0]["answer"].startswith("表里的答案"), (
        f"命中的不是表里的那条：{hits[0]}")


async def test_agent_has_no_in_memory_faq_constants(agent, monkeypatch):
    """★ 形态判据：Agent 在未加载时**没有任何话术**。

    改造前 `agent_cs` 模块里有一份 `MOCK_FAQ_DB` 常量，`__init__` 直接灌进
    `faq_database` ⇒ 新建实例就有 12 条。现在必须是 0 条：话术只能来自表。
    """
    import modules.customer_service.agent_cs as cs

    assert not hasattr(cs, "MOCK_FAQ_DB"), (
        "内存话术常量又回来了 —— 那正是本轮删掉的东西")
    assert agent.faq_database == [], "未加载时不应有任何话术"


async def test_faq_query_tells_apart_unavailable_and_not_configured(agent, monkeypatch):
    """三种「没答上来」必须给出**三种不同的回复**（运营据此知道该修哪里）。"""
    from modules.customer_service.agent_cs import SentimentAnalysis

    neutral = SentimentAnalysis(sentiment="neutral", confidence=0.5, intensity=0.2)

    # ★ 各分支的原料是 `ensure_faq` 加载的（真实链路上由 `_route_by_intent` 调），
    #   这里直接调 handler，必须自己先加载一次。
    # (a) 读不出来
    _patch_table(monkeypatch, exc=RuntimeError("database is down"))
    await agent.ensure_faq(SHOP)
    r = await agent._handle_faq_query("发货要多久", {"store_id": SHOP}, None, neutral)
    assert r.data["type"] == "faq_unavailable"
    assert "database is down" in r.content

    # (b) 还没配话术（表里 0 行）
    _patch_table(monkeypatch, rows=[])
    await agent.ensure_faq(SHOP)
    r = await agent._handle_faq_query("发货要多久", {"store_id": SHOP}, None, neutral)
    assert r.data["type"] == "faq_empty"

    # (c) 有话术但没命中 ⇒ 走正常检索分支（既不是 a 也不是 b）
    _patch_table(monkeypatch)
    await agent.ensure_faq(SHOP)
    r = await agent._handle_faq_query("python 怎么装", {"store_id": SHOP}, None, neutral)
    assert r.data.get("type") not in ("faq_unavailable", "faq_empty")


# =====================================================================
# 7. 反向注入：判据不是空跑
# =====================================================================
async def test_judge_is_not_vacuous(agent, monkeypatch):
    """把检索源换回「内存常量」，第 6 组的判据必须能抓到。

    ★ 这条测的是**判据本身**：若换成内存数据后第 6 组依然绿，
      说明那条断言根本没在看内容（空跑）。
    """
    async def _memory_faqs(shop_id):
        return [{
            "id": "faq-001", "question": "发货时间要多久？",
            "answer": "内存里的旧答案", "category": "物流",
            "keywords": ["发货"], "priority": 100, "views": 0,
            "helpful_count": 0, "usage_count": 0,
        }]

    monkeypatch.setattr(faq_source, "load_faq_items", _memory_faqs)

    hits = await agent.search_knowledge_base("发货时间要多久", shop_id=SHOP)
    assert hits and hits[0]["answer"] == "内存里的旧答案", (
        "换源没生效 ⇒ 第 6 组的判据可能是空跑")
