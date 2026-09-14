"""
划词翻译（SaaS 内建）测试
=========================
覆盖 `/api/v1/aigc/content/translate-selection` 与它的 Agent 实现。

设计约定（本文件据此断言，改实现时先想清楚要不要改约定）：
- 只要一个译文：不返回 SEO/文化/多版本结构
- 目标是 auto 时：含中文 → 译英；不含中文 → 译中（看海外商品页的主场景是英译中）
- **LLM 不可用时返回 degraded 且译文为空，绝不编造译文**（空状态优于虚构默认）
- 翻译必须压低 temperature，否则同一个词每次译法都不一样

全部用例都打桩，不发起真实 LLM 请求。
"""

import pytest

from modules.aigc_media.agent_aigc import AIGCMediaAgent
from modules.aigc_media.schemas import SelectionTranslateRequest
from modules.aigc_media.service import AIGCMediaService


# ============================================================
# 打桩
# ============================================================

@pytest.fixture
def stub_llm(monkeypatch):
    """
    替换 `_llm_generate_text`（翻译链路的唯一 LLM 出口）。

    返回一个 recorder，可以查看每次调用的 kwargs（用于断言 temperature / max_tokens），
    也能切换成「LLM 不可用」（返回 None）来验证降级路径。
    """
    calls = []
    box = {"reply": "译文占位"}

    async def fake(self, prompt, system_prompt=None, max_tokens=1500, temperature=0.8):
        calls.append({
            "prompt": prompt,
            "system_prompt": system_prompt,
            "max_tokens": max_tokens,
            "temperature": temperature,
        })
        return box["reply"]

    monkeypatch.setattr(AIGCMediaAgent, "_llm_generate_text", fake)
    return {"calls": calls, "box": box}


# ============================================================
# Agent：语言方向
# ============================================================

@pytest.mark.asyncio
async def test_english_text_translates_to_chinese(stub_llm):
    """主场景：英文商品标题 → 中文"""
    stub_llm["box"]["reply"] = "便携式迷你加湿器，适用于卧室和办公桌，USB供电，冷雾"
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Portable Mini Humidifier for Bedroom Desk USB Cool Mist")
    )
    assert res["success"] is True
    d = res["data"]
    assert d["source_lang"] == "en"
    assert d["target_lang"] == "zh"
    assert d["degraded"] is False
    assert "加湿器" in d["translation"]


@pytest.mark.asyncio
async def test_chinese_text_translates_to_english(stub_llm):
    """反向：中文原文 → 英文（auto 也要支持）"""
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="无线蓝牙耳机 主动降噪")
    )
    d = res["data"]
    assert d["source_lang"] == "zh"
    assert d["target_lang"] == "en"


@pytest.mark.asyncio
async def test_explicit_target_lang_is_respected(stub_llm):
    """显式指定目标语言时不被 auto 覆盖"""
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Wireless Earbuds", target_lang="ja")
    )
    assert res["data"]["target_lang"] == "ja"
    assert "日语" in stub_llm["calls"][0]["prompt"]


# ============================================================
# Agent：降级 —— 不编造译文
# ============================================================

@pytest.mark.asyncio
async def test_llm_unavailable_returns_degraded_with_empty_translation(stub_llm):
    """
    LLM 不可用时必须给出空译文 + degraded 标记。

    这条是刻意的产品决策：宁可让前端提示「暂不可用」，
    也不要返回 `[中文翻译] 原文` 这种假译文骗用户。
    """
    stub_llm["box"]["reply"] = None  # 模拟 LLM 不可用 / 调用失败
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Portable Mini Humidifier")
    )
    assert res["success"] is False
    d = res["data"]
    assert d["degraded"] is True
    assert d["translation"] == ""
    assert "暂不可用" in res["message"]


@pytest.mark.asyncio
async def test_blank_text_is_rejected_without_calling_llm(stub_llm):
    """纯空白不该白跑一次 LLM"""
    res = await AIGCMediaService.translate_selection(SelectionTranslateRequest(text="   \n  "))
    assert res["success"] is False
    assert res["data"]["translation"] == ""
    assert stub_llm["calls"] == []


