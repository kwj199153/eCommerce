# -*- coding: utf-8 -*-
"""路由盘点**真源本身**的门禁（第 247 轮）。

==============================================================================
★ 为什么需要「门禁的门禁」
==============================================================================
`scripts/route_inventory.py` 是全部路由盘点门禁的**唯一真源**（8 个用例 +
鉴权覆盖体检脚本）。它一旦失明，**所有消费方同时失明，而且大多以「空集合」的
形态表现为绿** —— 第 247 轮的 12 条红就是这么来的：

    FastAPI 0.141 起 `include_router()` 不再摊平子路由，改为往 `app.routes`
    追加惰性容器 `_IncludedRouter` ⇒ 「`for r in app.routes: r.path`」读到
    **7 条框架内置路由**，198 条业务端点一条都数不到。

所以真源自己必须被钉住：**判据不能只写「> 0」**（那 7 条框架路由足以喂饱它）。
本文件同时钉「数量级」与「具体业务路径在场」。

==============================================================================
★ 本文件钉四件事（缺一不可）
==============================================================================
  1. **规模 + 已知业务路径在场** —— 防「盘回框架路由就算过」。
  2. **空盘点必须抛错** —— 「禁把失明吞成绿」的落地点。
  3. **认不出的容器必须抛错** —— 上游再换容器形态时必须**响**，
     而不是静默把新容器当「非路由」跳过（0.141 的教训就是静默跳过）。
  4. **await 判据的唯一实现不能被退回** —— `fastapi_awaitable` 必须能区分
     `functools.partial(async_fn)`（False）与真 `async def`（True），
     且判据函数必须来自 `fastapi.dependencies.utils` 本身。
     ★ 若有人把实现换成 `asyncio.iscoroutinefunction`，这两者会**都判 True**
     ⇒ `test_route_dependency_form.py` 的形态 A/C 断言**恒假**（死门禁）。

==============================================================================
★ 反向注入（每条都必须让本文件转红）
==============================================================================
  RI-1 从 `_CHILD_ATTRIBUTES` 摘掉 `effective_candidates`
       ⇒ `test_inventory_scales_and_contains_known_business_paths` 转红。
  RI-2 删掉 `inventory()` 里「盘点数为 0 就抛」那段 ⇒ 第 2 条转红。
  RI-3 把 `scan()` 的 `unknown.append` 改成静默 `return` ⇒ 第 3 条转红。
  RI-4 把 `fastapi_awaitable` 换成 `asyncio.iscoroutinefunction` ⇒ 第 4 条转红。
"""

import asyncio
import functools

import pytest

#: 防空跑下限。★ 刻意写得很松（第 247 轮实测：端点 245 / 容器 25 / 业务路径 198）——
#: 它抓的是「盘回框架内置路由那 7 条」这种**数量级塌陷**，不是「有人删了几个端点」。
#: 照实测值写，正当重构就会变红 = 负资产。
MIN_ENDPOINTS = 100
MIN_BIZ_PATHS = 100

#: 必须盘得到的**具体业务路径**（跨模块选 4 条：店秘书 / 监控 / 计费 / 流式）。
#: ★ 为什么不能只断言数量：0.141 下仍有 7 条框架路由，一条「非空即通过」的判据
#:   会被它们喂饱 ⇒ 假绿。
KNOWN_PATHS = (
    "/api/v1/orchestrator/plan",
    "/api/v1/monitors",
    "/api/v1/billing/usage",
    "/api/v1/listing/chat/stream",
)


class _FakeApp:
    """只带 `routes` 的最小 app 替身 —— 用来喂坏形态。"""

    def __init__(self, routes):
        self.routes = routes


async def _async_probe():
    """给下面的鸭子样本当「协程 `__code__`」的来源。"""
    return 1


