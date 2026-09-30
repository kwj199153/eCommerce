# -*- coding: utf-8 -*-
"""工具目录门禁：`TOOL_CATALOG` 必须与**真实装配点**双向一致（第 185 轮 · 批 A）

==============================================================================
★ 这条门禁拦的是什么
==============================================================================
`modules/skills/tools_catalog.py` 是一张**手写表**（65 个业务工具），
手写表最容易出的问题不是"写错"，而是**过时**：

  · 某个工具改名 ⇒ 表里那个名字在运行时不存在 ⇒ 界面下发一个不存在的工具，
    租户勾了、后端存了、**运行期静默不生效**；
  · 新增一个工具（或新增一个 Agent 绑了一组工具）⇒ 表里没有 ⇒
    它在界面上**根本选不到**，而没有任何一处报错；
  · 某工具的副作用声明从 `SIDE_EFFECT_METADATA` 改成 `READ_ONLY_METADATA` ⇒
    表里仍标 `approval`（或反过来）⇒ 界面上的"需审批"标记**在骗人**。

三种症状的共同点是：**不报错、日志全绿、测试不红**。
⇒ 本文件把表的两侧都钉到**运行时可执行的真值**上。

==============================================================================
★ 为什么真值必须**运行时**取（本仓连续两轮踩过）
==============================================================================
真值 = 源码里 `BaseAgent(tools=...)` 实参所指向的那些工具的**真实名字**。

第 183/184 轮两个探针都用 AST 静态扫模块级属性，结果把「真接线工具数」
算成了 54（把内部构件也算进来）和 25（漏读秘书 3 个模块）——
**同一个问题两个错答案**。根因是秘书的装配长这样：

    product_tools = build_product_tools(shop_id)      # ← 工厂动态构造
    shop_tools = build_shop_tools()
    super().__init__(..., tools=navigation_tools + subscription_tools
                                       + product_tools + shop_tools, ...)

`build_product_tools` 产出哪些工具，**AST 看不见**，只有调用它才知道。
⇒ 本门禁 import 真实模块、真实调用工厂，取 `tool.name` 作为真值。
   实测口径 = 65。沿革：原文 28 → 第 204 轮接线 19 个后 55 →
   批 A 收敛「同端点多名」后 57 → 批 B 接入候选生命周期三条后 60
   （`get_candidate` / `review_candidate` / `approve_candidate`）→
   第 207 轮退役竞品 5 条后 55 →
   **第 218 轮资料库扩到 6 库后 59**（+`list_assets` / `list_monitors` /
   `list_faqs` / `list_platform_rules`，全是只读）→
   **第 243 轮新增只读 `list_shops` 后 60**（店秘书 9 → 10；方案 A′，
   见 `docs/round-240-shop-list-no-tool.md`。全是只读 ⇒ 分子不变）→
   **第 251 轮新增只读 `list_reviews`（复盘库读口）后 61**（运营复盘师 6 → 7；
   只读 ⇒ 分子仍为 4）→ **第 313 轮退役 `ad_review` 后 66**
   （运营复盘师 7 → 6；老板「运营复盘删除广告数据」⇒ 该工具连对话路由 /
   提示词清单一起退，只保留 `/review/ad-review` 端点作历史归档读口）→
   **第 316 轮退役广告分析师 2 个（`optimize_budget` / `detect_ad_anomalies`）后 64**
   （老板「广告分析师删除异常检测、广告预算再平衡」⇒ 工具 / 对话意图 /
   REST 端点 / 大屏 Tab / 技能一起退）。
   **第 325 轮新增只读 `query_market_insight`（选品大盘读口）后 65**
   （选品分析师 8 → 9；老板「让 agent 可以读数据库，**解耦前端界面大盘**」⇒
   这份数据从「只有前端面板一条通道」变成「面板与对话同走 `MARKET_SNAPSHOT_SPEC`
   这一份声明」；只读 ⇒ 分子仍为 5）。

==============================================================================
★ 五条判据（+ 两条自检）
==============================================================================
  A. 名字侧**集合相等**：目录表 == 装配点真值（双向，不是 ⊆）
  B. 副作用档一致：目录的 `effect` ⇔ 运行时 `has_side_effects()`
  C. 每个 `agent` ∈ `AGENT_CATALOG`（否则界面分组会与 Agent 装配 Tab 对不上）
  D. 表结构完整 + `name` 唯一 + `effect` 取值合法
  E. **防"门禁不知道的装配点"**：全仓每个 Agent 装配调用的 `tools=` 实参表达式，
     至少要引用一个本文件登记过的容器名 —— 否则新增 Agent 绑全新工具组时
     门禁会**静默放行**（本文件最容易出的假绿形态）

  ★ 自检 1：装配点解析出的工具数 == 65（防 import 失败导致的空集 ⇒ 集合相等变恒真）
  ★ 自检 2：`TOOL_CATALOG` 非空（防"两边都是空集也算相等"）

  ★★ 第 205 轮新增四条（收敛「同端点多名」的落点）：
  G. **跨 Agent 共用**：目录的 `agents` 必须**逐字等于**运行时「手里真有这个工具」
     的 Agent 集合（集合相等，两个方向都咬）；
  H. **一个能力一个实现**：同名工具在不同 Agent 手里必须是同一个
     `(模块, 限定名)` —— 两家各写一份同名工具会直接转红；
  I. **落选同义名不得复活**：`REJECTED_TOOL_ALIASES` 里的名字不得出现在
     目录或任何运行时工具集里；
  J. **共用工具的调用点必须注入归属来源**（`shop_id=` 或 `resolve=`），
     否则它会永远回「未选择店铺」，而调用方看不出自己漏了注入；
  K. **宿主机的装配点只能引用已登记容器**：`tools=` 实参里只允许「名字 + 加号」，
     且每个名字要么是已登记容器，要么在本文件里被绑定为「对已登记工厂的一次裸调用」
     —— 禁止在装配点**就地另拼**工具（那是 G/H 的共同盲区，实测注入不会红）。

==============================================================================
★ 反向注入（验证这五条真的会红）
==============================================================================
  · 把表里 `optimize_listing_title` 改成 `optimize_listing_title_v2` ⇒ A 红
  · 把 `save_candidate` 的 `effect` 改成 `read_only`              ⇒ B 红
  · 把表里某条 `agent` 改成 `nonexistent_agent`                   ⇒ C 红
  · 删掉表里任意一条                                              ⇒ A 红（真值多出）
  · 给 `listing_generator` 新增一个工具但不登记                    ⇒ A 红（真值多出）
"""

from __future__ import annotations

import ast
import inspect
import pathlib
from functools import lru_cache

BACKEND = pathlib.Path(__file__).resolve().parents[1]

#: 工具装配点 —— **运行时真值的取法**。
#:
#: `(agent_name, 模块路径, 成员名, 是否工厂)`。
#: 与 `modules/skills/tools_catalog.py` 的 docstring 列出的真源表逐条对应；
#: 少一条 ⇒ 判据 A 会红（真值变少、目录多出）。
#:
#: ★★ 真值的**射程**（第 204 轮反向注入实测 —— 别高估它）：
#:   本表是**容器级**的：判据 A 只问「这些**容器**里的工具名」，
#:   **不检查该容器有没有被某个 Agent 真的绑上**。
#:   实测：把 `agent_ad._build_router` 的 `tools=ad_analysis_tools` 换成
#:   `aigc_tools`（该容器就此悬空）后，判据 A **不红** —— 红的是
#:   `test_agent_tool_wiring.py::test_every_tool_registry_is_wired_to_an_agent`
#:   与 `...::test_wired_agents_pass_expected_registry`。
#:   ⇒ 两处是**分工**不是重复：
#:     · 本文件   —— 「表里的名字 == 这些容器产出的事实」（手写表不许漂移）；
#:     · 接线门禁 —— 「这些容器真的被某个 Agent 拿在手上」。
#:   缺任何一处都会造出「可勾选但调不起来」的工具，且**不报错**。
ASSEMBLY_POINTS: tuple = (
    ("ListingGenerator", "modules.listing_generator.tools", "listing_tools", False),
    ("ProductResearcher", "modules.product_research.tools", "product_research_tools", False),
    ("review_analyst", "modules.review_analyst.tools", "review_analyst_tools", False),
    # ★ 第 198 轮接线：竞品监控员从「范式 B（关键词路由、零工具）」迁到
    #   「范式 A（`_build_router()` + bind_tools）」，本行随之登记。
    ("competitor_intel", "modules.competitor_intel.tools", "competitor_intel_tools", False),
    ("secretary", "modules.secretary.navigation_tools", "navigation_tools", False),
    ("secretary", "modules.secretary.subscription_tools", "subscription_tools", False),
    ("secretary", "modules.secretary.product_tools", "build_product_tools", True),
    ("secretary", "modules.secretary.shop_tools", "build_shop_tools", True),
    # ★ 第 205 轮：**跨 Agent 共用**的资料库只读工具（`modules/library/`，
    #   SHARED 层）。这里登记的是**店秘书**那一份；选品分析师那一份随
    #   `product_research_tools` 的尾部相加一并进来 ⇒ 同一个工具名会同时
    #   出现在两家的真值里，这正是「共用」的定义。
    #   ★ 判据 G（`test_shared_tool_convergence.py`）拿这份真值去核对目录里的
    #     `agents` 字段 —— 多一家少一家都红。
    ("secretary", "modules.library.tools", "build_library_tools", True),
    # ★ 第 204 轮接线：这三个此前是**悬空注册表**（注册了但没有任何 Agent
    #   绑定，合计 19 个工具）。本轮各自补了 `_build_router()`（范式 A），
    #   本表随之登记 —— 漏登记 ⇒ 判据 E 红。
    #   ★ 第一列是 `AGENT_CATALOG` 的**精确** `agent_name`（含中文那两个），
    #     不能写模块名：判据 C 的补集会拿它跟 `grouped_catalog()` 对账。
    ("ad_analysis", "modules.ad_analysis.tools", "ad_analysis_tools", False),
    ("AIGC 媒体生成器", "modules.aigc_media.tools", "aigc_tools", False),
    ("智能客服", "modules.customer_service.tools", "customer_service_tools", False),
)

