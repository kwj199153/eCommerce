# -*- coding: utf-8 -*-
"""运营复盘师 Agent 门禁（第 166 轮 · `#726` 第 2 条）。

## 这个文件补的是什么

`review_analyst` 此前是全仓唯一「既无 agent 模块、也无 `prompts.py`」的
业务模块（其余 7 家都有），且是唯一**没有 chat 端点**的。实测依据：

  · `modules/*/router.py` 的端点对账 ⇒ 7 家有 `chat`，只有它没有；
  · `review_analyst_tools` 6 个工具全仓零装配（悬空）；
    ★ 第 251 轮起该容器是 7 个（新增复盘库读口 `list_reviews`）——
      本条记的是第 166 轮**当时**的实测，不改写历史。
  · 前端 `useChatOrchestrator.ts` 里挂着一条 review-analyst 专用 mock 分支，
★ 第 167 轮（#725）现状更新：那条 mock 分支已删除（改调 `POST /review/chat`）；`mock/reviewDashboard.ts` 本身也已删，由 `frontend/scripts/check-mock-retirement.cjs` 钉住不得回流。
    而 `mock/reviewDashboard.ts` 注释写着「真实上线替换为后端 review-analyst Agent 生成」。

本轮把这三件事一起接上：`prompts.py`（提示词）+ `agent.py`（工具路由子层）+
`POST /review/chat`（入口）。

## 本文件钉住的五件事

1. `test_agent_module_has_router_and_prompt`
   —— 形态判据（AST）：`agent.py` 里 `_build_router` **定义与调用点成对**、
   `ReviewAnalystAgent` 真的继承 `BaseAgent`、system prompt 来自 `prompts.py`。
2. `test_prompt_registered_in_the_single_registry`
   —— 运行期：`get_prompt_template("review_analyst")` 非空
   （提示词必须走唯一注册表，不许在 agent 里内联第二份）。
3. `test_router_assembles_the_review_tools`
   —— 运行期：`_build_router()` 真的注入**全部**复盘工具（第 251 轮起 7 个：
   6 项能力 + 复盘库读口 `list_reviews`）
   （`_build_router()` 返回 None 时**显式 skip**，不假装通过）。
4. `test_invoke_refuses_without_shop_id`
   —— ★ 缺归属 ⇒ 拒绝，且**零取数**（service 被打桩成「一被调用就炸」）。
5. `test_invoke_injects_shop_id_and_wraps_the_report`
   —— ★ `store_id` 由服务端注入（工具入参里没有它），并且用完
   **还原 ContextVar**（否则污染同进程其它调用）。

## 反向注入（改坏了必须转红，否则这些用例是在空跑）

* 把 `_build_router()` 的 `tools=review_analyst_tools` 删掉 ⇒ 判据 3 红；
* 把 `invoke()` 里 `if not shop: return ReviewChatResult(...degraded...)` 删掉
  ⇒ 判据 4 红（会去调 service）；
* 把 `_current_shop_id.set(shop)` 删掉 ⇒ 判据 5 红（service 收到 None）；
* 把 `finally: _current_shop_id.reset(...)` 删掉 ⇒ 判据 5 的「还原」子断言红。
"""
from __future__ import annotations

import ast
import pathlib

BACKEND = pathlib.Path(__file__).resolve().parents[1]
AGENT_REL = "modules/review_analyst/agent.py"


# ============================================================
# 1. 形态判据（零 IO）
# ============================================================