class _FunctionLikeDuck:
    """带**协程 `__code__`**、却不是真函数、且 `__call__` 是同步的鸭子对象。

    ★ 它存在的唯一理由：0.141 下**唯一**还能触发「asyncio 说是协程、而 FastAPI
      不 await」的形态。`inspect.iscoroutinefunction` 走
      `_signature_is_functionlike` 认它，而 FastAPI 的判据只问
      `isroutine()` / `__call__` ⇒ 两者分歧。
      ⇒ 它同时是「`test_route_dependency_form.py` 的断言还没死」的证据。
    """

    __code__ = _async_probe.__code__
    __name__ = _async_probe.__name__
    __defaults__ = _async_probe.__defaults__
    __kwdefaults__ = _async_probe.__kwdefaults__

    def __call__(self):  # noqa: D105 — 刻意同步
        return 1


# ============================================================================
# 1. 规模 + 已知业务路径在场
# ============================================================================


def test_inventory_scales_and_contains_known_business_paths():
    """★★★ 盘点必须同时满足「数量级」与「具体路径在场」。

    两条一起才成立：
      · 只判数量 ⇒ 0.141 的「盘回 7 条框架路由」也能过（7 < 100，其实挡得住，
        但下限一旦被调松就失守）；
      · 只判路径 ⇒ 换条路径就把判据绕过去了。
    """
    from main import app

    from scripts.route_inventory import inventory

    inv = inventory(app)

    assert len(inv.endpoints) >= MIN_ENDPOINTS, (
        f"只盘到 {len(inv.endpoints)} 条端点（下限 {MIN_ENDPOINTS}）—— "
        f"数量级塌陷，说明真源没穿透惰性容器（{inv.describe()}）。"
    )
    assert len(inv.endpoints) > inv.containers, (
        f"端点 {len(inv.endpoints)} 不多于容器 {inv.containers} —— "
        "几乎可以肯定「只登记了容器、没走进去」。"
    )

    biz = sorted(p for p in inv.paths if p.startswith("/api/v1"))
    assert len(biz) >= MIN_BIZ_PATHS, (
        f"/api/v1 业务路径只盘到 {len(biz)} 条（下限 {MIN_BIZ_PATHS}）—— "
        "这正是第 247 轮的失明形态（旧写法实测 0 条）。"
    )

    missing = [p for p in KNOWN_PATHS if p not in inv.paths]
    assert not missing, (
        f"这些已知业务路径没被盘到：{missing} —— 盘点结果不可信"
        "（不要当成「路由被删了」，先怀疑真源）。"
    )


# ============================================================================
# 2. 空盘点必须抛错（禁把失明吞成绿）
# ============================================================================


def test_inventory_raises_when_nothing_is_found():
    """★★★ 盘点为 0 必须**抛错**，不许返回空集合。

    ★ 这条是本模块存在的**全部理由**：旧的消费方写法（空集合 + 恒假断言 /
      `pytest.skip` 兜底）会把「判据失明」表现成绿。真源把这条路堵死。
    """
    from scripts.route_inventory import RouteInventoryError, inventory

    with pytest.raises(RouteInventoryError):
        inventory(_FakeApp([]))


# ============================================================================
# 3. 认不出的容器必须抛错（上游换形态时要响）
# ============================================================================


def test_inventory_raises_on_unrecognized_container():
    """★★★ 遇到本模块不认识的容器必须抛错。

    ★ 为什么这条是「下一次框架升级」的保险：0.141 把子路由从「摊平」改成
      「惰性容器」时，旧写法是**静默跳过**（`getattr(r,"path","")` 取不到 ⇒
      当成非路由）⇒ 失明无声无息。真源要求：认不出就**响**。
    """

    class _MysteryContainer:
        """有子节点，但没有本模块认识的任何访问器。"""

        def __init__(self, kids):
            self._kids = kids

    class _EndpointLike:
        """最小「真端点」替身 —— 真源判端点的判据就是 `path` + `dependant`。"""

        path = "/api/v1/_fake_probe"
        methods = {"GET"}
        dependant = None

    from scripts.route_inventory import RouteInventoryError, inventory

    # ★★★ 必须在「**已经盘到真端点**」的 app 上验 —— 不能只喂一个孤零零的未知容器。
    #   第 247 轮反向注入 RI-3 实测（这正是反向注入的价值所在）：
    #     只喂未知容器时，把 `unknown.append` 换成静默 `return` ⇒ 盘点退化成
    #     「0 端点」⇒ 被**第 2 条守卫**（空盘点抛错）顶住 ⇒ 本用例**照旧绿**。
    #     也就是说：它此前是「因为别的原因」被满足的**假绿**，
    #     压根没验证「认不出就响」这件事。
    #   ⇒ 加一条真端点后：静默 return ⇒ unknown 空 / endpoints=1 ⇒ 不抛 ⇒ 变红。
    #   `match="无法识别"` 再钉一层：不允许被「盘点为 0」那条守卫的文案顶替。
    app = _FakeApp([_EndpointLike(), _MysteryContainer([object()])])

    with pytest.raises(RouteInventoryError, match="无法识别"):
        inventory(app)


