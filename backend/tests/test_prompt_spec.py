"""第 283 轮 A 档：提示词规格（版本 / 指纹 / 变量契约）的判据与门禁。

为什么单独成文件
----------------
提示词此前是「住 .py 常量里的裸字符串」：没有版本、没有指纹、变量靠猜，
改了之后**没有任何一处会报错**，也不会有任何日志留下痕迹。
本文件的每一条判据都对应一个具体的失效形态：

* `fingerprint` —— 回答「线上跑的是哪一版」；
* `required_vars` —— 回答「这个模板到底要传什么」；
* 重名拒绝 —— 回答「两份提示词撞名时谁生效」；
* 正文归位 —— 回答「提示词能不能被对账 / 被覆写」。

★ 最后一条 `test_stray_prompt_gate_is_not_vacuous` 是**门禁自检**：
  没有它，「扫描器正则写错」与「没有违规」在读数上完全一样（都返回空列表）。
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest
from loguru import logger as _loguru

BACKEND = pathlib.Path(__file__).resolve().parent.parent

#: 正文长度阈值：短字符串（如 `NEGATIVE_PROMPT`）不算「模板正文」
BODY_MIN_CHARS = 200

_NAME_RE = re.compile(r"PROMPT|INSTRUCTIONS|TEMPLATE", re.I)


# --------------------------------------------------------------- 扫描器（门禁）

def _scan_text(text: str) -> list:
    """一段源码里「prompts.py 之外」的提示词正文常量。"""
    out = []
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or not _NAME_RE.search(target.id):
            continue
        if not (isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)):
            continue
        if len(node.value.value) >= BODY_MIN_CHARS:
            out.append((target.id, node.lineno, len(node.value.value)))
    return out


def scan_stray_prompts() -> list:
    """`modules/**` 下 `prompts.py` 之外的提示词正文常量。

    ★ 判据形态：模块级 / 类级 *赋值* 给名字里含 PROMPT|INSTRUCTIONS|TEMPLATE
      的字符串常量，长度 ≥ 200。
      只看 `prompts.py` 之外的文件 —— 正文**住进** `prompts.py` 是允许的（那是它的家）。
    """
    offenders = []
    for path in (BACKEND / "modules").rglob("*.py"):
        if path.name == "prompts.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):  # pragma: no cover
            continue
        for name, lineno, size in _scan_text(text):
            rel = path.relative_to(BACKEND).as_posix()
            offenders.append(f"{rel}:{lineno} {name} ({size} chars)")
    return offenders


# --------------------------------------------------------------- 1. 规格本身

def test_fingerprint_is_content_derived_and_stable():
    """指纹由正文算出：同文同指纹，改一个字符就变。"""
    from ai_infra.llm import PromptSpec

    a = PromptSpec(name="x", content="你是选品专家", version="1")
    b = PromptSpec(name="x", content="你是选品专家", version="2")
    c = PromptSpec(name="x", content="你是选品专家。", version="1")

    assert len(a.fingerprint) == 12
    assert a.fingerprint == b.fingerprint, "version 不该改变指纹（指纹回答的是文本变没变）"
    assert a.fingerprint != c.fingerprint, "正文改了一个字符，指纹必须变"


def test_required_vars_only_accepts_identifiers():
    """只有标识符形态才是变量；JSON 示例 / 空 `{}` / 位置参数都不算。"""
    from ai_infra.llm import PromptSpec

    spec = PromptSpec(
        name="x",
        content='市场={market} 示例={"section": "运营偏好"} 空={} 位置={0}',
    )
    assert spec.required_vars == ("market",)


def test_json_example_survives_rendering():
    """渲染只替换已声明变量，JSON 示例的花括号必须**原样**发给模型。

    ★ 活样本取自本仓真实提示词（`modules/memory/prompts.py::EXTRACT_INSTRUCTIONS`），
      它正文里有一整段 JSON 示例 —— 用 `str.format` 渲染它必然抛 `KeyError`。
    """
    from ai_infra.llm import PromptSpec
    from modules.memory.prompts import EXTRACT_INSTRUCTIONS

    spec = PromptSpec(name="memory_extract_probe", content=EXTRACT_INSTRUCTIONS)
    rendered = spec.render()
    assert rendered == EXTRACT_INSTRUCTIONS, "JSON 示例被渲染改动了"
    assert "{" in EXTRACT_INSTRUCTIONS, "样本本身应当含花括号（否则这条用例是空跑）"


def test_missing_variable_raises_instead_of_sending_placeholder():
    """缺变量必须显式失败，不许把 `{market}` 原样发给模型。"""
    from ai_infra.llm import PromptSpec, PromptVariableMissing

    spec = PromptSpec(name="x", content="你是 {market} 市场的分析师")
    with pytest.raises(PromptVariableMissing):
        spec.render()


def test_declared_vars_must_match_body():
    """声明与正文反解不一致 ⇒ 注册期就报错（不让契约漂到运行期）。"""
    from ai_infra.llm import PromptSpec, PromptSpecError

    with pytest.raises(PromptSpecError):
        PromptSpec(name="x", content="无变量的正文", required_vars=("market",))


def test_unpaired_brace_is_rejected_at_registration():
    """花括号不配对 ⇒ 注册期报错（好过运行期才炸，那时它已经在线上了）。"""
    from ai_infra.llm import PromptSpecError, extract_required_vars

    with pytest.raises(PromptSpecError):
        extract_required_vars("正文里有个落单的 { 括号")


def test_rendered_prompt_is_a_str():
    """渲染结果必须是 `str` —— 12 处 `system_prompt=get_prompt_template(...)` 靠这个零改动。"""
    from ai_infra.llm import PromptSpec

    spec = PromptSpec(name="x", content="你是 {market} 分析师", version="3")
    got = spec.render(market="全球")
    assert isinstance(got, str)
    assert got == "你是 全球 分析师"
    assert got.version == "3" and got.fingerprint == spec.fingerprint


# --------------------------------------------------------------- 2. 注册表

def test_duplicate_registration_is_rejected():
    """重名**当场拒绝** —— 静默覆盖会让先注册的那份悄悄消失且无人报错。

    ★ 判据与 `ai_infra.prompt_sections.register_prompt_section` 同源：
      同样是「重名 → ValueError」。下面顺带把两者对着测，防止它们再次漂移。
    """
    from ai_infra.llm import PROMPT_TEMPLATES, register_prompt_template

    key = "__dup_probe__"
    register_prompt_template(key, "第一份正文")
    try:
        with pytest.raises(ValueError):
            register_prompt_template(key, "第二份正文")
        assert PROMPT_TEMPLATES[key].content == "第一份正文", "被覆盖就等于没拦住"
    finally:
        PROMPT_TEMPLATES.pop(key, None)


def test_duplicate_policy_matches_prompt_sections():
    """两张注册表的「重名怎么办」必须是**同一个答案**。"""
    import ai_infra.prompt_sections as ps
    from ai_infra.llm import PROMPT_TEMPLATES, register_prompt_template

    sec = "__dup_section__"
    tpl = "__dup_template__"
    ps.register_prompt_section(sec, lambda ctx: "")
    register_prompt_template(tpl, "正文")
    try:
        with pytest.raises(ValueError):
            ps.register_prompt_section(sec, lambda ctx: "")
        with pytest.raises(ValueError):
            register_prompt_template(tpl, "另一份")
    finally:
        ps._SECTIONS.pop(sec, None)
        PROMPT_TEMPLATES.pop(tpl, None)


def test_unregistered_name_raises_keyerror():
    from ai_infra.llm import get_prompt_spec, get_prompt_template

    with pytest.raises(KeyError):
        get_prompt_template("__no_such_prompt__")
    with pytest.raises(KeyError):
        get_prompt_spec("__no_such_prompt__")


# --------------------------------------------------------------- 3. 归位结果

@pytest.mark.parametrize(
    "key,module",
    [
        ("ad_analysis", "modules.ad_analysis.prompts"),
        ("listing_generator", "modules.listing_generator.prompts"),
        ("product_research", "modules.product_research.prompts"),
        ("product_research_system", "modules.product_research.prompts"),
        ("secretary", "modules.secretary.prompts"),
        ("aigc_selection_translate", "modules.aigc_media.prompts"),
        ("aigc_enhance_prompt", "modules.aigc_media.prompts"),
        ("skills_icon", "modules.skills.prompts"),
    ],
)
def test_migrated_prompts_are_registered_with_fingerprint(key, module):
    """第 283 轮归位的 8 份提示词：注册可达 + 指纹可指认。"""
    __import__(module)
    from ai_infra.llm import get_prompt_spec

    spec = get_prompt_spec(key)
    assert spec.content.strip()
    assert re.fullmatch(r"[0-9a-f]{12}", spec.fingerprint), spec.fingerprint


def test_secretary_prompt_is_served_from_registry():
    """店秘书运行时那份**就是**注册表里的那份（而不是另一份同名常量）。

    ★ 为什么必须钉：`agent.py` 仍 re-export `SECRETARY_SYSTEM_PROMPT`
      （既有用例从那里取），于是「两份内容」可以静默漂移。
    """
    from ai_infra.llm import get_prompt_template
    from modules.secretary.agent import SECRETARY_SYSTEM_PROMPT

    assert get_prompt_template("secretary") == SECRETARY_SYSTEM_PROMPT


# --------------------------------------------------------------- 4. 归位门禁

def test_no_prompt_body_outside_prompts_module():
    """提示词正文不得散落在 `prompts.py` 之外（散落 ⇒ 无法对账 / 无法覆写）。"""
    offenders = scan_stray_prompts()
    assert not offenders, "以下位置仍有提示词正文，请归位到同模块的 prompts.py：\n  " + "\n  ".join(
        offenders
    )


def test_stray_prompt_gate_is_not_vacuous():
    """★ 门禁自检：人造违规必须被抓到，干净样本不得误报。

    没有这条，扫描器写错 ⇒ 恒绿 ⇒ 等于没有门禁。
    """
    body = "你是跨境电商选品专家" * 30  # 300 字符
    dirty = f'MY_SYSTEM_PROMPT = """{body}"""\n'
    assert _scan_text(dirty), "违规样本没被抓到（扫描器漏报）"

    clean = 'MY_SYSTEM_PROMPT = "短"\n'
    assert not _scan_text(clean), "短字符串被误报"

    # ★ 样本名里**不能**出现 prompt 这个词（正则大小写不敏感，`NOT_A_PROMPT_NAME`
    #   也会被匹配到 —— 首跑就是这么红的，留作注释以免有人再踩）
    unnamed = f'SOME_LONG_TEXT = """{body}"""\n'
    assert not _scan_text(unnamed), "名字不含 PROMPT/INSTRUCTIONS/TEMPLATE 的常量被误报"


# ----------------------------------------------------------- 5. 留痕（L3-4）

def _capture_loguru(level: str = "INFO"):
    """把 loguru 的 `level` 及以上收进列表（返回 `(messages, handler_id)`）。

    ★ **不要用 pytest 的 `caplog`**：它抓的是 stdlib `logging`，而
      `core.logger.get_logger()` 返回的是 **loguru** —— 本仓两套日志栈并存。
      用 caplog 抓 loguru 会「抓不到、但不报错」，于是这条判据永远假绿
      （同款注释见 `tests/test_llm_model_routing.py::_capture_loguru`）。

    ★ 默认级别取 **INFO 而不是 DEBUG**：这本身就是判据的一半 —— 留痕必须在
      **生产默认级别**就可见（`core/logger.py::_add_sinks`：非 debug 时 INFO）。
    """
    messages: list = []

    def sink(message):  # pragma: no cover - 纯转发
        messages.append(message.record["message"])

    handler_id = _loguru.add(sink, level=level)
    return messages, handler_id


def test_render_emits_fingerprint_trace_at_info_level():
    """★ 渲染必须留痕，且**在 INFO 级就能看到**。

    A 档给了 `version` / `fingerprint`，但只要**没有任何一处把它打出来**，
    这套元数据在生产上就等于不存在 —— 回答质量突变时仍然只能翻 git log 猜。
    用 INFO 抓（而不是 DEBUG）守的正是「别把它写成 DEBUG ⇒ 线上永远不打印」。
    """
    from ai_infra.llm import PromptSpec, render_prompt

    spec = PromptSpec(name="trace_probe", content="你是 {market} 分析师", version="7")
    messages, handler_id = _capture_loguru("INFO")
    try:
        render_prompt(spec, market="全球")
    finally:
        _loguru.remove(handler_id)

    joined = "\n".join(messages)
    assert messages, "渲染没有留下任何 INFO 日志（是不是写成 DEBUG 了？）"
    assert "trace_probe" in joined, f"留痕里没有提示词名：{messages}"
    assert spec.fingerprint in joined, f"留痕里没有指纹 —— 答不出「跑的是哪一版」：{messages}"
    assert "v7" in joined, f"留痕里没有版本：{messages}"


def test_render_trace_follows_the_content():
    """留痕里的指纹必须**跟着正文走** —— 否则它只是个恒定的装饰串。"""
    from ai_infra.llm import PromptSpec, render_prompt

    a = PromptSpec(name="trace_probe2", content="你是 {market} 分析师")
    b = PromptSpec(name="trace_probe2", content="你是 {market} 分析师。")  # 只差一个句号
    assert a.fingerprint != b.fingerprint, "夹具前提：改一个字符指纹就应变"

    seen = []
    for spec in (a, b):
        messages, handler_id = _capture_loguru("INFO")
        try:
            render_prompt(spec, market="全球")
        finally:
            _loguru.remove(handler_id)
        seen.append("\n".join(messages))

    assert a.fingerprint in seen[0] and b.fingerprint in seen[1]
    assert a.fingerprint not in seen[1], "正文改了，留痕里的指纹却没跟着变"


def test_render_trace_logs_variable_names_but_not_values():
    """只记**变量名**、不记变量值 —— 值是业务数据，日志不该承载它。"""
    from ai_infra.llm import PromptSpec, render_prompt

    secret = "SECRET-VALUE-FROM-SHOP-FACT"
    spec = PromptSpec(name="trace_probe3", content="本轮事实：{shop_fact}")
    messages, handler_id = _capture_loguru("INFO")
    try:
        render_prompt(spec, shop_fact=secret)
    finally:
        _loguru.remove(handler_id)

    joined = "\n".join(messages)
    assert "shop_fact" in joined, f"变量名应出现在留痕里（否则不知道渲染了什么）：{messages}"
    assert secret not in joined, f"变量值泄漏进了日志：{messages}"


# --------------------------------------------- 6. 返回注解不得擦除（L3-4）

def _return_annotation(src: str, func_name: str, cls: str | None = None) -> str | None:
    """取 `func_name` 的返回注解源码文本（`cls=None` 取模块级函数）。

    ★ 返回**源码文本**（`ast.unparse`）而不是求值结果：注解写成字符串
      （`-> "RenderedPrompt"`）时求值会 `NameError`，而本仓正是这么写的。
    """
    tree = ast.parse(src)
    scope = tree.body
    if cls is not None:
        node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        scope = node.body
    for n in scope:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == func_name:
            return None if n.returns is None else ast.unparse(n.returns)
    raise AssertionError(f"没找到 {cls or '<module>'}.{func_name}")


def test_prompt_template_return_annotation_is_not_erased():
    """三处同名 `get_prompt_template` 的返回注解都必须是 `RenderedPrompt`。

    ★ 为什么钉注解而不是钉运行期：`RenderedPrompt` **是** `str` 的子类，
      所以「返回值的运行期类型」在这件事上**永远判不出来**
      （`isinstance(x, str)` 对两者都为真）。L3-4 报的就是「注解把元数据擦除了」，
      而注解只在静态层面可见 —— 判据也就只能落在静态层面。
    """
    llm_src = (BACKEND / "ai_infra" / "llm" / "dashscope_client.py").read_text(encoding="utf-8")
    agent_src = (BACKEND / "ai_infra" / "base_agent.py").read_text(encoding="utf-8")

    got = {
        "DashScopeLLM.get_prompt_template": _return_annotation(
            llm_src, "get_prompt_template", "DashScopeLLM"),
        "llm.get_prompt_template": _return_annotation(llm_src, "get_prompt_template"),
        "BaseAgent.get_prompt_template": _return_annotation(
            agent_src, "get_prompt_template", "BaseAgent"),
    }
    bad = {k: v for k, v in got.items() if (v or "").strip("'\"") != "RenderedPrompt"}
    assert not bad, (
        f"返回注解把「是哪一版提示词」擦除了：{bad} —— 应为 RenderedPrompt"
        "（写成字符串亦可，只要指向同一个名字）"
    )


def test_return_annotation_gate_is_not_vacuous():
    """★ 门禁自检：人造 `-> str` 样本必须被抓到，合格样本不得误报。

    没有这条，「解析器写错」与「注解都合格」在读数上完全一样（都返回同一个值）。
    """
    dirty = "def get_prompt_template(name, **kw) -> str:\n    return 1\n"
    clean = 'def get_prompt_template(name, **kw) -> "RenderedPrompt":\n    return 1\n'
    assert _return_annotation(dirty, "get_prompt_template") == "str"
    assert _return_annotation(clean, "get_prompt_template").strip("'\"") == "RenderedPrompt"
