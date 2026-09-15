"""
平台规则库（platform_rules）测试

分三层覆盖：
  1. **LLM 结果清洗**（`ai_split.normalize_llm_rules`）—— 纯函数。
     LLM 返回的 JSON 形状不稳定（可能包一层 `{"rules": [...]}`、可能因解析失败给
     `{"raw_text": ...}`、可能缺字段），清洗层是「AI 拆分能不能用」的关键闸门。
  2. **字段契约**（`rule_to_dict` / `doc_to_dict`）—— 前端 `PlatformRule` /
     `PlatformRuleDoc` 的字段一个都不能少，JSON 列必须兜底成数组。
  3. **端点行为** —— 租户过滤 / 必填校验 / 批量跳过坏行 / 文档 CRUD / AI 拆分降级。

所有用例针对真实本地 PostgreSQL，用**测试专属 shop_id** 隔离，结束清理自己写入的行。

**不测真实 LLM 调用**：一是慢、二是依赖 API key（CI 上未必有）。
「LLM 不可用要降级而非编造」这条通过「无正文文档 → degraded」用例覆盖（不触发 LLM）。
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import delete

from core.database import async_session_factory
from modules.platform_rules.ai_split import MAX_RULES, normalize_llm_rules
from modules.platform_rules.db_model import PlatformRuleDocRecord, PlatformRuleRecord
from modules.platform_rules.service import (
    build_doc_record,
    build_rule_record,
    describe_missing_fields,
    doc_to_dict,
    missing_required_fields,
    rule_to_dict,
)


# 前端 PlatformRule 的字段集（改动前端类型时必须同步这里，否则前端读不到值）
FRONTEND_RULE_KEYS = {
    "id", "platform", "category", "title", "content",
    "effective_date", "expiry_date", "status", "tags",
    "source", "source_doc_id", "created_at", "updated_at",
}

FRONTEND_DOC_KEYS = {
    "id", "platform", "filename", "file_type", "size",
    "uploaded_at", "description",
}


# ====== 夹具 ======

@pytest_asyncio.fixture
async def shop_headers(ensure_shop):
    """只属于本次测试的店铺 id；用例跑完清掉该店铺的全部规则与文档"""
    # ensure_shop：自造 shop_id 必须在 stores_store 里真实存在（迁移 d5e6f7a8b9c0 的外键）
    sid = await ensure_shop(f"store_pytest_pr_{uuid.uuid4().hex[:8]}")
    yield {"X-Shop-ID": sid}
    async with async_session_factory() as session:
        await session.execute(delete(PlatformRuleRecord).where(PlatformRuleRecord.shop_id == sid))
        await session.execute(delete(PlatformRuleDocRecord).where(PlatformRuleDocRecord.shop_id == sid))
        await session.commit()


@pytest_asyncio.fixture
async def two_shop_headers(ensure_shop):
    """两个互不相干的店铺（验证租户隔离）"""
    a = await ensure_shop(f"store_pytest_pra_{uuid.uuid4().hex[:6]}")
    b = await ensure_shop(f"store_pytest_prb_{uuid.uuid4().hex[:6]}")
    yield ({"X-Shop-ID": a}, {"X-Shop-ID": b})
    async with async_session_factory() as session:
        for sid in (a, b):
            await session.execute(delete(PlatformRuleRecord).where(PlatformRuleRecord.shop_id == sid))
            await session.execute(delete(PlatformRuleDocRecord).where(PlatformRuleDocRecord.shop_id == sid))
        await session.commit()


def _fake_doc(doc_id="doc-fake", platform="shopee"):
    """normalize_llm_rules 只读 doc.id / doc.platform，用轻量替身即可"""
    return SimpleNamespace(id=doc_id, platform=platform, filename="x.pdf")


# ====== 1. LLM 结果清洗 ======

def test_normalize_returns_empty_on_raw_text():
    """structured_chat 解析失败会给 {"raw_text": ...} —— 必须视为无结果，不许猜"""
    assert normalize_llm_rules({"raw_text": "[不是 JSON]"}, _fake_doc()) == []


def test_normalize_accepts_plain_list():
    data = [{"title": "标题", "content": "正文", "category": "listing", "tags": ["a", "b"]}]
    out = normalize_llm_rules(data, _fake_doc())
    assert len(out) == 1
    assert out[0]["title"] == "标题"
    assert out[0]["content"] == "正文"
    assert out[0]["category"] == "listing"
    assert out[0]["tags"] == ["a", "b"]


@pytest.mark.parametrize("wrapper", ["rules", "items", "data", "result", "list"])
def test_normalize_unwraps_dict_wrapper(wrapper):
    """LLM 常把数组包一层 {"rules": [...]}，这几种键名都要能解出来"""
    data = {wrapper: [{"title": "T", "content": "C"}]}
    out = normalize_llm_rules(data, _fake_doc())
    assert len(out) == 1


def test_normalize_unrecognized_dict_yields_empty():
    """既不是数组也没有已知包装键 → 不猜，直接空"""
    assert normalize_llm_rules({"foo": "bar"}, _fake_doc()) == []


@pytest.mark.parametrize("bad", [
    {"title": "", "content": "有正文"},
    {"title": "有标题", "content": "   "},
    {"title": "有标题"},
    {"content": "有正文"},
    "不是对象",
    None,
])
def test_normalize_drops_incomplete_items(bad):
    """缺 title 或 content 的条目直接丢弃，不补空壳（补出来的规则对用户无意义）"""
    assert normalize_llm_rules([bad], _fake_doc()) == []


def test_normalize_caps_at_max_rules():
    """一篇长文档可能吐出几十条，必须按 MAX_RULES 截断，否则确认弹窗被撑爆"""
    data = [{"title": f"T{i}", "content": f"C{i}"} for i in range(MAX_RULES + 10)]
    assert len(normalize_llm_rules(data, _fake_doc())) == MAX_RULES


def test_normalize_forces_doc_platform():
    """平台一律取文档的 —— LLM 无权把 shopee 文档的规则挂到 amazon 名下"""
    data = [{"title": "T", "content": "C", "platform": "amazon"}]
    out = normalize_llm_rules(data, _fake_doc(platform="shopee"))
    assert out[0]["platform"] == "shopee"


def test_normalize_sets_defaults_and_source():
    """默认值收敛：category 默认 policy、status 恒 auto、source_doc_id 指向文档"""
    out = normalize_llm_rules([{"title": "T", "content": "C"}], _fake_doc(doc_id="doc-x"))
    assert out[0]["category"] == "policy"
    assert out[0]["status"] == "auto"
    assert out[0]["source_doc_id"] == "doc-x"
    assert out[0]["effective_date"]          # 有默认日期（今天）
    assert out[0]["tags"] == []


def test_normalize_cleans_tags():
    """tags 里混进数字 / 空白项要清洗掉，且最多 6 个"""
    data = [{"title": "T", "content": "C", "tags": ["a", "  ", 12, "", "b", "c", "d", "e", "f", "g"]}]
    out = normalize_llm_rules(data, _fake_doc())
    assert out[0]["tags"] == ["a", "12", "b", "c", "d", "e"]


# ====== 2. 字段契约 ======

def test_rule_dict_keys_match_frontend_contract():
    """前端 PlatformRule 的字段一个都不能少（少了前端就读不到值）"""
    rec = build_rule_record({"title": "T", "content": "C"}, shop_id="s1")
    assert set(rule_to_dict(rec).keys()) == FRONTEND_RULE_KEYS


def test_rule_dict_tags_fallback_to_empty_list():
    """tags 列在库里是 NULL，前端直接 .some() / .length —— 必须兜底成数组"""
    rec = build_rule_record({"title": "T", "content": "C", "tags": None}, shop_id="s1")
    rec.tags = None
    assert rule_to_dict(rec)["tags"] == []


def test_doc_dict_excludes_content_by_default():
    """
    列表接口不带正文：单篇 3~4k 字符 × 5 篇纯属浪费
    （前端文档列表只用 filename / size / description）
    """
    rec = build_doc_record({"filename": "a.pdf", "content": "很长很长的正文"}, shop_id="s1")
    assert "content" not in doc_to_dict(rec)
    assert doc_to_dict(rec, include_content=True)["content"] == "很长很长的正文"


def test_doc_dict_keys_match_frontend_contract():
    rec = build_doc_record({"filename": "a.pdf"}, shop_id="s1")
    assert set(doc_to_dict(rec).keys()) == FRONTEND_DOC_KEYS
    assert set(doc_to_dict(rec, include_content=True).keys()) == FRONTEND_DOC_KEYS | {"content"}


def test_build_rule_defaults():
    """只给 title + content 时的默认值收敛（平台/分类/状态/日期/标签）"""
    rec = build_rule_record({"title": "T", "content": "C"}, shop_id="s1")
    assert rec.platform == "amazon"
    assert rec.category == "policy"
    assert rec.status == "auto"
    assert rec.effective_date                     # 默认今天
    assert rec.expiry_date is None
    assert rec.tags == []
    assert rec.shop_id == "s1"


def test_build_rule_respects_explicit_values():
    """显式给了就用给的（含 status 手动覆盖、expiry_date 有值）"""
    rec = build_rule_record({
        "title": "T", "content": "C", "platform": "temu", "category": "policy",
        "status": "expired", "expiry_date": "2025-01-01", "tags": ["x"],
    }, shop_id="s1")
    assert rec.platform == "temu"
    assert rec.status == "expired"
    assert rec.expiry_date == "2025-01-01"
    assert rec.tags == ["x"]


def test_ids_are_unique_for_batch():
    """批量导入同一毫秒会造多条，id 必须带随机后缀（只靠时间戳会主键冲突）"""
    ids = {build_rule_record({"title": "T", "content": "C"}).id for _ in range(50)}
    assert len(ids) == 50


def test_missing_required_fields_and_labels():
    assert missing_required_fields({"platform": "amazon"}) == ["title", "content"]
    assert missing_required_fields({"title": "  ", "content": "C"}) == ["title"]
    assert missing_required_fields({"title": "T", "content": "C"}) == []
    # 提示必须是中文，不能把字段名甩给用户
    msg = describe_missing_fields(["title", "content"])
    assert "规则标题" in msg and "规则正文" in msg


# ====== 3. 端点 ======

async def test_list_returns_empty_without_shop_header(client, auth_off):
    """无租户上下文 → 返回空（与 candidates / monitors / products 一致）"""
    r = await client.get("/api/v1/platform-rules")
    assert r.status_code == 200
    assert r.json() == {"items": [], "docs": [], "total": 0}


async def test_create_requires_title_and_content(client, auth_off, shop_headers):
    r = await client.post("/api/v1/platform-rules", json={"platform": "amazon"}, headers=shop_headers)
    assert r.status_code == 422
    assert "规则标题" in r.json()["detail"]


async def test_create_then_list(client, auth_off, shop_headers):
    r = await client.post(
        "/api/v1/platform-rules",
        json={"title": "标题限制", "content": "最多 200 字符", "platform": "amazon", "tags": ["标题"]},
        headers=shop_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["title"] == "标题限制"
    assert created["tags"] == ["标题"]

    lst = await client.get("/api/v1/platform-rules", headers=shop_headers)
    body = lst.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == created["id"]
    assert body["docs"] == []


async def test_update_rule(client, auth_off, shop_headers):
    created = (await client.post(
        "/api/v1/platform-rules",
        json={"title": "T", "content": "C"},
        headers=shop_headers,
    )).json()

    r = await client.put(
        f"/api/v1/platform-rules/{created['id']}",
        json={"status": "expired", "tags": ["x"]},
        headers=shop_headers,
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["status"] == "expired"
    assert updated["tags"] == ["x"]
    assert updated["title"] == "T"          # 未提及的字段保持不变


async def test_delete_rule_and_404_afterwards(client, auth_off, shop_headers):
    created = (await client.post(
        "/api/v1/platform-rules", json={"title": "T", "content": "C"}, headers=shop_headers,
    )).json()

    r = await client.delete(f"/api/v1/platform-rules/{created['id']}", headers=shop_headers)
    assert r.status_code == 200

    r2 = await client.delete(f"/api/v1/platform-rules/{created['id']}", headers=shop_headers)
    assert r2.status_code == 404


async def test_update_and_delete_unknown_rule_404(client, auth_off, shop_headers):
    assert (await client.put(
        "/api/v1/platform-rules/rule-not-exist", json={"title": "T"}, headers=shop_headers
    )).status_code == 404
    assert (await client.delete(
        "/api/v1/platform-rules/rule-not-exist", headers=shop_headers
    )).status_code == 404


async def test_batch_skips_invalid_rows(client, auth_off, shop_headers):
    """
    导入文件常有缺字段的行 —— 跳过坏行并回报 skipped，
    整批 422 会让用户不知道是哪一行坏了。
    """
    r = await client.post("/api/v1/platform-rules/batch", json={"items": [
        {"title": "A", "content": "正文A"},
        {"title": "B", "content": "正文B"},
        {"title": "缺正文"},
    ]}, headers=shop_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 2
    assert body["skipped"] == 1
    assert len(body["items"]) == 2


async def test_batch_rejects_all_invalid(client, auth_off, shop_headers):
    r = await client.post("/api/v1/platform-rules/batch", json={"items": [{"title": "只有标题"}]}, headers=shop_headers)
    assert r.status_code == 422


async def test_batch_rejects_empty_items(client, auth_off, shop_headers):
    r = await client.post("/api/v1/platform-rules/batch", json={"items": []}, headers=shop_headers)
    assert r.status_code == 422


async def test_tenant_isolation(client, auth_off, two_shop_headers):
    """A 店铺建的规则，B 店铺看不到也改不动"""
    ha, hb = two_shop_headers
    created = (await client.post(
        "/api/v1/platform-rules", json={"title": "A 的规则", "content": "C"}, headers=ha,
    )).json()

    assert (await client.get("/api/v1/platform-rules", headers=hb)).json()["total"] == 0
    assert (await client.put(
        f"/api/v1/platform-rules/{created['id']}", json={"title": "越权改"}, headers=hb
    )).status_code == 404
    assert (await client.delete(
        f"/api/v1/platform-rules/{created['id']}", headers=hb
    )).status_code == 404


async def test_doc_create_and_delete(client, auth_off, shop_headers):
    r = await client.post(
        "/api/v1/platform-rule-docs",
        json={"filename": "amazon-2026.pdf", "platform": "amazon", "size": 1024, "description": "规范"},
        headers=shop_headers,
    )
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["filename"] == "amazon-2026.pdf"
    assert "content" not in doc          # 列表形态不带正文

    lst = (await client.get("/api/v1/platform-rules", headers=shop_headers)).json()
    assert len(lst["docs"]) == 1

    assert (await client.delete(f"/api/v1/platform-rule-docs/{doc['id']}", headers=shop_headers)).status_code == 200
    assert (await client.delete(f"/api/v1/platform-rule-docs/{doc['id']}", headers=shop_headers)).status_code == 404


async def test_doc_requires_filename(client, auth_off, shop_headers):
    r = await client.post("/api/v1/platform-rule-docs", json={"platform": "amazon"}, headers=shop_headers)
    assert r.status_code == 422


async def test_get_single_doc_includes_content(client, auth_off, shop_headers):
    """
    单篇文档接口**要带正文** —— 列表接口刻意不返回 content（正文动辄数千字符），
    来源文档预览改为点开时按 id 拉这一条。两者契约相反，别顺手"统一"掉。
    """
    doc = (await client.post(
        "/api/v1/platform-rule-docs",
        json={"filename": "a.md", "platform": "amazon", "content": "规则正文内容"},
        headers=shop_headers,
    )).json()
    assert "content" not in doc                    # 创建响应走的是列表形态

    r = await client.get(f"/api/v1/platform-rule-docs/{doc['id']}", headers=shop_headers)
    assert r.status_code == 200
    full = r.json()
    assert full["content"] == "规则正文内容"
    assert full["id"] == doc["id"]

    # 同一篇文档在列表里依然不带正文
    lst = (await client.get("/api/v1/platform-rules", headers=shop_headers)).json()
    assert "content" not in lst["docs"][0]


async def test_get_single_doc_unknown_404(client, auth_off, shop_headers):
    assert (await client.get("/api/v1/platform-rule-docs/doc-does-not-exist", headers=shop_headers)).status_code == 404


async def test_get_single_doc_tenant_isolated(client, auth_off, two_shop_headers):
    """跨租户按 id 直取必须 404，不能因为知道 id 就拿到别人的文档正文"""
    ha, hb = two_shop_headers
    doc = (await client.post(
        "/api/v1/platform-rule-docs",
        json={"filename": "private.md", "platform": "amazon", "content": "A 店铺的私有正文"},
        headers=ha,
    )).json()

    assert (await client.get(f"/api/v1/platform-rule-docs/{doc['id']}", headers=hb)).status_code == 404
    assert (await client.get(f"/api/v1/platform-rule-docs/{doc['id']}", headers=ha)).status_code == 200


async def test_deleting_doc_keeps_rules(client, auth_off, shop_headers):
    """删文档不级联删规则：source_doc_id 只是溯源自标，删附件不该连带删业务数据"""
    doc = (await client.post(
        "/api/v1/platform-rule-docs", json={"filename": "d.pdf"}, headers=shop_headers,
    )).json()
    await client.post(
        "/api/v1/platform-rules",
        json={"title": "引用文档的规则", "content": "C", "source_doc_id": doc["id"]},
        headers=shop_headers,
    )

    await client.delete(f"/api/v1/platform-rule-docs/{doc['id']}", headers=shop_headers)

    body = (await client.get("/api/v1/platform-rules", headers=shop_headers)).json()
    assert body["total"] == 1
    assert body["docs"] == []


async def test_ai_split_missing_doc_404(client, auth_off, shop_headers):
    r = await client.post(
        "/api/v1/platform-rules/ai-split", json={"doc_id": "doc-not-exist"}, headers=shop_headers
    )
    assert r.status_code == 404


async def test_ai_split_requires_doc_id(client, auth_off, shop_headers):
    r = await client.post("/api/v1/platform-rules/ai-split", json={}, headers=shop_headers)
    assert r.status_code == 422


async def test_ai_split_without_content_degrades_not_fabricates(client, auth_off, shop_headers):
    """
    无正文的文档必须 degraded=True + 空规则 + 中文原因 —— **绝不编造规则**。

    这条不触发真实 LLM（正文为空时在调用前就返回），所以不受 API key 影响。
    它是「宁可空状态，不要虚构默认」家规的守门用例：
    旧实现是前端用写死的模板冒充 AI 提取，会产出文档里根本没有的「FCC/CE 认证」。
    """
    doc = (await client.post(
        "/api/v1/platform-rule-docs",
        json={"filename": "no-content.pdf", "platform": "amazon"},
        headers=shop_headers,
    )).json()

    r = await client.post(
        "/api/v1/platform-rules/ai-split", json={"doc_id": doc["id"]}, headers=shop_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["degraded"] is True
    assert body["extracted"] == 0
    assert body["rules"] == []
    assert body["reason"]          # 有中文原因给用户看


# ====== BUSINESS_AUTH 闸门回归 ======

def test_routes_under_business_auth_gate():
    """
    防以后新增模块漏挂鉴权闸门。
    （不能用 auth_on 断言 401 —— BUSINESS_AUTH 是 import 时求值一次的启动期快照，
      演示模式启动则恒为空列表，运行期改 config.auth_required 对它无效。）
    """
    import inspect
    import main

    flat = " ".join(inspect.getsource(main).split())
    assert "platform_rules_router, dependencies=BUSINESS_AUTH" in flat
