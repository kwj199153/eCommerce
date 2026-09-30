"""工具化路由子层的 `agent_name` 归一（第 198 轮）

==============================================================================
★ 这条门禁为什么必须存在
==============================================================================
`listing_generator` / `product_research` / `review_analyst` / `competitor_intel`
的 `_build_router()` 把路由子层建成：

    BaseAgent(agent_name=f"{self.agent_name}_router", tools=..., ...)

而技能启用（`skills.enabled_agents`）存的是**业务** agent_name ——
`service._validate_agents` 只接受 `modules/skills/agents.py::AGENT_CATALOG`
里那 8 个值。两条技能注入通道都按 `agent_name in enabled_agents` 过滤：

  · 目录（第一级披露）：`provider._catalog_provider` → `build_catalog_for`
  · 正文（点名加载）：`selected_skill_section` → `provider.read_skill_text`

⇒ 不做归一时，**走工具通道的 Agent 技能目录恒为空、点名读不到正文**，
   而且**一处日志都没有**（第 197 轮「技能目录不生效」的根因之一）。

==============================================================================
★ 反向注入（改坏了必须转红，否则这些用例是在空跑）
==============================================================================
  ① 删掉 `provider._catalog_provider` 里的 `business_agent_name(...)` 调用
     ⇒ `test_catalog_provider_normalizes_router_suffix` 红；
  ② 删掉 `selected_skill_section` 里的归一
     ⇒ `test_selected_skill_section_normalizes_router_suffix` 红；
  ③ 把 `business_agent_name` 改成恒等函数
     ⇒ 上面两条同时红；
  ④ 把某个 `_build_router()` 的后缀改成 `-router`（而 `ROUTER_SUFFIX` 不动）
     ⇒ `test_router_suffix_constant_matches_all_sub_layers` 红
        （★ 这条是 ① ② 3 条行为判据**覆盖不到**的缺口：它们打桩的是 provider
          自身，测的是「调用了归一函数」，不是「归一对得上」）。

★ ③ 的形态判据为什么也要有：行为判据只覆盖**已存在**的两条通道。
  将来新加第三条注入通道而忘了归一，行为判据看不见它 ⇒
  `test_both_injection_boundaries_call_the_normalizer` 用 AST 把
  「哪些文件必须调用归一」变成可执行名单。
"""

from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]


# ============================================================================
# A. 纯函数：归一只剥 `_router`，其它名字原样穿过
# ============================================================================


def test_business_agent_name_strips_only_router_suffix():
    """`X_router` → `X`；别的名字**一个字都不动**。

    ★ 为什么必须断言「别的名字不动」：归一是**字符串操作**，最容易写反成
      「取前缀」或「按 `_` 切第一段」—— 那会把 `review_analyst` 变成
      `review`、`competitor_intel` 变成 `competitor`，于是技能又不注入了，
      而且是从**另一个方向**坏掉（比不归一回更难查）。
    """
    from modules.skills.agents import ROUTER_SUFFIX, business_agent_name

    assert ROUTER_SUFFIX == "_router", "对外承诺的后缀变了 —— 请同步 `_build_router()`"
    assert business_agent_name("ListingGenerator_router") == "ListingGenerator"
    assert business_agent_name("listing_router") == "listing"
    assert business_agent_name("competitor_intel_router") == "competitor_intel"
    # ★ 下划线的业务名不能被切坏（回归防线）
    for name in ("review_analyst", "competitor_intel", "ad_analysis", "secretary"):
        assert business_agent_name(name) == name
    # 边界：空串 / None / 恰好等于后缀 / 后缀出现在中间
    assert business_agent_name("") == ""
    assert business_agent_name(None) == ""
    assert business_agent_name("_router") == "_router", "剥成空串会让名字消失"
    assert business_agent_name("a_router_router") == "a_router"
    assert business_agent_name("router") == "router"


# ============================================================================
# B. 行为判据：两条注入通道都必须**用归一后的名字**去过滤
# ============================================================================


