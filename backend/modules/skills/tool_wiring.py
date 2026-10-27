# -*- coding: utf-8 -*-
"""装配点真值 —— 「源码里 `BaseAgent(tools=...)` 实参到底交了哪些工具」（第 400 轮 · P1-2）

==============================================================================
★ 为什么这份名单从测试搬到了生产代码
==============================================================================
在此之前，它只活在 `tests/test_tool_catalog.py::ASSEMBLY_POINTS` 里：
门禁拿它算出「真值」，再去核对 `tools_catalog.TOOL_CATALOG` 这张**手写表**。
那张表里 `agent` / `effect` 两个字段是**冗余**的 —— 门禁已经用运行时真值
把它们钉死，也就是说这两个字段**只可能写错，不可能写对出额外信息**。

第 400 轮 P1-2 把方向反过来：**表里只留写给「人」看的文案**，
`agent` / `agents` / `effect` 一律从这里**派生**。于是：

  · 新增一个工具 ⇒ 只需要写一句文案（不再需要人肉判断归属、判断要不要审批；
    而「判错了」这类错误现在是**结构上不可能**的，不是靠门禁事后抓）；
  · `effect` 直接取自工具自己的 `metadata`（`has_side_effects`，fail-closed）
    ⇒ 界面上那个「需审批」标记**不可能**在骗人；
  · 装配点名单成了唯一真源，测试与生产**共用一份**（此前是两份逐字抄写的
    常量，改一处忘另一处就是一条静默失配）。

★★ 代价与纪律：本模块的 `assembly_tools()` 会**真的 import 并调用**工具工厂。
   因此它**不能**在 import 期执行（见 `assembly_tools()` 的 `lru_cache` 说明），
   且工具工厂必须保持「构造期无副作用」—— 这一点本来就是既有要求
   （`secretary/agent.py` 在 Agent 初始化时就调它们）。

★★★ 分层纪律（`tests/test_module_layering.py` 的**盲区**，必须靠这条注释守）：
   `modules/skills` 是 PLUGIN，而本模块 import 的是**其它 PLUGIN**
   （8 家业务 Agent 的工具容器）。它之所以没踩「PLUGIN → PLUGIN 顶层 import」
   红线，纯粹是因为这里用的是 `importlib.import_module(<字符串>)` ——
   **静态 AST 门禁看不见动态 import**。也就是说这条红线在本模块上是
   「注释在守，不是门禁在守」。

   真正要保的不变量只有一条：**那 8 家里不许有任何一家在顶层 import
   `modules.skills`**（否则 `modules.skills` → 本模块 → 该家 → `modules.skills`
   就是一条环，而且报出来的是难读的半初始模块错误）。
   这条不变量**已经**被 `test_module_layering.py::test_no_plugin_imports_another_plugin_at_import_time`
   覆盖（`skills` 与那 8 家都是 PLUGIN）—— 所以别在这里再发明一份。
   全仓现状（第 400 轮实测）：只有 6 处 `from modules.skills import tool_title`，
   **全部在函数体内**（延迟 import），没有顶层边。

==============================================================================
★ 真值的**射程**（别高估它 —— 第 204 轮反向注入实测）
==============================================================================
本表是**容器级**的：只回答「这些**容器**里有哪些工具名」，
**不回答**「该容器有没有被某个 Agent 真的绑上」。
实测：把 `agent_ad._build_router` 的 `tools=ad_analysis_tools` 换成
`aigc_tools`（该容器就此悬空）后，本表派生的目录**不变** —— 红的是
`tests/test_agent_tool_wiring.py::test_every_tool_registry_is_wired_to_an_agent`。

⇒ 两者是**分工**不是重复：
   · 本模块     —— 「目录里的名字 == 这些容器产出的事实」；
   · 接线门禁   —— 「这些容器真的被某个 Agent 拿在手上」。
缺任何一处都会造出「可勾选但调不起来」的工具，且**不报错**。
"""
from __future__ import annotations

import importlib
import inspect
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

#: `(agent_name, 模块路径, 成员名, 是否工厂)` —— **唯一真源**。
#:
#: 第一列必须是 `AGENT_CATALOG` 的**精确** `agent_name`（含中文那两个），
#: 不能写模块名：`grouped_catalog()` 拿它跟 `AGENT_CATALOG` 对账。
#:
#: ★ 顺序有意义：同一个工具被多家持有时，`TOOL_CATALOG` 条目的 `agent`
#:   字段取**本表里先出现的那一家**（`agents` 字段才是全集）。
#:   现有 6 个共用工具的先出现者都是 `ProductResearcher` —— 与第 205 轮
#:   收敛时的归属一致（见 `tools_catalog.py` 的说明）。
ASSEMBLY_POINTS: Tuple[Tuple[str, str, str, bool], ...] = (
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
    # ★ 第 205 轮：**跨 Agent 共用**的资料库只读工具（`modules/library/`，SHARED 层）。
    #   这里登记的是**店秘书**那一份；选品分析师那一份随
    #   `product_research_tools` 的尾部相加一并进来 ⇒ 同一个工具名会同时
    #   出现在两家的真值里，这正是「共用」的定义。
    ("secretary", "modules.library.tools", "build_library_tools", True),
    # ★ 第 204 轮接线：这三个此前是**悬空注册表**（注册了但没有任何 Agent
    #   绑定，合计 19 个工具）。本轮各自补了 `_build_router()`（范式 A）。
    ("ad_analysis", "modules.ad_analysis.tools", "ad_analysis_tools", False),
    ("AIGC 媒体生成器", "modules.aigc_media.tools", "aigc_tools", False),
    ("智能客服", "modules.customer_service.tools", "customer_service_tools", False),
)