#: 机制型工具 —— 它们由 `ai_infra.skills.build_skill_tools()` 恒装在每个 Agent 上，
#: **不是业务能力**，不属于「租户可绑定的工具」。判据 A 要把它们排除，
#: 否则「目录缺 load_skill」会变成一条永远红的判据。
MECHANISM_TOOLS: frozenset = frozenset({"load_skill"})

#: Agent **装配点所在文件**（判据 K 的扫描面）。
#: 与 `tests/test_agent_tool_wiring.py::WIRED_AGENTS` / `WIRED_SECRETARY` 同一批宿主
#: —— 那边管「容器有没有交出去 / 交的对不对」，这边管「交出去的只能是容器」。
ASSEMBLY_HOSTS: tuple = (
    "modules/ad_analysis/agent_ad.py",
    "modules/aigc_media/agent_aigc.py",
    "modules/customer_service/agent_cs.py",
    "modules/competitor_intel/agent_competitor.py",
    "modules/listing_generator/agent_listing.py",
    "modules/product_research/agent_product_research.py",
    "modules/review_analyst/agent.py",
    "modules/secretary/agent.py",
)


def _call_factory(fn):
    """调用工具工厂。参数个数用 `inspect` 取，不硬编码 ——
    工厂签名变化（`build_product_tools(shop_id)` → 加参数）时本门禁仍能跑。"""
    sig = inspect.signature(fn)
    required = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        and p.default is p.empty
    ]
    args = tuple("__probe_shop__" for _ in required)
    return fn(*args)


@lru_cache(maxsize=1)
def real_assembly_tools() -> dict:
    """运行时取每个装配点的**真实工具**。

    返回 `{agent_name: [tool 对象, …]}`。工厂型装配点会**真的调用**工厂。

    ★ 用 `lru_cache` 而不是模块级常量：本函数会 import 全部业务模块，
      成本高；但若在 import 期执行，任何一处业务模块的 import 错误都会
      变成**本文件收集失败**（pytest 报 error 而不是 fail，看不出是哪条判据）。
      放进函数里 ⇒ 失败被定位到具体用例。
    """
    import importlib
    import sys

    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))

    out: dict = {}
    for agent, modname, ref, is_factory in ASSEMBLY_POINTS:
        mod = importlib.import_module(modname)
        obj = getattr(mod, ref)
        tools = _call_factory(obj) if is_factory else obj
        if not isinstance(tools, (list, tuple)):
            raise AssertionError(
                f"装配点 {modname}.{ref} 不是列表（{type(tools).__name__}）—— "
                f"它是工具工厂的返回值吗？请同步本文件的 ASSEMBLY_POINTS。"
            )
        out.setdefault(agent, [])
        out[agent].extend(list(tools))
    return out


def real_tool_names() -> set:
    """运行时真值的**名字集合**（已剔除机制型工具）。"""
    names = set()
    for tools in real_assembly_tools().values():
        for t in tools:
            name = str(getattr(t, "name", "") or "")
            if name and name not in MECHANISM_TOOLS:
                names.add(name)
    return names


def real_tool_objects() -> dict:
    """运行时真值的 `名字 → tool 对象`（判据 B 要读对象的 `metadata`）。"""
    out = {}
    for tools in real_assembly_tools().values():
        for t in tools:
            name = str(getattr(t, "name", "") or "")
            if name and name not in MECHANISM_TOOLS:
                out[name] = t
    return out


# ============================================================================
# 自检：真值不能是空集（否则判据 A 会变成"空 == 空"式的恒真）
# ============================================================================


def test_real_assembly_is_not_vacuous():
    """★ 自检：装配点必须真的解析出 65 个工具。

    ★ 这条拦的是本文件最危险的假绿形态：**import 失败 / 工厂调用失败**，
      让 `real_tool_names()` 返回空集。那时若把判据 A 写成
      「目录 ⊆ 真值」，空集照样通过 —— 门禁变成装饰。
      （本文件用集合**相等**，空集也过不了，但这条自检能让失败原因
        直接指向"解析没跑起来"，而不是让人去猜。）
    """
    names = real_tool_names()
    assert len(names) == 65, (
        f"装配点解析出 {len(names)} 个工具（期望 65）：{sorted(names)}\n"
        f"⇒ 要么某个模块 import 失败、要么某个工厂调用失败、"
        f"要么新增/删除了工具而本文件的 ASSEMBLY_POINTS 没跟。"
    )
    assert MECHANISM_TOOLS.isdisjoint(names), "机制型工具混进了业务真值"


def test_catalog_is_not_vacuous():
    """★ 自检：目录表非空 —— 防"两边都是空集也算相等"。"""
    from modules.skills.tools_catalog import TOOL_CATALOG

    assert len(TOOL_CATALOG) == 65, f"目录表有 {len(TOOL_CATALOG)} 条（期望 65）"


# ============================================================================
# A. 名字侧：集合相等
# ============================================================================


def test_catalog_names_match_real_assembly():
    """★★★ 判据 A（核心）：目录表工具名 == 真实装配点工具名，**集合相等**。

    用相等而不是 ⊆，是为了让两个方向都能咬住：
      · 工具改名 / 被删 ⇒ 目录里那个名字在真值中不存在 ⇒ 红（过时的表）
      · 新增工具但没登记 ⇒ 真值多出一个名字           ⇒ 红（缺失的表）

    两个方向的后果**都是静默的**（界面下发不存在的工具 / 新工具选不到），
    所以这条判据是整张表唯一的守门人。
    """
    from modules.skills.tools_catalog import all_tool_names

    catalog = set(all_tool_names())
    real = real_tool_names()

    stale = sorted(catalog - real)
    missing = sorted(real - catalog)

    assert not stale, (
        f"目录表里的这些工具名**在装配点已不存在**：{stale}。\n"
        f"⇒ 界面会下发一个不存在的工具，租户勾了、存了、**运行期不生效**，且不报错。\n"
        f"   改名/删除工具时请同步 `modules/skills/tools_catalog.py::TOOL_CATALOG`。"
    )
    assert not missing, (
        f"装配点里有这些工具，但目录表**没有登记**：{missing}。\n"
        f"⇒ 新增工具时忘了同步目录表。后果是它在界面上根本选不到"
        f"（该工具永远无法被任何技能绑定），而且没有任何一处会报错。"
    )


# ============================================================================
# B. 副作用档一致
# ============================================================================


def test_catalog_effect_matches_runtime_side_effect_declaration():
    """★★★ 判据 B：目录的 `effect` 必须与工具自己的 `metadata` 声明一致。

    ★ 这条的**方向性**很关键（`ai_infra/tools/side_effects.py` 的 fail-closed）：
      真源是工具对象上的 `metadata={"side_effects": …}`，
      `has_side_effects()` 未声明时默认 `True`（宁可多审批）。
      目录若把「有副作用」的标成 `read_only`，界面就不会提示"需审批" ——
      那是**危险方向**的错。

    反向注入：把 `save_candidate` 的 `effect` 改成 `read_only` ⇒ 本条必红。
    """
    from ai_infra.tools.side_effects import has_side_effects

    from modules.skills.tools_catalog import EFFECT_APPROVAL, EFFECT_READ_ONLY, TOOL_CATALOG

    objs = real_tool_objects()
    problems = []
    for item in TOOL_CATALOG:
        tool = objs.get(item["name"])
        if tool is None:
            # 名字缺失由判据 A 负责报；这里跳过避免重复报错掩盖真因。
            continue
        runtime_effect = EFFECT_APPROVAL if has_side_effects(tool) else EFFECT_READ_ONLY
        if item["effect"] != runtime_effect:
            problems.append(
                f"{item['name']}: 目录写 {item['effect']!r}，"
                f"运行时判定 {runtime_effect!r}"
            )

    assert not problems, (
        "目录的副作用档与工具自己的 `metadata` 声明不一致：\n  "
        + "\n  ".join(problems)
        + "\n⇒ 界面上的「需审批」标记在骗人。改声明时请同步目录表。"
    )


