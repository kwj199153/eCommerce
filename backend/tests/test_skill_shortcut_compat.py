# -*- coding: utf-8 -*-
"""点名技能 ⇄ 关键词短路的兼容契约（第 246 轮 P0-a / P1 / P2）。

背景（实测复现，不是推测）
--------------------------
老板点复盘技能卡，5 张里 3 张返回**别的报表**。决定性对照：
同一条技能、消息换成不含关键词的「帮我看一下，按上面说的办法来做」——
不传 `skill` = 39 字反问；传 `skill` = **1019 字**技能驱动的答案
（含「### 四线指标表」这类技能正文的产物）。
⇒ 通道是通的，**只有被关键词短路时才失效**。

根因：**短路发生在技能注入之前**。技能正文 / 技能目录 / `load_skill` 工具
**全都住在 system prompt 里**（由 `BaseAgent` 的图构造，见
`ai_infra/base_agent.py` 的 `collect_prompt_sections` → `_system_prompt_with_plan`），
而关键词短路路径**不构造 prompt** —— 技能一次都没渲染。

本文件钉住那条不变量：
    **点名技能时，任何「不构造 system prompt 的短路」都不得抢先。**
    允许的结局只有两个：① 走技能通道（工具环路）；② 如实说通道不可用。

六组判据
--------
① 机制契约：`is_skill_requested()` 的行为（含作用域还原）+ 「判定只有一处」；
② 名单式：每个技能可落地的对话入口都必须**真的**引用它（AST，不是字符串包含）；
③ 顺序性质：技能通道（工具环路）必须排在关键词分类**之前**；
④ 行为对照：点名 ⇒ 走技能通道；未点名 ⇒ 原路径（**这是「零回归」的判据**）；
⑤ 跨端对账：后端 `display_type` ↔ 前端会话结论卡注册表 + 卡片消息形状；
⑥ 门禁非空跑自检（反向注入 ⇒ 必须转红）。

★ 为什么 ② 用 AST 的 `ast.Name` 而不是 `"is_skill_requested" in src`：
  本仓判据明确禁止「源码字符串包含」—— docstring 里写一句就能骗过（假绿）。
"""
import ast
import pathlib
import re

import pytest

from ai_infra.skills import bind_requested_skill, is_skill_requested

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
FRONTEND = REPO / "frontend"


# ================================================================ 判据 ①

def test_mechanism_default_is_false():
    """没人点名 ⇒ False。它是「未点名行为逐字不变」这条回归判据的前提。"""
    assert is_skill_requested() is False


async def test_mechanism_true_inside_scope_and_restored():
    """点名 ⇒ True；退出作用域 ⇒ **无条件还原**（异常路径同样还原）。

    ★ 还原不是装饰：ContextVar 的写入会顺着任务继承下去，一次请求设过之后
      不复位，同进程后续请求会继续沿用上一次的选择（本仓真实咬过人的形态）。
    """
    assert is_skill_requested() is False

    async with bind_requested_skill("review-weekly-brief"):
        assert is_skill_requested() is True
    assert is_skill_requested() is False

    with pytest.raises(RuntimeError):
        async with bind_requested_skill("x"):
            raise RuntimeError("boom")
    assert is_skill_requested() is False, "异常退出后没有还原点名状态"

    # 嵌套：内层退出 ⇒ 回到外层的选择，而不是 None
    async with bind_requested_skill("outer"):
        async with bind_requested_skill("inner"):
            assert is_skill_requested() is True
        assert is_skill_requested() is True, "内层退出把外层的点名一起清了"


async def test_blank_selection_means_not_requested():
    """空串 / 纯空白 / None 都收敛成「没点名」——「没点名」只有一种表示。"""
    for blank in ("", "   ", "\n\t", None):
        async with bind_requested_skill(blank):
            assert is_skill_requested() is False, "空白 %r 被当成了点名" % blank


