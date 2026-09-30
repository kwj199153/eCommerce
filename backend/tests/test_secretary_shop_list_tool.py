# -*- coding: utf-8 -*-
"""店秘书「列出店铺」只读工具门禁（第 243 轮 = 第 240 轮方案 A′）。

事故（`docs/round-240-shop-list-no-tool.md`，老板实测，不是假想）
------------------------------------------------------------------
老板问「我有几家店」→ 模型答成**套餐上限**（「最多可绑定 3 家」）；换一种措辞问，
它调 `switch_shop` 去数 —— **真的把店切了**。三层根因：

  ① 《列店铺》**没有专属工具**：`build_shop_tools()` 只产出 `switch_shop`，
     而它是**替换语义**（调一次就切一次），拿它回答「有几家店」= 无授权的状态变更；
  ② system prompt 的规则里**没有一条**覆盖「问有几家店」，只有「换店铺 → switch_shop」；
  ③ 全部工具里 **9 个在 prompt 零点名**，其中 6 个是业务能力
     （`list_candidates` / `list_products` / `list_assets` / `list_monitors` /
     `list_faqs` / `list_platform_rules`）⇒ 模型在「工具清单」里**看不到它们**。

修法（本文件钉的就是这三条）
----------------------------
  · 新增只读 `list_shops`（`build_shop_tools()` 1 → 2 个工具），出参与资料库家族同形；
  · prompt 点名 `list_shops`，并显式把「**问**店铺」与「**换**店铺」分成两条动作；
  · prompt 新增【资料库查询工具】分组，点名 6 个 `list_*`。

本文件钉六件事
--------------
A. **工具形态**：`build_shop_tools()` 恰两个工具、只读在前、`list_shops` 的
   `coroutine` 真的指向那个**会去查库**的实现（防"空壳工具"）；
B. **出参契约**：`list_shops` 的键集合恰为 `type/total/returned/items` 四键，
   **不含 `action`**（这是「查询不得带切换副作用」的机器可判形式）；
C. **读写两套契约并存且不同**：`switch_shop` 仍带 `action`，`list_shops` 不带；
D. **prompt 与工具集对齐**：点名的 snake token **必须都能解析成真实工具名**，
   且被点名集合**冻结**（工具改名/新增而 prompt 不跟 ⇒ 转红）；
E. **prompt 里「问 ≠ 换」是明文规则**（不是靠模型自己悟）：要有同段落同时出现
   `list_shops` / `switch_shop` / 否定词，且点名 `get_my_subscription` 的**上限**语义；
F. **目录表登记且副作用档为只读**（防"新增工具忘了登记"与"标成需审批"两种静默错）。

★ 为什么判据要**成对**（本仓铁律：「没有反例的断言 = 没有断言」）：
  `test_judgments_are_not_vacuous_and_can_be_injected` 给每个判据码都配了
  「一种能让它转红的**具体**改法」，并断言**每个判据码都被至少一个样本覆盖**
  —— 否则「扫描器写错了（永远返回空集）」与「全部合规」在读数上完全一样。
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
SHOP_TOOLS_PY = BACKEND / "modules" / "secretary" / "shop_tools.py"

#: A′ 要求被 prompt 点名的 6 个资料库只读工具（跨 Agent 共用，见 `modules/library/`）。
LIBRARY_LIST_TOOLS = (
    "list_candidates",
    "list_products",
    "list_assets",
    "list_monitors",
    "list_faqs",
    "list_platform_rules",
)

#: `list_shops` 出参的**契约键集合**（对齐 `modules/library/tools.py` 的四键家族）。
PAYLOAD_KEYS = {"type", "total", "returned", "items"}

#: `list_shops` 每个 item 的键集合（多一个 `action` 就会让前端误切店）。
ITEM_KEYS = {
    "id",
    "name",
    "platform",
    "index",
    "platform_family",
    "platform_index",
    "platform_total",
}

#: prompt 里允许被点名的 snake_case token **冻结集**（第 243 轮实测）。
#: ★ 冻结的意义：本仓第 240 轮的根因就是「prompt 与工具集不对齐」——
#:   工具加了没人告诉模型（看不见），改名了 prompt 还指着旧名（误导）。
#:   这张表把「prompt 点名了哪些工具」变成**可 diff 的规格**。
EXPECTED_PROMPT_TOKENS = frozenset(
    {
        "ask_clarification",
        "get_my_subscription",
        "handoff_to_agent",
        "list_assets",
        "list_candidates",
        "list_faqs",
        "list_monitors",
        "list_platform_rules",
        "list_products",
        "list_shops",
        "open_account_menu",
        "open_view",
        "select_product",
        "set_theme",
        "switch_agent",
        "switch_shop",
    }
)

SNAKE = re.compile(r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b")
DENIAL_WORDS = ("不要", "别", "禁止", "严禁", "绝不允许", "不允许")

#: 判据码全集（**除**动态的 `missing:X` / `unknown:Y`）—— 反向注入必须全覆盖。
STATIC_JUDGMENT_CODES = frozenset(
    {
        # _check_payload / _check_item_shape
        "payload_keys",
        "payload_type",
        "payload_has_action",
        "payload_items_not_list",
        "payload_total",
        "payload_returned",
        "item_keys",
        "no_items_to_check",
        # _check_source
        "no_factory",
        "factory_tool_count",
        "factory_tool_names_or_order",
        "list_shops_coroutine",
        "switch_shop_coroutine",
        "list_shops_desc_not_readonly",
        "no_payload_fn",
        "payload_does_not_call_list_shops",
        "payload_literal_action",
        # _check_prompt
        "prompt_tokens_changed",
        "no_read_write_rule",
        "no_subscription_boundary",
    }
)

#: 固定夹具：3 家店 / 2 个平台（**不进 DB** —— 判出参形态不需要真库）。
FAKE_SHOPS = [
    {"id": "store_a", "name": "亚马逊1", "platform": "amazon_us", "index": 1,
     "platform_family": "amazon", "platform_index": 1, "platform_total": 2, "total": 3},
    {"id": "store_b", "name": "虾皮1", "platform": "shopee_my", "index": 2,
     "platform_family": "shopee", "platform_index": 1, "platform_total": 1, "total": 3},
    {"id": "store_c", "name": "亚马逊2", "platform": "amazon_uk", "index": 3,
     "platform_family": "amazon", "platform_index": 2, "platform_total": 2, "total": 3},
]


# ============================================================================
# 取真实工件（判据的输入必须是**真物件**，不是手抄的副本）
# ============================================================================


def _read_source() -> str:
    return SHOP_TOOLS_PY.read_text(encoding="utf-8", errors="replace")


def _prompt() -> str:
    from modules.secretary.agent import SECRETARY_SYSTEM_PROMPT

    return SECRETARY_SYSTEM_PROMPT


def _tools():
    from modules.secretary.shop_tools import build_shop_tools

    return build_shop_tools()


def _tool(name: str):
    tools = _tools()
    for t in tools:
        if t.name == name:
            return t
    raise AssertionError(f"build_shop_tools() 里没有 {name}：{[t.name for t in tools]}")


def _run_payload(shops=None) -> dict:
    """用**真协程**跑一遍出参（把 `_list_shops` 换成固定夹具 ⇒ 零 DB）。

    ★ 为什么替换的是 `_list_shops` 而不是手写一个 dict：后者只能证明"我写对了字面量"，
      证明不了"工具真的把 `_list_shops` 的返回值按契约包了一层"。
    """
    from modules.secretary import shop_tools as st

    async def _fake():
        return list(FAKE_SHOPS if shops is None else shops)

    original = st._list_shops
    st._list_shops = _fake
    try:
        raw = asyncio.run(st._list_shops_payload())
    finally:
        st._list_shops = original
    return json.loads(raw)


# ============================================================================
# 判据实现（**全部是可被喂"脏输入"的纯函数** ⇒ 反向注入才可能）
# ============================================================================


def _check_payload(payload: dict) -> set[str]:
    """B：出参契约（键集合 / type / 两个计数 / 无 action）。"""
    bad: set[str] = set()
    if set(payload) != PAYLOAD_KEYS:
        bad.add("payload_keys")
    if payload.get("type") != "shop_list":
        bad.add("payload_type")
    if "action" in payload:
        bad.add("payload_has_action")
    items = payload.get("items")
    if not isinstance(items, list):
        bad.add("payload_items_not_list")
    else:
        if payload.get("total") != len(items):
            bad.add("payload_total")
        if payload.get("returned") != len(items):
            bad.add("payload_returned")
    return bad


def _check_item_shape(items: list) -> set[str]:
    bad: set[str] = set()
    if not items:
        bad.add("no_items_to_check")
    for it in items:
        if set(it) != ITEM_KEYS:
            bad.add("item_keys")
    return bad


def _check_source(src: str) -> set[str]:
    """A：装配形态（AST，不认注释与 docstring —— 本仓被"源码串包含"骗过多次）。"""
    bad: set[str] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return {"no_factory"}

    factory = _find_def(tree, "build_shop_tools")
    if factory is None:
        return {"no_factory"}

    calls = _factory_calls(factory)
    if len(calls) != 2:
        bad.add("factory_tool_count")

    named = [_kw_literal(c, "name") for c in calls]
    if named != ["list_shops", "switch_shop"]:
        # ★ 顺序也钉：只读的在前（同 `navigation_tools` 把 ask_clarification
        #   排在 handoff 之前的做法 —— 工具排列对 LLM 有弱提示作用）。
        bad.add("factory_tool_names_or_order")

    coros = {_kw_literal(c, "name"): ast.unparse(_kw_node(c, "coroutine")) for c in calls}
    if coros.get("list_shops") != "_list_shops_payload":
        bad.add("list_shops_coroutine")
    if coros.get("switch_shop") != "_switch_shop":
        bad.add("switch_shop_coroutine")

    # ★ 只读这件事必须在**给模型看的 desc 里**说清楚：模型不会读我们的 metadata。
    #   修前的实测形态正是"模型不知道还有只读的店铺查询"，只能拿会切店的凑数。
    desc = _desc_literal(next((c for c in calls if _kw_literal(c, "name") == "list_shops"), None))
    if "只读" not in desc:
        bad.add("list_shops_desc_not_readonly")

    payload_fn = _find_def(tree, "_list_shops_payload")
    if payload_fn is None:
        return bad | {"no_payload_fn"}

    called = {ast.unparse(n.func) for n in ast.walk(payload_fn) if isinstance(n, ast.Call)}
    # ★ 防空壳：工具接了、docstring 写了，但实现没去查库（本仓最爱出的形态）。
    if "_list_shops" not in called:
        bad.add("payload_does_not_call_list_shops")

    # 出参里不许出现字符串字面量 `action`（剥掉 docstring 再扫）。
    if "action" in _string_literals(payload_fn):
        bad.add("payload_literal_action")
    return bad


def _check_prompt(prompt: str) -> set[str]:
    """D/E：prompt 与工具集的**对齐**（点名存在性 + token 冻结 + 明文规则）。"""
    bad: set[str] = set()

    for name in ("list_shops",) + LIBRARY_LIST_TOOLS:
        if name not in prompt:
            bad.add("missing:" + name)

    tokens = set(SNAKE.findall(prompt))
    if tokens != EXPECTED_PROMPT_TOKENS:
        bad.add("prompt_tokens_changed")

    from modules.secretary.agent import SecretaryAgent

    real = {t.name for t in SecretaryAgent().tools}
    for tok in sorted(tokens - real):
        bad.add("unknown:" + tok)

    # ★ 判「同一**行**」而不是「同一**段**」：规则 1–8 是**一个**大段（中间没有空行），
    #   段级判据会被段里别处的「不要」（规则 1/6/7/8）无条件满足 —— 那等于没有判据。
    #   实测：把规则 4 里两个否定词都换成肯定词，段级判据**照样绿**。
    if not any(
        "switch_shop" in line and any(d in line for d in DENIAL_WORDS)
        for line in prompt.splitlines()
    ):
        bad.add("no_read_write_rule")

    # ★ 用**有界窗口**串起跨行的两半：`get_my_subscription` 与其「上限」语义被换行隔开
    #   （前半在前一行行尾、后半在后一行行首），按行判会假红 ⇒ 给 80 字符窗口。
    if not re.search(r"get_my_subscription[\s\S]{0,80}上限", prompt):
        bad.add("no_subscription_boundary")
    return bad


# ---- AST 小工具 ----


def _find_def(tree: ast.AST, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _factory_calls(factory) -> list:
    return sorted(
        [
            n for n in ast.walk(factory)
            if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("from_function")
        ],
        key=lambda c: c.lineno,
    )


def _kw_node(call: ast.Call, key: str):
    for kw in call.keywords:
        if kw.arg == key:
            return kw.value
    return ast.Constant(value=None)


def _kw_literal(call: ast.Call, key: str):
    node = _kw_node(call, key)
    return node.value if isinstance(node, ast.Constant) else None


def _desc_literal(call) -> str:
    """取 `description=` 的**字面量**值（相邻字符串字面量由解析器自动折叠）。"""
    if call is None:
        return ""
    try:
        return str(ast.literal_eval(_kw_node(call, "description")) or "")
    except (ValueError, SyntaxError):
        return ""


def _string_literals(fn) -> set[str]:
    """函数体里的字符串字面量（**剥掉 docstring** —— 它常复述这些词）。"""
    out: set[str] = set()
    for i, stmt in enumerate(fn.body):
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                out.add(node.value)
    return out


# ============================================================================
# A/B/C —— 工具形态与出参契约（跑真物件）
# ============================================================================


def test_build_shop_tools_has_both_read_and_switch():
    """★ A：读（`list_shops`）与写/切（`switch_shop`）**必须同时存在**。

    ★ 反向注入已验证：删掉 `list_shops`（回到修前形态）⇒ 本用例红。
    """
    names = [t.name for t in _tools()]
    assert names == ["list_shops", "switch_shop"], (
        f"店铺工具应为 [list_shops, switch_shop]（只读在前），实为 {names}。\n"
        "⇒ 少了 list_shops 就回到第 240 轮那个形态：「问有几家店」只能拿会切店的\n"
        "   switch_shop 或套餐上限 get_my_subscription 去回答（两个都是错答案）。"
    )
    assert _check_source(_read_source()) == set()


def test_list_shops_is_declared_read_only():
    """★ F：`list_shops` 的 metadata 必须是**只读**（否则会给老板弹一个无谓的审批）。"""
    from ai_infra.tools.side_effects import has_side_effects

    tool = _tool("list_shops")
    assert has_side_effects(tool) is False, (
        "list_shops 只读，却被声明成有副作用 ⇒ HITL 会给「列个店铺」弹审批框。"
    )
    assert not tool.args, f"list_shops 不该需要入参（模型只需说一句「我有几家店」），实为 {tool.args}"


def test_list_shops_payload_contract():
    """★ B：出参形态 —— 四键 + `total` 是**真实条数** + 每项 7 个定位字段。"""
    payload = _run_payload()
    assert _check_payload(payload) == set(), payload
    assert _check_item_shape(payload["items"]) == set(), payload["items"]

    assert payload == {
        "type": "shop_list",
        "total": 3,
        "returned": 3,
        "items": [
            {"id": "store_a", "name": "亚马逊1", "platform": "amazon_us", "index": 1,
             "platform_family": "amazon", "platform_index": 1, "platform_total": 2},
            {"id": "store_b", "name": "虾皮1", "platform": "shopee_my", "index": 2,
             "platform_family": "shopee", "platform_index": 1, "platform_total": 1},
            {"id": "store_c", "name": "亚马逊2", "platform": "amazon_uk", "index": 3,
             "platform_family": "amazon", "platform_index": 2, "platform_total": 2},
        ],
    }, "出参逐键对不上 —— 契约靠这段字面量钉住（改它必须是有意识的）"


def test_list_shops_payload_has_no_action_key():
    """★★★ B 的核心：查询工具**绝不能**带 `action` 键。

    为什么这条是整轮的正题：前端 `dispatchAppAction` 见到 `action: "switch_shop"`
    就**真的切店**。修前的缺陷形态正是「拿 switch_shop 数店铺 ⇒ 顺手把店切了」。
    只要出参里没有 `action`，这条路就被机器堵死 —— 与提示词里怎么写无关。
    """
    payload = _run_payload()
    assert "action" not in payload
    assert '"action"' not in json.dumps(payload, ensure_ascii=False), (
        "出参文本里出现了 action 键 —— 前端的动作分发可能据此误切店"
    )


def test_list_shops_handles_zero_shops_without_raising():
    """空店铺时也要回**合法四键**（total=0），不能抛错、也不能回 `{}`。

    ★ 为什么单列一条：修前 `_switch_shop` 在无店铺时回的是 `{"action": ..., "reason": ...}`
      —— 若有人把 `list_shops` 也套用那个形态，模型会拿到 `reason` 而不是 `total`，
      于是「我还没建店」与「读不出来」在模型眼里长得一样（归因错方向）。
    """
    payload = _run_payload(shops=[])
    assert _check_payload(payload) == set(), payload
    assert payload == {"type": "shop_list", "total": 0, "returned": 0, "items": []}


def test_switch_shop_still_returns_action_marker():
    """★ C 对照：`switch_shop` 的契约**不变**（仍带 `action`，前端据此切店）。

    ★ 为什么必须有这条对照：只断言「list_shops 没有 action」是不够的 ——
      若有人把 `switch_shop` 的 `action` 也删了（"统一出参形态"这种好心），
      功能会静默失效（前端再也切不了店），而 list_shops 那条判据照样绿。
    """
    from modules.secretary import shop_tools as st

    async def _fake():
        return list(FAKE_SHOPS)

    original = st._list_shops
    st._list_shops = _fake
    try:
        raw = asyncio.run(st._switch_shop(shop_name="虾皮1"))
    finally:
        st._list_shops = original

    data = json.loads(raw)
    assert data["action"] == "switch_shop"
    assert data["shop"]["name"] == "虾皮1"
    assert data["total"] == 3


def test_factory_ast_shape_and_payload_is_not_a_hollow_shell():
    """★ A（AST）：装配形态 + `_list_shops_payload` 真的去查库。

    ★ 为什么这条不能省：出参形态判据只证明"包装对了"，证明不了"里面真有数据"。
      一个 `return json.dumps({...items: []})` 的空壳能通过上面所有值判据。
    """
    src = _read_source()
    assert _check_source(src) == set()
    payload_fn = _find_def(ast.parse(src), "_list_shops_payload")
    assert isinstance(payload_fn, ast.AsyncFunctionDef), "它必须是个 async 协程"
    # 最后一个语句必须是 `return json.dumps(` —— 证明它返回的是**序列化字符串**
    # 而不是把原始 list 直接塞给模型（后者与资料库家族出参形态不一致）。
    assert ast.unparse(payload_fn.body[-1]).startswith("return json.dumps(")


# ============================================================================
# D/E —— prompt 与工具集对齐（第 240 轮的根因 ②③）
# ============================================================================


def test_prompt_names_list_shops_and_the_six_library_tools():
    """★ D：7 个工具（`list_shops` + 6 个 `list_*`）必须**被 prompt 点名**。

    ★ 根因 ③ 的形态就是"工具在、但 prompt 的清单里没有它" ⇒ 模型选不到。
      判据必须是**点名**（token 出现在 prompt 里），不是"工具被装配了"。
    """
    prompt = _prompt()
    assert _check_prompt(prompt) == set(), sorted(_check_prompt(prompt))
    for name in ("list_shops",) + LIBRARY_LIST_TOOLS:
        assert name in prompt, f"prompt 没点名 {name} —— 模型在工具清单里看不见它"


def test_prompt_snake_tokens_all_resolve_to_real_tools():
    """★★★ D 的通用形态：prompt 里出现的**每个** snake token 都必须是真实工具名。

    这条是第 240 轮根因的**通用判据**（不是只盯这 7 个）：
      · 工具改名而 prompt 不跟 ⇒ prompt 指着不存在的工具（误导模型）；
      · prompt 里新写一个名字但工具不存在 ⇒ 同上；
      · 工具新增而 prompt 不跟 ⇒ token 集合变小 ⇒ `prompt_tokens_changed` 转红。
    """
    from modules.secretary.agent import SecretaryAgent

    real = {t.name for t in SecretaryAgent().tools}
    tokens = set(SNAKE.findall(_prompt()))

    assert tokens <= real, f"prompt 指着不存在的工具：{sorted(tokens - real)}"
    assert tokens == EXPECTED_PROMPT_TOKENS, (
        f"prompt 点名的工具集变了：多了 {sorted(tokens - EXPECTED_PROMPT_TOKENS)}、"
        f"少了 {sorted(EXPECTED_PROMPT_TOKENS - tokens)}。\n"
        "⇒ 这是**有意识的**改动吗？本仓第 240 轮的事故就是「prompt 与工具集不对齐」：\n"
        "   工具加了不告诉模型 = 模型看不见；工具改名不改 prompt = 模型被误导。\n"
        "   若确认要改，请同步 `EXPECTED_PROMPT_TOKENS` 并说明理由。"
    )


def test_prompt_separates_asking_from_switching():
    """★ E：prompt 必须**明文**把「问店铺」与「换店铺」分成两条动作。

    ★ 为什么判"同**行**"而不是判某个句子、也不是判"同段"：
      · 只判 `list_shops in prompt` 会被"清单里列了、规则里没说"骗过 ——
        而根因 ② 正是**规则里没有一条**覆盖「问有几家店」；
      · 判"同段"同样无效：规则 1–8 是**一个**大段，段里别处的「不要」会让它恒真
        （实测：把规则 4 的两个否定词都换成肯定词，段级判据照样绿）。
      ⇒ 把否定词钉在**它约束的那一行**上（含 `switch_shop` 的那行），才有区分力。
    """
    lines = _prompt().splitlines()

    sep = [l for l in lines if "switch_shop" in l and any(d in l for d in DENIAL_WORDS)]
    assert sep, (
        "找不到「不许拿 switch_shop 去数店铺」的明文行。要求**同一行**里同时出现：\n"
        "  · switch_shop（被约束的工具）\n"
        "  · 一个否定词（不要/别/禁止/严禁/不允许）\n"
        "⇒ 缺了它，修前那种「拿 switch_shop 去数店铺」的行为没有任何东西拦着。"
    )

    bnd = re.search(r"get_my_subscription[\s\S]{0,80}上限", _prompt())
    assert bnd, (
        "找不到「get_my_subscription 是套餐**上限**、不是店铺数」的边界说明。\n"
        "⇒ 这是第 240 轮实测的第一个衍生危害（答成「最多可绑定 3 家」），必须有明文排除。\n"
        "   （判据用 80 字符窗口而不是「同一行」：这两半被换行隔开了。）"
    )


def test_list_shops_desc_tells_the_model_it_is_read_only():
    """★ E 的姊妹判据：只读这件事必须写在**给模型看的 desc** 里。

    ★ 模型不读我们的 `metadata`（那是给 HITL 门禁用的人话判定）——
      它只读 `description`。修前「问有几家店」出事的直接原因就是
      **没有任何一处告诉模型存在只读的店铺查询**。
    """
    assert "只读" in (_tool("list_shops").description or "")
    assert _check_source(_read_source()) == set()


def test_catalog_registers_list_shops_as_read_only():
    """★ F：工具目录表必须登记 `list_shops`，且副作用档为**只读**。

    ★ 与 `tests/test_tool_catalog.py` 的分工：那条管"表 == 装配点真值"（通用）；
      这里独立钉一次「本工具是只读」—— 因为一旦标成 `approval`，
      界面上「列个店铺」会被标成"需审批"，而通用门禁只比对两侧是否**一致**
      （两侧一起改成 approval 它也绿）。
    """
    from modules.skills.tools_catalog import EFFECT_READ_ONLY, TOOL_CATALOG

    rows = [t for t in TOOL_CATALOG if t["name"] == "list_shops"]
    assert len(rows) == 1, f"目录表里 list_shops 有 {len(rows)} 条（要求恰好 1 条）"
    row = rows[0]
    assert row["agent"] == "secretary"
    assert row["effect"] == EFFECT_READ_ONLY, row
    assert row["title"] and row["description"]


# ============================================================================
# G —— 反向注入自检：每个判据码都必须能被一种**具体**改法点红
# ============================================================================


def _drop_factory_entry(src: str, name: str) -> str:
    """删掉 `build_shop_tools()` 返回列表里的**整个**条目（按 AST 行号，语法仍合法）。"""
    tree = ast.parse(src)
    calls = _factory_calls(_find_def(tree, "build_shop_tools"))
    target = next(c for c in calls if _kw_literal(c, "name") == name)
    lines = src.split("\n")
    return "\n".join(lines[: target.lineno - 1] + lines[target.end_lineno:])


def _swap_factory_entries(src: str) -> str:
    """把返回列表里的两个条目**对调**（只读排到后面）。"""
    tree = ast.parse(src)
    calls = _factory_calls(_find_def(tree, "build_shop_tools"))
    a, b = calls[0], calls[1]
    lines = src.split("\n")
    a_lines = lines[a.lineno - 1: a.end_lineno]
    b_lines = lines[b.lineno - 1: b.end_lineno]
    return "\n".join(lines[: a.lineno - 1] + b_lines + a_lines + lines[b.end_lineno:])


def test_judgments_are_not_vacuous_and_can_be_injected():
    """★ 没有反例的断言 = 没有断言。

    做三件事：
      ① 真实工件上四条判据**必须零违规**（否则下面每个样本的读数都没有意义）；
      ② 20 个样本，每个声明 `expect`（**应当**命中的判据码），逐码精确比对 ——
         "多命中"与"少命中"都判红（不用 `in` 模糊放过）；
      ③ 断言 `STATIC_JUDGMENT_CODES` **被样本全覆盖**，且动态码
         （`missing:*` / `unknown:*`）各至少有 1 个样本 —— 防"某个判据从来没有反例"。
    """
    clean_src = _read_source()
    clean_prompt = _prompt()
    clean_payload = _run_payload()

    # ① 真实工件零违规。
    assert _check_source(clean_src) == set()
    assert _check_prompt(clean_prompt) == set()
    assert _check_payload(clean_payload) == set()
    assert _check_item_shape(clean_payload["items"]) == set()

    # ---- 出参侧的样本（在真出参上做最小改动）----
    def _mut(**kw):
        p = json.loads(json.dumps(clean_payload))
        p.update(kw)
        return p

    payload_samples = {
        # 有人在出参里塞了 action（= 查询工具长出了切换副作用）
        "payload_gets_action": (_mut(action="switch_shop"), {"payload_keys", "payload_has_action"}),
        # total 变成"我猜的数"而不是真实条数（模型会照着答错）
        "payload_total_lies": (_mut(total=99), {"payload_total"}),
        # returned 与 items 脱钩（模型按 returned 判断"还有下一页"）
        "payload_returned_drifts": (_mut(returned=2), {"payload_returned"}),
        # type 改名 ⇒ 模型认不出这是哪一族出参
        "payload_type_renamed": (_mut(type="shops"), {"payload_type"}),
        # items 不是数组（有人图省事回了个字符串）
        "payload_items_not_list": (
            _mut(items="亚马逊1,虾皮1"),
            {"payload_items_not_list"},
        ),
        # items 少一个键 ⇒ 模型拿不到平台内序号（修前"第二个虾皮店铺"切错店的老坑）
        "item_missing_platform_index": (
            {"type": "shop_list", "total": 1, "returned": 1,
             "items": [{k: v for k, v in clean_payload["items"][0].items()
                        if k != "platform_index"}]},
            {"item_keys"},
        ),
        # 空 items：形态判据自己不许"空集恒真"（这就是那条自检的反例）
        "item_shape_on_empty_list": (
            {"type": "shop_list", "total": 0, "returned": 0, "items": []},
            {"no_items_to_check"},
        ),
    }

    # ---- 源码侧的样本 ----
    source_samples = {
        # 回到修前形态：工厂只产 switch_shop
        # （顺带命中 desc 判据 —— 条目都没了，自然也没有它的只读 desc）
        "factory_drops_list_shops": (
            _drop_factory_entry(clean_src, "list_shops"),
            {"factory_tool_count", "factory_tool_names_or_order",
             "list_shops_coroutine", "list_shops_desc_not_readonly"},
        ),
        # 顺序反了（只读排到后面）—— 有人"顺手"重排
        "factory_order_swapped": (
            _swap_factory_entries(clean_src),
            {"factory_tool_names_or_order"},
        ),
        # 工厂整体改名/消失
        "factory_renamed": (
            clean_src.replace("def build_shop_tools()", "def build_shop_tools_v2()", 1),
            {"no_factory"},
        ),
        # 读工具被接到"有副作用"的那个实现上（读语义被换掉 ⇒ 形态门禁必须拦住）
        "list_shops_wired_to_switch": (
            clean_src.replace(
                "            coroutine=_list_shops_payload,\n            name=\"list_shops\",",
                "            coroutine=_switch_shop,\n            name=\"list_shops\",",
                1,
            ),
            {"list_shops_coroutine"},
        ),
        # 排他性对照：switch_shop 被改接到只读实现上（前端再也切不了店）
        "switch_shop_wired_to_payload": (
            clean_src.replace(
                "        StructuredTool.from_function(\n            coroutine=_switch_shop,\n            name=\"switch_shop\",",
                "        StructuredTool.from_function(\n            coroutine=_list_shops_payload,\n            name=\"switch_shop\",",
                1,
            ),
            {"switch_shop_coroutine"},
        ),
        # 协程实现函数被改名（工具还在，指向的东西没了）
        "payload_fn_renamed": (
            clean_src.replace("async def _list_shops_payload(", "async def _list_shops_payload_x(", 1),
            {"no_payload_fn"},
        ),
        # 空壳：接了工具但不查库（本仓最爱出的形态：机制齐全、永远空）
        "payload_is_hollow_shell": (
            clean_src.replace("    shops = await _list_shops()", "    shops = []", 1),
            {"payload_does_not_call_list_shops"},
        ),
        # 出参里手写了一个 action 字面量（绕过 json 包装往里塞动作）
        "payload_literal_action": (
            clean_src.replace(
                '        {\n            "type": "shop_list",',
                '        {\n            "action": "switch_shop",\n            "type": "shop_list",',
                1,
            ),
            {"payload_literal_action"},
        ),
        # desc 不再声明「只读」⇒ 模型仍可能把列店铺当成"顺带切一下"
        "desc_not_readonly": (
            clean_src.replace(
                '"列出当前身份可见的全部店铺（**只读**，不会切换店铺）。"',
                '"列出当前身份可见的全部店铺。"',
                1,
            ),
            {"list_shops_desc_not_readonly"},
        ),
    }

    # ---- prompt 侧的样本 ----
    prompt_samples = {
        # 老病复发：工具还在，但 prompt 不再点名（= 模型看不见）
        "prompt_drops_library_tools": (
            clean_prompt.replace("list_monitors", "monitor_list_off", 1),
            {"missing:list_monitors", "prompt_tokens_changed", "unknown:monitor_list_off"},
        ),
        # 工具改名而 prompt 不跟 ⇒ prompt 指着旧名（误导）
        "prompt_keeps_stale_name": (
            clean_prompt.replace("list_shops", "list_shop", 2),
            {"missing:list_shops", "prompt_tokens_changed", "unknown:list_shop"},
        ),
        # token 集合变了但都是真工具名（新增工具没登记进冻结集）
        "prompt_token_set_changed": (
            clean_prompt + "\n\n- list_faqs2：占位说明",
            {"prompt_tokens_changed", "unknown:list_faqs2"},
        ),
        # ★ 「问 ≠ 换」那条规则**只剩摆设**：switch_shop 与它同一行的否定词被拿掉
        #   ⇒ 这正是根因 ② 的形态（规则写得像建议、没有任何一层拦着）。
        "prompt_drops_read_write_rule": (
            clean_prompt.replace("**绝不允许**为了回答", "**可以直接**为了回答", 1),
            {"no_read_write_rule"},
        ),
        # 套餐上限那条边界被删（衍生危害 ① 复发）
        "prompt_drops_subscription_boundary": (
            clean_prompt.replace("是套餐**最多能绑几家**的上限", "是套餐信息", 1),
            {"no_subscription_boundary"},
        ),
    }

    samples: list[tuple[str, str, set]] = []
    for name, (payload, expect) in payload_samples.items():
        got = _check_payload(payload)
        if set(payload) >= PAYLOAD_KEYS and isinstance(payload.get("items"), list):
            got |= _check_item_shape(payload["items"])
        samples.append((name, "payload", (got, expect)))
    for name, (src, expect) in source_samples.items():
        samples.append((name, "source", (_check_source(src), expect)))
    for name, (prompt, expect) in prompt_samples.items():
        samples.append((name, "prompt", (_check_prompt(prompt), expect)))

    failures: list[str] = []
    covered: set[str] = set()
    for name, kind, (got, expect) in samples:
        if not expect:
            failures.append(f"[{kind}] {name}: 该样本没有声明任何期望命中 ⇒ 它不是反例")
        if got != expect:
            failures.append(
                f"[{kind}] {name}: 期望 {sorted(expect)}，实得 {sorted(got)}\n"
                f"      ⇒ 要么样本改错了地方（注入本身失败），要么判据漏检/误检"
            )
        covered |= {c for c in expect if ":" not in c}

    missing_codes = sorted(STATIC_JUDGMENT_CODES - covered)
    assert not missing_codes, (
        f"这些判据码**没有任何反例**：{missing_codes}\n"
        "⇒ 「没有反例的断言 = 没有断言」（本仓铁律）。请补样本或删掉该判据。"
    )
    assert any(":" in c for _n, _k, (_g, e) in samples for c in e), "`missing:`/`unknown:` 一个样本都没有"

    assert not failures, "反向注入失败：\n  " + "\n  ".join(failures)
