"""
划词翻译（SaaS 内建）测试
=========================
覆盖 `/api/v1/aigc/content/translate-selection` 与它的 Agent 实现。

设计约定（本文件据此断言，改实现时先想清楚要不要改约定）：
- 只要一个译文：不返回 SEO/文化/多版本结构
- **默认一律译成中文**（`target_lang` 默认 `"zh"`）
- 原文已是中文 ⇒ **不调模型**，回 `same_lang=True`（前端据此给「译为英文」入口）
- **显式**传 `auto` 时保留旧语义：含中文 → 译英；不含中文 → 译中
- **夹了外文词的混合文本要真的翻**（第 365 轮）：`detect_lang` 是二值判据
  （含任一 CJK ⇒ zh），分不出「纯中文」与「中文夹英文词」，所以短路只对**纯目标语言**生效
- 模型把混合文本**原样退回**时按「没翻」呈现（`same_lang`），不显示「中文 → 中文」这种方向

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
async def test_chinese_text_with_default_target_is_not_translated(stub_llm):
    """★ 默认目标 = 中文，选到中文 ⇒ **不调模型**，如实回 `same_lang`。

    老板 2026-10-02 实测报的原话：「翻译完居然是英文的」—— 选中「这个 listing」
    得到「This listing」。根因是这里的默认值还是 `auto`（含中文则译英）；
    拍板后改成 `zh`（一律译成中文）。本用例把这个默认口径钉死。

    ★ 为什么不能「照译一遍」：目标与原文同语言时，模型要么原样回显（白花一次调用），
      要么把中文**改写**一遍 —— 后者是静默的语义漂移（用户看到的中文不再是他选中的那段，
      且全程没有任何报错）。
    """
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="无线蓝牙耳机 主动降噪")
    )
    assert res["success"] is True
    d = res["data"]
    assert d["source_lang"] == "zh"
    assert d["target_lang"] == "zh"
    assert d["same_lang"] is True
    assert d["translation"] == ""      # 不编造译文
    assert d["degraded"] is False      # ★ 这不是故障（与「降级」严格区分）
    assert stub_llm["calls"] == [], "已经是中文就不该白跑一次 LLM"


@pytest.mark.asyncio
async def test_auto_is_still_honored_when_explicitly_passed(stub_llm):
    """显式传 `auto` ⇒ 保留旧语义（中文 → 英文）。

    默认值变了，但**语义面没有收窄** —— 老调用方显式带 auto 时行为不变。
    """
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="无线蓝牙耳机 主动降噪", target_lang="auto")
    )
    d = res["data"]
    assert d["source_lang"] == "zh"
    assert d["target_lang"] == "en"
    assert d.get("same_lang", False) is False
    assert len(stub_llm["calls"]) == 1, "auto 且方向相反 ⇒ 必须真的翻"


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
    """system prompt 的关键约束不能丢（丢了模型就会加解释/加营销词）

    ★ 第 283 轮：提示词版本化时正文已从 `AIGCMediaAgent._SELECTION_TRANSLATE_SYSTEM`
      归位到 `modules/aigc_media/prompts.py`（注册表键 `aigc_selection_translate`）。
      本用例原先仍读那个**已删除的类属性** ⇒ AttributeError。
    """
    from modules.aigc_media.prompts import AIGC_SELECTION_TRANSLATE_SYSTEM

    sp = AIGC_SELECTION_TRANSLATE_SYSTEM
    assert "只输出译文" in sp
    assert "不要解释" in sp
    assert "主动降噪" in sp, "电商术语惯例是划词翻译的核心价值，不能被删"
    assert "原样保留" in sp, "型号/规格必须保留"


# ============================================================
# 同语言短路（第 364 轮）
# ============================================================

def test_detect_lang_is_public_and_old_private_name_is_gone():
    """★ 改名的反向保护：`lang_guard` 要消费它，所以它必须是**公开名**。

    谁把名字改回 `_detect_lang`（或删掉），这条立刻红；否则消费方只会在
    **运行期**以 `AttributeError` 现形 —— 静态检查看不见这种动态面。
    """
    assert hasattr(AIGCMediaAgent, "detect_lang")
    assert not hasattr(AIGCMediaAgent, "_detect_lang"), "旧私有名不该再存在（会变成两个真源）"


def test_language_rule_has_exactly_one_source():
    """方向判定只有一个真源：`AIGCMediaAgent.detect_lang`。

    `lang_guard` 里**不许**再写一份「含 CJK ⇒ zh」—— 这里按源码形态钉住
    （不是 grep 字面量：先 AST 取函数体，再找有没有独立语言判定痕迹）。
    """
    import ast

    from pkg_source import read_source

    src = read_source("modules/aigc_media/lang_guard.py")
    tree = ast.parse(src)
    # 该模块只应有 2 个顶层函数；判定逻辑只经由 agent 传入的 detect_lang
    funcs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    assert funcs == {
        "same_lang_result",
        "has_foreign_word",
        "guard_same_lang",
        "reconcile_noop",
        "_substantive_equal",
    }, funcs

    assert "detect_lang(" in src, "判据必须来自 agent.detect_lang"
    for ch in ("\u3400", "\u9fff"):
        assert ch not in src, "本模块不许自带语言判定表（那会是第二份实现）"


def test_guard_short_circuits_only_on_explicit_same_language():
    """`guard_same_lang` 的三态：命中 ⇒ 短路结果；auto/空/不同语言 ⇒ None（让路）。

    ★ 直接传**类**当 agent：`detect_lang` 是 classmethod，不吃实例 —— 这同时证明
      这条短路**不依赖任何实例状态**（无 LLM 客户端、无 session，纯函数判据）。
    """
    from modules.aigc_media import lang_guard

    hit = lang_guard.guard_same_lang(AIGCMediaAgent, "无线耳机", "zh")
    assert hit is not None
    assert hit["success"] is True
    assert hit["data"]["same_lang"] is True
    assert hit["data"]["translation"] == ""
    assert hit["data"]["degraded"] is False

    assert lang_guard.guard_same_lang(AIGCMediaAgent, "Wireless Earbuds", "zh") is None
    assert lang_guard.guard_same_lang(AIGCMediaAgent, "无线耳机", "ja") is None
    # auto / 空 ⇒ 交给 agent 自己解析（在别处再解析一次就是第二份方向实现）
    assert lang_guard.guard_same_lang(AIGCMediaAgent, "无线耳机", "auto") is None
    assert lang_guard.guard_same_lang(AIGCMediaAgent, "无线耳机", "") is None
    assert lang_guard.guard_same_lang(AIGCMediaAgent, "   ", "zh") is None


# ============================================================
# 混合语言：中文夹外文词（第 365 轮）
# ============================================================

def test_guard_lets_mixed_text_through():
    """★ 夹了拉丁字母 ⇒ **不短路**，交给模型。

    老板实测（2026-10-02 20:00）：「我选择的是『这个 listing』，翻译结果应该是
    『该商品链接』，目前是否识别为了全中文。」—— 是的：二值判据把它整段判成 zh，
    于是一次都不译。而跨境电商场景里「中文夹英文词」是常态。
    """
    from modules.aigc_media import lang_guard

    for mixed in ("这个 listing", "这个 Noise Cancelling 耳机", "帮我改下这个 listing，谢谢"):
        assert lang_guard.guard_same_lang(AIGCMediaAgent, mixed, "zh") is None, mixed
    assert lang_guard.has_foreign_word("这个 listing") is True
    assert lang_guard.has_foreign_word("这个商品") is False
    # 纯中文仍然短路（这条是防止「放行」放过头）
    assert lang_guard.guard_same_lang(AIGCMediaAgent, "这个商品", "zh") is not None


@pytest.mark.asyncio
async def test_mixed_text_is_translated_with_term_render(stub_llm):
    """★ 主场景：中文夹英文术语 → 外文那部分被落成中文（这是本能力对跨境卖家的价值）"""
    stub_llm["box"]["reply"] = "这款主动降噪耳机"
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="这个 Noise Cancelling 耳机")
    )
    d = res["data"]
    assert len(stub_llm["calls"]) == 1, "夹了外文词就必须真的翻，别再短路"
    assert d["translation"] == "这款主动降噪耳机"
    assert d.get("same_lang", False) is False
    assert d["degraded"] is False


@pytest.mark.asyncio
async def test_model_echoing_mixed_text_falls_back_to_same_lang(stub_llm):
    """★ 模型把混合文本**原样退回** ⇒ 归回 `same_lang`（不是「翻了个一模一样的」）。

    实测：「店管家 AI」这种「纯中文 + 英文缩写」，模型原样返回。此时若照常显示译文，
    界面会出现「中文 → 中文」这种自相矛盾的方向徽标。
    """
    stub_llm["box"]["reply"] = "店管家 AI"
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="店管家 AI")
    )
    d = res["data"]
    assert d["same_lang"] is True
    assert d["translation"] == ""
    assert d["degraded"] is False          # ★ 不是故障
    assert len(stub_llm["calls"]) == 1, "这一步不额外花钱：只比对已有输出，不加调用"


@pytest.mark.parametrize(
    "a,b,same",
    [
        ("店管家 AI", "店管家 ai", True),           # 忽略大小写
        ("店管家 AI", " 店管家 AI。 ", True),       # 忽略空白与标点
        ("这个 listing", "该商品链接", False),
        ("", "", False),                            # 空串不算「实质相同」（防判据恒真）
        ("", "店管家 AI", False),
    ],
)
def test_substantive_equal(a, b, same):
    """「实质相同」的判据本身：抹空白/标点、忽略大小写；**空串一律 False**"""
    from modules.aigc_media import lang_guard

    assert lang_guard._substantive_equal(a, b) is same


@pytest.mark.asyncio
async def test_endpoint_translates_mixed_text(client, auth_off, stub_llm):
    """端点级：混合文本不再返回空译文"""
    stub_llm["box"]["reply"] = "该商品链接"
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "这个 listing"},
    )
    assert r.status_code == 200, r.text
    body = r.json()["response"]
    assert body["translation"] == "该商品链接"
    assert body.get("same_lang", False) is False


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
async def test_endpoint_exposes_same_lang_for_chinese_text(client, auth_off, stub_llm):
    """端点必须把 `same_lang` 透出去 —— 前端靠它显示「已是中文」。

    ★ 不能只看外层 `success`（这里是 True）也不能只看 `translation`（这里是空串，
      与「降级」长得一样），必须有一个**显式字段**说明「没翻是因为不需要翻」。
    """
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "这款保温杯的容量是多少"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["response"]["same_lang"] is True
    assert body["response"]["translation"] == ""
    assert body["response"]["degraded"] is False
    assert stub_llm["calls"] == []


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