#: 允许直接读**原始名字** `current_requested_skill()` 的两处：
#:   · 机制层自己（它就是这个 ContextVar 的定义者）；
#:   · 技能段的渲染点（`selected_skill_section.py`，它要拿名字去查正文）。
#: 其余任何地方要判「这次点名了没有」**只能用 `is_skill_requested()`** ——
#: 本仓「同一判定两份实现 ⇒ 至少一份永远测不到」。
#:
#: ★ 第 251 轮第 3 处（`context_target_gate.py`）：它读名字是为了**查表**
#:   （哪几条技能必须先有「作用对象」），不是重做布尔判定 ——
#:   那个判定它显式调 `is_skill_requested()`。名单式登记同源于
#:   `test_memory_injection.py` 的 `ALLOWED_SECTION_REGISTRARS`。
RAW_JUDGMENT_ALLOWED = {
    "ai_infra/skills.py",
    "modules/skills/selected_skill_section.py",
    "modules/product_research/context_target_gate.py",
}

SCAN_SKIP_DIRS = {
    "tests", ".venv", "__pycache__", "node_modules", ".git", "logs", "data",
    ".pytest_cache", "_attic", ".mypy_cache", "htmlcov",
}


def test_only_one_judgment_helper():
    """★ 全仓「是否点名」的布尔判定只有 `is_skill_requested()` 一处。"""
    offenders = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if any(part in SCAN_SKIP_DIRS for part in path.relative_to(BACKEND).parts):
            continue
        if rel in RAW_JUDGMENT_ALLOWED:
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        if "current_requested_skill" in src:
            offenders.append(rel)
    assert not offenders, (
        "这些文件自己拼了「是否点名」的判定，应改用 ai_infra.skills.is_skill_requested()：\n  "
        + "\n  ".join(offenders)
    )


# ================================================================ 判据 ②③

#: 技能名会被 `bind_requested_skill` 绑到、且**用户真的会从卡片点进来**的入口。
#: 每加一个「能点名」的对话入口，必须同步在这里登记 —— 只接线不登记 = 新开门禁真空区。
SKILL_GATED_ENTRIES = {
    "modules/review_analyst/agent.py": ("invoke",),
    "modules/product_research/agent_product_research.py": (
        "_invoke_impl",
        "_stream_chat_impl",
        "_resume_pending_save",
    ),
    "modules/listing_generator/agent_listing.py": ("stream_chat",),
    "modules/ad_analysis/agent_ad.py": ("stream_chat",),
    "modules/competitor_intel/agent_competitor.py": ("stream_chat",),
    "modules/customer_service/agent_cs.py": ("stream_chat",),
    "modules/aigc_media/agent_aigc.py": ("stream_chat",),
    "modules/aigc_media/service.py": ("chat_service",),
}

#: 「技能通道**已经**排在关键词分类之前」的入口 —— 值是该模块**分类器的属性名**。
#: 这四家不需要改代码 —— 但它们靠的是**顺序**，所以必须被门禁钉住：
#: 谁把 `_stream_via_tools` 挪到 `_classify_intent` 后面，就是重新制造本轮的 bug。
#: ★ `aigc_media` 的分类器是**公开名** `classify_intent` ——
#:   `modules/aigc_media/service.py` 直接 `agent.classify_intent(...)` 调用它，
#:   不允许改名（`test_intent_single_source.py` 的名单注释同一条）。
CHANNEL_FIRST = {
    "modules/ad_analysis/agent_ad.py": "_classify_intent",
    "modules/competitor_intel/agent_competitor.py": "_classify_intent",
    "modules/customer_service/agent_cs.py": "_classify_intent",
    "modules/aigc_media/agent_aigc.py": "classify_intent",
}
CHANNEL_ATTR = "_stream_via_tools"


