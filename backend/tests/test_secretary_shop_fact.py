"""店秘书「当前店铺」上下文门禁（第 242 轮）。

事故（老板实测，不是假想）
--------------------------
在「虾皮1」问「我的资料库每个库有多少数据了」→ 答 `当前店铺（虾皮1）`，数字正确；
切到「亚马逊1」再问 → 数字**真的**换成了亚马逊1 的（checkpoint 里那一轮 6 条工具
回执 id 全为 `…-store_c3529ab1`、`product_list total=16`、`asset_list total=9`），
**但开场白与结论仍写「当前店铺（虾皮1）」**。老板据此判定「切了店铺还是旧店铺的
数据」。

⇒ 数据链 `X-Shop-ID → scoped() → shop_id` 是**对的**；错的是「模型自称的当前
店铺」在修复前**没有任何权威来源**：全部工具里没有「读当前店铺」的（唯一的
`switch_shop` 有副作用 —— 调它等于真的切店），system prompt 里也不含店铺名，
于是模型只能从**对话历史**里取旧店名。修法与理由见
`backend/modules/secretary/shop_context.py` 头注释。

★ 为什么修法有**两半**（这是实测逼出来的，不是设计偏好）
--------------------------------------------------------
只做「注入事实」那一半时，模型**仍然**照抄历史里的旧店名：
  · 三组**措辞**（抽象规则 / 点名禁用旧店名 / 点名作废历史示范）→ 全 BAD；
  · 阳性对照（把事实段里的店名换成本账号不存在的假名）→ 模型**照写假名**
    ⇒ 证明事实段确实被读到、缺陷不在位置或权重；
  · 把历史里那个旧店名换成中性占位符 → 模型**把占位符当店名抄下来**
    ⇒ 历史那个位置的内容会被逐字照抄；
  · 只删「当前店铺（X）」片段、留着别处的旧店名 → 模型从**另一条**历史里把
    旧店名捞回来；历史里完全不存在旧店名 → 改口 ✅；
  · 只去污染、不注入 → 模型**干脆不提店名**（信息缺失）。
⇒ 唯一稳定形态 = **注入事实 + 历史去污染**，缺一不可（探针：
  `.workbuddy/probes/r242_probe_variants.py` / `_beta.py` / `_gamma.py`）。

本文件钉五件事
--------------
A. 事实段的内容与判空（纯函数 + Agent 构造，**零 DB**）；
B. 「空 ⇒ 提示词一个字不变；非空 ⇒ **追加**而不是替换」；
C. **去污染的规则与行为**（纯函数 + 两处钩子，零 DB）；
D. **接线**（AST 形态判据，不看源码字符串）：两个对话端点各自构造一次上下文，
   沿 `route` / `route_stream` → `get_secretary_agent` → `SecretaryAgent`
   → `system_prompt`（事实）与 `_sanitize_history_for_model`（去污染）一路传到底，
   中途**任何一环掉了都转红**；
E. 反向注入自检：上面每条判据都能被一种具体改法点红。

★ 为什么 D 必须走 AST：本仓反复踩「源码字符串包含」被判据骗过 —— 注释与
  docstring 里出现同名字符串即假绿。而 D 恰恰是「接线」判据，它的真空区
  （渲染了没接上 / 覆写了没调用）正是最难靠肉眼发现的那类。
"""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage

from ai_infra.base_agent import BaseAgent
from modules.secretary.agent import (
    SECRETARY_SYSTEM_PROMPT,
    SecretaryAgent,
    get_secretary_agent,
)
from modules.secretary.shop_context import (
    ShopBrief,
    ShopContext,
    list_other_shop_names,
    render_shop_banner,
    render_shop_fact,
    sanitize_history,
    strip_foreign_shop_names,
)

BACKEND = Path(__file__).resolve().parents[1]
AGENT_PY = BACKEND / "modules" / "secretary" / "agent.py"
ROUTER_PY = BACKEND / "modules" / "secretary" / "router.py"
SHOP_CONTEXT_PY = BACKEND / "modules" / "secretary" / "shop_context.py"
BASE_AGENT_PY = BACKEND / "ai_infra" / "base_agent.py"

#: 一个「正常」的店铺 brief（值取自老板事故那一轮的 checkpoint：亚马逊1）。
BRIEF = ShopBrief(id="store_c3529ab1", name="亚马逊1", platform="amazon_us")

#: 事故里那家**旧**店铺（虾皮1）—— 去污染要抹掉的就是它。
OLD_NAME = "虾皮1"

#: 污染源原文（逐字抄自 checkpoint 里那一轮的 assistant 消息）。
POLLUTED_AI_TEXT = "当前店铺（虾皮1）下各资料库的数据总量如下：\n\n- **产品库**：0 条记录"


def _read_source(path: Path) -> str:
    """读源码并**显式**把行尾归一化成 `\\n`。

    ★ 为什么显式做、不靠 `open(..., newline=None)` 的隐式转换：本仓生产文件
      **CRLF / LF 混存**（`backend/modules/secretary/*.py` 是 CRLF，
      `backend/ai_infra/base_agent.py` 与 `backend/tests` 多个文件是 LF）。
      下面的反向注入用的是「替换源码里的某一段」，锚点若与文件真实行尾不一致
      就会 **0 命中**，而 0 命中的表现与「改法无效」长得一样 —— 会得出相反结论。
      这里归一到 LF 并把「真的归一了」用断言钉住（不是"我假设它是 LF"）。
    """
    text = path.read_bytes().decode("utf-8")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    assert "\r" not in text, f"{path.name} 归一化后仍含 \\r —— 归一化没真做"
    return text


