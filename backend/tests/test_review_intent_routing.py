# -*- coding: utf-8 -*-
"""运营复盘师意图路由：**两级判定**回归门禁（第 265 轮）。

缺陷现场
--------
`modules/review_analyst/agent.py` 的 `_INTENT_ROUTES` 是单链「有序首命中」，
而 `weekly_report` 排在**末位** ⇒ 查询正文里只要出现「利润 / 广告 / 库存 / sku」
任一词，用户**显式点名**的「周报」就永远轮不到。

实测（第 265 轮）：`周报里利润是多少` → `profit_audit`；
老板那句「请按周报执行 + 正文含净利润率」同样落到 `profit_audit`
⇒ 他收到的是一份「利润审计」，点「归档到复盘库」也按 `profit_audit` 落库。

修复：关键词分**两级** —— 级一是「显式报表类型名」（产物名），
级二是「正文里的业务指标词」。显式点名先被看见。

本文件钉住两件事
----------------
1. **显式类型名必须赢**：正文里带别组业务词也一样（CASE_EXPLICIT）。
2. **没点名时行为不变**：业务词仍按原顺序各自命中（CASE_IMPLICIT）——
   这是「不许比改造前更差」的判据。

★ 用**生产实例**的分类器断言，不复制关键词表 / 不复制匹配控制流 ——
  复制一份来断言等于把同一判定写成两份实现，测不到生产行为。
"""
import pytest

#: ① 显式点名了**报表类型名** ⇒ 正文里的业务词不许把它顶掉
CASE_EXPLICIT = [
    ("周报里利润是多少", "weekly_report"),
    ("请按周报执行 本周整体表现良好 主要驱动因素是净利润率的提升", "weekly_report"),
    ("周报里的广告投放情况", "weekly_report"),
    ("看看经营大盘", "weekly_report"),
    ("月报里的利润和库存", "monthly_review"),
    ("利润审计", "profit_audit"),
    ("看看商品表现", "product_performance"),
    ("库存健康怎么样", "inventory_health"),
]

#: ② 没点名类型名 ⇒ 业务词按原顺序命中（与改造前逐字一致）
CASE_IMPLICIT = [
    ("这个月的利润怎么样", "profit_audit"),
    ("哪些 sku 滞销", "product_performance"),
    ("库存周转多少天", "inventory_health"),
    ("看看本月月报", "monthly_review"),
    ("本周整体怎么样", "weekly_report"),
    ("随便聊聊", "general"),
]


def _agent():
    """运营复盘师单例。

    ★ 分类器只做关键词判定：不连库、不调 LLM，构造本身也很轻
      （见 `get_review_analyst_agent` 的 docstring）。
    """
    from modules.review_analyst.agent import get_review_analyst_agent

    return get_review_analyst_agent()


@pytest.mark.parametrize("query,expected", CASE_EXPLICIT)
async def test_explicit_report_type_wins_over_body_words(query, expected):
    assert await _agent()._classify_intent(query) == expected


@pytest.mark.parametrize("query,expected", CASE_IMPLICIT)
async def test_implicit_routing_unchanged(query, expected):
    assert await _agent()._classify_intent(query) == expected


def test_ad_review_is_retired_from_chat_routing():
    """★ 第 313 轮：运营复盘师的**对话路由**不再含 `ad_review`（老板「删除广告数据」）。

    判据取自「**只有退役成功才可能出现**」的集合：三条路由表 + 服务调用表里都没有它。
    ★ 保留的 `/review/ad-review` REST 端点不在此列（那是复盘库历史归档读口，
      与"对话里说一句就出广告报告"是两条不同的通道）。

    反向注入：把 `Route("ad_review", ...)` 加回任一表，或把 `"ad_review"` 加回
    `_SERVICE_CALLS` / `_TOOL_NAMES` ⇒ 本条转红。
    """
    from modules.review_analyst import agent as ra

    labels = {r.label for r in ra._EXPLICIT_TYPE_ROUTES} | {r.label for r in ra._INTENT_ROUTES}
    assert "ad_review" not in labels, "广告归因又回到了对话路由（本轮要求它只保留 REST 端点）"
    assert "ad_review" not in ra._SERVICE_CALLS, "ad_review 又回到了 _SERVICE_CALLS"
    assert "ad_review" not in ra._TOOL_NAMES, "ad_review 又回到了 _TOOL_NAMES"


async def test_the_reported_regression_is_pinned():
    """把老板那次现场**逐字**钉住：他点的是「周报」，不能拿到「利润审计」。

    ★ 反向注入自检：把级一去掉（等价于回到单链），本用例必须转红 ——
      否则说明这组判据根本没咬住那个缺陷。
    """
    agent = _agent()
    query = "请按周报执行 本周整体表现良好 主要驱动因素是净利润率的提升"
    assert await agent._classify_intent(query) == "weekly_report"