def _find_fn(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _attr_name(func):
    """取调用目标的末段名：`self._stream_via_tools` → `_stream_via_tools`。"""
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return ""


def entry_gate_report(src: str, fn_name: str):
    """检查一个入口函数：返回 `(函数体引用判定?, 模块导入判定?, 说明)`。

    ★ 拆成「接受源码字符串」的纯函数，是为了让门禁自检（判据 ⑥）能把
      **反向注入的样本**喂进来 —— 只测真实文件的门禁无法证明它会红。
    """
    tree = ast.parse(src)
    imported = any(
        isinstance(n, ast.ImportFrom)
        and n.module == "ai_infra.skills"
        and any(a.name == "is_skill_requested" for a in n.names)
        for n in ast.walk(tree)
    )
    fn = _find_fn(tree, fn_name)
    if fn is None:
        return False, imported, "找不到函数 %s" % fn_name
    used = any(
        isinstance(n, ast.Name) and n.id == "is_skill_requested" for n in ast.walk(fn)
    )
    why = "" if used else "%s 里没有引用 is_skill_requested（点名时不会让路）" % fn_name
    return used, imported, why


def channel_precedes_keyword(src: str, fn_name: str, classify_attr: str = "_classify_intent") -> bool:
    """技能通道（`_stream_via_tools`）的最小行号 < 关键词分类的最小行号。"""
    fn = _find_fn(ast.parse(src), fn_name)
    assert fn is not None, "找不到函数 %s" % fn_name

    def _min_line(attr):
        lines = [
            n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and _attr_name(n.func) == attr
        ]
        return min(lines) if lines else None

    chan, cls = _min_line(CHANNEL_ATTR), _min_line(classify_attr)
    assert chan is not None, "%s 里没有调 %s" % (fn_name, CHANNEL_ATTR)
    assert cls is not None, "%s 里没有调 %s" % (fn_name, classify_attr)
    return chan < cls


def test_every_skill_entry_consults_the_judgment():
    """★ 名单式：每个能点名的对话入口都必须真的引用 `is_skill_requested()`。"""
    bad = []
    for rel, fns in sorted(SKILL_GATED_ENTRIES.items()):
        path = BACKEND / rel
        assert path.exists(), "登记了不存在的文件: %s" % rel
        src = path.read_text(encoding="utf-8", errors="replace")
        for fn_name in fns:
            used, imported, why = entry_gate_report(src, fn_name)
            if not imported:
                bad.append("%s: 未从 ai_infra.skills 导入 is_skill_requested" % rel)
            if not used:
                bad.append("%s / %s" % (rel, why))
    assert not bad, "点名时不会让路的对话入口：\n  " + "\n  ".join(bad)


def test_channel_precedes_keyword_classification():
    """★ 顺序性质：技能通道必须排在关键词分类之前（否则短路会抢在注入前）。"""
    bad = []
    for rel, classify_attr in CHANNEL_FIRST.items():
        src = (BACKEND / rel).read_text(encoding="utf-8", errors="replace")
        if not channel_precedes_keyword(src, "stream_chat", classify_attr):
            bad.append(rel)
    assert not bad, (
        "这些模块把关键词分类排在了技能通道（%s）之前 —— 点名时会被短路：\n  %s"
        % (CHANNEL_ATTR, "\n  ".join(bad))
    )


def test_product_research_sentinel_is_not_a_shortcut():
    """★ 「不短路」那一档写成 `general`，前提是它**不命中任何短路分支**。

    这是个**耦合前提**，不是巧合：若哪天有人把 `"general"` 加进
    `INTENT_SHORTCUTS`，PR 的点名让路会**静默失效**（点名变成走清点/挖矿）。
    """
    from modules.product_research import agent_product_research as pr

    assert "general" not in pr.INTENT_SHORTCUTS
    assert "general" not in pr.ProductResearchAgent._APPROVAL_GATED_INTENTS
    assert pr.QUERY_CANDIDATES_INTENT != "general"

    from modules.review_analyst import agent as rv

    assert "general" not in rv._SERVICE_CALLS


# ================================================================ 判据 ④

class _Recorder:
    """记录「点名期到底走了哪条路」。"""

    def __init__(self):
        self.calls = []

    def mark(self, name):
        self.calls.append(name)

    @property
    def routes(self):
        return self.calls.count("route")


def _review_with_skill(rec, query="本周周报"):
    from modules.review_analyst.agent import ReviewAnalystAgent
    from modules.review_analyst.schemas import ReviewChatResult

    agent = ReviewAnalystAgent()

    async def fake_route(query, context=None, session_id=None, user_id=None):
        rec.mark("route")
        return ReviewChatResult(reply="ROUTED")

    async def fake_one(intent, context=None):
        rec.mark("shortcut")
        return ReviewChatResult(reply="SHORTCUT")

    agent._route_via_tools = fake_route
    agent._run_one = fake_one
    return agent, query


async def test_review_named_skill_bypasses_keyword_shortcut():
    """★ 行为对照（review）：同一句**命中关键词**的话 ——

    未点名 ⇒ 走关键词短路（`_run_one`，改造前的行为，逐字不变）；
    点名   ⇒ 走技能通道（工具环路，唯一会构造 prompt 的路）。
    """
    rec = _Recorder()
    agent, query = _review_with_skill(rec)

    plain = await agent.invoke(query, shop_id="store_x")
    assert plain.reply == "SHORTCUT", "未点名的行为变了（这轮要求逐字不变）"
    assert rec.routes == 0

    rec.calls.clear()
    async with bind_requested_skill("review-weekly-brief"):
        named = await agent.invoke(query, shop_id="store_x")
    assert named.reply == "ROUTED", "点名后没有让路给技能通道"
    assert rec.calls == ["route"], "点名时仍碰了关键词短路：%s" % rec.calls


async def test_listing_named_skill_uses_a_channel_it_did_not_have():
    """★ 行为对照（listing）：本函数此前是本仓**唯一**「对话链没有工具环路」的入口。

    未点名 ⇒ `_route_via_tools` **一次都不许被调**（原路径逐字不变）；
    点名   ⇒ 必须走它（在此之前，listing 卡片点了等于没点）。
    """
    from modules.listing_generator.agent_listing import AgentResponse, ListingGeneratorAgent

    rec = _Recorder()
    agent = ListingGeneratorAgent()

    async def fake_route(query, context=None, session_id=None, user_id=None):
        rec.mark("route")
        return AgentResponse(content="ROUTED", display_type="text")

    async def fake_proc(query, context=None):
        rec.mark("shortcut")
        return AgentResponse(content="SHORTCUT", display_type="text")

    async def fake_llm_stream(*a, **k):
        rec.mark("llm")
        yield "LLM"

    agent._route_via_tools = fake_route
    agent._process_query = fake_proc
    agent.llm_stream = fake_llm_stream  # 断网、确定性

    async def _collect():
        out = []
        async for c in agent.stream_chat("帮我写一个标题"):
            if isinstance(c, str):
                out.append(c)
        return "".join(out)

    plain = await _collect()
    assert rec.routes == 0, "未点名时不该走技能通道"
    assert plain in ("LLM", "SHORTCUT")

    rec.calls.clear()
    async with bind_requested_skill("listing-title-basic"):
        named = await _collect()
    assert rec.routes == 1, "点名后没有走技能通道"
    assert named == "ROUTED"


async def test_product_research_named_skill_bypasses_shortcuts():
    """★ 行为对照（product_research）：关键词短路同样不构造 prompt。"""
    from modules.product_research.agent_product_research import (
        AgentResponse,
        ProductResearchAgent,
    )

    rec = _Recorder()
    agent = ProductResearchAgent()

    async def fake_classify(q):
        return "blue_ocean"

    async def fake_route(query, context_id=None, user_id=None, shop_id=None):
        rec.mark("route")
        return AgentResponse(content="ROUTED", display_type="text")

    async def fake_proc(query, context_id=None, intent=None, shop_id=None):
        rec.mark("shortcut")
        return AgentResponse(content="SHORTCUT", display_type="text")

    agent._classify_intent = fake_classify
    agent._route_via_tools = fake_route
    agent._process_query = fake_proc

    class _Router:
        pass

    agent._get_router = lambda: _Router()

    plain = await agent._invoke_impl("看看蓝海")
    assert plain.content == "SHORTCUT", "未点名的行为变了"
    assert rec.routes == 0

    rec.calls.clear()
    async with bind_requested_skill("pr-blue-ocean"):
        named = await agent._invoke_impl("看看蓝海")
    assert named.content == "ROUTED", "点名后没有让路"
    assert rec.routes == 1


async def test_review_named_skill_reports_unavailable_channel():
    """★ 点名 + 技能通道不可用 ⇒ **如实说**，不许拿关键词短路顶替。

    改前这里返回的是 `_GUIDE_REPLY`（「我需要知道你这次想看哪一项」）——
    而用户**刚刚才点过卡**，那句话会让他以为系统没收到他的选择。
    """
    from ai_infra.skills import SKILL_CHANNEL_UNAVAILABLE
    from modules.review_analyst.agent import ReviewAnalystAgent
    from modules.review_analyst.schemas import ReviewChatResult

    agent = ReviewAnalystAgent()

    async def fake_one(intent, context=None):
        return ReviewChatResult(reply="SHORTCUT")

    async def fake_route(*a, **k):
        return None

    agent._run_one = fake_one
    agent._route_via_tools = fake_route
    agent._get_router = lambda: None

    plain = await agent.invoke("本周周报", shop_id="store_x")
    assert plain.reply == "SHORTCUT"

    async with bind_requested_skill("review-weekly-brief"):
        named = await agent.invoke("本周周报", shop_id="store_x")
    assert named.reply == SKILL_CHANNEL_UNAVAILABLE
    assert named.degraded is True and named.degraded_reason == "skill_channel_unavailable"


# ================================================================ 判据 ⑤

REGISTRY_REL = "src/components/ChatPanel/results/conversation/registry.ts"
SHORTCUTS_REL = "src/composables/chat/useAgentShortcuts.ts"


def test_review_report_display_type_has_a_frontend_card():
    """★ 跨端对账：后端下发的 `display_type` 必须在前端注册表里有卡片。

    不对账的后果是**静默按纯文本渲染**（`resolveConversationResult` 未登记返回
    null）—— 结构化 `data` 照样下发、界面上一点看不出来，是本仓反复咬过人的形态。
    """
    from modules.review_analyst.agent import REVIEW_REPORT_DISPLAY_TYPE

    path = FRONTEND / REGISTRY_REL
    assert path.exists(), "前端注册表不存在: %s" % path
    src = path.read_text(encoding="utf-8")
    assert re.search(
        r"(?m)^\s*%s\s*:" % re.escape(REVIEW_REPORT_DISPLAY_TYPE), src
    ), "后端 display_type=%r 在前端注册表里没有登记" % REVIEW_REPORT_DISPLAY_TYPE
    # 反向：注册表里那个键确实指向一个组件文件，而不是一行注释
    assert "ReviewReportCard" in src


def test_review_success_wrap_is_not_plain_text():
    """★ `_wrap` 的成功档必须是具名类型；降级两档仍按纯文本（它们没有可渲染的报告）。"""
    from modules.review_analyst.agent import REVIEW_REPORT_DISPLAY_TYPE, ReviewAnalystAgent

    agent = ReviewAnalystAgent()
    ok = agent._wrap("weekly_report", {"summary": "s", "metrics": [], "details": {}})
    assert ok.display_type == REVIEW_REPORT_DISPLAY_TYPE

    err = agent._wrap("weekly_report", {"error": "boom"})
    assert err.display_type == "text" and err.degraded is True
    assert agent._wrap("weekly_report", "not-a-dict").display_type == "text"


def test_skill_card_message_does_not_embed_description():
    """★ 卡片消息**不得内嵌 `description`**（第 246 轮 P0-b）。

    `description` 是「什么场景该用它」的方法说明，天然夹带别主题的词：
      · 「周报」那条写着「销售 / **广告** / 库存 / 利润四条线」⇒ 命中广告路由；
      · 「复盘结论写法」那条写着「输出周报/**月报**时使用」⇒ 命中月度复盘。
    实测 5 张卡 3 张被路由到别的报表。它本来就随技能正文进 system prompt
    ⇒ 塞进用户消息是纯重复，且是唯一的误判来源。
    """
    path = FRONTEND / SHORTCUTS_REL
    assert path.exists(), "前端卡片动作条不存在: %s" % path
    src = path.read_text(encoding="utf-8")
    # 只看代码行，行首注释里保留「改前的形状」说明是对的、不算违规
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.lstrip().startswith(("*", "//", "/*"))
    )
    assert "card.description" not in code, "卡片消息又把 description 塞回去了"
    assert re.search(r"请按「\$\{card\.title\}」执行。", code), "卡片消息形状被改掉了"