# ============================================================================
# 扫描器（入参是**文本**，不是路径）—— 反向注入因此不必碰真文件
# ============================================================================


def _find_func(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _call_kwarg(call: ast.Call, name: str):
    return next((k for k in call.keywords if k.arg == name), None)


def _awaited_names(fn) -> set:
    """函数体内 `await f(...)` 里被调用的名字集合（`ast.Await` 的 value 才是 Call）。"""
    out = set()
    for node in ast.walk(fn):
        if (
            isinstance(node, ast.Await)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            out.add(node.value.func.id)
    return out


def _context_names(fn) -> set:
    """端点体内「由 `build_shop_context` 赋值出来的名字」集合。

    ★ 判据必须是「这个值**来自**构造」而不是「这里是某个局部变量」：
      只查"是不是局部名"会放过 `shop_context = "亚马逊1"` 这种**写死**——
      那比没注入更糟（它永远自称同一家店，且看起来完全正常）。
      第 242 轮把裸字符串 `shop_fact` 换成**包裹** `ShopContext`，就是为了让
      "只传了一半"这种半修状态在类型上就说不通（见 `ShopContext` 的判据段）。
    """
    out = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        # ★ `shop_context = await build_shop_context(...)` 的 value 是 **`ast.Await`**
        #   而不是 `ast.Call` —— 只判 `Call` 会让本判据**恒认为没构造**
        #   （首跑实测就是这样：真源码被判成 no_context_build）。
        if isinstance(value, ast.Await):
            value = value.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "build_shop_context"
        ):
            continue
        out |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    return out


def _fact_of_consumes_context(call: ast.Call) -> bool:
    """`_with_shop_fact(<业务提示词>, _fact_of(shop_context))` 的**形态**判据。

    ★ 为什么必须判形态而不是"有没有出现 _fact_of 这个名字"：把 `_fact_of(...)`
      写成注释、或写成 `_fact_of("亚马逊1")`（写死），都会让"名字出现过"成立
      而事实段其实没接上 —— 本仓铁律：判据禁"源码字符串包含"。
    """
    cands = [a for a in call.args] + [k.value for k in call.keywords]
    for a in cands:
        if not (
            isinstance(a, ast.Call)
            and isinstance(a.func, ast.Name)
            and a.func.id == "_fact_of"
        ):
            continue
        if any(isinstance(x, ast.Name) and x.id == "shop_context" for x in a.args):
            return True
        if any(
            isinstance(k.value, ast.Name) and k.value.id == "shop_context" for k in a.keywords
        ):
            return True
    return False


def scan_router_endpoints(text: str) -> set:
    """两个对话端点各自必须「构造上下文 + 带上去」。返回违规集合，空集 = 合规。"""
    bad: set = set()
    tree = ast.parse(text)
    for fn_name, callee in (
        ("secretary_chat", "route"),
        ("secretary_chat_stream", "route_stream"),
    ):
        fn = _find_func(tree, fn_name)
        if fn is None:
            bad.add(f"{fn_name}:no_endpoint")
            continue
        built = _context_names(fn)
        if not built:
            bad.add(f"{fn_name}:no_context_build")
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == callee
        ]
        if not calls:
            bad.add(f"{fn_name}:{callee}_missing")
            continue
        for call in calls:
            kw = _call_kwarg(call, "shop_context")
            if kw is None:
                bad.add(f"{fn_name}:{callee}_without_shop_context")
            elif not (isinstance(kw.value, ast.Name) and kw.value.id in built):
                bad.add(f"{fn_name}:{callee}_shop_context_not_from_build")
    return bad