def test_agent_module_has_router_and_prompt():
    """`agent.py` 的形态：路由子层定义/调用成对 + 继承 BaseAgent + prompt 外置。"""
    src = (BACKEND / AGENT_REL).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)

    cls = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ReviewAnalystAgent":
            cls = node
    assert cls is not None, "找不到 ReviewAnalystAgent 类"
    bases = {ast.unparse(b) for b in cls.bases}
    assert "BaseAgent" in bases, f"ReviewAnalystAgent 没继承 BaseAgent：{bases}"

    methods = {
        m.name for m in cls.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "_build_router" in methods, "没有 `_build_router` ⇒ 工具没有路由子层可装配"
    calls = {
        ast.unparse(n.func)
        for n in ast.walk(cls)
        if isinstance(n, ast.Call)
    }
    assert "self._build_router" in calls, (
        "`_build_router` 只定义没调用 ⇒ 是死代码（装配从未发生）"
    )

    # system prompt 必须来自 prompts.py（不许在 agent 里内联第二份）
    assert "from .prompts import REVIEW_ANALYST_PROMPT" in src, (
        "system prompt 没有从 prompts.py 引入 —— 那是第二份真源"
    )
    assert "REVIEW_ANALYST_PROMPT)" in src or "REVIEW_ANALYST_PROMPT " in src


# ============================================================
# 2. 提示词走唯一注册表
# ============================================================


def test_prompt_registered_in_the_single_registry():
    """`review_analyst` 提示词必须在 `ai_infra.llm` 的注册表里可查。"""
    from ai_infra.llm import get_prompt_template

    import modules.review_analyst.prompts  # noqa: F401  (import 即注册)

    text = get_prompt_template("review_analyst")
    assert text and "复盘" in text, (
        "提示词没注册进唯一注册表（或内容为空）—— 其余 7 家都注册了，别只留一份内联的"
    )


# ============================================================
# 3. 路由子层真的注入全部复盘工具
# ============================================================


def test_router_assembles_the_review_tools():
    """`_build_router()` 必须在**真机**上注入全部复盘工具（当前 6 个）。

    ★ 分母为什么是 6（第 313 轮）：5 项复盘能力之外有复盘库读口
      `list_reviews`（读「资料库 → 复盘库」里已归档的历史复盘）。
      它**不是**第 6 项能力 —— 那 5 项是「算」，它是「读」；
      存在理由是让「下一期复盘读到上期做对比」在数据层成立。
      （第 251 轮曾为 7：6 项能力 + 读口；第 313 轮退役 `ad_review` 后回到 6。）
    """
    import pytest

    from core.checkpoint import get_checkpointer
    from modules.review_analyst.agent import ReviewAnalystAgent
    from modules.review_analyst.tools import review_analyst_tools

    agent = ReviewAnalystAgent()
    router = agent._build_router()
    if router is None:
        pytest.skip(
            "当前环境建不出路由子层（`ENABLE_LLM=False` 或装配异常）—— "
            "运行期形态不可证；**形态**由判据 1（AST）无条件覆盖。"
        )
    got = {t.name for t in router.tools}
    want = {t.name for t in review_analyst_tools}
    assert want <= got, f"路由子层漏装工具：期望 ⊇ {sorted(want)}，实际 {sorted(got)}"
    # ★ 分母写死是**有意**的：它等于「复盘师手里有几个工具」这个产品事实，
    #   写 `.` 之外的动态表达式会让「悄悄多挂一个工具」不被任何人发现
    #   （与 `tests/test_tool_catalog.py` 的装配点计数同一思路）。
    assert len(want) == 6, f"注册表应为 6 个工具，实为 {len(want)}：{sorted(want)}"
    assert "list_reviews" in want, (
        "复盘库读口 `list_reviews` 丢了 —— 下一期复盘将读不到上期（老板点名的用法）"
    )
    assert router.checkpointer is not None or get_checkpointer() is None, (
        "环境有可用 checkpointer、router 也装了工具，它却没绑上 ⇒ "
        "`interrupt()` 会在图里直接抛（详见 test_hitl_wiring 的同名说明）"
    )


# ============================================================
# 4/5. 入口：缺归属硬拒绝 + 归属服务端注入
# ============================================================


async def test_invoke_refuses_without_shop_id(monkeypatch):
    """★ 缺店铺归属 ⇒ 拒绝，且**零取数**（service 一被调用就炸）。"""
    import modules.review_analyst.agent as ra

    def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("缺归属时居然去取数了 —— fail-closed 破了")

    monkeypatch.setattr(
        ra, "_SERVICE_CALLS", {k: (_boom, v[1], v[2]) for k, v in ra._SERVICE_CALLS.items()}
    )
    agent = ra.ReviewAnalystAgent()
    res = await agent.invoke("给我本周周报", shop_id=None)
    assert res.degraded is True
    assert res.degraded_reason == "missing_shop_context"
    assert "店铺" in res.reply, "拒绝文案必须可行动（说清怎么办）"

    # 空串 / 纯空白 同样算没有（半有效输入的经典坑）
    for bad in ("", "   "):
        res2 = await agent.invoke("给我本周周报", shop_id=bad)
        assert res2.degraded is True and res2.degraded_reason == "missing_shop_context", (
            f"shop_id={bad!r} 没被当成「没有归属」—— 半有效输入会漏过去"
        )


async def test_invoke_injects_shop_id_and_wraps_the_report(monkeypatch):
    """★ 归属由服务端注入（工具入参里没有它），且用完**还原 ContextVar**。"""
    import modules.review_analyst.agent as ra
    from modules.review_analyst.schemas import WeeklyReportRequest

    seen: dict = {}

    async def _fake_weekly(request, store_id):
        seen["store_id"] = store_id
        seen["days"] = request.days
        return {
            "report_type": "weekly",
            "period_days": request.days,
            "store_id": store_id,
            "summary": "本期 GMV 环比 +12.3%，广告 ACoS 偏高。",
        }

    monkeypatch.setitem(
        ra._SERVICE_CALLS, "weekly_report", (_fake_weekly, WeeklyReportRequest, 7)
    )

    agent = ra.ReviewAnalystAgent()
    assert ra._current_shop_id.get() is None, "跑之前 ContextVar 就脏了，先修夹具"

    res = await agent.invoke("给我本周周报", context={"days": 14}, shop_id="store_probe_A")

    assert seen.get("store_id") == "store_probe_A", (
        "service 收到的不是**服务端注入**的归属 —— 归属通道断了"
    )
    assert seen.get("days") == 14, "上下文里的 days 没传进 service"
    assert res.reply == "本期 GMV 环比 +12.3%，广告 ACoS 偏高。"
    assert res.degraded is False
    assert isinstance(res.data, dict) and res.data.get("report_type") == "weekly"

    assert ra._current_shop_id.get() is None, (
        "invoke 返回后 ContextVar 没还原 —— 会污染同进程的其它请求（跨店铺串数据）"
    )
