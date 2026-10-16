"""店铺术语表（第 369 轮 P0）测试
=================================
覆盖 `modules/aigc_media/glossary.py`（纯函数）以及它接进划词链路后的行为。

设计约定（改实现前先看这里）：
- **空表 ⇒ 渲染空串**（连标题都不拼）⇒ 提示词与「术语表上线前」**逐字相同**。
  基线不是手写的：`.workbuddy/probes/r369/baseline_prompt.py` 在改动前实测打印过它。
- 术语表是 **user prompt** 的一段，**不进 system prompt**。
  `register_prompt_template` 会按正文反解 `{var}` 占位符并在缺变量时抛
  `PromptVariableMissing`；把占位符写进 system 模板 ⇒ 全仓调用方被迫传参 +
  提示词指纹变化。这条约定由 `test_system_prompt_is_untouched_by_glossary` 钉住。
- 解析**宽松跳错**：非法行既不报错也不注入；同名词取首次出现；条数有上限。
- 提示词拼装**只有一处实现**（`glossary.build_selection_prompt`）。
  `agent_aigc.py` 是体量棘轮冻结项（上限 1849），拼装留两处会同时撞门禁。

全部用例都打桩，不发起真实 LLM 请求。
"""

import ast

import pytest

from modules.aigc_media import glossary as gl
from modules.aigc_media.agent_aigc import AIGCMediaAgent
from modules.aigc_media.schemas import SelectionTranslateRequest
from modules.aigc_media.service import AIGCMediaService
from pkg_source import read_source


# ============================================================
# 打桩（与 test_selection_translate.py 同一手法：记录 kwargs）
# ============================================================

@pytest.fixture
def stub_llm(monkeypatch):
    """替换 `_llm_generate_text`（划词链路的唯一 LLM 出口）。"""
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


#: 改动前实测的提示词（**基线**，从 probe 输出逐字复制，不是凭记忆手写）。
#: 来源：`python .workbuddy/probes/r369/baseline_prompt.py`（在 backend/ 下跑）。
LEGACY_PROMPT = (
    "目标语言：简体中文\n"
    "上下文：ecommerce\n\n"
    "原文：\nPortable Mini Humidifier for Bedroom Desk USB Cool Mist"
)


# ============================================================
# parse_glossary：宽松跳错
# ============================================================

def test_parse_basic_lines():
    entries = gl.parse_glossary(
        "Noise Cancelling=主动降噪\nWaterproof=防水\n"
    )
    assert entries == [("Noise Cancelling", "主动降噪"), ("Waterproof", "防水")]


def test_parse_accepts_fullwidth_separator():
    """中文输入法下 `＝` 很容易打出来，不认它就等于这条术语静默失效。"""
    assert gl.parse_glossary("Gift Box＝礼盒装") == [("Gift Box", "礼盒装")]


def test_parse_skips_blank_and_comment_lines():
    entries = gl.parse_glossary(
        "# 耳机类\n"
        "\n"
        "   \n"
        "Noise Cancelling=主动降噪\n"
        "# 箱包类\n"
        "Gift Box=礼盒装\n"
    )
    assert entries == [("Noise Cancelling", "主动降噪"), ("Gift Box", "礼盒装")]


@pytest.mark.parametrize("bad", ["没有等号的一行", "=只有译文", "只有原文=", "= ", "  =  "])
def test_parse_skips_malformed_lines_without_raising(bad):
    """残缺行**既不报错也不注入** —— 用户笔误不该升级成划词故障，也不该污染提示词。"""
    assert gl.parse_glossary(bad) == []


def test_parse_keeps_first_occurrence_on_duplicate():
    """同名词取**首次**出现：用户把新写法写在上面覆盖下面留的旧行，是更常见的用法。"""
    entries = gl.parse_glossary("Earbuds=耳机\nEarbuds=耳塞\n")
    assert entries == [("Earbuds", "耳机")]


def test_parse_splits_on_first_separator_only():
    """译文里带 `=` 不该被二次切开（按第一个分隔符切）。"""
    assert gl.parse_glossary("Note=A=B") == [("Note", "A=B")]


def test_parse_caps_entry_count():
    raw = "\n".join(f"term{i}=译{i}" for i in range(gl.MAX_ENTRIES + 50))
    assert len(gl.parse_glossary(raw)) == gl.MAX_ENTRIES


@pytest.mark.parametrize("empty", ["", "   ", "\n\n", None])
def test_parse_empty_input_yields_nothing(empty):
    assert gl.parse_glossary(empty) == []


# ============================================================
# render_glossary_block：空表必须是**空串**（连标题都不拼）
# ============================================================