def scan_agent_layer(text: str) -> set:
    """上下文必须从工厂一路传到 system prompt（事实半）+ 覆写钩子（去污染半）。"""
    bad: set = set()
    tree = ast.parse(text)

    # ① 工厂签名收 `shop_context`
    factory = _find_func(tree, "get_secretary_agent")
    if factory is None:
        return {"no_factory"}
    params = {a.arg for a in factory.args.args} | {a.arg for a in factory.args.kwonlyargs}
    if "shop_context" not in params:
        bad.add("factory_no_param")

    # ② 工厂体在**按请求重建**那条路上把它交给 `SecretaryAgent(...)`
    #    ★ 只认 `return SecretaryAgent(...)`：工厂里有**两个**构造点 ——
    #      `_agent = SecretaryAgent(checkpointer=cp)`（`shop_id` 为空时的共享单例，
    #      刻意不带任何店铺绑定）与 `return SecretaryAgent(..., shop_context=...)`
    #      （按请求重建，必须带）。要求"每个构造点都带"会误伤单例那条。
    per_request = [
        n.value
        for n in ast.walk(factory)
        if isinstance(n, ast.Return)
        and isinstance(n.value, ast.Call)
        and isinstance(n.value.func, ast.Name)
        and n.value.func.id == "SecretaryAgent"
    ]
    if not per_request:
        bad.add("factory_no_per_request_build")
    else:
        for call in per_request:
            kw = _call_kwarg(call, "shop_context")
            if kw is None or not (isinstance(kw.value, ast.Name) and kw.value.id == "shop_context"):
                bad.add("factory_does_not_forward")

    # ③ 两条路由都把上下文交给工厂
    for fn_name in ("route", "route_stream"):
        fn = _find_func(tree, fn_name)
        if fn is None:
            bad.add(f"{fn_name}:no_func")
            continue
        calls = [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "get_secretary_agent"
        ]
        if not calls:
            bad.add(f"{fn_name}:factory_missing")
            continue
        for call in calls:
            kw = _call_kwarg(call, "shop_context")
            if kw is None or not (isinstance(kw.value, ast.Name) and kw.value.id == "shop_context"):
                bad.add(f"{fn_name}:factory_without_shop_context")

    cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "SecretaryAgent"),
        None,
    )
    init = _find_func(cls, "__init__") if cls is not None else None
    if init is None:
        bad.add("no_agent_init")
        return bad

    # ④ `__init__` 真的从**包裹**里渲染出事实段交给 system prompt
    #    ★ 形态要求 `_with_shop_fact(SECRETARY_SYSTEM_PROMPT, _fact_of(shop_context))`：
    #      换成裸字符串（`shop_context` 直接当文本用）会静默产出
    #      「当前工作店铺：<repr>」这种垃圾事实段。
    rendered = False
    for node in ast.walk(init):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "__init__"
            and isinstance(node.func.value, ast.Call)
            and isinstance(node.func.value.func, ast.Name)
            and node.func.value.func.id == "super"
        ):
            continue
        kw = _call_kwarg(node, "system_prompt")
        if kw is None:
            bad.add("init_no_system_prompt")
            continue
        value = kw.value
        if not (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "_with_shop_fact"
        ):
            bad.add("init_prompt_not_rendered")
            continue
        if _fact_of_consumes_context(value):
            rendered = True
    if not rendered:
        bad.add("init_does_not_render")

    # ⑤ `__init__` 把**去污染名单**存下来（另一 half 不许被丢在路上）
    stored = any(
        isinstance(node, ast.Attribute)
        and node.attr == "_shop_foreign_names"
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        for node in ast.walk(init)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store)
    )
    if not stored:
        bad.add("init_does_not_store_names")

    # ⑥ SecretaryAgent 覆写钩子，且钩子体内**真的调** `sanitize_history`
    #    ★ 只查"有没有这个方法"会放过「覆写了个空壳 → 去污染静默失效」。
    override = _find_func(cls, "_sanitize_history_for_model")
    if override is None:
        bad.add("agent_no_sanitize_override")
    else:
        called = {
            n.func.id
            for n in ast.walk(override)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        # 注：本仓去污染的**默认恒等**在 BaseAgent 上，店秘书必须真覆写。
        if "sanitize_history" not in called:
            bad.add("agent_override_does_not_sanitize")

    # ⑦ 服务端「当前店铺」标注必须经由**唯一取口**、且两条路都带上
    digest = _find_func(tree, "_digest_graph_state")
    if digest is None:
        bad.add("no_digest")
    else:
        dparams = {a.arg for a in digest.args.args} | {a.arg for a in digest.args.kwonlyargs}
        if "banner" not in dparams:
            bad.add("digest_no_banner_param")
        elif not any(
            isinstance(n, ast.Name)
            and n.id == "banner"
            and isinstance(n.ctx, ast.Load)
            for n in ast.walk(digest)
        ):
            # ★ 收了参数却不拼 = 机制齐全、永远不生效（本仓最难发现的那类失效）
            bad.add("digest_ignores_banner")
    for fn_name in ("route", "route_stream"):
        fn = _find_func(tree, fn_name)
        if fn is None:
            continue
        for call in [
            n
            for n in ast.walk(fn)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_digest_graph_state"
        ]:
            kw = _call_kwarg(call, "banner")
            if kw is None or not (
                isinstance(kw.value, ast.Call)
                and isinstance(kw.value.func, ast.Name)
                and kw.value.func.id == "_banner_of"
            ):
                bad.add(f"{fn_name}:digest_without_banner")
    return bad


def scan_base_agent_layer(text: str) -> set:
    """基类必须**定义**钩子，且 `_llm_call_node` 真的**调用**它。"""
    bad: set = set()
    tree = ast.parse(text)
    cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "BaseAgent"),
        None,
    )
    if cls is None:
        return {"no_base_agent"}
    if _find_func(cls, "_sanitize_history_for_model") is None:
        bad.add("base_no_hook")
    node = _find_func(cls, "_llm_call_node")
    if node is None:
        bad.add("no_llm_call_node")
    else:
        calls = [
            n
            for n in ast.walk(node)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_sanitize_history_for_model"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "self"
        ]
        if not calls:
            bad.add("llm_call_does_not_sanitize")
    return bad