def test_the_expected_tools_need_approval():
    """★ 已知事实固化：65 个工具里**恰好 5 个**需要人工审批（会写库的那 5 个）。

    ★ 为什么分子 +1（第 287 轮）：`propose_review_disposition` 真往
      `review_dispositions` 落一行 —— 这是给那张三无表补的**写入点**。
      它必须进审批档，否则「Agent 自己发券」这条路就开了。

    ★ 为什么分母又变了（第 251 轮）：新增只读 `list_reviews`（读复盘库，不写库）
      ⇒ **分子不动**。本条真正钉的是分子，分母只是顺手写实。

    ★ 为什么分母又变了（第 243 轮）：新增只读 `list_shops`（读店铺列表，不写库）
      ⇒ **分子不动**。本条真正钉的是分子，分母只是顺手写实。

    ★ 为什么分母又变了（第 218 轮）：资料库从 2 库扩到 6 库（+4 条**只读**工具）
      ⇒ **分子没动**。本条真正钉的是分子，分母只是顺手写实。

    ★ 为什么分母变了（第 207 轮）：退役竞品 5 条工具（60 → 55），全是只读 ⇒
      **分子没动**。这条判据真正钉的是分子，分母只是顺手写实。

    ★ 为什么数字变了（第 205 轮）：本文件批 B 把候选生命周期的两条写库动作
      （`review_candidate` / `approve_candidate`）从 REST handler 下沉到
      `service` 并注册成 Agent 工具。它们**本来就在写库**（REST 端点的既有
      行为），只是此前 Agent 够不着 ⇒ 这次是「既有写库动作**第一次**进入模型
      可调范围」，与下面第 204 轮 `create_ticket` 的情形同类。
      ⇒ 界面上的「需审批」标记必须跟上，否则它在骗人。

    ★ 为什么数字变了（第 204 轮）：`create_ticket` 随 `customer_service_tools`
      接线进入可勾选清单 —— 它**本来就有**副作用（会写 `cs_tickets` 表），
      此前只是因为注册表**悬空**才没在界面上露面。
      ⇒ **不是新增了写库工具，是原本就有的那个写库工具第一次出现在界面上。**
        但界面上的「需审批」标记必须跟上，否则它在骗人。

    ★ 为什么要单独钉住：这个数字是**产品语义**的一部分（"工具技能里会弹审批的
      只有写选品库与建客服工单那两个"），它会出现在文案与用户预期里。
      数量变化本身不一定是错（新增一个写库工具是合理的），
      但必须是**有意识**的变化 ⇒ 这条红的时候请确认文案与提示是否也要改。

    （本仓判据「门禁是墓志铭」：需求变了，钉住旧形态的断言就从资产变负资产。
      所以这里断言的是"当前有意为之的形态"，改需求时同步改本条。）
    """
    from modules.skills.tools_catalog import EFFECT_APPROVAL, TOOL_CATALOG

    approvals = sorted(t["name"] for t in TOOL_CATALOG if t["effect"] == EFFECT_APPROVAL)
    assert approvals == [
        "approve_candidate",
        "create_ticket",
        "propose_review_disposition",
        "review_candidate",
        "save_candidate",
    ], (
        f"需要审批的工具变成 {approvals}"
        f"（期望 ['approve_candidate', 'create_ticket', "
        f"'propose_review_disposition', 'review_candidate', 'save_candidate']）。\n"
        f"⇒ 若这是有意的（新增写库工具），请同步：①本断言 ②界面文案 "
        f"③`ai_infra/tools/side_effects.py` 的 WRITE_VERB_PREFIXES 覆盖。"
    )


# ============================================================================
# C. agent 侧
# ============================================================================


def test_catalog_agents_are_known_agents():
    """★ 判据 C：每条 `agent` 必须是 `AGENT_CATALOG` 里的真实 `agent_name`。

    ★ 为什么重要：界面上工具按 Agent 分组，而「Agent 装配」Tab 也用同一张
      `AGENT_CATALOG`。两处若对不上，用户会看到「一个不存在的 Agent 名下有工具」
      ——或者更常见的是：他想给某 Agent 绑工具，但那个 Agent 在工具清单里没出现。
    """
    from modules.skills.agents import all_agent_names
    from modules.skills.tools_catalog import TOOL_CATALOG

    known = set(all_agent_names())
    bad = sorted({t["agent"] for t in TOOL_CATALOG if t["agent"] not in known})
    assert not bad, (
        f"目录表里出现未知 Agent：{bad}\n"
        f"（合法值 = `modules/skills/agents.py::AGENT_CATALOG` 的 name 字段）"
    )


def test_every_agent_with_tools_is_covered():
    """★ 判据 C 的补集：至少一个工具的那个 Agent，在 `grouped_catalog()` 里必须出现。

    （只查「目录里的 agent 合法」是不够的 —— 还要查「真值里带工具的 Agent
      一个都没漏」，否则某个 Agent 的工具全被漏登记时，判据 A 会红但
      判据 C 仍然绿，症状指向不明。）
    """
    from modules.skills.agents import all_agent_names
    from modules.skills.tools_catalog import grouped_catalog

    grouped_agents = {g["agent"] for g in grouped_catalog()}
    known = set(all_agent_names())
    assert grouped_agents <= known, f"分组里出现未知 Agent：{sorted(grouped_agents - known)}"

    # 真值里有工具的 Agent 必须都在分组里
    real_agents = {a for a, tools in real_assembly_tools().items() if tools}
    assert real_agents == grouped_agents, (
        f"分组 Agent ≠ 真值里有工具的 Agent。\n"
        f"  真值有而分组缺: {sorted(real_agents - grouped_agents)}\n"
        f"  分组有而真值缺: {sorted(grouped_agents - real_agents)}"
    )


# ============================================================================
# D. 表结构
# ============================================================================


def test_catalog_entries_are_well_formed():
    """每项必须有 agent / name / title / description / effect，且 `name` 唯一。"""
    from modules.skills.tools_catalog import EFFECT_APPROVAL, EFFECT_READ_ONLY, TOOL_CATALOG

    seen = set()
    for item in TOOL_CATALOG:
        for key in ("agent", "name", "title", "description", "effect"):
            assert str(item.get(key) or "").strip(), f"目录项缺 {key}：{item!r}"
        assert item["name"] not in seen, f"工具名重复：{item['name']}"
        assert item["effect"] in (EFFECT_READ_ONLY, EFFECT_APPROVAL), (
            f"{item['name']} 的 effect 取值非法：{item['effect']!r}"
        )
        # 工具名是给模型看的函数名，必须是 ASCII snake_case ——
        # 界面允许自由输入时最容易混进中文或空格。
        assert item["name"].isascii() and " " not in item["name"], (
            f"{item['name']!r} 不是合法的工具名形态（应为 ASCII snake_case）"
        )
        seen.add(item["name"])


def test_lookup_helpers_are_total():
    """`is_known_tool` / `tool_title` 对未知输入必须**安全降级**（不抛错）。"""
    from modules.skills.tools_catalog import (
        all_tool_names,
        is_known_tool,
        tool_entry,
        tool_title,
    )

    assert is_known_tool("save_candidate") is True
    assert is_known_tool("__nope__") is False
    assert is_known_tool("") is False
    assert is_known_tool(None) is False
    assert tool_entry("save_candidate")["effect"] == "approval"
    assert tool_entry("__nope__") is None
    # ★ 未知工具**原样返回**：库里可能存在本表登记之前写入的工具名，
    #   它们必须能被显示（否则租户看不见、也就删不掉）。
    assert tool_title("__nope__") == "__nope__"
    assert tool_title("save_candidate") == "加入选品库"
    assert all_tool_names() == tuple(t["name"] for t in __import__(
        "modules.skills.tools_catalog", fromlist=["TOOL_CATALOG"]
    ).TOOL_CATALOG)


# ============================================================================
# E. 防"门禁不知道的装配点"（本文件最容易出的假绿）
# ============================================================================


#: 本仓 Agent 装配的**调用名**。
#:
#: ★ 第 338 轮（P0-6 第四刀）：追加 `build_router` —— `product_research` 的
#:   装配点从 `BaseAgent(...)` 移到了 `agent_routing.build_router(...)`
#:   （主文件薄壳委托）。只认 `BaseAgent` 会让「选品分析师绑了哪张注册表」
#:   从**判据 E 的扫描面里静默消失** —— 反向注入 INJ-L 实测过：
#:   把那一行改坏而判据 E 不红。
#:
#: ★ 这份名单只允许**一处**：自检用例原先把它内联复制了一份，于是补名字时
#:   只改了扫描器 ⇒ 自检仍「漏认新形态」（第 338 轮实测踩过）。
ASSEMBLY_CALL_NAMES = frozenset({"BaseAgent", "__init__", "build_router"})


def _is_assembly_tools_kwarg(kw) -> bool:
    """`tools=` 实参是否构成一个**真实装配点**。

    ★ 排除「同名转发」（`tools=tools`）：那只是把调用方传进来的容器再往下一层
      传，真正的容器名在**调用方**。不排除的话，`agent_routing.build_router`
      这类「显式传参装配器」（P0-6 第四刀新建）会被当成一个伪装配点 ——
      判据 E 于是出现一条**永远红**的条目。
      ★ 反向注入实测：真实装配点写的是 `tools=xxx_tools`（名字不同）或
        `tools=a + b`（BinOp），都不会被这条排除规则误伤。
    """
    if kw.arg != "tools":
        return False
    return not (isinstance(kw.value, ast.Name) and kw.value.id == "tools")