# ============================================================================
# 4. await 判据的唯一实现不能被退回
# ============================================================================


#: 上游对 `functools.partial` 的 unwrap 分界（实测）：
#:   <0.141 `fastapi.dependencies.utils.is_coroutine_callable` —— 不 unwrap ⇒ partial 判 False
#:   ≥0.141 `fastapi.dependencies.models._is_coroutine_callable` 前置 `_impartial()`
#:          循环 unwrap ⇒ partial 判 True
_AWAIT_PARTIAL_UNWRAP_SINCE: tuple[int, int] = (0, 141)


def _installed_fastapi_version() -> tuple[int, int]:
    """本机 FastAPI 的 `(major, minor)` —— 读不出来就**当场失败**，不许静默跳过。

    ★ 为什么不做成「猜一个默认值」：这条判据的全部意义就是「本机版本 ↔ 上游行为」
      的对应关系。读不到版本号还继续跑，等于用一个**无声的假设**顶替事实。
    """
    import re

    import fastapi

    ver = str(getattr(fastapi, "__version__", ""))
    m = re.match(r"(\d+)\.(\d+)", ver)
    assert m is not None, (
        f"读不出 `fastapi.__version__`（拿到 {ver!r}）—— 本用例靠它决定"
        "「`partial` 该被判 True 还是 False」，读不出就不能假装通过。"
    )
    return int(m.group(1)), int(m.group(2))