#: 机制型工具 —— 由 `ai_infra.skills.build_skill_tools()` 恒装在每个 Agent 上，
#: **不是业务能力**，不属于「租户可绑定的工具」。
#: 不排除 ⇒ 「目录缺 load_skill」会变成一条永远红的判据。
MECHANISM_TOOLS: frozenset = frozenset({"load_skill"})


class WiringError(RuntimeError):
    """装配点解析失败（模块不在 / 成员不在 / 不是列表）。

    ★ 独立异常类型而不是 `AssertionError`：生产侧要打日志并**如实**降级，
      测试侧要能把它与"目录为空"区分开。
    """


def _call_factory(fn) -> List[Any]:
    """调用工具工厂。必填位置参数一律传 `None`。

    ★ 为什么不在 `inspect` 上硬编码参数表：`build_product_tools(shop_id)`
      这类签名未来加参数时，本函数仍然能跑（多给的照传 `None`）。
    ★ 为什么传 `None` 而不是一个假店铺 ID：`None` 在三个工厂里都是
      **有明确语义**的「用户还没选店铺」（见 `library/tools.py` 的
      `_shop()`），而假 ID 会让未来的某次 DB 查询去查一个不存在的店铺，
      白白在日志里留一条误导性的噪声。
      我们只要**工具名**，构造期绑定什么值都不影响名字。
    """
    sig = inspect.signature(fn)
    required = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.default is p.empty
    ]
    return fn(*([None] * len(required)))


@lru_cache(maxsize=1)
def assembly_tools() -> Dict[str, List[Any]]:
    """运行时取每个装配点的**真实工具对象**：`{agent_name: [tool, …]}`。

    ★ 用 `lru_cache` 而不是模块级常量：本函数会 import 全部业务模块、**真的
      调用工厂**，成本不低；但若在 import 期执行，任何一处业务模块的 import
      错误都会变成**调用方整体起不来**（而且看不出是哪一条装配点）。
      按需执行 ⇒ 失败被定位到具体那一行。
    """
    out: Dict[str, List[Any]] = {}
    for agent, modname, ref, is_factory in ASSEMBLY_POINTS:
        try:
            mod = importlib.import_module(modname)
        except Exception as e:  # noqa: BLE001
            raise WiringError(f"装配点 {modname} import 失败：{type(e).__name__}: {e}") from e
        if not hasattr(mod, ref):
            raise WiringError(f"装配点 {modname}.{ref} 不存在（改名了？请同步 ASSEMBLY_POINTS）")
        obj = getattr(mod, ref)
        tools = _call_factory(obj) if is_factory else obj
        if not isinstance(tools, (list, tuple)):
            raise WiringError(
                f"装配点 {modname}.{ref} 不是列表（{type(tools).__name__}）—— "
                f"它是工具工厂的返回值吗？请同步 ASSEMBLY_POINTS 的 `is_factory`。"
            )
        out.setdefault(agent, [])
        out[agent].extend(list(tools))
    return out


def derive_wiring() -> Tuple[Dict[str, Tuple[str, ...]], Dict[str, str], List[str]]:
    """派生 `(归属全集, 副作用档, 冲突说明)`。

    * 归属：`{工具名: (agent, …)}`，**同一条装配点顺序**（决定 `agent` 主字段）；
    * 副作用：`{工具名: "read_only" | "approval"}`，取自工具自己的 `metadata`；
    * 冲突：同一个工具名在不同容器里声明了**不同**副作用档 —— 这不该出现
      （同一份实现只有一份 metadata），真出现了要**报出来**而不是"后写覆盖"：
      静默取一方会让「界面说只读、运行期过审批」这种矛盾难以归因。

    ★ 副作用判定用 `has_side_effects()`（**fail-closed**：未声明 = 有副作用）。
      自己写 `metadata.get("side_effects")` 会把"未声明"读成只读 ——
      方向正好反了，且看起来完全正常。
    """
    from ai_infra.tools.side_effects import has_side_effects

    owner: Dict[str, List[str]] = {}
    effect: Dict[str, str] = {}
    conflicts: List[str] = []

    for agent, tools in assembly_tools().items():
        for t in tools:
            name = str(getattr(t, "name", "") or "")
            if not name or name in MECHANISM_TOOLS:
                continue
            bucket = owner.setdefault(name, [])
            if agent not in bucket:
                bucket.append(agent)
            got = "approval" if has_side_effects(t) else "read_only"
            prev = effect.get(name)
            if prev is None:
                effect[name] = got
            elif prev != got:
                conflicts.append(
                    f"{name}: {prev}（先见的容器） vs {got}（{agent}）"
                )
    return {k: tuple(v) for k, v in owner.items()}, effect, conflicts


def agent_of(name: str) -> Optional[str]:
    """某个工具的**主归属** Agent（并列时取 `ASSEMBLY_POINTS` 里先出现的）。"""
    owners = derive_wiring()[0].get(str(name or ""))
    return owners[0] if owners else None


__all__ = [
    "ASSEMBLY_POINTS",
    "MECHANISM_TOOLS",
    "WiringError",
    "agent_of",
    "assembly_tools",
    "derive_wiring",
]