def _tools_kwarg_expressions() -> list:
    """AST 扫全仓，取**Agent 装配调用**的 `tools=` 实参表达式文本。

    ★ 只认 `BaseAgent(...)` / `super().__init__(...)` 两种调用形态 ——
      这是本仓 Agent 装配的两种真实写法（见 `probes/o183_wiring.txt` A 段）。
      `SkillRecord(tools=…)`（技能表写入）**不是** Agent 装配，必须排除，
      否则它的实参 `list(spec.get('tools') or [])` 会被当成一个"未知装配点"。
    """
    agent_call_names = ASSEMBLY_CALL_NAMES
    out: list = []
    for p in sorted((BACKEND / "modules").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = p.relative_to(BACKEND).as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if name not in agent_call_names:
                continue
            for kw in n.keywords:
                if _is_assembly_tools_kwarg(kw):
                    out.append((rel, n.lineno, ast.unparse(kw.value)))
    return out


def test_every_agent_assembly_point_is_registered():
    """★★★ 判据 E：全仓每个 Agent 装配的 `tools=` 实参，至少要引用一个已登记容器。

    ★ 为什么需要这条（A 管不到的地方）：
      判据 A 比较的是「目录 vs **本文件登记的**装配点」。如果新增一个 Agent
      绑了一组**全新**工具（例如 `modules/xxx/agent.py` 里
      `BaseAgent(tools=brand_new_tools)`），而 `build_product_tools` 那类工厂
      又不需要登记 —— 那么：
        · 判据 A 照样绿（它只比它自己那 12 个装配点）
        · 界面上那个 Agent 的工具**永远选不到**，且不报错
      本条把「**全仓所有** tools= 实参」拉进来对账，堵住这个缺口。

    ★ 判据形态：实参表达式里**包含**某个已登记容器名（子串匹配）。
      用「包含」而不是「相等」是因为秘书那种 `a + b + c + d` 形态 ——
      四个容器名都要能被识别。反向注入：新增 `tools=foo_tools` ⇒ 红。
    """
    known_refs = {ref for _, _, ref, _ in ASSEMBLY_POINTS}
    # 秘书的 `product_tools` / `shop_tools` 在源码里是**函数内局部变量**
    # （由工厂赋值），表达式里出现的是局部名而非工厂名 ⇒ 两个都要认。
    known_refs |= {"product_tools", "shop_tools", "library_tools"}

    exprs = _tools_kwarg_expressions()
    assert len(exprs) >= 4, (
        f"只扫到 {len(exprs)} 处 Agent 装配的 tools= 实参（期望 ≥4）：{exprs}\n"
        f"⇒ 扫描器空跑会让本条变成恒绿；Agent 装配写法变了请同步 `_tools_kwarg_expressions`。"
    )

    unregistered = [
        (rel, line, expr)
        for rel, line, expr in exprs
        if not any(ref in expr for ref in known_refs)
    ]
    assert not unregistered, (
        "这些 Agent 装配点了**未登记**的工具容器：\n  "
        + "\n  ".join(f"{rel}:{line}  tools={expr}" for rel, line, expr in unregistered)
        + "\n⇒ 若这是新 Agent / 新工具组，请同步："
        "①本文件 `ASSEMBLY_POINTS` ②`modules/skills/tools_catalog.py::TOOL_CATALOG`。"
        "\n   否则那些工具在界面上**永远选不到**，而且没有任何一处会报错。"
    )


def test_tools_scanner_is_not_vacuous():
    """★ 自检：`tools=` 扫描器能认出两种调用形态，且**不误收** `SkillRecord`。"""
    src = (
        "class A:\n"
        "    def __init__(self):\n"
        "        super().__init__(tools=navigation_tools + product_tools)\n"
        "\n"
        "class B:\n"
        "    def __init__(self):\n"
        "        BaseAgent(agent_name='x', tools=other_tools)\n"
        "\n"
        "def f():\n"
        "    return SkillRecord(tools=list(spec.get('tools') or []))\n"
        "\n"
        "def build_router(*, tools):\n"
        "    return BaseAgent(agent_name='r', tools=tools)\n"
        "\n"
        "def g():\n"
        "    return _routing.build_router(tools=assembled_tools)\n"
    )
    tree = ast.parse(src)
    got = []
    for n in ast.walk(tree):
        if not isinstance(n, ast.Call):
            continue
        fn = n.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
        if name not in ASSEMBLY_CALL_NAMES:
            continue
        for kw in n.keywords:
            if _is_assembly_tools_kwarg(kw):
                got.append(ast.unparse(kw.value))

    assert len(got) == 3, f"扫描器应只认 Agent 装配的 3 处，实得 {got}"
    assert any("assembled_tools" in e for e in got), (
        f"漏了 `_routing.build_router(tools=…)` 形态 —— "
        f"那正是 P0-6 第四刀后的 product_research 装配点：{got}"
    )
    assert any("navigation_tools" in e for e in got), f"漏了 super().__init__ 形态：{got}"
    assert any("other_tools" in e for e in got), f"漏了 BaseAgent 形态：{got}"
    assert not any("spec.get" in e for e in got), (
        "扫描器把 `SkillRecord(tools=…)` 当成 Agent 装配了 —— "
        "那会让判据 E 出现一条永远红的伪装配点"
    )
    assert not any(e == "tools" for e in got), (
        "扫描器把「同名转发」（`tools=tools`）当成装配点了 —— "
        "那只是显式传参装配器，真正的容器名在**调用方**"
    )

# ============================================================================
# F. 「每个 Agent 都有工具，或已登记为纯文本型」（第 198 轮 · 老板点名要的那条）
# ============================================================================


def test_every_agent_has_tools_or_is_declared_text_only():
    """★★★ 判据 F：`AGENT_CATALOG` 里每个 Agent，要么名下有 ≥1 个工具，
    要么在 `TEXT_ONLY_AGENTS` 里**显式登记**（并写明理由）。

    ★ 这条补的是什么缺口（第 197 轮实测）：本文件原来的五条判据都只回答
      「登记的工具对不对」，**没有一条**回答「某个 Agent 一个工具都没有」。
      实测有 4 个 Agent 的工具数为 0（`ad_analysis` / `AIGC 媒体生成器` /
      `智能客服` / `competitor_intel`），而这件事在任何门禁里都看不见：
        · 那个 Agent 在工具清单里不出现（`grouped_catalog` 跳过空组 ——
          这是对的，界面不该出现空标题）；
        · 运行期它拿不到任何数据，且不报错。
      ⇒ 新写一个 Agent 忘了绑工具时，唯一能拦住它的就是本条。

    ★ 为什么用「显式白名单 + 理由」而不是「允许为空」：
      允许为空 ⇒ 本条恒绿，等于没有。白名单让每一处「零工具」都是
      **有人签过字**的（同族：`test_tool_registry_guard` 的悬空棘轮）。

    ★ 反向注入：把白名单里任一 Agent 绑上工具、或新增一个零工具 Agent 而不
      登记 ⇒ 本条必红。
    """
    from modules.skills.agents import all_agent_names
    from modules.skills.tools_catalog import TEXT_ONLY_AGENTS, grouped_catalog

    known = set(all_agent_names())
    assert len(known) == 8, f"AGENT_CATALOG 应有 8 个 Agent，实为 {len(known)}"

    with_tools = {g["agent"] for g in grouped_catalog()}
    declared = set(TEXT_ONLY_AGENTS)

    # ① 白名单本身必须合法（防改名后变成一份无声失效的死名单）
    unknown = sorted(declared - known)
    assert not unknown, (
        f"TEXT_ONLY_AGENTS 里出现未知 Agent：{unknown}\n"
        f"⇒ Agent 改名后这份白名单会**静默失效**（它不再约束任何东西）。"
    )

    # ② 覆盖：每个 Agent 都要有出口
    naked = sorted(known - with_tools - declared)
    assert not naked, (
        f"这些 Agent **一个业务工具都没有**，也没有登记进 TEXT_ONLY_AGENTS：{naked}\n"
        f"⇒ 它们在运行期拿不到任何数据、在工具清单里也不出现，而且**不报错**。\n"
        f"   二选一：给它绑工具（`_build_router()` 或 `super().__init__(tools=…)`），"
        f"或在 `modules/skills/tools_catalog.py::TEXT_ONLY_AGENTS` 登记并写明理由。"
    )

    # ③ 反向：已经有工具的 Agent 不许留在白名单里（否则白名单会腐烂成谎话）
    stale = sorted(declared & with_tools)
    assert not stale, (
        f"这些 Agent 名下已有工具，却仍登记在 TEXT_ONLY_AGENTS 里：{stale}\n"
        f"⇒ 白名单已经过时（它现在在骗人）。请把它们从白名单里删掉。"
    )


def test_text_only_agents_entries_are_substantive():
    """★ 自检：白名单**里每一条**都必须写了像样的理由（**空表是合格状态**）。

    ★ 为什么不再要求「非空」（第 204 轮）：原断言是 `assert TEXT_ONLY_AGENTS`
      —— 当时有 4 个零工具 Agent（`ad_analysis` / `AIGC 媒体生成器` /
      `智能客服` / `competitor_intel`），「必须非空」是防占位符的合理约束。
      第 204 轮把最后 3 个接上工具后，这份白名单**应当为空** ——
      此时「非空」从资产变成了**负资产**：它会把「所有 Agent 都有工具」
      这个更好的状态判成红，逼人往白名单里塞一条假条目。
      （同族判据：`test_hitl_wiring.py` 里记的「门禁是墓志铭」。）

    ★ 那「白名单恒空」会不会让判据 F 的 ③ 变成恒真？不会 ——
      真正咬住「有没有 Agent 零工具」的是判据 F 的 **②**：
      `naked = known - with_tools - declared` 必须为空，且
      `len(known) == 8` 把 Agent 总数钉死。③ 的职责（防白名单腐烂）
      在表为空时**无事可做**，退化成恒真是可接受的，不是缺口。
    """
    from modules.skills.tools_catalog import TEXT_ONLY_AGENTS

    for name, why in TEXT_ONLY_AGENTS.items():
        text = str(why or "").strip()
        assert len(text) >= 20, f"{name} 的理由过短或为空（{why!r}）"


# ============================================================================
# G/H. 跨 Agent 共用：归属集合 ⇔ 运行时真值（第 205 轮「收敛同端点多名」）
# ============================================================================


def _runtime_holders() -> dict:
    """`{工具名: {手里真有它的 Agent}}` —— 由**装配点真值**反推。

    ★ 这份真值只回答「哪个 Agent 的容器里有这个工具名」。
      它**不检查**那些容器有没有被真的交给 Agent —— 后者是
      `tests/test_agent_tool_wiring.py` 的职责（两处是分工不是重复，
      见本文件 `ASSEMBLY_POINTS` 上方「真值的射程」注释）。
    """
    out: dict = {}
    for agent, tools in real_assembly_tools().items():
        for t in tools:
            name = str(getattr(t, "name", "") or "")
            if name and name not in MECHANISM_TOOLS:
                out.setdefault(name, set()).add(agent)
    return out


def _runtime_tool_objects() -> dict:
    """`{工具名: {Agent: tool 对象}}`（判据 H 要比对底层实现）。"""
    out: dict = {}
    for agent, tools in real_assembly_tools().items():
        for t in tools:
            name = str(getattr(t, "name", "") or "")
            if name and name not in MECHANISM_TOOLS:
                out.setdefault(name, {})[agent] = t
    return out


def test_shared_tools_exist_and_are_the_decided_ones():
    """★ 自检：**声明为共用**的工具必须恰好是那两个 —— 否则 G/H 形同虚设。

    ★ 为什么把名字写死：这是一条**决策记录**（第 205 轮老板拍板的收敛结果），
      不是自动推导出来的。写死它，等于让「共用面扩大了 / 缩小了」都必须
      有人**有意识地**改这一行。（同族判据：本仓「门禁是墓志铭」。）
    """
    from modules.skills.tools_catalog import shared_tools

    got = shared_tools()
    # ★ 第 218 轮（P1）从 2 → 6：资料库 6 库全覆盖，共用面**有意识地**扩大了。
    assert set(got) == {
        "list_candidates",
        "list_products",
        "list_assets",
        "list_monitors",
        "list_faqs",
        "list_platform_rules",
    }, (
        f"声明为跨 Agent 共用的工具变成 {sorted(got)}，"
        f"期望 ['list_assets', 'list_candidates', 'list_faqs', 'list_monitors', "
        f"'list_platform_rules', 'list_products']。\n"
        f"⇒ 若这是有意的收敛结果，请同步本断言；否则是有人把单归属的条目"
        f"误加了 `agents`。"
    )
    for name, agents in got.items():
        assert len(agents) == 2, f"{name} 的归属应是 2 家，实为 {agents}"


def test_shared_tool_agents_match_runtime_holders():
    """★★★ 判据 G：目录声明的归属集合 == 运行时**真有**这个工具的 Agent 集合。

    ★ 这条钉的是什么（否则 `agents` 只是一句没人验证的说明）：
      · 写了 `agents: [A, B]` 而其实只有 A 装了 ⇒ 界面上 B 也能勾它，
        但 B 运行期手里根本没有这个工具（「绑了调不到」，本仓反复踩过）；
      · 只写了 `agent: A` 而其实 A、B 都装了 ⇒ 界面上 B 看不到自己**确实能用**
        的工具（能力被静默藏起来）。
      两个方向都不报错 ⇒ 必须用**集合相等**双向钉住（同判据 A 的理由）。

    ★ 反向注入（已实测）：把 `list_candidates` 的 `agents` 改成
      `["ProductResearcher"]` ⇒ 本条必红（真值里还有 `secretary`）。
    """
    from modules.skills.tools_catalog import TOOL_CATALOG, entry_agents

    holders = _runtime_holders()
    assert holders, "运行时真值解析为空 —— 本条会假绿（先查 ASSEMBLY_POINTS）"

    problems = []
    for item in TOOL_CATALOG:
        declared = set(entry_agents(item))
        actual = holders.get(item["name"], set())
        if declared != actual:
            problems.append(
                f"{item['name']}: 目录声明 {sorted(declared)}，运行时真值 {sorted(actual)}"
            )
    assert not problems, (
        "目录的归属集合与「谁手里真有这个工具」对不上：\n  "
        + "\n  ".join(problems)
        + "\n⇒ 多写了 ⇒ 那家 Agent 在界面上能勾却调不起来；"
        "少写了 ⇒ 它看不到自己能用的工具。两者都不报错。"
    )


def test_one_capability_has_exactly_one_implementation():
    """★★★ 判据 H：同名工具在不同 Agent 手里必须是**同一个实现**。

    ★ 为什么「目录里声明了共用」还不够：那只是**声明**。真正决定是不是共用的
      是底层函数对象 —— 两家各写一个 `list_candidates`，模型看到的是两个
      同名但实现不同的工具，而**测试只会覆盖其中一条**，另一条永远测不到
      （本仓铁律：同一判定两份实现 ⇒ 至少一份永远测不到）。

    ★ 实现指纹取 `(module, qualname)` 而不是 `id()`：秘书那一份走**工厂**
      （每次构建都是新对象，`id()` 天然不同），而底层协程函数是模块级的，
      限定名稳定且可复现。

    ★ 反向注入（已实测）：在 `modules/secretary/agent.py` 里另建一个同名工具
      （而不是用 `build_library_tools`）⇒ 本条必红。
    """
    objs = _runtime_tool_objects()
    assert objs, "运行时真值解析为空 —— 本条会假绿"

    problems = []
    for name, by_agent in sorted(objs.items()):
        if len(by_agent) < 2:
            continue
        prints = {}
        for agent, t in by_agent.items():
            fn = getattr(t, "coroutine", None) or getattr(t, "func", None)
            prints[agent] = (
                f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', '?')}"
            )
        if len(set(prints.values())) > 1:
            problems.append(
                f"{name}: " + "; ".join(f"{a} -> {p}" for a, p in sorted(prints.items()))
            )
    assert not problems, (
        "同一个工具名在不同 Agent 手里是**不同的实现** —— 同一能力两份实现，"
        "至少一份永远测不到：\n  "
        + "\n  ".join(problems)
        + "\n⇒ 把实现收拢到一家（或 `modules/library/` 这类 SHARED 层）后共用。"
    )


def test_library_tool_names_are_truthfully_declared():
    """★★★ 判据 L：`modules/library` 的 `LIBRARY_TOOL_NAMES` 必须**如实**声明本包产出。

    ★ 这条补的是一个**真实存在的空缺**（第 218 轮发现）：
      `LIBRARY_TOOL_NAMES` 的注释写着「**唯一真源**，供门禁与目录对账」，
      但实测**全仓没有任何门禁读过它**（只被 `__all__` re-export）。
      一句没有反例的断言等于没有断言 —— 第 218 轮给资料库加 4 个工具时，
      只改目录表而漏改它，谁都发现不了。

    ★ 判据形态：另一侧取**运行时真值**里「底层实现落在 `modules.library.tools`
      的工具集合」（按 `(module, qualname)` 认，不按名字认）。
      「同名不同实现」由判据 H 咬；这里咬的是**声明本身漏项 / 多写**。

    ★ 反向注入（必须能转红）：
      · 从 `LIBRARY_TOOL_NAMES` 里删掉 `list_assets` ⇒ 红；
      · 给工厂加第 7 个工具而不登记 ⇒ 红（真值多出）。
    """
    from modules.library import LIBRARY_TOOL_NAMES

    objs = _runtime_tool_objects()
    assert objs, "运行时真值解析为空 —— 本条会假绿（先查 ASSEMBLY_POINTS）"

    actual = set()
    for name, by_agent in objs.items():
        for tool in by_agent.values():
            fn = getattr(tool, "coroutine", None) or getattr(tool, "func", None)
            if getattr(fn, "__module__", "") == "modules.library.tools":
                actual.add(name)
                break

    assert actual, (
        "运行时真值里找不到任何底层实现落在 `modules.library.tools` 的工具 —— "
        "本条会假绿（先查 ASSEMBLY_POINTS 里 library 那一行还在不在）"
    )

    declared = set(LIBRARY_TOOL_NAMES)
    assert declared == actual, (
        f"`LIBRARY_TOOL_NAMES` 声明 {sorted(declared)}，运行时真值 {sorted(actual)}；"
        f"声明多出（写了但没产出）: {sorted(declared - actual)}；"
        f"声明遗漏（产出了但没写）: {sorted(actual - declared)}。"
        f"⇒ 这份「唯一真源」一旦与工厂脱钩，就会静默地不再约束任何东西。"
    )


# ============================================================================
# I. 落选同义名不得复活
# ============================================================================


def test_rejected_aliases_never_appear():
    """★★★ 判据 I：`REJECTED_TOOL_ALIASES` 里的落选名不得出现在任何工具集里。

    ★ 为什么要这条：收敛如果不登记落选者，它会在下一轮被**重新捡起来**
      —— 有人要补 `GET /api/v1/skus` 的工具，顺手取名 `list_skus`，
      「一个能力两个名字」就回来了，而没有任何东西会报错。

    ★ 覆盖面刻意分两层：`TOOL_CATALOG`（面向租户的清单）+ **运行时真值**
      （真的交到模型手里的工具集）。只查前者会漏掉「注册了但没登记进目录」
      的那一类。

    ★ 反向注入（已实测）：把 `list_skus` 加回 `TOOL_CATALOG` ⇒ 本条必红。
    """
    from modules.skills.tools_catalog import REJECTED_TOOL_ALIASES, all_tool_names

    assert REJECTED_TOOL_ALIASES, "禁名表为空 ⇒ 本条恒绿（等于没有门禁）"

    catalog = set(all_tool_names())
    real = real_tool_names()
    assert real, "运行时真值解析为空 ⇒ 本条会假绿"

    revived = sorted(n for n in REJECTED_TOOL_ALIASES if n in catalog or n in real)
    assert not revived, (
        f"这些**已裁决落选**的工具名又出现了：{revived}\n"
        + "\n".join(f"  · {n}: {REJECTED_TOOL_ALIASES[n]}" for n in revived)
        + "\n⇒ 同一能力两个名字 ⇒ 模型会在两处乱选，而测试只覆盖其中一条。"
    )


# ============================================================================
# J. 共用工具的调用点必须注入归属来源
# ============================================================================


def _library_build_call_sites() -> list:
    """AST 扫全仓，取 `build_library_tools(...)` 的 (文件, 行号, 关键字集合)。"""
    out = []
    for p in sorted((BACKEND / "modules").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        try:
            tree = ast.parse(p.read_bytes().decode("utf-8", "replace"))
        except SyntaxError:
            continue
        rel = p.relative_to(BACKEND).as_posix()
        for n in ast.walk(tree):
            if not isinstance(n, ast.Call):
                continue
            fn = n.func
            nm = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            if nm == "build_library_tools":
                out.append((rel, n.lineno, {kw.arg for kw in n.keywords}))
    return out


def test_every_build_call_site_injects_a_shop_source():
    """★★★ 判据 J：每个 `build_library_tools(...)` 调用点必须给归属来源。

    ★ 为什么这门禁必须在**调用点**上：工具本体刻意不对「没注入」抛错
      （抛错会让「没注入」与「用户确实还没选店铺」混成一个异常，而后者是
      秘书的正常开局）。⇒ 缺口只能在这里堵：调用点必须显式写
      `shop_id=`（构造期绑定）或 `resolve=`（运行期取值）之一。

    ★ 两种通道都必须有真实使用者：只留一种 ⇒ 另一种是**死代码**，
      而它的 docstring 会继续说「有两种用法」（本仓的「过时承诺」形态）。

    ★ 反向注入（已实测）：删掉秘书那行的 `shop_id=` ⇒ 本条必红。
    """
    sites = _library_build_call_sites()
    assert len(sites) >= 2, (
        f"只扫到 {len(sites)} 处 `build_library_tools(...)` 调用点（期望 ≥2）：{sites}\n"
        f"⇒ 扫描器空跑会让本条恒绿；或共用工具只剩一个宿主（那就不是「共用」了）。"
    )

    missing = [(rel, ln) for rel, ln, kws in sites if not ({"shop_id", "resolve"} & kws)]
    assert not missing, (
        "这些调用点没写 `shop_id=` 也没写 `resolve=`：\n  "
        + "\n  ".join(f"{rel}:{ln}" for rel, ln in missing)
        + "\n⇒ 工具会永远回「未选择店铺」，而调用方看不出自己漏了注入"
        "（第 204 轮 ad_analysis 踩过的形态）。"
    )

    used = set()
    for _rel, _ln, kws in sites:
        used |= {"shop_id", "resolve"} & kws
    assert used == {"shop_id", "resolve"}, (
        f"两种归属注入通道没有都被用到（实际用到 {sorted(used)}）：\n"
        f"⇒ 没被用到的那条是死代码，而两个宿主的形态确实不同 ——"
        f"秘书按请求重建 Agent（构造期绑定），选品分析师的路由子层被缓存"
        f"（必须运行期取值）。只留一条说明有一家的注入方式被改错了。"
    )


# ============================================================================
# K. 装配点只能引用已登记容器（G/H 的共同盲区）
# ============================================================================


def _tools_expr_nodes(rel: str) -> list:
    """该 Agent 文件里每个 `tools=` 实参的 (表达式 AST, 行号)。"""
    out = []
    for n in ast.walk(ast.parse((BACKEND / rel).read_bytes().decode("utf-8", "replace"))):
        if isinstance(n, ast.Call):
            for kw in n.keywords:
                if kw.arg == "tools":
                    out.append((kw.value, n.lineno))
    return out


def _local_assign_bindings(rel: str) -> dict:
    """本文件里 `名字 = 表达式` 的绑定 → `{名字: (右值 AST, 行号)}`（含函数内赋值）。"""
    out = {}
    for n in ast.walk(ast.parse((BACKEND / rel).read_bytes().decode("utf-8", "replace"))):
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                if isinstance(tgt, ast.Name):
                    out[tgt.id] = (n.value, n.lineno)
    return out


def test_assembly_sites_reference_only_registered_containers():
    """★★★ 判据 K：`tools=` 只能「把已登记的容器加起来」。

    ★ 这条补的是判据 G/H 的**共同盲区**（第 205 轮反向注入实测）：
      G/H 的运行时真值取自 `ASSEMBLY_POINTS` 登记的**容器/工厂**。若某个宿主
      在 `__init__` 里**就地另拼**一个同名工具
      （`library_tools = build_library_tools(...) + [<现场造的 list_candidates>]`），
      那份实现**根本不在真值里** ⇒ G/H 全绿，而「同一个工具名两个实现」
      ——本仓最警惕的形态——静默成立。

    ★ 判据形态（两条，都对 AST 说话）：
      ① `tools=` 实参里**只允许** `Name` 与 `+`：出现 `Call` / `List` / 下标等
         任何「就地构造」形态 ⇒ 红；
      ② 表达式里每个 `Name` 要么是**已登记容器名**，要么在本文件里被绑定为
         **对已登记工厂的一次裸调用**（`product_tools = build_product_tools(shop_id)`
         那种）—— 绑成「一次调用 + 别的东西」⇒ 红。

    ★ 反向注入（已实测）：把秘书的
      `library_tools = build_library_tools(shop_id=shop_id)`
      改成 `... + [现场造的 list_candidates]` ⇒ 本条必红（而 G/H 都不红）。

    ★ 为什么判据要写「裸调用」而不是只判「含已知容器名」：
      后者对 `known_tools + [某新工具]` 是**恒真**的（子串/包含匹配的经典假绿）。
    """
    known_refs = {ref for _, _, ref, _ in ASSEMBLY_POINTS}
    known_factories = {ref for _, _, ref, is_factory in ASSEMBLY_POINTS if is_factory}

    hosts = list(ASSEMBLY_HOSTS)
    assert len(hosts) >= 8, f"宿主清单只有 {len(hosts)} 个 —— 扫描面被改瘦了"

    #: 装配表达式里**允许**出现的节点类型：名字、加号、加法运算、加载上下文。
    #: 其余一律视为「就地构造」（`Call` / `List` / `Subscript` / `Mult` …）。
    allowed = (ast.Name, ast.Load, ast.Add)

    problems = []
    for rel in hosts:
        bindings = _local_assign_bindings(rel)
        for expr, lineno in _tools_expr_nodes(rel):
            for node in ast.walk(expr):
                if isinstance(node, (allowed, ast.BinOp)):
                    continue
                problems.append(
                    f"{rel}:{lineno} `tools=` 实参里出现 `{type(node).__name__}`"
                    f"（{ast.unparse(node)[:60]}）—— 装配点只能把已登记的容器加起来"
                )
            for node in ast.walk(expr):
                if not isinstance(node, ast.Name):
                    continue
                name = node.id
                if name in known_refs:
                    continue
                bound = bindings.get(name)
                if bound is None:
                    problems.append(
                        f"{rel}:{lineno} `tools=` 引用了未登记且本文件无绑定的名字 `{name}`"
                    )
                    continue
                rhs, bl = bound
                if not isinstance(rhs, ast.Call):
                    problems.append(
                        f"{rel}:{bl} 局部容器 `{name}` 不是「对工厂的一次裸调用」"
                        f"（实为 `{type(rhs).__name__}`）—— 就地另拼会让装配真值"
                        f"看不见这份工具"
                    )
                    continue
                fname = rhs.func.attr if isinstance(rhs.func, ast.Attribute) else getattr(
                    rhs.func, "id", ""
                )
                if fname not in known_factories:
                    problems.append(
                        f"{rel}:{bl} 局部容器 `{name}` 绑定到了未登记的工厂 `{fname}()`"
                    )

    assert not problems, (
        "这些 Agent 装配点没有「只引用已登记容器」：\n  "
        + "\n  ".join(sorted(set(problems)))
        + "\n⇒ 在装配点就地另拼工具的后果：`real_assembly_tools()` 看不见它，"
        "于是判据 G/H（共用/唯一实现）与判据 A（目录对账）**同时静默失效**。"
        "\n   要么把它做成已登记的容器/工厂，要么别在这里拼。"
    )


def test_assembly_site_scanner_is_not_vacuous():
    """★ 自检：装配点扫描器必须真的看到「名字 + 加号」两种形态。"""
    seen_names = seen_add = 0
    for rel in ASSEMBLY_HOSTS:
        for expr, _ln in _tools_expr_nodes(rel):
            if isinstance(expr, ast.Name):
                seen_names += 1
            if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
                seen_add += 1
    assert seen_names >= 5, f"只看到 {seen_names} 处单名字装配（期望 ≥5）"
    assert seen_add >= 1, f"没看到任何「名字相加」形态（{seen_add}）—— 扫描器可能没读对文件"


# ---------------------------------------------------------------------------
# 术语规格（第 298 轮 · 老板指令：处理 / 处置 二选一，我来定）
# ---------------------------------------------------------------------------


def test_review_disposition_terms_use_chuzhi():
    """业务面统一用**处置**：目录里这条 title 不许退回旧叫法。

    ★ 为什么值得一条判据：这条 `title` 是**界面上看得见**的
      （Skill 仓库 / 工具仓库的「名字」列，以及思考链里的工具标题
      `modules/skills/tools_catalog.py::tool_title()`）。
      第 298 轮把「处理」统一成「处置」，而它此前已经**改过两次名**
      （功能栏按钮、技能卡 title），每次都只改一半、靠人肉 grep 收尾。
      钉住它 ⇒ 下一次改名至少会红在 CI 上，而不是靠老板再发现一遍。
    """
    from modules.skills.tools_catalog import TOOL_CATALOG

    rows = [t for t in TOOL_CATALOG if t["name"] == "get_customer_review_context"]
    assert rows, "TOOL_CATALOG 里没有 get_customer_review_context —— 本判据会空跑"
    title = rows[0]["title"]
    assert "处置" in title, f"title={title!r} 里没有「处置」—— 业务面已统一为「处置」"
    assert "差评处理" not in title, (
        f"title={title!r} 还在用旧叫法「差评处理」。第 298 轮已定：业务面只留「处置」"
        "（泛动词「待处理 / 人工处理 / 升级处理」不在此列，不受本判据管）"
    )



# ---------------------------------------------------------------------------
# 判据 M：已登记库的工具层读法（第 326 轮）
# ---------------------------------------------------------------------------
#
# 起因：`modules/secretary/product_tools.py::_select_product` **绕开
#   `PRODUCT_SPEC` 自写了一份 `scoped(select(SkuRecord, ...))`**，而
#   `products/spec.py` 的 docstring 明写「REST 与 Agent 工具同走它」
#   —— **声明与实现相反**。它一直没被拦住：判据 H 只比「不同 Agent 手里的
#   **同名**工具」，**看不见**「工具 vs 内核」，也看不见「单个工具自己另写一份」。
#
# ★ 为什么只守**工具层**（不守 `router.py`）—— 这是**有意的边界，不是漏写**：
#   实测 `router.py` 里有 20 处对已登记 model 的裸 `select()`，但它们多是
#   详情 / 写入 / 审核类端点（`assets` / `candidates` / `monitors` / `products`
#   各自的第 2、3 个端点），**不是「同一列表能力的第二份实现」** ⇒ 一并判红是误报。
#   本判据守的是「**Agent 能力面**的口径唯一」；REST 列表端点那一半由
#   `products/spec.py` 的 docstring 自述为**已知**边界，另行评估。
#
# ★ 实测（第 326 轮落地时）：工具层**零命中** ⇒ **不需要豁免表**。
#   若将来有人要加豁免，请先回答「它是不是真的不该走内核」。
#
# ★ 反向注入（已实测）：把 `product_tools.py` 的 `query_library(PRODUCT_SPEC, ...)`
#   改回 `scoped(select(SkuRecord, ...))` ⇒ 本条必红。


def _tool_layer_files() -> list:
    """工具层 = **产出 `StructuredTool` 的文件**（而不是按文件名 `tools.py` 认）。

    ★ 为什么不用文件名：`modules/secretary/` 下的工具叫 `product_tools.py` /
      `shop_tools.py` / `navigation_tools.py` / `subscription_tools.py` ——
      按 `tools.py` 扫会**漏掉本次修的 `product_tools.py`**（扫描面错 = 门禁假绿）。
      用「产出 StructuredTool」定义，增删工具文件时自动跟着走。
    """
    import ast as _ast
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent / "modules"
    out = []
    for p in sorted(root.rglob("*.py")):
        if p.name == "__init__.py":
            continue
        src = p.read_text(encoding="utf-8")
        if "StructuredTool" not in src:
            continue
        tree = _ast.parse(src)
        if any(
            isinstance(n, _ast.Call)
            and isinstance(n.func, _ast.Attribute)
            and n.func.attr == "from_function"
            for n in _ast.walk(tree)
        ):
            out.append(p)
    return out


def _registered_library_models() -> dict:
    """全仓 `LibrarySpec(...)` 登记项 → `{model 属性名: (spec 变量名, 位置)}`。"""
    import ast as _ast
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent / "modules"
    out: dict = {}
    for p in sorted(root.rglob("*.py")):
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Assign):
                continue
            call = node.value
            if not (isinstance(call, _ast.Call) and isinstance(call.func, _ast.Name)):
                continue
            if call.func.id != "LibrarySpec":
                continue
            kw = {k.arg: k.value for k in call.keywords if k.arg}
            m = kw.get("model")
            name = (
                m.id if isinstance(m, _ast.Name)
                else m.attr if isinstance(m, _ast.Attribute)
                else None
            )
            tgt = node.targets[0]
            if name:
                out[name] = (
                    tgt.id if isinstance(tgt, _ast.Name) else "?",
                    f"{p.relative_to(root.parent).as_posix()}:{node.lineno}",
                )
    return out


def test_tool_layer_reads_registered_libraries_only_through_the_kernel():
    """★★★ 判据 M：已登记 `LibrarySpec` 的库，**工具层只能经内核读**。

    ★ 两种绕过形态都会被抓住（AST，不是字符串包含）：
        · `select(<Model>)` / `select_from(<Model>)` 直接组查询；
        · 包在 `scoped(...)` 或任何包装器里同样命中 —— 判据看的是**内层调用**。

    ★ 自检（防「扫描器空转」）：登记库数、工具层文件数都必须达标；
      否则「什么都没扫到」会假绿（本仓踩过：排除规则过宽 ⇒ 静默归零）。
    """
    import ast as _ast
    from pathlib import Path as _P

    models = _registered_library_models()
    assert len(models) >= 8, (
        f"只解析出 {len(models)} 个 LibrarySpec —— 扫描器空转了：{sorted(models)}"
    )

    files = _tool_layer_files()
    assert len(files) >= 13, (
        f"只识别出 {len(files)} 个工具层文件 —— 扫描面不对：{[p.name for p in files]}"
    )

    root = _P(__file__).resolve().parent.parent
    problems = []
    for p in files:
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Call):
                continue
            f = node.func
            fname = (
                f.id if isinstance(f, _ast.Name)
                else f.attr if isinstance(f, _ast.Attribute)
                else None
            )
            if fname not in ("select", "select_from"):
                continue
            for a in list(node.args) + [k.value for k in node.keywords]:
                n = a.id if isinstance(a, _ast.Name) else None
                if n in models:
                    spec_name, spec_loc = models[n]
                    problems.append(
                        f"{p.relative_to(root).as_posix()}:{node.lineno} "
                        f"`{fname}({n})` —— 绕过 {spec_name}（登记于 {spec_loc}）"
                    )

    assert not problems, (
        "工具层绕过 `core.library_query` 内核、直接查已登记库：\n  "
        + "\n  ".join(problems)
        + "\n⇒ 请改走 `query_library(<SPEC>, shop_id, ...)`。"
        "否则 REST 与工具就是**同一能力两份实现**，其中一份永远测不到。"
    )





