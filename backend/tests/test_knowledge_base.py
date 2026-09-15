"""
业务话术库（knowledge_base）测试

分三层覆盖：
  1. **字段契约**（`kb_to_dict` / `faq_to_dict` / `doc_to_dict`）—— 前端
     `KnowledgeBase` / `FaqItem` / `KnowledgeDoc` 的字段一个都不能少，
     JSON 列必须兜底成数组，文档列表默认不带正文。
  2. **构造与校验**（`build_*_record` / `missing_required_fields`）—— 默认值收敛、
     id 加店铺后缀（单主键表多店铺的必要条件）、必填判定与中文提示。
  3. **端点行为** —— 租户过滤 / 必填 422 / 话术 CRUD / 批量导入跳过坏行 /
     批量删除 / 文档 CRUD / **删容器级联删其下话术与文档**。

所有用例针对真实本地 PostgreSQL，用**测试专属 shop_id** 隔离，结束清理自己写入的行。

**`kb_id` 为什么算必填**：它是话术与文档的**唯一归属维度**，前端
`currentItems` / `currentDocs` 都按 kb_id 过滤 —— 没有归属的行在 UI 里永远不可见，
只会污染总数统计。故后端主动拦 422，而不是静默落库。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from core.database import async_session_factory
from modules.knowledge_base.db_model import (
    KnowledgeBaseRecord,
    KnowledgeDocRecord,
    KnowledgeFaqRecord,
)
from modules.knowledge_base.service import (
    build_doc_record,
    build_faq_record,
    build_kb_record,
    describe_missing_fields,
    doc_to_dict,
    faq_to_dict,
    kb_to_dict,
    missing_required_fields,
)


# 前端类型的字段集（改动前端类型时必须同步这里，否则前端读不到值）
FRONTEND_KB_KEYS = {
    "id", "name", "description", "icon", "type", "is_default",
    "faq_count", "doc_count", "created_at", "updated_at",
}

FRONTEND_FAQ_KEYS = {
    "id", "kb_id", "question", "answer", "category", "keywords",
    "priority", "status", "usage_count", "created_at", "updated_at",
}

FRONTEND_DOC_KEYS = {
    "id", "kb_id", "filename", "file_type", "size",
    "uploaded_at", "description",
}


# ====== 夹具 ======

async def _purge(*shop_ids: str) -> None:
    async with async_session_factory() as session:
        for sid in shop_ids:
            await session.execute(delete(KnowledgeFaqRecord).where(KnowledgeFaqRecord.shop_id == sid))
            await session.execute(delete(KnowledgeDocRecord).where(KnowledgeDocRecord.shop_id == sid))
            await session.execute(delete(KnowledgeBaseRecord).where(KnowledgeBaseRecord.shop_id == sid))
        await session.commit()


@pytest_asyncio.fixture
async def shop_headers(ensure_shop):
    """只属于本次测试的店铺 id；用例跑完清掉该店铺的全部容器/话术/文档"""
    # ensure_shop：把自造的 shop_id 在 stores_store 里建出真实行
    # （迁移 d5e6f7a8b9c0 之后 shop_id 必须真实存在，否则外键拒绝写入）
    sid = await ensure_shop(f"store_pytest_kb_{uuid.uuid4().hex[:8]}")
    yield {"X-Shop-ID": sid}
    await _purge(sid)


@pytest_asyncio.fixture
async def two_shop_headers(ensure_shop):
    """两个互不相干的店铺（验证租户隔离）"""
    a = await ensure_shop(f"store_pytest_kba_{uuid.uuid4().hex[:6]}")
    b = await ensure_shop(f"store_pytest_kbb_{uuid.uuid4().hex[:6]}")
    yield ({"X-Shop-ID": a}, {"X-Shop-ID": b})
    await _purge(a, b)


async def _make_kb(client, headers, name="测试库") -> dict:
    r = await client.post("/api/v1/knowledge-base", json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ====== 1. 字段契约 ======

def test_kb_dict_keys_match_frontend_contract():
    rec = build_kb_record({"name": "库"}, shop_id="s1")
    assert set(kb_to_dict(rec).keys()) == FRONTEND_KB_KEYS


def test_faq_dict_keys_match_frontend_contract():
    rec = build_faq_record({"kb_id": "kb-1", "question": "q", "answer": "a"}, shop_id="s1")
    assert set(faq_to_dict(rec).keys()) == FRONTEND_FAQ_KEYS


def test_faq_keywords_falls_back_to_empty_list():
    """JSON 列在库里可能是 NULL，前端期望恒为数组 —— 不允许吐 None"""
    rec = build_faq_record({"kb_id": "kb-1", "question": "q", "answer": "a"}, shop_id="s1")
    rec.keywords = None
    assert faq_to_dict(rec)["keywords"] == []


def test_doc_dict_excludes_content_by_default():
    rec = build_doc_record(
        {"kb_id": "kb-1", "filename": "a.md", "file_type": "md", "size": 10, "content": "正文"},
        shop_id="s1",
    )
    doc = doc_to_dict(rec, include_content=False)
    assert "content" not in doc
    assert set(doc.keys()) == FRONTEND_DOC_KEYS
    assert doc_to_dict(rec, include_content=True)["content"] == "正文"


def test_doc_defaults_converge():
    rec = build_doc_record({"kb_id": "kb-1", "filename": "a"}, shop_id="s1")
    d = doc_to_dict(rec)
    assert d["file_type"] == "other"
    assert d["size"] == 0
    assert d["description"] == ""


def test_kb_is_default_is_real_bool():
    """前端拿 is_default 直接做 v-if，必须是布尔而不是 0/1 或字符串"""
    rec = build_kb_record({"name": "库", "is_default": True}, shop_id="s1")
    assert kb_to_dict(rec)["is_default"] is True
    assert kb_to_dict(build_kb_record({"name": "库"}, shop_id="s1"))["is_default"] is False


# ====== 2. 构造与校验 ======

def test_build_kb_record_appends_shop_suffix():
    """
    单主键表多店铺灌入必须给 id 加店铺后缀，否则第二个店铺主键冲突。
    这里覆盖「显式 id」与「自动 id」两条路径。
    """
    assert build_kb_record({"id": "kb-default", "name": "库"}, shop_id="s1").id == "kb-default-s1"
    auto = build_kb_record({"name": "库"}, shop_id="s1")
    assert auto.id.endswith("-s1")

    # 无租户上下文时不加后缀（与 candidates / monitors 的 demo 占位同理）
    assert build_kb_record({"id": "kb-default", "name": "库"}).id == "kb-default"


def test_build_kb_record_does_not_double_suffix():
    """同一个 shop_id 重复构造不应叠加后缀（防止 seed 重跑把 id 越接越长）"""
    once = build_kb_record({"id": "kb-default", "name": "库"}, shop_id="s1").id
    twice = build_kb_record({"id": once, "name": "库"}, shop_id="s1").id
    assert once == twice == "kb-default-s1"


def test_faq_defaults_converge():
    rec = build_faq_record({"kb_id": "kb-1", "question": "q", "answer": "a"}, shop_id="s1")
    d = faq_to_dict(rec)
    assert d["category"] == "other"
    assert d["priority"] == "medium"
    assert d["status"] == "active"
    assert d["usage_count"] == 0


@pytest.mark.parametrize("payload,missing", [
    ({"question": "q", "answer": "a"}, ["kb_id"]),
    ({"kb_id": "kb-1", "answer": "a"}, ["question"]),
    ({"kb_id": "kb-1", "question": "q"}, ["answer"]),
    ({"kb_id": "kb-1", "question": "  ", "answer": "a"}, ["question"]),
    ({"kb_id": "kb-1", "question": "q", "answer": "a"}, []),
])
def test_faq_required_fields(payload, missing):
    assert missing_required_fields(payload, ("kb_id", "question", "answer")) == missing


def test_describe_missing_fields_is_chinese():
    """别把 `kb_id` 这种字段名甩给用户"""
    assert describe_missing_fields(["kb_id"]) == "所属知识库"
    assert describe_missing_fields(["kb_id", "answer"]) == "所属知识库、答案"


def test_new_id_is_unique_under_same_millisecond():
    """批量导入时同一毫秒会造多条，只靠时间戳会主键冲突"""
    from modules.knowledge_base.service import _new_id
    ids = {_new_id("faq") for _ in range(60)}
    assert len(ids) == 60


# ====== 3. 端点行为 ======

async def test_list_empty_without_tenant(client, auth_off):
    """无租户上下文一律返回空 —— 返回全库数据会造成跨租户串数据"""
    body = (await client.get("/api/v1/knowledge-base")).json()
    assert body == {"bases": [], "faqs": [], "docs": [], "total": 0}


async def test_create_kb_and_list_counts(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")
    assert kb["faq_count"] == 0
    assert kb["doc_count"] == 0
    assert kb["type"] == "custom"

    await client.post(
        "/api/v1/knowledge-base/faqs",
        json={"kb_id": kb["id"], "question": "q1", "answer": "a1"},
        headers=shop_headers,
    )
    body = (await client.get("/api/v1/knowledge-base", headers=shop_headers)).json()
    assert len(body["bases"]) == 1
    # 计数由后端读时统计，加一条话术后立刻反映
    assert body["bases"][0]["faq_count"] == 1
    assert len(body["faqs"]) == 1


async def test_create_kb_requires_name(client, auth_off, shop_headers):
    r = await client.post("/api/v1/knowledge-base", json={"description": "没名字"}, headers=shop_headers)
    assert r.status_code == 422
    assert r.json()["detail"] == "缺少必填字段：知识库名称"


async def test_update_kb_renames_only_given_fields(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")
    r = await client.put(
        f"/api/v1/knowledge-base/{kb['id']}", json={"name": "_t_改名"}, headers=shop_headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "_t_改名"
    assert r.json()["type"] == kb["type"]


@pytest.mark.parametrize("method,url", [
    ("put", "/api/v1/knowledge-base/nope"),
    ("delete", "/api/v1/knowledge-base/nope"),
    ("put", "/api/v1/knowledge-base/faqs/nope"),
    ("delete", "/api/v1/knowledge-base/faqs/nope"),
    ("get", "/api/v1/knowledge-base/docs/nope"),
    ("delete", "/api/v1/knowledge-base/docs/nope"),
])
async def test_unknown_ids_return_404(client, auth_off, shop_headers, method, url):
    kwargs = {"headers": shop_headers}
    if method == "put":
        kwargs["json"] = {"name": "x", "answer": "x"}
    assert (await getattr(client, method)(url, **kwargs)).status_code == 404


async def test_faq_requires_kb_id_and_question_answer(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")

    r = await client.post(
        "/api/v1/knowledge-base/faqs",
        json={"question": "只有问题"},
        headers=shop_headers,
    )
    assert r.status_code == 422
    assert r.json()["detail"] == "缺少必填字段：所属知识库、答案"

    r2 = await client.post(
        "/api/v1/knowledge-base/faqs",
        json={"kb_id": kb["id"], "question": "q"},
        headers=shop_headers,
    )
    assert r2.status_code == 422


async def test_faq_crud(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")
    faq = (await client.post(
        "/api/v1/knowledge-base/faqs",
        json={"kb_id": kb["id"], "question": "_t_q", "answer": "_t_a"},
        headers=shop_headers,
    )).json()

    upd = (await client.put(
        f"/api/v1/knowledge-base/faqs/{faq['id']}",
        json={"priority": "high", "keywords": ["k1"], "status": "draft"},
        headers=shop_headers,
    )).json()
    assert upd["priority"] == "high"
    assert upd["keywords"] == ["k1"]
    assert upd["status"] == "draft"
    assert upd["question"] == "_t_q"          # 未传字段保持不变

    assert (await client.delete(f"/api/v1/knowledge-base/faqs/{faq['id']}", headers=shop_headers)).status_code == 200
    assert (await client.delete(f"/api/v1/knowledge-base/faqs/{faq['id']}", headers=shop_headers)).status_code == 404


async def test_faq_batch_skips_bad_rows(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")
    r = await client.post(
        "/api/v1/knowledge-base/faqs/batch",
        json={"items": [
            {"kb_id": kb["id"], "question": "q1", "answer": "a1"},
            {"kb_id": kb["id"], "question": "q2", "answer": "a2"},
            {"kb_id": kb["id"], "question": "缺答案"},
            {"question": "缺归属", "answer": "a"},
        ]},
        headers=shop_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["added"] == 2
    assert body["skipped"] == 2
    assert len(body["items"]) == 2


async def test_faq_batch_all_bad_is_422(client, auth_off, shop_headers):
    r = await client.post(
        "/api/v1/knowledge-base/faqs/batch",
        json={"items": [{"question": "无归属"}]},
        headers=shop_headers,
    )
    assert r.status_code == 422
    assert "全部条目都缺少必填字段" in r.json()["detail"]


@pytest.mark.parametrize("url,payload", [
    ("/api/v1/knowledge-base/faqs/batch", {"items": []}),
    ("/api/v1/knowledge-base/faqs/batch-delete", {"ids": []}),
])
async def test_batch_endpoints_reject_empty_payload(client, auth_off, shop_headers, url, payload):
    assert (await client.post(url, json=payload, headers=shop_headers)).status_code == 422


async def test_faq_batch_delete(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")
    ids = []
    for i in range(3):
        ids.append((await client.post(
            "/api/v1/knowledge-base/faqs",
            json={"kb_id": kb["id"], "question": f"q{i}", "answer": f"a{i}"},
            headers=shop_headers,
        )).json()["id"])

    r = await client.post(
        "/api/v1/knowledge-base/faqs/batch-delete",
        json={"ids": ids[:2]},
        headers=shop_headers,
    )
    assert r.json()["deleted"] == 2

    body = (await client.get("/api/v1/knowledge-base", headers=shop_headers)).json()
    assert body["bases"][0]["faq_count"] == 1
    assert len(body["faqs"]) == 1


async def test_doc_requires_kb_id_and_filename(client, auth_off, shop_headers):
    kb = await _make_kb(client, shop_headers, "_t_kb")

    r = await client.post("/api/v1/knowledge-base/docs", json={"kb_id": kb["id"]}, headers=shop_headers)
    assert r.status_code == 422
    assert r.json()["detail"] == "缺少必填字段：文件名"

    # 没有 kb_id 的文档在资料库页任何列表里都取不到 → 必须拦住，不能静默落库
    r2 = await client.post("/api/v1/knowledge-base/docs", json={"filename": "孤立.md"}, headers=shop_headers)
    assert r2.status_code == 422
    assert r2.json()["detail"] == "缺少必填字段：所属知识库"


async def test_get_single_doc_includes_content(client, auth_off, shop_headers):
    """
    单篇文档接口**要带正文** —— 列表接口刻意不返回 content（整篇数千字符），
    两者契约相反，别顺手"统一"掉。
    """
    kb = await _make_kb(client, shop_headers, "_t_kb")
    doc = (await client.post(
        "/api/v1/knowledge-base/docs",
        json={"kb_id": kb["id"], "filename": "a.md", "content": "售后政策正文"},
        headers=shop_headers,
    )).json()
    assert "content" not in doc

    full = (await client.get(f"/api/v1/knowledge-base/docs/{doc['id']}", headers=shop_headers)).json()
    assert full["content"] == "售后政策正文"
    assert full["kb_id"] == kb["id"]

    lst = (await client.get("/api/v1/knowledge-base", headers=shop_headers)).json()
    assert "content" not in lst["docs"][0]


async def test_delete_kb_cascades_to_faqs_and_docs(client, auth_off, shop_headers):
    """
    删容器级联删其下话术与文档 —— kb_id 是唯一归属维度，容器没了条目在 UI 里不可达。
    （与 platform_rules「删文档不级联删规则」相反，因为那边是溯源附件、这边是归属父级。）
    """
    kb_a = await _make_kb(client, shop_headers, "_t_kbA")
    kb_b = await _make_kb(client, shop_headers, "_t_kbB")

    for kb in (kb_a, kb_b):
        await client.post(
            "/api/v1/knowledge-base/faqs",
            json={"kb_id": kb["id"], "question": f"q-{kb['id']}", "answer": "a"},
            headers=shop_headers,
        )
    await client.post(
        "/api/v1/knowledge-base/docs",
        json={"kb_id": kb_a["id"], "filename": "x.md"},
        headers=shop_headers,
    )

    r = await client.delete(f"/api/v1/knowledge-base/{kb_a['id']}", headers=shop_headers)
    assert r.status_code == 200
    assert r.json()["deleted_faqs"] == 1
    assert r.json()["deleted_docs"] == 1

    body = (await client.get("/api/v1/knowledge-base", headers=shop_headers)).json()
    assert [b["id"] for b in body["bases"]] == [kb_b["id"]]
    # B 库与自己那条话术都不受影响
    assert len(body["faqs"]) == 1
    assert body["docs"] == []
    assert body["bases"][0]["faq_count"] == 1

    assert (await client.delete(f"/api/v1/knowledge-base/{kb_a['id']}", headers=shop_headers)).status_code == 404


async def test_tenant_isolated(client, auth_off, two_shop_headers):
    ha, hb = two_shop_headers
    kb_a = await _make_kb(client, ha, "_t_kbA")
    await client.post(
        "/api/v1/knowledge-base/faqs",
        json={"kb_id": kb_a["id"], "question": "A 的话术", "answer": "a"},
        headers=ha,
    )

    body_b = (await client.get("/api/v1/knowledge-base", headers=hb)).json()
    assert body_b == {"bases": [], "faqs": [], "docs": [], "total": 0}

    # 知道 id 也不能跨租户改名 / 删除 / 直取
    assert (await client.put(
        f"/api/v1/knowledge-base/{kb_a['id']}", json={"name": "改"}, headers=hb,
    )).status_code == 404
    assert (await client.delete(f"/api/v1/knowledge-base/{kb_a['id']}", headers=hb)).status_code == 404

    body_a = (await client.get("/api/v1/knowledge-base", headers=ha)).json()
    assert len(body_a["faqs"]) == 1


def test_routes_under_business_auth_gate():
    """
    防以后新增模块漏挂鉴权闸门。
    （不能用 auth_on 断言 401 —— BUSINESS_AUTH 是 import 时求值一次的启动期快照，
      演示模式启动则恒为空列表，运行期改 config.auth_required 对它无效。）
    """
    import inspect
    import main

    flat = " ".join(inspect.getsource(main).split())
    assert "knowledge_base_router, dependencies=BUSINESS_AUTH" in flat