@pytest.mark.parametrize("empty", ["", "   ", "\n\n", "# 只有注释\n", "非法行没有等号\n"])
def test_render_empty_table_is_empty_string(empty):
    """★ 契约 1：表空（或全是跳过的行）⇒ 返回 `""`。

    若这里返回了「术语表（…）：\n\n」这种只剩标题的段落，提示词就与上线前不同了，
    等于给每个没配术语表的用户白塞一段噪声。
    """
    assert gl.render_glossary_block(empty) == ""


def test_render_non_empty_block_shape():
    block = gl.render_glossary_block("Noise Cancelling=主动降噪\nWaterproof=防水")
    assert block.startswith("术语表（")
    assert "Noise Cancelling → 主动降噪" in block
    assert "Waterproof → 防水" in block
    assert block.endswith("\n\n"), "尾部空行是排版契约：块与「原文：」之间要空一行"


# ============================================================
# build_selection_prompt：空表 ⇒ 逐字不变（向后兼容）
# ============================================================

def test_empty_glossary_prompt_is_byte_identical_to_legacy():
    """★ 最重要的那条：没配术语表时，提示词与第 369 轮之前**逐字相同**。

    期望值是**实测基线**（`LEGACY_PROMPT`，取自改动前的 probe 输出），不是照抄实现。
    这条同时等价于「老调用方零行为变化」——`glossary` 默认空串走的就是这条路。
    """
    got = gl.build_selection_prompt(
        "简体中文", "ecommerce", "Portable Mini Humidifier for Bedroom Desk USB Cool Mist"
    )
    assert got == LEGACY_PROMPT


def test_glossary_block_sits_between_context_and_source():
    got = gl.build_selection_prompt("简体中文", "ecommerce", "Wireless Earbuds", "Wireless=无线")
    assert got.startswith("目标语言：简体中文\n上下文：ecommerce\n\n")
    assert "- Wireless → 无线\n\n原文：\nWireless Earbuds" in got
    assert got.endswith("原文：\nWireless Earbuds"), "原文必须仍在最后（模型读最后一段最稳）"


def test_prompt_header_unaffected_by_glossary():
    """有术语表时，前两行（目标语言 / 上下文）不许被改动。"""
    with_g = gl.build_selection_prompt("日语", "listing", "Earbuds", "Earbuds=耳机")
    without = gl.build_selection_prompt("日语", "listing", "Earbuds")
    head = "目标语言：日语\n上下文：listing\n\n"
    assert with_g.startswith(head) and without.startswith(head)


# ============================================================
# 「拼装只住一处」——AST 形态判据（剥 docstring）
# ============================================================

def _string_constants(rel: str) -> list:
    """AST 取某源码里所有字符串字面量，**排除 docstring**。

    ★ 为什么剥 docstring：docstring 在 AST 里也是 `ast.Constant`，
      不排除的话「本模块不许出现 XXX 字面量」这类判据会被自己的说明文字打假。
      做法：Module/ClassDef/FunctionDef 的 body[0] 若是裸字符串表达式，按 `id()` 剔除。
    """
    tree = ast.parse(read_source(rel))
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docs.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs
    ]


def test_prompt_template_lives_in_exactly_one_file():
    """提示词模板（`目标语言：` 那段）只许住 `glossary.py`。

    判据分两半：agent 那里必须**一个都没有**（否则又是两份实现，且会把
    `agent_aigc.py` 推过体量棘轮上限），`glossary.py` 那里**恰好一个**。
    """
    agent_hits = [s for s in _string_constants("modules/aigc_media/agent_aigc.py") if "目标语言" in s]
    assert agent_hits == [], f"agent 里又出现了提示词模板：{agent_hits}"

    gl_hits = [s for s in _string_constants("modules/aigc_media/glossary.py") if "目标语言" in s]
    assert len(gl_hits) == 1, f"glossary.py 里的模板份数不是 1：{gl_hits}"


def test_agent_actually_calls_the_single_source():
    """★ 上面那条只证「agent 里没有旧模板」，不证「agent 真的用了新函数」。

    两者合起来才闭环：删掉旧实现却没接上新实现，会让**全部**提示词契约用例
    仍然通过（因为它们走的是 service → agent 的同一入口，而 mock 打的是
    `_llm_generate_text`，prompt 变成什么都没人看）。
    """
    tree = ast.parse(read_source("modules/aigc_media/agent_aigc.py"))
    called = {
        n.func.id
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }
    assert "build_selection_prompt" in called