# ============================================================================
# 判据 P：数据域 → 允许读它的函数集合
# ============================================================================
#
# ★ 为什么还要 P（M 已经守了「工具层不得绕过内核」）
#   M 的扫描面**只有工具层**（产出 `StructuredTool` 的文件）。但同一个数据域
#   的读取者有两条腿：
#       REST 侧（`router.py` / `service.py`）—— 列表端点、详情、写前读、seed
#       工具侧（`*tools.py`）        —— Agent 工具
#   两腿若各写各的查询，「同一能力两份实现 ⇒ 至少一份永远测不到」就复活，
#   而且**只在 REST 侧复活时 M 完全看不见**（M 不扫 router/service）。
#
# ★ P 的口径 = 老板原话「按数据域 → 允许读它的函数集合」：
#     对每个已登记 `LibrarySpec`，把**全仓**读它的函数列成集合，分两栏登记：
#       kernel：**直接**调 `core.library_query` 内核读该 spec 的函数
#       direct：不经内核、直接 `select/select_from(<Model>)` 的函数
#     断言「实际集合 == 登记集合」。任何**新增/改名/搬移**的读取者都会红，
#     逼迫作者显式回答两件事：
#       ① 它该不该走内核？ ② 它做了租户收窄没有？
#
# ★ 别名 import 必须解析（第 1 版漏了，实测漏检 6 个消费者中的 1 个直接消费者）
#   `modules/library/tools.py:93-97` 写的是
#       from core.library_query import (
#           count_library as _svc_count_library,
#           query_library  as _svc_query_library,
#       )
#   按函数名**字面**匹配会整体漏掉这个文件 —— 而 `_rows_to_products` 正是
#   「产品库」工具的直接取数点。⇒ 扫描器先解析 `import ... as ...` 别名。
#
# ★ direct 栏不是「坏味道清单」—— 详情/写前读/seed 本来就不该走列表内核。
#   它的价值是**地图**：本域到底有几个读取者、分别在哪，一目了然。
#   ★ 实测（第 326 轮落地时）direct 栏里三个**多行读取者**均已收窄租户：
#       candidates/service.py::_load_scoped          → scoped(...) 无条件挂（第 283 轮）
#       customer_service/faq_source.py::load_faq_items → scope_condition + 空店铺 raise
#       trade/service.py::list_reviews_for_spu       → scope_condition(SpuRecord) 两处收窄
#     其余 direct 项为 单条详情 / 存在性判定 / 写前读 / seed，均按主键或归属容器取。
#
# ★ 反向注入（已实测 3/3）：
#   I-P1 登记表 kernel 项改名        ⇒ `[PRODUCT_SPEC][kernel]` 归因
#   I-P2 登记表 direct 删一项        ⇒ `[ASSET_SPEC][direct]` 归因
#   I-P3 生产源+登记表**同步**改掉工具侧内核路径 ⇒ 只剩 `[lane D]` 红
#        （证明 D 段独立于登记表：同步改登记表也绕不过）