def test_await_predicate_asks_the_library_and_its_premise_holds():
    """★★★ `fastapi_awaitable` 必须问**库本身**，且它的两条前提必须成立。

    ★ 为什么这条是门禁的门禁：形态 A/C 的判据是
        `asyncio.iscoroutinefunction(call) and not fastapi_awaitable(call)`
      —— 若 `fastapi_awaitable` 被换成 `asyncio.iscoroutinefunction`，两边**恒等**
      ⇒ 后半永远 False ⇒ `test_route_dependency_form.py` 成为**结构性死门禁**
      （永远绿，而它看起来完全像在守第 153 轮那次事故）。

    ★★ 第 247 轮实测更正（**别再把那两条当与版本无关的「活的 bug 捕手」看**）：
      FastAPI 0.141 把判据搬到了 `fastapi.dependencies.models._is_coroutine_callable`，
      并引入 `_impartial()`（循环 unwrap `functools.partial`）与 `inspect.unwrap()`
      （跟随 `__wrapped__`）⇒ **形态 A / C 在 0.141 起不可达**（实测表）：

          样本                                    asyncio  FastAPI(<0.141)  FastAPI(≥0.141)
          真 async def                              True       True             True
          functools.partial(async_fn)   【形态 A】     True       **False**        True
          保留 __wrapped__ 的同步包装     【形态 C】     False      False            True
          协程 __code__ + 同步 __call__ 的鸭子对象      True       False            False

      ⇒ ★★★ **第 300 轮更正：A / C 的可达性取决于「本机装的是哪个 FastAPI」**。
        本仓 `requirements.txt` 是 `fastapi>=0.104.0,<0.142`，**实装 0.115.12**
        （starlette 0.46.2）⇒ 那两条老坏形态在**本机是活的**，
        `test_route_dependency_form.py` 此刻是**真捕手**，不是报警器。

        此前这里写死 `partial is True`（= 0.141 的行为）⇒ **恒红**。
        错不在判据、也不在门禁本意，而在**把「上游某个版本的行为」当成了
        「本机不变式」**。⇒ 改成版本自适应：

          ① 期望值由 `_installed_fastapi_version()` × `_AWAIT_PARTIAL_UNWRAP_SINCE`
             推出（<0.141 ⇒ 应判 False；≥0.141 ⇒ 应判 True）；
          ② 观测值仍来自 `scripts.route_inventory.fastapi_awaitable`（唯一真源，
             **问库本身**）；
          ③ **两个方向都是红** —— 任何一边不符都说明上游反转或本文件的口径过时，
             报文里直接给出「形态 A 现在可达/不可达」以及该回去重验哪个文件。
          ④ 必须**仍存在**一个「asyncio 说真、FastAPI 说假」的可达样本（鸭子对象），
             否则那条断言就是结构性死门禁 —— 本仓最忌讳的形态。这一条与版本无关。
    """
    from scripts.route_inventory import fastapi_await_predicate, fastapi_awaitable

    assert fastapi_awaitable(_async_probe) is True, (
        "真 `async def` 被判为不可 await —— 判据函数取错了对象。"
    )

    ver = _installed_fastapi_version()
    expects_partial = ver >= _AWAIT_PARTIAL_UNWRAP_SINCE
    observed_partial = fastapi_awaitable(functools.partial(_async_probe))
    assert observed_partial is expects_partial, (
        f"★ **前提变红**：本机 FastAPI {ver[0]}.{ver[1]} 上，"
        f"`functools.partial(async_fn)` 被判为 {observed_partial!r}，"
        f"而该版本应为 {expects_partial!r}"
        f"（分界 {_AWAIT_PARTIAL_UNWRAP_SINCE[0]}.{_AWAIT_PARTIAL_UNWRAP_SINCE[1]}）。\n"
        "  含义：上游把 `partial` 的 unwrap 行为**反转**了 —— \n"
        "    · 本机 <0.141 却观测到 True ⇒ 形态 A **不再可达**，"
        "`tests/test_route_dependency_form.py` 的形态 A 断言已变成死门禁，"
        "必须去重验那条断言还在不在守东西；\n"
        "    · 本机 ≥0.141 却观测到 False ⇒ 老形态 A **复活**"
        "（FastAPI 不 await ⇒ handler 拿到协程对象 ⇒ 端点 500，像「数据库挂了」），"
        "必须回去重验 `test_route_dependency_form.py` 的形态 A，"
        "并把 `modules/memory/router.py::_REQUIRE_USER` 这类身份门的形态重新对一遍。\n"
        f"  当前处置：本机 {ver[0]}.{ver[1]} 上形态 A "
        + ("**可达**（该文件此刻是真捕手）" if observed_partial is False
           else "**不可达**（该文件只剩报警器作用）")
        + "。"
    )

    duck = _FunctionLikeDuck()
    assert asyncio.iscoroutinefunction(duck) is True and fastapi_awaitable(duck) is False, (
        "★ **前提变红**：找不到「asyncio 说是协程、而 FastAPI 不 await」的可达样本了"
        "（鸭子 `_FunctionLikeDuck` 不再构成分歧）。\n"
        "  含义：`test_route_dependency_form.py` 的形态 A/C 断言变成**结构性死门禁**"
        "（永远绿）—— 要么上游把判据改得更宽，要么那张样本本身失效了。\n"
        "  处理：先读本机 `fastapi/dependencies/utils.py` 确认判据现状，再决定是收紧"
        "本样本还是把那条断言降级成「历史记录 + 前提哨兵」（不许留着假装在守）。"
    )

    fn, name = fastapi_await_predicate()
    assert getattr(fn, "__module__", "").startswith("fastapi.dependencies."), (
        f"判据函数来自 `{getattr(fn, '__module__', '?')}`，不是 FastAPI 自己 —— "
        "本模块的立场是**问库本身**，不许自己复刻一份三分支判定"
        "（复刻版会在库改判据时继续按旧规则「正确」地判定 ⇒ 静默失真）。"
    )
    assert name in ("is_coroutine_callable", "_is_coroutine_callable"), (
        f"判据函数名 {name!r} 不在候选表里 —— 上游改名了，请同步 "
        "`_FASTAPI_AWAIT_PREDICATE_NAMES`。"
    )