# ============================================================
# Agent：译文清洗与提示词契约
# ============================================================

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("```\n无线耳机\n```", "无线耳机"),
        ("```text\n无线耳机\n```", "无线耳机"),
        ("译文：无线耳机", "无线耳机"),
        ("翻译: 无线耳机", "无线耳机"),
        ('"无线耳机"', "无线耳机"),
        ("「无线耳机」", "无线耳机"),
        ("第一行\n第二行", "第一行\n第二行"),
    ],
)
def test_clean_translation_strips_model_noise(raw, expected):
    """模型偶尔仍会包代码块 / 加前缀 / 加引号，输出前必须洗掉"""
    assert AIGCMediaAgent._clean_translation(raw) == expected


@pytest.mark.asyncio
async def test_prompt_carries_target_lang_and_source_text(stub_llm):
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Noise Cancelling Headphones")
    )
    prompt = stub_llm["calls"][0]["prompt"]
    assert "简体中文" in prompt, "提示词必须写明目标语言的中文名"
    assert "Noise Cancelling Headphones" in prompt, "提示词必须带上原文"
    assert res["success"] is True


@pytest.mark.asyncio
async def test_translation_uses_low_temperature(stub_llm):
    """翻译不能用创作型 temperature，否则同一个词每次译法都不一样"""
    await AIGCMediaService.translate_selection(SelectionTranslateRequest(text="Wireless Earbuds"))
    call = stub_llm["calls"][0]
    assert call["temperature"] <= 0.3, f"temperature 太高: {call['temperature']}"
    assert call["max_tokens"] <= 1200, "划词是短文本，不需要大 token 预算"


def test_system_prompt_forbids_extra_output():
    """system prompt 的关键约束不能丢（丢了模型就会加解释/加营销词）"""
    sp = AIGCMediaAgent._SELECTION_TRANSLATE_SYSTEM
    assert "只输出译文" in sp
    assert "不要解释" in sp
    assert "主动降噪" in sp, "电商术语惯例是划词翻译的核心价值，不能被删"
    assert "原样保留" in sp, "型号/规格必须保留"


# ============================================================
# 端点
# ============================================================

@pytest.mark.asyncio
async def test_endpoint_returns_translation(client, auth_off, stub_llm):
    stub_llm["box"]["reply"] = "无线蓝牙5.3耳机，主动降噪，续航40小时，IPX5防水"
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Wireless Earbuds Bluetooth 5.3 Noise Cancelling, 40H Playtime, IPX5 Waterproof"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    assert body["intent"] == "translate_selection"
    assert body["response"]["translation"] == "无线蓝牙5.3耳机，主动降噪，续航40小时，IPX5防水"
    assert body["response"]["source_lang"] == "en"
    assert body["response"]["target_lang"] == "zh"


@pytest.mark.asyncio
async def test_endpoint_response_has_no_seo_fields(client, auth_off, stub_llm):
    """
    划词响应**不能**带上 SEO/文化/多版本字段。

    这是与 /content/translate 的分工边界：背上一堆内容生产用的结构，
    首字只会更慢，而划词用户一个字都用不到。
    """
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Portable Mini Humidifier"},
    )
    assert r.status_code == 200, r.text
    data = r.json()["response"]
    for field in ("seo_optimized", "keyword_inclusion", "cultural_notes", "alternative_versions"):
        assert field not in data, f"划词响应不应包含 {field}"


@pytest.mark.asyncio
async def test_endpoint_returns_503_when_llm_unavailable(client, auth_off, stub_llm):
    """依赖不可用 → 503（不是 500：请求本身没问题）"""
    stub_llm["box"]["reply"] = None
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Portable Mini Humidifier"},
    )
    assert r.status_code == 503, r.text


@pytest.mark.asyncio
async def test_endpoint_rejects_empty_text(client, auth_off, stub_llm):
    """空文本在 schema 层就被拦掉"""
    r = await client.post("/api/v1/aigc/content/translate-selection", json={"text": ""})
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_endpoint_rejects_overlong_text(client, auth_off, stub_llm):
    """划词是短文本场景，超长直接被拦（前端也会拦，这里是兜底）"""
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "a" * 2001},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_endpoint_requires_auth_when_enabled(client, auth_on, stub_llm):
    """
    开启鉴权开关后，匿名调用必须 401。

    这个端点会真花 LLM 的钱，不能裸奔。
    """
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Portable Mini Humidifier"},
    )
    assert r.status_code == 401, r.text
    assert stub_llm["calls"] == [], "被鉴权拦下时不该已经花钱调 LLM"