_LIBRARY_READERS: dict = {
    "ASSET_SPEC": {
        "kernel": {
            "modules/assets/service.py::count_assets",
            "modules/assets/service.py::list_assets",
        },
        "direct": {
            "modules/assets/router.py::batch_delete_assets",
            "modules/assets/router.py::delete_asset",
            "modules/assets/router.py::delete_group",
            "modules/assets/router.py::get_asset",
            "modules/assets/router.py::update_asset",
            "modules/assets/seed.py::seed_assets_if_empty",
        },
    },
    "CANDIDATE_SPEC": {
        "kernel": {
            "modules/candidates/service.py::count_candidates",
            "modules/candidates/service.py::list_candidates",
        },
        "direct": {
            "modules/candidates/router.py::batch_delete_candidates",
            "modules/candidates/router.py::delete_candidate",
            "modules/candidates/router.py::delete_group",
            "modules/candidates/router.py::monitor_candidate",
            "modules/candidates/router.py::update_candidate",
            "modules/candidates/seed.py::seed_candidates_if_empty",
            "modules/candidates/service.py::_load_scoped",
            "modules/candidates/service.py::find_candidate_by_asin",
        },
    },
    "FAQ_SPEC": {
        "kernel": {
            "modules/knowledge_base/service.py::count_faqs",
            "modules/knowledge_base/service.py::list_faqs",
        },
        "direct": {
            "modules/customer_service/faq_source.py::load_faq_items",
            "modules/customer_service/faq_source.py::seed_cs_faqs",
            "modules/knowledge_base/service.py::create_faq_drafts",
            "modules/knowledge_base/service.py::delete_faq",
            "modules/knowledge_base/service.py::get_faq_by_id",
            "modules/knowledge_base/service.py::get_kb_dict",
            "modules/knowledge_base/service.py::publish_draft_faqs",
            "modules/knowledge_base/service.py::update_faq",
        },
    },
    "MARKET_SNAPSHOT_SPEC": {
        "kernel": {
            "modules/product_research/service.py::get_market_insight_treemap",
            "modules/product_research/tools.py::_query_market_insight_tool",
        },
        "direct": {
            "modules/product_research/seed.py::seed_market_snapshots_if_empty",
        },
    },
    "MONITOR_SPEC": {
        "kernel": {
            "modules/monitors/service.py::count_monitors",
            "modules/monitors/service.py::list_monitors",
        },
        "direct": {
            "modules/amazon_sp/seed.py::seed_competitor_snapshots_if_empty",
            "modules/monitors/router.py::_monitor_exists_session",
            "modules/monitors/router.py::_mutate_groups",
            "modules/monitors/router.py::delete_monitor",
            "modules/monitors/router.py::delete_monitor_group",
            "modules/monitors/router.py::get_monitor",
            "modules/monitors/router.py::update_monitor",
            "modules/monitors/seed.py::seed_monitors_if_empty",
            "modules/monitors/service.py::monitor_exists",
            "modules/monitors/service.py::upsert_monitor",
        },
    },
    "PRODUCT_SPEC": {
        "kernel": {
            "modules/library/tools.py::_rows_to_products",
            "modules/products/router.py::list_skus",
            "modules/secretary/product_tools.py::_select_product",
        },
        "direct": {
            "modules/products/router.py::delete_sku",
            "modules/products/router.py::delete_spu",
            "modules/products/router.py::get_sku",
            "modules/products/router.py::update_sku",
            "modules/products/router.py::update_sku_listing",
            "modules/trade/seed.py::pick_anchor_sku",
            "modules/trade/service.py::_not_bound_to_sku",
            "modules/trade/service.py::list_reviews_for_spu",
        },
    },
    "REVIEW_SPEC": {
        "kernel": {
            "modules/review_analyst/service.py::count_saved_reports",
            "modules/review_analyst/service.py::list_saved_reports",
        },
        "direct": {
            "modules/review_analyst/service.py::get_saved_report",
            "modules/review_analyst/service.py::save_report",
        },
    },
    "RULE_SPEC": {
        "kernel": {
            "modules/platform_rules/service.py::count_rules",
            "modules/platform_rules/service.py::list_rules",
        },
        "direct": {
            "modules/platform_rules/seed.py::seed_platform_rules_if_empty",
            "modules/platform_rules/service.py::delete_rule",
            "modules/platform_rules/service.py::get_rule_by_id",
            "modules/platform_rules/service.py::update_rule",
        },
    },
}

