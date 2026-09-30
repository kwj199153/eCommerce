# -*- coding: utf-8 -*-
"""候选生命周期三条原子工具（第 205 轮批 B）：归属与副作用档的可执行判据。

==============================================================================
★ 这文件拦的是什么
==============================================================================
第 205 轮把 `get_candidate` / `review_candidate` / `approve_candidate` 从
`candidates/router.py` 的内联 handler 下沉到 `service` 并注册成 Agent 工具。
三条工具在源码注释里都许下了两个承诺：

    ① 「拿不到店铺归属 ⇒ 硬拒绝，绝不拿默认店铺兜底」；
    ② 「归属由 `_resolve_shop_id()` 透传，工具入参里塞不进去」。

**注释里的承诺不构成门禁**（本仓判据「注释承诺型假门禁」）。本文件把这两条
承诺各配一条**可执行**用例：①靠「零 service 调用」证，②靠「桩收到 shop_id」
证 —— 都不是读源码字符串。

★ 为什么用打桩而不是真连库：这两条要钉的是**纯参数传递与守卫**，
  真连库会让用例依赖「PG 起没起、店铺存不存在」，而失败时的报错会伪装成
  「数据库不可用」，把人支去查一个不存在的问题（本仓既有教训）。

★ 打桩目标必须是 `pr_tools._xxx` 这个**模块级别名**：
  生产代码在 `tools.py` 顶部 `from modules.candidates import (...) as _xxx`，
  名字在 **import 时**就绑定到本模块了 —— 事后改门面的属性不会传播过来。
  （`test_hitl_wiring.py::test_save_candidate_tool_passes_shop_id` 打门面是因为
  那条路径走的是 `_service.agent` 内部的属性查找；两条路径不同，别照抄。）

★ 为什么不用 pytest 夹具管 ContextVar 的 set/reset：
  `ContextVar.set()` 返回的 Token **绑定在创建它的那个 Context 上**，
  跨 context 调 `reset()` 会抛
  `ValueError: Token was created in a different Context`。
  pytest-asyncio 里**夹具的** context 与**用例体**的 context 不是同一个
  ⇒ 「夹具里 set、用例里用、夹具里 reset」这种写法必然在 teardown 炸
  （第 205 轮实测：4 passed / 3 errors，全部错在 teardown）。
  正解是把 set 与 reset 都放进**用例体内**的同步上下文管理器。

★ 反向注入（改坏了必须转红，否则这些用例是在空跑）：
  ① 删掉 `_get_candidate_tool` 里的 `if not shop_id: return _NO_SHOP_HINT`
     ⇒ `test_all_three_refuse_without_shop` 转红（会带着 None 去查库）；
  ② 把 `_approve_candidate(candidate_id, shop_id)` 改成传 `None`
     ⇒ `test_all_three_pass_shop_id` 转红（写库归属丢了）；
  ③ 把 `approve_candidate` 的 `metadata=` 从 `SIDE_EFFECT_METADATA` 改成
     `READ_ONLY_METADATA` ⇒ `test_new_write_tools_are_approval_gated` 转红
     （且 `tests/test_hitl_policy.py` / `test_tool_catalog.py` 一起红）。
"""

import json

import modules.product_research.tools as pr_tools
from ai_infra.tools.side_effects import has_side_effects
from modules.product_research.agent_product_research import _current_shop_id

#: 探针店铺归属（`_current_shop_id` 的真源 = `ProductResearchAgent._bind_context`）
SHOP = "probe-shop-r205"

#: 「不存在」与「不属于本店铺」的**同一个**出口文案（写两条略多一句动作说明）
NOT_FOUND_HINT = "没找到这个候选（id=cand-x），也可能它不属于当前店铺。"


class _ShopScope:
    """在**同一个 Context** 里 set / reset 店铺归属（set 与 reset 不能跨 context）。"""

    def __init__(self, value):
        self.value = value
        self._tok = None

    def __enter__(self):
        self._tok = _current_shop_id.set(self.value)
        return self

    def __exit__(self, *exc):
        _current_shop_id.reset(self._tok)
        return False


def _recorder(seen):
    async def _fn(*args, **kwargs):
        seen.append((args, kwargs))
        return {"id": "cand-x", "title": "回归候选"}
    return _fn


# ============================================================================
# ① 承诺一：没有归属 ⇒ 三条都硬拒绝，且**零 service 调用**
# ============================================================================


async def test_all_three_refuse_without_shop(monkeypatch):
    """无店铺归属时三条工具都必须**明确拒绝**，且**一次都不碰 service**。

    ★ 为什么数「service 调用次数」而不是断言返回文案：文案是可以伪装的
      （先带着 `shop_id=None` 查一遍库、再回一句「请先选店铺」同样能过断言，
      而那时**已经跨租户读到了数据**）。只有调用计数能证明「这个动作没发生」。
    """
    seen = []
    monkeypatch.setattr(pr_tools, "_get_candidate", _recorder(seen))
    monkeypatch.setattr(pr_tools, "_review_candidate", _recorder(seen))
    monkeypatch.setattr(pr_tools, "_approve_candidate", _recorder(seen))

    with _ShopScope(None):
        got = [
            await pr_tools._get_candidate_tool("cand-x"),
            await pr_tools._review_candidate_tool("cand-x", "rejected", "不合适"),
            await pr_tools._approve_candidate_tool("cand-x"),
        ]

    assert seen == [], f"无归属却仍然调了 service（{len(seen)} 次）—— 守卫失效"
    for g in got:
        assert "店铺" in g, f"拒绝文案没告诉用户该做什么：{g!r}"