def scan_shop_context_layer(text: str) -> set:
    """唯一入口必须把**两半**都取到；`sanitize_history` 必须真的调用抹名函数。"""
    bad: set = set()
    tree = ast.parse(text)
    entry = _find_func(tree, "build_shop_context")
    if entry is None:
        return {"no_entry"}
    awaited = _awaited_names(entry)
    for need in ("load_shop_brief", "load_other_shop_names"):
        if need not in awaited:
            bad.add(f"entry_skips_{need}")
    sh = _find_func(tree, "sanitize_history")
    if sh is None:
        bad.add("no_sanitize_history")
    else:
        called = {
            n.func.id
            for n in ast.walk(sh)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        if "strip_foreign_shop_names" not in called:
            bad.add("sanitize_does_not_strip")
    return bad


# ============================================================================
# A：事实段内容与判空（纯函数，零 DB）
# ============================================================================


def test_render_shop_fact_carries_facts_and_the_rule():
    """事实段必须同时给出**事实**（名称/ID/平台）与**规则**。

    ★ 规则的形态是「**正文里不要写店名**」，不是「请写对店名」—— 后者被真实 LLM
      实测证伪到底：写「禁止出现『虾皮1』」时模型把**禁令里的旧店名**回显了出来；
      写「请以『当前店铺（X）』表述」时它写成了「当前店铺（**虾皮**）」，那个"虾皮"
      来自历史里**老板原话**「切换到虾皮」。⇒ 「指名」这件事模型做不到稳定，
      权威店名改由服务端渲染（`render_shop_banner`），模型只被要求**不写**。
    """
    fact = render_shop_fact(BRIEF)
    assert "亚马逊1" in fact
    assert "store_c3529ab1" in fact
    assert "amazon_us" in fact
    assert "正文里不要再写店铺名" in fact
    assert "属于**过去**" in fact


def test_render_shop_banner_is_deterministic_and_silent_without_a_name():
    """服务端标注是**确定性**的：同一个 brief 得到逐字相同的一行。

    ★ 它替代了「模型自称当前店铺」这条通道 —— 那条通道在措辞层面不可稳定
      （见上一条的判据段），而这一条完全不过模型 ⇒ 切店后必然跟随。
    """
    assert render_shop_banner(BRIEF) == "当前店铺：亚马逊1\n\n"
    assert render_shop_banner(None) == ""
    for blank in ("", "   ", "\t", "\n"):
        assert render_shop_banner(ShopBrief(id="store_x", name=blank, platform="amazon")) == ""


def test_digest_prepends_the_banner_through_the_single_outlet():
    """标注必须在**唯一取口**里拼 —— 两条路（流式 / 非流式）才能自动同源。"""
    from modules.secretary.agent import _digest_graph_state

    state = {"messages": [HumanMessage(content="问"), AIMessage(content="答")]}
    assert _digest_graph_state(state, banner="当前店铺：亚马逊1\n\n")["reply"] == (
        "当前店铺：亚马逊1\n\n答"
    )
    assert _digest_graph_state(state)["reply"] == "答", "没给标注时正文必须逐字不变"


def test_render_shop_fact_refuses_to_claim_an_authoritative_blank():
    """没有名称 ⇒ 空串（不注入）。

    ★ 为什么判空要从严：一段**自称权威却什么都没说**的块（「当前工作店铺：   」）
      比不注入更糟 —— 它把"没有店铺"伪装成了"有权威事实"。
    """
    assert render_shop_fact(None) == ""
    for blank in ("", "   ", "\t", "\n"):
        assert render_shop_fact(ShopBrief(id="store_x", name=blank, platform="amazon")) == ""


# ============================================================================
# B：追加而非替换 + 空值逐字不变（Agent 构造，零 DB）
# ============================================================================


def test_no_shop_context_keeps_system_prompt_byte_identical():
    """没有上下文 ⇒ 提示词**逐字不变**。

    ★ 这是「追加型」改动最容易犯的错：空值也让提示词长了一点（多两个换行）。
      本仓既有用例 `test_secretary_agent.py` 断言
      `agent.system_prompt == SECRETARY_SYSTEM_PROMPT`，它守的正是这条。
    """
    for kwargs in ({}, {"shop_id": None}, {"shop_context": None}, {"shop_context": ShopContext()}):
        agent = SecretaryAgent(llm=MagicMock(), **kwargs)
        assert agent.system_prompt == SECRETARY_SYSTEM_PROMPT, kwargs


def test_shop_fact_is_appended_not_substituted():
    """有事实 ⇒ `startswith(业务提示词)` 且 `endswith(事实段)`（**追加**，不是替换）。

    ★ 替换会静默删掉整段业务规则（规则 1–8），而且不会有任何红灯 ——
      所以这里用一个业务规则锚（规则 8 的原文）证明它还在。
    """
    fact = render_shop_fact(BRIEF)
    agent = SecretaryAgent(llm=MagicMock(), shop_id=BRIEF.id, shop_context=ShopContext(brief=BRIEF))
    sp = agent.system_prompt
    assert sp.startswith(SECRETARY_SYSTEM_PROMPT)
    assert sp.endswith(fact)
    assert "8. 一次只做最贴合意图的一件事" in sp


def test_shop_fact_reaches_the_per_turn_prompt():
    """每轮真正发给模型的那份 system prompt 里也要有它。

    ★ 只验 `agent.system_prompt` 是不够的：那一份还会被
      `BaseAgent._system_prompt_with_plan()` 重新拼一次（业务提示词 → 外部段落 →
      规划说明 → 当前计划）。若哪天那段拼接不再以 `self.system_prompt` 打头，
      事实段就会**在真正发给模型的文本里消失**，而上面那几条断言全绿。
      （同族判据：第 152 轮 `test_sections_survive_without_planning`。）
    """
    agent = SecretaryAgent(llm=MagicMock(), shop_id=BRIEF.id, shop_context=ShopContext(brief=BRIEF))
    per_turn = agent._system_prompt_with_plan({})
    assert render_shop_fact(BRIEF) in per_turn, "事实段没进「每轮现拼」的那份 system prompt"


# ============================================================================
# C：去污染（规则 + 行为，零 DB）
# ============================================================================


def test_strip_removes_the_self_report_slot_entirely():
    """「当前店铺（X）」这个**污染槽位**必须整段删掉，不能替换成别的词。

    ★ 依据（实测）：把该槽位里的旧店名换成中性占位符 `⟨历史轮次店铺⟩` 后，
      模型随即把**占位符本身**当成店名抄了下来 —— 写成
      「当前店铺（⟨历史轮次店铺⟩）」。换什么词，它就会自称什么词。
    """
    out = strip_foreign_shop_names(POLLUTED_AI_TEXT, (OLD_NAME,))
    assert "当前店铺" not in out
    assert OLD_NAME not in out
    assert out.startswith("下各资料库的数据总量如下：")


def test_strip_drops_the_whole_quoted_span_including_platform_suffix():
    """含其它店名的**整段引号**必须连平台后缀一起删。

    ★ 依据（真实 LLM 实测，不是推理）：只删店名本体时，同段残留的 `(Shopee MY)`
      会孤零零留下来，而模型**能从它反推出平台、再反推回「虾皮」** —— 收口实测里
      它写出了「您当前店铺「虾皮 (Shopee MY)」下…」，既不是当前店名、也不是历史原文。
    """
    out = strip_foreign_shop_names("您已成功切换到「虾皮1 (Shopee MY)」店铺。", (OLD_NAME,))
    assert out == "您已成功切换到店铺。"
    assert "Shopee" not in out, "平台后缀留下了 —— 模型能顺着它推回旧店铺"


def test_strip_removes_bare_names_outside_quotes_too():
    """引号之外的**裸店名**也要抹 —— 否则模型会从别处把旧店名捞回来。

    ★ 依据（实测）：只删「当前店铺（X）」片段时，模型曾从切店确认那条历史里把
      旧店名捞回来，改写成「您当前店铺「虾皮1 (Shopee MY)」的各资料库…」。
    ★ 同时钉住"抹名不许伤数据"：数字必须原样留在历史里。
    """
    out = strip_foreign_shop_names("在虾皮1 上：产品库 16 条记录", (OLD_NAME,))
    assert OLD_NAME not in out
    assert "16 条记录" in out, "抹店名伤到了数据 —— 那会把历史里的数字也改掉"


def test_strip_is_longest_name_first():
    """长名优先：`虾皮1` 是 `虾皮10` 的前缀，先替换短名会把长名剁成 `0`。

    ★ 同族坑见 `shop_tools._switch_shop` 的「全字匹配优先」—— 那是"匹配"，
      这里是"替换"，坑是同一个。
    """
    out = strip_foreign_shop_names("已切换到虾皮10", ("虾皮1", "虾皮10"))
    assert "虾皮1" not in out
    assert "虾皮10" not in out
    assert out == "已切换到"


def test_strip_skips_single_char_names():
    """单字店名不参与去污染 —— 否则会把历史里所有 `1` 抹掉（大范围误伤）。

    ★ 方向选择：**宁可不抹**。留下一个旧店名只会让自称错一次；
      抹掉所有数字会破坏历史里的**数据**（「16 条记录」→「6 条记录」）。
    """
    assert strip_foreign_shop_names("产品库：16 条记录", ("1",)) == "产品库：16 条记录"


def test_list_other_shop_names_excludes_current_and_junk():
    """名单只收**其它**店铺名：排除当前店、去重、跳过空名与短名。"""
    shops = [
        {"id": "store_c3529ab1", "name": "亚马逊1"},     # 当前店 ⇒ 排除
        {"id": "store_27a9e7ec", "name": "虾皮1"},
        {"id": "store_dup", "name": "虾皮1"},            # 重名 ⇒ 去重
        {"id": "store_blank", "name": "   "},            # 空名 ⇒ 跳过
        {"id": "store_short", "name": "x"},              # 单字 ⇒ 跳过
        {"id": "store_temu", "name": "Temu1"},
    ]
    assert list_other_shop_names(shops, "store_c3529ab1") == ("虾皮1", "Temu1")
    assert list_other_shop_names(shops, None) == ("亚马逊1", "虾皮1", "Temu1")


def test_strip_handles_a_platform_suffix_inside_the_slot():
    """槽位里带平台后缀（`当前店铺（虾皮1 (Shopee MY)）`）也要**整段**吃掉。

    ★ 这个形态不是假想：`switch_shop` 的确认文案就是「已切换到「虾皮1 (Shopee
      MY)」店铺。」—— 括号是**嵌套**的。首版正则把半角 `)` 也当收口，于是在半角处
      提前截断，留下一个孤零零的 `）`（门禁首跑实测到的真实缺口）。
    """
    out = strip_foreign_shop_names("当前店铺（虾皮1 (Shopee MY)）下的数据", (OLD_NAME,))
    assert "当前店铺" not in out
    assert OLD_NAME not in out and "Shopee" not in out
    assert "）" not in out, "槽位没收干净 —— 留下了半个右括号"
    assert out == "下的数据"


def test_strip_removes_the_server_banner_line_form():
    """服务端自己标注的 `当前店铺：X` 也必须能被抹掉。

    ★ 为什么这是**必须**的一条：那行标注会随回复落进会话历史（回复要落库），
      切店之后它就成了一条"旧名" —— 不抹的话，等于每轮都在给下一轮制造新的
      污染源（同一个失败模式换了个形状回来）。
    """
    out = strip_foreign_shop_names("当前店铺：亚马逊1\n\n产品库：16 条记录", (OLD_NAME,))
    assert out.strip() == "产品库：16 条记录"
    assert "当前店铺" not in out


def test_sanitize_history_touches_only_ai_messages():
    """只动模型自己的话（`AIMessage`）；老板原话里的店名是**正当引用**，不许动。

    ★ 第三个断言是**故意**这么严的：`当前店铺（…）` 那个槽位**一律**删，即使括号
      里写的就是当前店名。理由是那条信息**本来就不权威** —— 修复前它就是模型自己
      编的，本次事故的全部价值就在于「历史里的自称不可信」；留着它等于继续养着
      "槽位内容会被逐字回显"这条通道。要知道"当时在哪家店"，去 system prompt 取。
    """
    msgs = [
        HumanMessage(content="虾皮1 有多少产品"),
        AIMessage(content=POLLUTED_AI_TEXT),
        AIMessage(content="当前店铺（亚马逊1）下…"),
    ]
    out = sanitize_history(msgs, (OLD_NAME,))
    assert out[0].content == "虾皮1 有多少产品", "老板原话被改了 —— 那是历史事实，不是污染"
    assert OLD_NAME not in out[1].content
    assert out[2].content == "下…", "槽位一律删（里面写的是不是当前店名不影响）"


def test_sanitize_history_copies_and_leaves_input_intact():
    """只清洗**副本**：`state` / checkpoint 里的历史保持原样、可审计。"""
    original = AIMessage(content=POLLUTED_AI_TEXT)
    out = sanitize_history([original], (OLD_NAME,))
    assert original.content == POLLUTED_AI_TEXT, "原消息被就地改了 —— 落库历史就不可审计了"
    assert out[0] is not original


def test_sanitize_history_is_identity_when_no_names():
    """名单为空 ⇒ **同一个对象**原样返回（零开销，且不靠"看起来没变"判等）。

    ★ 这条同时保住另一个既有判据：没绑店铺时，历史必须与不开启该机制时**完全一致**。
    """
    msgs = [AIMessage(content=POLLUTED_AI_TEXT)]
    assert sanitize_history(msgs, ()) is msgs


def test_base_hook_defaults_to_identity():
    """基类钩子的默认实现必须是**恒等** —— 它对**所有** Agent 都生效。

    ★ 传 `object()` 当 self：默认实现不读任何实例状态，这正是"默认对别人零影响"
      的形态证明。若哪天默认实现开始动消息，这条会红。
    """
    msgs = [AIMessage(content=POLLUTED_AI_TEXT)]
    assert BaseAgent._sanitize_history_for_model(object(), msgs) is msgs


def test_secretary_agent_sanitizes_only_when_it_has_names():
    """行为判据：带上下文 ⇒ 历史被抹；不带 ⇒ 逐字不变（同一个对象）。"""
    ctx = ShopContext(brief=BRIEF, foreign_names=(OLD_NAME,))
    agent = SecretaryAgent(llm=MagicMock(), shop_id=BRIEF.id, shop_context=ctx)
    msgs = [HumanMessage(content="虾皮1 有多少产品"), AIMessage(content=POLLUTED_AI_TEXT)]

    out = agent._sanitize_history_for_model(msgs)
    assert OLD_NAME not in out[1].content
    assert out[0] is msgs[0], "user 侧不该被碰"

    plain = SecretaryAgent(llm=MagicMock(), shop_id=BRIEF.id)
    assert plain._sanitize_history_for_model(msgs) is msgs


# ============================================================================
# 唯一入口：两半各自取、各自失败（替身，零 DB）
# ============================================================================


def test_build_shop_context_takes_both_halves():
    """唯一入口必须一次把事实与名单都取到（少一半就是静默半修）。"""
    from modules.secretary import shop_context as sc

    with patch.object(sc, "load_shop_brief", AsyncMock(return_value=BRIEF)), patch.object(
        sc, "load_other_shop_names", AsyncMock(return_value=(OLD_NAME,))
    ):
        ctx = asyncio.run(sc.build_shop_context("store_c3529ab1"))
    assert ctx.brief == BRIEF
    assert ctx.foreign_names == (OLD_NAME,)


def test_build_shop_context_degrades_one_half_without_killing_the_other():
    """任一半读库失败 ⇒ **只**退化那一半，另一半照常（增益不是门禁）。

    ★ 若两半共用一个 try，一次失败会把两半一起清空 —— 表现是"什么也没注入"，
      而日志里分不清是哪一半坏了。
    """
    from modules.secretary import shop_context as sc

    with patch.object(
        sc, "load_shop_brief", AsyncMock(side_effect=RuntimeError("db down"))
    ), patch.object(sc, "load_other_shop_names", AsyncMock(return_value=(OLD_NAME,))):
        ctx = asyncio.run(sc.build_shop_context("store_c3529ab1"))
    assert ctx.brief is None and ctx.foreign_names == (OLD_NAME,)

    with patch.object(sc, "load_shop_brief", AsyncMock(return_value=BRIEF)), patch.object(
        sc, "load_other_shop_names", AsyncMock(side_effect=RuntimeError("db down"))
    ):
        ctx = asyncio.run(sc.build_shop_context("store_c3529ab1"))
    assert ctx.brief == BRIEF and ctx.foreign_names == ()


def test_build_shop_context_skips_the_db_without_a_shop():
    """没有 shop_id ⇒ **一次查询都不发**（而不是查了再判空）。"""
    from modules.secretary import shop_context as sc

    brief_mock, names_mock = AsyncMock(), AsyncMock()
    with patch.object(sc, "load_shop_brief", brief_mock), patch.object(
        sc, "load_other_shop_names", names_mock
    ):
        ctx = asyncio.run(sc.build_shop_context(None))
    assert ctx == ShopContext()
    assert brief_mock.await_count == 0 and names_mock.await_count == 0


# ============================================================================
# 工厂：把上下文交给**按请求重建**的那个实例（行为判据，比形态判据更硬）
# ============================================================================


def test_factory_binds_the_context_to_the_per_request_instance():
    """`get_secretary_agent(shop_id, shop_context=…)` 产出的实例必须两半都带着。

    ★ 为什么这条要**行为**验证而不是只靠上面的 AST：工厂里有两条岔路 ——
      `shop_id` 为空时返回**共享单例**，非空时**每次新建**。行为判据能同时钉住
      「非空那条把上下文带上了」与「单例那条**没有**被染上」
      （后者若被染上，就是一个跨请求的真实泄露：A 店的名称会出现在 B 店的会话里，
      更糟的是去污染名单会按 A 店把 B 店历史里的店名抹掉）。
    """
    ctx = ShopContext(brief=BRIEF, foreign_names=(OLD_NAME,))
    agent = get_secretary_agent(BRIEF.id, shop_context=ctx)
    assert isinstance(agent, SecretaryAgent)
    assert agent.system_prompt.endswith(render_shop_fact(BRIEF))
    assert agent._shop_foreign_names == (OLD_NAME,)

    shared = get_secretary_agent(None)
    assert shared is get_secretary_agent(None), "shop_id 为空时应当是共享单例"
    assert shared.system_prompt == SECRETARY_SYSTEM_PROMPT, (
        "共享单例不许携带任何店铺事实（否则会跨请求串店名）"
    )
    assert shared._shop_foreign_names == (), "共享单例不许携带去污染名单（否则会抹错别家历史）"


# ============================================================================
# D：接线形态门禁 + E：反向注入自检
# ============================================================================


def test_router_endpoints_build_and_pass_the_context():
    bad = scan_router_endpoints(_read_source(ROUTER_PY))
    assert bad == set(), f"接线缺失：{sorted(bad)}"


def test_agent_layer_threads_the_context_to_prompt_and_hook():
    bad = scan_agent_layer(_read_source(AGENT_PY))
    assert bad == set(), f"接线缺失：{sorted(bad)}"


def test_base_agent_invokes_the_hook():
    bad = scan_base_agent_layer(_read_source(BASE_AGENT_PY))
    assert bad == set(), f"接线缺失：{sorted(bad)}"


def test_shop_context_entry_takes_both_halves():
    bad = scan_shop_context_layer(_read_source(SHOP_CONTEXT_PY))
    assert bad == set(), f"接线缺失：{sorted(bad)}"


def test_wiring_gates_are_not_vacuous():
    """反向注入：每条判据都必须能被一种具体改法点红，且真实源码必须零违规。

    ★ 没有这一步，「扫描器写错了」与「接线全对」在读数上完全一样（都返回空集）
      —— 一句没有反例的断言等于没有断言（本仓铁律）。
    ★ 锚点前置 `\\n`：`/chat` 的 8 空格缩进行是 `/chat/stream` 的 12 空格行的
      **子串**，不前置换行会命中错的那一处（本仓同类坑：第 242 轮反向注入探针）。
    """
    clean_router = _read_source(ROUTER_PY)
    clean_agent = _read_source(AGENT_PY)
    clean_ctx = _read_source(SHOP_CONTEXT_PY)
    clean_base = _read_source(BASE_AGENT_PY)

    # 自检 ①：真实源码必须零违规。否则下面每个样本的读数都没有意义。
    assert scan_router_endpoints(clean_router) == set()
    assert scan_agent_layer(clean_agent) == set()
    assert scan_shop_context_layer(clean_ctx) == set()
    assert scan_base_agent_layer(clean_base) == set()

    router_samples = {
        # 端点改名（扫描器自己找错了函数时，同类样本会全变成 no_endpoint）
        "no_endpoint": clean_router.replace(
            "async def secretary_chat(", "async def secretary_chat_renamed(", 1
        ),
        # /chat 不构造上下文（赋成 None）
        "no_context_build": clean_router.replace(
            "\n    shop_context = await build_shop_context(shop_id)",
            "\n    shop_context = None",
            1,
        ),
        # /chat 把 `shop_context=` 从 route 调用里摘掉
        "without_shop_context": clean_router.replace(
            "\n        shop_context=shop_context,", "\n", 1
        ),
        # /chat 传的是**写死值**而不是构造结果（比不传更隐蔽）
        "not_from_build": clean_router.replace(
            "\n        shop_context=shop_context,",
            '\n        shop_context="亚马逊1",',
            1,
        ),
    }
    agent_samples = {
        # 工厂签名不接 shop_context
        "factory_no_param": clean_agent.replace(
            "def get_secretary_agent(\n"
            "    shop_id: Optional[str] = None,\n"
            "    shop_context: Optional[ShopContext] = None,\n"
            ") -> SecretaryAgent:",
            "def get_secretary_agent(shop_id: Optional[str] = None) -> SecretaryAgent:",
            1,
        ),
        # 工厂收了却不往下给
        "factory_does_not_forward": clean_agent.replace(
            "return SecretaryAgent(shop_id=shop_id, checkpointer=cp, shop_context=shop_context)",
            "return SecretaryAgent(shop_id=shop_id, checkpointer=cp)",
            1,
        ),
        # route 不把上下文交给工厂
        "route_without_shop_context": clean_agent.replace(
            "    agent = get_secretary_agent(shop_id, shop_context=shop_context)\n\n    # 决策层 C",
            "    agent = get_secretary_agent(shop_id)\n\n    # 决策层 C",
            1,
        ),
        # route_stream 不把上下文交给工厂
        "route_stream_without_shop_context": clean_agent.replace(
            "    agent = get_secretary_agent(shop_id, shop_context=shop_context)\n"
            "    messages = _input_messages",
            "    agent = get_secretary_agent(shop_id)\n    messages = _input_messages",
            1,
        ),
        # 渲染了，但 system prompt 没接（最隐蔽的半接线：一切"看起来都对"）
        "init_prompt_not_rendered": clean_agent.replace(
            "            system_prompt=_with_shop_fact(get_prompt_template(\"secretary\"), _fact_of(shop_context)),",
            "            system_prompt=get_prompt_template(\"secretary\"),",
            1,
        ),
        # 事实接上了，但**去污染名单**没存下来（另一半静默丢失）
        "init_does_not_store_names": clean_agent.replace(
            "        self._shop_foreign_names: tuple = tuple(",
            "        self._shop_foreign_names_unused: tuple = tuple(",
            1,
        ),
        # 覆写了个空壳：方法在、但不调 sanitize_history ⇒ 去污染静默失效
        "agent_override_noop": clean_agent.replace(
            "        return sanitize_history(messages, self._shop_foreign_names)",
            "        return messages",
            1,
        ),
        # 唯一取口不收 banner
        "digest_no_banner_param": clean_agent.replace(
            'def _digest_graph_state(state: dict, *, banner: str = "") -> dict:',
            "def _digest_graph_state(state: dict) -> dict:",
            1,
        ),
        # 收了 banner 却不拼（机制齐全、永远不生效）
        "digest_ignores_banner": clean_agent.replace(
            '    if banner and result.get("reply"):\n'
            '        result["reply"] = banner + result["reply"]\n',
            "",
            1,
        ),
        # 非流式那条忘了带标注
        "route_digest_without_banner": clean_agent.replace(
            "    result = _digest_graph_state(state, banner=_banner_of(shop_context))",
            "    result = _digest_graph_state(state)",
            1,
        ),
        # 流式那条忘了带标注
        "route_stream_digest_without_banner": clean_agent.replace(
            "    result = _digest_graph_state(final_state, banner=_banner_of(shop_context))",
            "    result = _digest_graph_state(final_state)",
            1,
        ),
    }
    ctx_samples = {
        # 入口忘了取名单那一半
        "entry_skips_load_other_shop_names": clean_ctx.replace(
            "            names = await load_other_shop_names(shop_id)", "            names = ()", 1
        ),
        # 入口忘了取事实那一半
        "entry_skips_load_shop_brief": clean_ctx.replace(
            "            brief = await load_shop_brief(shop_id)", "            brief = None", 1
        ),
        # sanitize_history 拿了名单却不抹
        "sanitize_does_not_strip": clean_ctx.replace(
            "            cleaned = strip_foreign_shop_names(m.content, foreign_names)",
            "            cleaned = m.content",
            1,
        ),
    }
    base_samples = {
        # 钩子改名（= 没定义）
        "base_no_hook": clean_base.replace(
            "    def _sanitize_history_for_model(self, messages: list) -> list:",
            "    def _sanitize_history_for_model_disabled(self, messages: list) -> list:",
            1,
        ),
        # 钩子定义了，但 LLM 节点不调它（最隐蔽：机制齐全、永远不生效）
        "llm_call_does_not_sanitize": clean_base.replace(
            "        clean_messages = self._sanitize_history_for_model(clean_messages)\n", "", 1
        ),
    }

    groups = (
        (scan_router_endpoints, router_samples, clean_router),
        (scan_agent_layer, agent_samples, clean_agent),
        (scan_shop_context_layer, ctx_samples, clean_ctx),
        (scan_base_agent_layer, base_samples, clean_base),
    )

    missed = []
    fired = 0
    total = 0
    for scanner, samples, clean in groups:
        for expect, text in samples.items():
            total += 1
            if text == clean:
                missed.append(f"{expect}: 样本没改到任何东西（替换锚点失效 ⇒ 本组会空跑）")
                continue
            if not scanner(text):
                missed.append(f"{expect}: 没被抓到（实得空集 —— 判据是真空区）")
            else:
                fired += 1

    assert not missed, "反向注入自检失败：\n  " + "\n  ".join(missed)
    # ★ 「红的总数 == 命中数」：防止某条样本"被抓到"其实是靠另一条判据顺带点红，
    #   或某些样本互相掩盖。这里要求**每个**样本都独立点红。
    assert fired == total, f"点红数 {fired} != 样本数 {total}"