def _kernel_aliases(tree):
    """`from core.library_query import query_library as X` ⇒ `{X: "query_library"}`。

    ★ 不解析别名会**整体漏掉** `modules/library/tools.py`（6 个 `list_*` 工具的
      直接取数点 `_rows_to_products` 就在那里）。实测：漏检后 kernel 16 项，
      解析后 17 项。
    """
    import ast as _ast

    alias: dict = {}
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.ImportFrom):
            continue
        if not (node.module and node.module.endswith("library_query")):
            continue
        for a in node.names:
            alias[a.asname or a.name] = a.name
    return alias


def _library_reader_map(root):
    """扫全仓 → `(spec名→model名, {spec名: {"kernel": set, "direct": set}})`。

    ★ 与 `r325_m7_gen_registry.py::library_reader_map` **同一份逻辑** ——
      登记表就是由它生成的，两处漂移则门禁失去意义。
    """
    import ast as _ast

    specs: dict = {}
    models: dict = {}
    for p in sorted((root / "modules").rglob("*.py")):
        tree = _ast.parse(p.read_text(encoding="utf-8"))
        for node in _ast.walk(tree):
            if not isinstance(node, _ast.Assign):
                continue
            call = node.value
            if not (isinstance(call, _ast.Call) and isinstance(call.func, _ast.Name)):
                continue
            if call.func.id != "LibrarySpec":
                continue
            tgt = node.targets[0]
            if not isinstance(tgt, _ast.Name):
                continue
            m = "?"
            for kw in call.keywords:
                if kw.arg == "model":
                    v = kw.value
                    m = (
                        v.id if isinstance(v, _ast.Name)
                        else v.attr if isinstance(v, _ast.Attribute)
                        else "?"
                    )
            specs[tgt.id] = m
            if m != "?":
                models[m] = tgt.id

    readers: dict = {s: {"kernel": set(), "direct": set()} for s in specs}
    for sub_dir in ("modules", "core", "scripts", "ai_infra"):
        base = root / sub_dir
        if not base.exists():
            continue
        for p in sorted(base.rglob("*.py")):
            rel = p.relative_to(root).as_posix()
            try:
                tree = _ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            alias = _kernel_aliases(tree)

            class _W(_ast.NodeVisitor):
                def __init__(self) -> None:
                    self.path: list = []

                def visit_ClassDef(self, node):  # noqa: ANN001
                    self.path.append(node.name)
                    self.generic_visit(node)
                    self.path.pop()

                def visit_FunctionDef(self, node):  # noqa: ANN001
                    self.path.append(node.name)
                    pid = f"{rel}::" + ".".join(self.path)
                    for sub in _ast.walk(node):
                        if not isinstance(sub, _ast.Call):
                            continue
                        f = sub.func
                        fname = (
                            f.id if isinstance(f, _ast.Name)
                            else f.attr if isinstance(f, _ast.Attribute)
                            else None
                        )
                        args = list(sub.args) + [k.value for k in sub.keywords]
                        if alias.get(fname, fname) in ("query_library", "count_library"):
                            for a in args:
                                if isinstance(a, _ast.Name) and a.id in specs:
                                    readers[a.id]["kernel"].add(pid)
                        if fname in ("select", "select_from"):
                            for a in args:
                                if isinstance(a, _ast.Name) and a.id in models:
                                    readers[models[a.id]]["direct"].add(pid)
                        if fname in ("select", "query", "delete", "update"):
                            for a in args:
                                if (
                                    isinstance(a, _ast.Attribute)
                                    and isinstance(a.value, _ast.Name)
                                    and a.value.id in models
                                ):
                                    readers[models[a.value.id]]["direct"].add(pid)
                    self.generic_visit(node)
                    self.path.pop()

                visit_AsyncFunctionDef = visit_FunctionDef

            _W().visit(tree)

    for _s, _d in readers.items():
        _d["direct"] -= _d["kernel"]
    return specs, readers