async def test_catalog_provider_normalizes_router_suffix(monkeypatch):
    """目录通道：传给 `build_catalog_for` 的必须是**业务** agent_name。

    ★ 用打桩断言「参数传对了」而不是真去查库：
      真查库会让这条用例依赖 PG 与账号夹具，而它要钉的是一个**纯参数传递**问题
      （同族写法见 `test_hitl_wiring.py::test_save_candidate_tool_passes_shop_id`）。
    """
    import modules.skills.provider as P
    from ai_infra.prompt_sections import PromptContext

    seen: list = []

    async def _fake(agent_name, user_id):
        seen.append(agent_name)
        return ""

    monkeypatch.setattr(P, "build_catalog_for", _fake)

    await P._catalog_provider(PromptContext(agent_name="ListingGenerator_router"))
    await P._catalog_provider(PromptContext(agent_name="competitor_intel_router"))
    await P._catalog_provider(PromptContext(agent_name="secretary"))

    assert seen == ["ListingGenerator", "competitor_intel", "secretary"], (
        f"目录通道没归一（实得 {seen}）—— 走工具通道的 Agent 技能目录会恒为空"
    )


async def test_selected_skill_section_normalizes_router_suffix(monkeypatch):
    """点名通道：读正文时用的也必须是**业务** agent_name。

    ★ 这一条比目录那条更致命：目录为空只是「模型不知道有这个技能」，
      而点名读不到正文是「用户明确点了，模型却拿不到内容」
      —— 用户看到的就是一份没按他选的技能做的答案，而链接全绿。
    """
    import modules.skills.provider as P
    import modules.skills.selected_skill_section as S
    from ai_infra.prompt_sections import PromptContext
    from ai_infra.skills import bind_requested_skill

    seen: list = []

    async def _fake(user_id, agent_name, skill_name):
        seen.append((agent_name, skill_name))
        return "正文"

    monkeypatch.setattr(P, "read_skill_text", _fake)

    async with bind_requested_skill("price-drop-triage"):
        out = await S.selected_skill_prompt_section(
            PromptContext(agent_name="competitor_intel_router")
        )

    assert seen == [("competitor_intel", "price-drop-triage")], (
        f"点名通道没归一（实得 {seen}）—— 走工具通道时点名技能读不到正文"
    )
    assert "正文" in out, "归一对不上时这里会退化成「不可用」文案"


# ============================================================================
# C. 形态判据：两个注入边界都必须真的调用归一函数
# ============================================================================


def _calls_to(rel: str, func_name: str) -> list:
    """AST 取某文件里 `func_name(...)` 的调用节点（不看 docstring / 注释）。"""
    tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8", errors="replace"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Call):
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name == func_name:
                out.append(n.lineno)
    return out


def test_both_injection_boundaries_call_the_normalizer():
    """两条注入边界都必须**真的调用** `business_agent_name`。

    ★ 行为判据（B 组）打桩的是 provider 自身的函数 —— 它们证明「调用了」，
      但看不见**将来新增的第三条通道**。本条把「哪些文件必须调用」变成名单：
      新加一条技能注入通道时，把它加进本用例，忘了归一会当场红。
    """
    boundaries = {
        "modules/skills/provider.py": _calls_to(
            "modules/skills/provider.py", "business_agent_name"
        ),
        "modules/skills/selected_skill_section.py": _calls_to(
            "modules/skills/selected_skill_section.py", "business_agent_name"
        ),
    }
    empty = sorted(k for k, v in boundaries.items() if not v)
    assert not empty, (
        f"这些注入边界没有调用 `business_agent_name`：{empty}\n"
        f"⇒ 路由子层（`X_router`）的技能注入会静默失效。"
    )
    # 反向自检：扫描器本身不能空跑（名字写错时上面会「全都非空」而假绿）
    assert not _calls_to("modules/skills/tools_catalog.py", "business_agent_name"), (
        "扫描器把不存在的调用也算上了 ⇒ 本判据是空跑"
    )


def _router_suffix_fstrings() -> list:
    """扫全仓 `f"{<...>agent_name}<首尾常量>"` 形态的**两段式** f-string。

    ★ 口径为什么必须收得这么紧（第 198 轮实测教训）：
      初版是「f-string 尾常量里含 `router`」。各 Agent 的 `_build_router()` 里
      还有一条**日志** f-string：

          logger.warning(f"[competitor_intel] router build failed: {e}")

      它的尾常量 `"[competitor_intel] router build failed: "` 同样含 `router`
      ⇒ 4 条日志被当成 4 条路由子层 ⇒ 判据**恒红**、且红得毫无信息量。
      ★ 一般教训：「**含某子串**」是最弱的形态判据；能用**结构**表达就别用子串。
        这里真正的结构是：第一段是 `agent_name` 表达式、第二段是纯后缀常量。

    返回 `[(相对路径, 行号, 第一段表达式源码, 尾常量), ...]`。
    """
    out = []
    for p in sorted((BACKEND / "modules").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.JoinedStr) or len(n.values) != 2:
                continue
            first, last = n.values
            if not isinstance(first, ast.FormattedValue):
                continue
            if not (isinstance(last, ast.Constant) and isinstance(last.value, str)):
                continue
            expr = ast.unparse(first.value)
            if "agent_name" not in expr:
                continue
            out.append((p.relative_to(BACKEND).as_posix(), n.lineno, expr, last.value))
    return out