# ================================================================ 判据 ⑥

def test_gate_is_not_vacuous():
    """★ 反向注入：把守卫拆掉，门禁必须转红；干净样本不得误报。

    `expect_hit` / `expect_green` 都要显式声明，并断言**红的总数 == 命中数**
    —— 否则「门禁空跑」会和「门禁通过」长得一模一样。
    """
    good = (
        "from ai_infra.skills import is_skill_requested\n"
        "\n"
        "class A:\n"
        "    async def stream_chat(self, q):\n"
        "        async for c in self._stream_via_tools(q):\n"
        "            yield c\n"
        "        if is_skill_requested():\n"
        "            return\n"
        "        intent = self._classify_intent(q)\n"
    )
    bad_no_guard = good.replace("        if is_skill_requested():\n", "")
    bad_no_import = good.replace("from ai_infra.skills import is_skill_requested\n", "")

    # 干净样本：判定与 import 都在 ⇒ 不许误报
    assert entry_gate_report(good, "stream_chat") == (True, True, ""), "干净样本被误报（假红）"
    assert channel_precedes_keyword(good, "stream_chat") is True, (
        "干净样本的顺序判据误报（假红）"
    )
    expect_green = 2

    # 反向注入 1：拆掉守卫 ⇒ 函数体不再引用判定
    hit, _, _ = entry_gate_report(bad_no_guard, "stream_chat")
    assert hit is False, "反向注入 1（拆掉守卫）没有被抓出来"

    # 反向注入 2：拆掉 import ⇒ 模块级导入判据必须发现
    _, imported, _ = entry_gate_report(bad_no_import, "stream_chat")
    assert imported is False, "反向注入 2（拆掉 import）没有被抓出来"

    # 反向注入 3：把技能通道挪到关键词分类**之后** ⇒ 顺序判据必须发现
    swapped = (
        "class A:\n"
        "    async def stream_chat(self, q):\n"
        "        intent = self._classify_intent(q)\n"
        "        async for c in self._stream_via_tools(q):\n"
        "            yield c\n"
    )
    assert channel_precedes_keyword(swapped, "stream_chat") is False, (
        "反向注入 3（通道排到关键词之后）没有被抓出来"
    )

    # 反向注入 4：把「找不到函数」当成过关 —— 这条防的是解析静默失效
    assert entry_gate_report(good, "no_such_fn")[0] is False, "函数缺失被当成过关"

    expect_hit = 4

    # 真实文件必须过（否则门禁会掩盖实现）
    for rel, classify_attr in CHANNEL_FIRST.items():
        src = (BACKEND / rel).read_text(encoding="utf-8", errors="replace")
        assert channel_precedes_keyword(src, "stream_chat", classify_attr), rel
        expect_green += 1

    assert expect_hit == 4 and expect_green == 6, (
        "自检计数漂了：hit=%d green=%d" % (expect_hit, expect_green)
    )