def test_library_data_domains_have_registered_reader_sets():
    """★★★ 判据 P：每个数据域的读取者集合 == 登记表（不多不少）。

    四段断言：
      A. **域完备**  —— 源码里的 `LibrarySpec` 登记项与登记表**同名同数**；
      B. **kernel 栏相等** —— 直接调内核的消费者集合必须逐字相符；
      C. **direct 栏相等** —— 不经内核直查 ORM 的函数集合必须逐字相符；
      D. **REST↔工具覆盖非空转** —— 至少一个域（本仓是 `PRODUCT_SPEC`）
         的 kernel 栏同时含 REST 侧与工具侧消费者。没有 D，P 会退化成
         一张纯登记簿：只要两边都为空，B/C 照样绿。
    """
    from pathlib import Path as _P

    root = _P(__file__).resolve().parent.parent
    specs, readers = _library_reader_map(root)

    # ---- A. 域完备 ----
    assert len(specs) >= 8, (
        f"只解析出 {len(specs)} 个 LibrarySpec —— 扫描器空转了：{sorted(specs)}"
    )
    missing_domains = sorted(set(specs) - set(_LIBRARY_READERS))
    extra_domains = sorted(set(_LIBRARY_READERS) - set(specs))
    assert not missing_domains and not extra_domains, (
        "数据域登记表与源码登记项不一致（新增 spec 必须登记它的读取者集合）：\n"
        f"  未登记的新域：{missing_domains}\n"
        f"  已失效的死登记：{extra_domains}"
    )

    # ---- B/C. 逐域逐栏对账 ----
    problems = []
    for spec_name in sorted(specs):
        declared = _LIBRARY_READERS[spec_name]
        actual = readers[spec_name]
        for lane in ("kernel", "direct"):
            want, got = set(declared[lane]), set(actual[lane])
            for h in sorted(got - want):
                problems.append(
                    f"[{spec_name}][{lane}] 未登记的新读取者：{h}"
                    + ("  ⇒ 若属列表/计数语义，请改走 `query_library`；"
                       "否则显式登记并说明租户收窄方式。"
                       if lane == "direct" else
                       "  ⇒ 登记表未同步。")
                )
            for h in sorted(want - got):
                problems.append(
                    f"[{spec_name}][{lane}] 登记了但源码里已不存在（改名/搬移？）：{h}"
                )

    assert not problems, (
        "数据域读取者集合与登记表不符：\n  " + "\n  ".join(problems)
    )

    # ---- D. REST↔工具覆盖非空转 ----
    # ★ 用 `readers`（**源码实测**）而不是 `_LIBRARY_READERS`（登记表）：
    #   若用登记表，D 就只是复述 B/C 的前提，被同步改登记表即可绕过；
    #   用实测结果，则「工具侧改回裸 select」时**即便登记表被同步更新，D 仍会红**。
    dual = {
        s for s, d in readers.items()
        if any("router.py" in h or "service.py" in h for h in d["kernel"])
        and any("tools.py" in h for h in d["kernel"])
    }
    assert dual, (
        "[lane D] 没有任何数据域的 kernel 栏**同时**覆盖 REST 侧与工具侧 —— "
        "判据 P 退化成了纯登记簿（B/C 在两边都为空时也绿）。"
        "本仓应至少 `PRODUCT_SPEC` 满足：REST `router.py::list_skus` + "
        "工具 `secretary/product_tools.py::_select_product`。"
    )
    assert "PRODUCT_SPEC" in dual, (
        f"[lane D] REST↔工具双通道的锚点域丢了（实际满足的域：{sorted(dual)}）—— "
        "要么 select_product 不再走内核，要么 REST 列表端点挪走了，两者都要人判。"
    )