def _all_fstring_tails_containing(token: str) -> list:
    """宽口径（反例来源）：全仓所有「尾常量含 `token`」的 f-string 尾常量。

    ★ 只用于反向自检 —— 证明上面的收窄**真的**排除了日志 f-string，
      而不是因为「日志被删了」才绿的。
    """
    out = []
    for p in sorted((BACKEND / "modules").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:  # pragma: no cover
            continue
        for n in ast.walk(tree):
            if not isinstance(n, ast.JoinedStr):
                continue
            consts = [
                v.value for v in n.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            ]
            if consts and token in consts[-1]:
                out.append(consts[-1])
    return out


def test_router_suffix_constant_matches_all_sub_layers():
    """`ROUTER_SUFFIX` 必须与全仓 `_build_router()` 真实用的后缀**逐字一致**。

    ★ 这条补的是 B 组行为判据的盲区：归一是按后缀剥字符串，
      若有人把子层改成 `f"{name}__router"` 或 `f"{name}-router"`，
      `endswith("_router")` 为假 ⇒ 原样返回 ⇒ 技能又不注入了，
      而 B 组两条仍然绿（它们只证明「调用了归一函数」，不证明「对得上」）。
    """
    from modules.skills.agents import ROUTER_SUFFIX

    found = _router_suffix_fstrings()

    assert found, (
        "没扫到任何 `f\"{…agent_name…}\"` 形态的 f-string ⇒ 扫描器空跑"
        "（各 Agent 的 `_build_router()` 都被删了？那本条判据失去意义，"
        "但也不该是绿的）"
    )
    bad = [(rel, ln, tail) for rel, ln, _expr, tail in found if tail != ROUTER_SUFFIX]
    assert not bad, (
        f"这些路由子层的后缀与 `ROUTER_SUFFIX`({ROUTER_SUFFIX!r}) 对不上：{bad}\n"
        f"⇒ `business_agent_name` 会**静默失配**（原样返回）⇒ 技能注入再次失效。"
    )
    # ★ 第 204 轮：4 → **7**。本轮把 19 个悬空工具接上对应 Agent，新增 3 个走
    #   范式 A（工具路由子层）的 Agent：ad_analysis / aigc_media / customer_service。
    #   名单与 `tests/test_agent_tool_wiring.py::WIRED_AGENTS` 是**同一批**（那边用
    #   集合相等钉「每个工具容器都被某个 Agent 装配」，这边钉「每个装配点都在
    #   技能注入边界上走归一」）—— 两边数字对不上就是漏了一处。
    assert len(found) == 7, (
        f"工具化路由子层应为 7 个（listing / product_research / review_analyst / "
        f"competitor_intel / ad_analysis / aigc_media / customer_service），"
        f"实得 {len(found)}：{found}\n"
        f"★ 新增一个走范式 A 的 Agent 时请同步本数字，并确认它在技能注入边界上"
        f"也走归一（`business_agent_name`）。"
    )

    # ★ 反向自检（第 198 轮补）：宽口径必须**严格多于**收窄口径。
    #   两者相等只有两种可能：① 日志 f-string 被删了（本就该是红的信号），
    #   ② 扫描器退回了子串匹配（本判据失去指示价值）。两种都不该静默。
    broad = _all_fstring_tails_containing("router")
    assert len(broad) > len(found), (
        f"宽口径({len(broad)})与收窄口径({len(found)})一样多 ⇒ 收窄已失效："
        f"要么日志 f-string 没了，要么扫描器退回了子串匹配。\n"
        f"  宽口径命中：{broad}"
    )
    # 宽口径多出来的，必须全部是日志（即：确实只是被结构收窄排除掉的噪音）
    extra = [t for t in broad if t not in {f[3] for f in found}]
    assert all(" " in t for t in extra), (
        f"宽口径多出的项里出现了**不像日志**的尾常量 ⇒ 收窄可能把真的路由子层"
        f"也排除了：{extra}"
    )
