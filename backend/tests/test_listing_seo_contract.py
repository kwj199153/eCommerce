"""
`/api/v1/listing/analyze/seo` 契约守护（第 128 轮 · P0-2 批 1）

为什么值得单独一个文件
----------------------
`modules/listing_generator` 是**唯一一个零测试文件**的业务模块（11 个端点）。
第 128 轮做前端「4 个高曝光工具接真后端」时，端到端实测第一次把它接上界面，
立刻暴露一个真缺陷：

    service.py::analyze_seo 里
        seo_data = result.data.get("seo_score", {})
    而 `agent.invoke()` 在 **LLM 不可用 / 路由未产出结构化数据** 时返回
        AgentResponse(content='...', data=None, display_type='text')
    ⇒ `None.get(...)` ⇒ AttributeError ⇒ 路由层 `except Exception` 包成
        HTTPException(500, detail="'NoneType' object has no attribute 'get'")

用户看到的是**指向错方向**的报错（像代码崩了，实际是 LLM 没产出结果），
且这个 500 会让前端「SEO 诊断」工具卡整条链路失效。

★ 本文件的判据不是「多少个用例」，而是**一条能在 CI 里对这个维度说不的断言**：
    ① 缺失结构化数据时，报错必须**说明真因**，不得出现 `NoneType`；
    ② 有结构化数据时，出参字段名必须与前端适配层
       （`frontend/src/utils/toolResultAdapters.ts::adaptSeoAudit`）消费的
       字段**逐一对上** —— 少一个字段，前端那张卡就少一块内容，且**不报错**。

反向注入（证明不是空跑）
------------------------
把 `service.py::analyze_seo` 的守卫改回 `seo_data = result.data.get("seo_score", {})`，
则 `test_missing_structured_data_error_points_at_real_cause` 必须转红。
实测已确认（第 128 轮）。
"""

import pytest


# ====== 前端 adaptSeoAudit 消费的字段（契约真源）======

ADAPTED_DIMS = [
    "title_score",
    "bullet_score",
    "description_score",
    "keywords_score",
]
ADAPTED_TOP = ["overall_score", "checklist", "improvement_areas", "grade"]


SEO_SCORE = {
    "overall_score": 72.5,
    "title_score": 80.0,
    "bullet_score": 68.0,
    "description_score": 70.0,
    "keywords_score": 72.0,
    "checklist": {
        "标题含主关键词": True,
        "标题长度 80-200 字符": True,
        "五点均以大写标题开头": False,
        "后台搜索词已填": True,
    },
    "improvement_areas": ["五点描述首句建议突出差异化", "描述可补充使用场景"],
}


REQ = {
    "title": "Stainless Steel Coffee Grinder Manual Burr Mill Adjustable Settings Portable",
    "bullets": ["PRECISION BURR: 40 settings", "PORTABLE: 7.5 inch body"],
    "description": "Enjoy fresh coffee anywhere with our manual burr grinder.",
    "search_terms": "coffee grinder manual",
    "main_keyword": "coffee grinder",
}


class _FakeAgent:
    """只替 `invoke`，返回受控的 AgentResponse（不打 LLM）。"""

    def __init__(self, data):
        self._data = data
        self.seen_query = None

    async def invoke(self, query, context=None):
        from modules.listing_generator.agent_listing import AgentResponse

        self.seen_query = query
        return AgentResponse(content="[测试桩]", data=self._data, display_type="report")


@pytest.fixture
def seo_service(monkeypatch):
    """把路由层单例 service 的 agent 换成受控桩。返回 (service, set数据回调)。"""

    from modules.listing_generator import router as lg_router

    holder = {}

    def install(data):
        agent = _FakeAgent(data)
        monkeypatch.setattr(lg_router.service, "agent", agent, raising=True)
        holder["agent"] = agent
        return agent

    return install, holder


# ====== ① 缺失结构化数据：报错必须指向真因 ======


async def test_missing_structured_data_error_points_at_real_cause(client, auth_off, seo_service):
    """
    `agent.invoke()` 返回 `data=None` 时（LLM 不可用 / 路由未产出）：
      · 不得出现 `'NoneType' object has no attribute 'get'` 这类**指向错方向**的报错；
      · 文案必须说清「未产出结构化结果」并给出下一步动作。
    """
    install, _ = seo_service
    install(None)

    r = await client.post("/api/v1/listing/analyze/seo", json=REQ)

    assert r.status_code != 200, "缺失结构化数据时不得返回 200（那是拿空数据冒充分析结果）"
    detail = str(r.json().get("detail", "")) + r.text
    assert "NoneType" not in detail, f"报错仍指向错方向（NoneType）：{detail}"
    assert "has no attribute" not in detail, f"报错仍是 Python 内部报错：{detail}"
    assert "seo_score" in detail, f"报错应说明真实原因（未返回 seo_score）：{detail}"


async def test_empty_seo_score_also_rejected(client, auth_off, seo_service):
    """`data={"seo_score": {}}` 同样视为「未产出」，不得回落成全 0 分报告。"""
    install, _ = seo_service
    install({"seo_score": {}})

    r = await client.post("/api/v1/listing/analyze/seo", json=REQ)

    assert r.status_code != 200, "空 seo_score 不得变成一份全 0 分的『有效报告』"
    assert "NoneType" not in r.text


# ====== ② 有结构化数据：出参字段名必须与前端适配层对上 ======


async def test_response_field_names_match_frontend_adapter(client, auth_off, seo_service):
    """
    出参必须**恰好**带上前端适配层消费的全部字段。

    ★ 为什么值得断言字段名：字段少了前端**不报错**，只是那张卡少一块内容
      （第 128 轮已实测到两起「接线了但没渲染」：广告诊断的 `displayType`
      与竞品卡的 `differentiation` 键名不匹配）。少字段 = 静默缺内容。
    """
    install, holder = seo_service
    install({"seo_score": dict(SEO_SCORE)})

    r = await client.post("/api/v1/listing/analyze/seo", json=REQ)
    assert r.status_code == 200, r.text

    body = r.json()
    assert body.get("success") is True
    data = body["data"]

    for f in ADAPTED_TOP + ADAPTED_DIMS:
        assert f in data, f"出参缺字段 {f}（前端 adaptSeoAudit 会消费它）"

    # 等级由后端自算（前端不自算，避免两套阈值）
    assert data["grade"] == "C", f"72.5 分应为 C，实际 {data['grade']!r}"

    # checklist 是 {检查项: bool} —— 前端据此算 passed_count / failed_items
    assert isinstance(data["checklist"], dict)
    assert all(isinstance(v, bool) for v in data["checklist"].values()), \
        "checklist 的值必须是布尔（前端按 `=== true` 判定通过）"

    assert isinstance(data["improvement_areas"], list)

    # 保留原值，不做二次加工（防「后端偷偷改写前端要展示的真值」）
    assert data["overall_score"] == SEO_SCORE["overall_score"]


async def test_grade_thresholds_are_backend_owned(client, auth_off, seo_service):
    """等级阈值归后端（A≥90 / B≥80 / C≥70 / D≥60 / else F），前端不得另立一套。"""
    install, _ = seo_service
    expect = [(95, "A"), (85, "B"), (75, "C"), (65, "D"), (30, "F")]
    for score, grade in expect:
        install({"seo_score": dict(SEO_SCORE, overall_score=score)})
        r = await client.post("/api/v1/listing/analyze/seo", json=REQ)
        assert r.status_code == 200, r.text
        assert r.json()["data"]["grade"] == grade, f"{score} 分应为 {grade}"