def test_glossary_module_surface_is_closed():
    """本模块的对外函数集是封闭的：多一个就该先问「它是不是第二份实现」。"""
    tree = ast.parse(read_source("modules/aigc_media/glossary.py"))
    funcs = {
        n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert funcs == {"parse_glossary", "render_glossary_block", "build_selection_prompt"}, funcs


def test_glossary_module_owns_no_language_detection():
    """术语表模块**不做语言判定**（那是 `AIGCMediaAgent.detect_lang` 的职责）。

    同 `lang_guard.py` 的既有判据：CJK 码点区间只以 `\\uXXXX` 形式存在于代码里，
    这里按该形态钉住（出现即说明又长出了第二份方向实现）。
    """
    src = read_source("modules/aigc_media/glossary.py")
    for ch in ("\u3400", "\u9fff"):
        assert ch not in src, "术语表模块不许自带语言判定表"


# ============================================================
# 接线：术语表真的到达 prompt（且不污染 system / 响应）
# ============================================================

@pytest.mark.asyncio
async def test_glossary_reaches_the_prompt(stub_llm):
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Gift Box for Birthday", glossary="Gift Box=礼盒装")
    )
    prompt = stub_llm["calls"][0]["prompt"]
    assert "- Gift Box → 礼盒装" in prompt
    assert res["success"] is True


@pytest.mark.asyncio
async def test_absent_glossary_adds_nothing_to_prompt(stub_llm):
    """★ 不传术语表 ⇒ 提示词里**根本不该出现**「术语表」三个字（空表零成本）。"""
    await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Gift Box for Birthday")
    )
    prompt = stub_llm["calls"][0]["prompt"]
    assert "术语表" not in prompt
    assert prompt.endswith("原文：\nGift Box for Birthday")


@pytest.mark.asyncio
async def test_malformed_glossary_adds_nothing_to_prompt(stub_llm):
    """★ 全是解析不出来的行 ⇒ 等价于没配术语表（不能只剩一个空标题）。"""
    await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Gift Box", glossary="这一行没有等号\n=只有译文")
    )
    assert "术语表" not in stub_llm["calls"][0]["prompt"]


@pytest.mark.asyncio
async def test_system_prompt_is_untouched_by_glossary(stub_llm):
    """★ 术语表**不许**进 system prompt。

    进了 system ⇒ 注册表把它当成模板变量 ⇒ 提示词指纹随用户配置浮动，
    `prompt_versions` 对账立刻失去意义；而且没配术语表的用户也会因为
    「模板变了」而被算成一次提示词变更。
    """
    await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Gift Box", glossary="Gift Box=礼盒装")
    )
    system_prompt = stub_llm["calls"][0]["system_prompt"]
    assert "术语表" not in system_prompt
    assert "Gift Box=礼盒装" not in system_prompt


@pytest.mark.asyncio
async def test_glossary_is_not_echoed_in_response(stub_llm):
    """术语表是**入参**，不该出现在响应里（响应结构是划词专用的窄结构）。"""
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="Gift Box", glossary="Gift Box=礼盒装")
    )
    assert "glossary" not in res["data"]


@pytest.mark.asyncio
async def test_same_lang_short_circuit_still_wins_over_glossary(stub_llm):
    """纯中文 + 目标中文 ⇒ 仍然短路，**一次 LLM 都不调**（术语表不改变这条）。"""
    res = await AIGCMediaService.translate_selection(
        SelectionTranslateRequest(text="无线蓝牙耳机", glossary="Noise Cancelling=主动降噪")
    )
    assert res["data"]["same_lang"] is True
    assert stub_llm["calls"] == []


# ============================================================
# 端点
# ============================================================

@pytest.mark.asyncio
async def test_endpoint_accepts_and_uses_glossary(client, auth_off, stub_llm):
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Gift Box for Birthday", "glossary": "Gift Box=礼盒装"},
    )
    assert r.status_code == 200, r.text
    assert "- Gift Box → 礼盒装" in stub_llm["calls"][0]["prompt"]
    assert "glossary" not in r.json()["response"]


@pytest.mark.asyncio
async def test_endpoint_works_without_glossary_field(client, auth_off, stub_llm):
    """老客户端（不带 `glossary` 字段）必须继续工作 —— 字段有默认值。"""
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Gift Box for Birthday"},
    )
    assert r.status_code == 200, r.text
    assert "术语表" not in stub_llm["calls"][0]["prompt"]


@pytest.mark.asyncio
async def test_endpoint_rejects_overlong_glossary(client, auth_off, stub_llm):
    """术语表有长度上限（自由文本域不该成为烧 token 的入口）。"""
    r = await client.post(
        "/api/v1/aigc/content/translate-selection",
        json={"text": "Gift Box", "glossary": "a" * 4001},
    )
    assert r.status_code == 422, r.text
    assert stub_llm["calls"] == [], "被 schema 拦下时不该已经花钱调 LLM"