# ============================================================================
# ② 承诺二：有归属 ⇒ 三条都把它**原样透传**下去
# ============================================================================


async def test_all_three_pass_shop_id(monkeypatch):
    """有归属时，三条工具必须把**已校验的 shop_id** 传给 service。

    ★ 为什么这条不能省：漏传 shop_id 在 service 层表现为
      「`_load_scoped` 跳过归属过滤」⇒ **跨租户**能读到 / 改到别人的候选，
      而**不报任何错**。这是最难发现的一类缺陷，必须有一条能说「不」的断言。
    """
    calls = {}

    async def _get(cid, shop_id):
        calls["get"] = (cid, shop_id)
        return {"id": cid}

    async def _review(cid, shop_id, **kw):
        calls["review"] = (cid, shop_id, kw)
        return {"id": cid, "review_status": kw.get("review_status")}

    async def _approve(cid, shop_id, product_id=None):
        calls["approve"] = (cid, shop_id, product_id)
        return {"message": "ok", "candidate_id": cid, "product": {"id": "spu-1"}}

    monkeypatch.setattr(pr_tools, "_get_candidate", _get)
    monkeypatch.setattr(pr_tools, "_review_candidate", _review)
    monkeypatch.setattr(pr_tools, "_approve_candidate", _approve)

    with _ShopScope(SHOP):
        await pr_tools._get_candidate_tool("cand-x")
        raw = await pr_tools._review_candidate_tool("cand-x", "rejected", "不合适")
        await pr_tools._approve_candidate_tool("cand-x")

    assert calls["get"] == ("cand-x", SHOP), f"读详情漏传归属：{calls['get']}"
    assert calls["review"][0] == "cand-x" and calls["review"][1] == SHOP, (
        f"评审漏传归属：{calls['review']}"
    )
    assert calls["review"][2]["review_status"] == "rejected"
    assert calls["approve"] == ("cand-x", SHOP, None), f"入产品库漏传归属：{calls['approve']}"

    # 写两条要回写**结构化事件类型**，前端与模型靠它判断结果种类
    assert json.loads(raw)["type"] == "candidate_reviewed"


# ============================================================================
# ③「不存在」与「不属于你」同一出口（否则可枚举候选 id）
# ============================================================================


async def test_not_found_and_foreign_share_one_message(monkeypatch):
    """service 返回 None（= 不存在 **或** 不属于本店铺）时，文案必须**逐字相同**。

    ★ 两者一旦可区分，攻击面就是「拿 id 逐个试，直到某条返回『不属于你』」
      —— 那等于确认了这个 id 真实存在，可以枚举别人的候选清单。
    """
    async def _none(*a, **k):
        return None

    for name in ("_get_candidate", "_review_candidate", "_approve_candidate"):
        monkeypatch.setattr(pr_tools, name, _none)

    with _ShopScope(SHOP):
        got_get = await pr_tools._get_candidate_tool("cand-x")
        got_rev = await pr_tools._review_candidate_tool("cand-x", "rejected")
        got_app = await pr_tools._approve_candidate_tool("cand-x")

    assert got_get == NOT_FOUND_HINT, got_get

    # 写两条的「没找到」措辞与读取那条相同（服务端不区分原因），
    # 都必须**同时容纳两种原因**，不得只提其中一种。
    for g in (got_rev, got_app):
        assert g == NOT_FOUND_HINT, g


# ============================================================================
# ④ 副作用档：读的免审批，写的自动进审批面
# ============================================================================


def test_new_write_tools_are_approval_gated():
    """运行时真值：三条新工具的副作用档必须与业务事实一致。

    ★ 为什么读**运行时**而不是常量名：`metadata` 若整条被删掉，
      `has_side_effects()` 会 fail-closed 判成「有副作用」—— 安全但静默，
      而界面上的「需审批」标记会与目录表不一致。这条直接问对象本身。
    """
    by_name = {t.name: t for t in pr_tools.product_research_tools}

    assert has_side_effects(by_name["review_candidate"]) is True, (
        "review_candidate 会写库，副作用档却是只读 —— 审批闸门会静默漏掉它"
    )
    assert has_side_effects(by_name["approve_candidate"]) is True, (
        "approve_candidate 会把候选推进产品库，副作用档却是只读 —— 同上"
    )
    assert has_side_effects(by_name["get_candidate"]) is False, (
        "get_candidate 是只读，却被判成有副作用 ⇒ 每次查详情都要人工审批（功能不可用）"
    )
