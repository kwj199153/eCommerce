"""
交易履约 + 买家反馈域 → 工具表（供 Agent 经 bind_tools 调用）

====================================================
★ 工具从哪里取数：唯一答案是 `modules.trade.service`
====================================================
本文件**不做任何计算**：

    · 「是不是迟了」= `service.compute_transit_and_delay`（seed 落库时就算好了）
    · 「是什么原因」= `service.attribute_review`
    · 「赔多少」    = `service.match_compensation_rule`
    · 「健康分」    = `service.compute_sku_health`

工具层只做「取租户 → 调 service → 序列化」。计算换个口径只需改 service 一处，
不会在工具里留第二份实现 —— 这是本仓那条教训的直接应用。

====================================================
★ 为什么 `fetch_order_tracking` 现在**不**走 AmazonDataSource
====================================================
`AmazonDataSource.fetch_order_tracking()` 还在（`amazon_sp/data_sources/`），
但它的定位已经变：它是**上游取数**，将来由「订单落库同步任务」调用它把数据
写进 `orders` / `shipments`；本工具读的是**落库之后的表**。

不这么做会出现两个替身答案：
    客服问「这笔订单到哪了」
      · 走 SP-API：返回 Orders 接口能给的（**没有运单号**，属 Shipping API）
      · 走 DB：返回我们存的（有运单号、有轨迹、有「迟到几天」）
同一个问题两种答案，谁也不会报错。⇒ 定一个：**表是唯一真源**，
DB 查不到就如实说查不到（fail-closed），不回头再问一次另一个源。

====================================================
★ 租户归属只能服务端注入
====================================================
所有工具都不接受 `shop_id` 形参 —— 归属由绑定方的 ContextVar 提供
（见 `set_shop_id_resolver`）。形参会让 LLM 有机会「指定另一个店铺」，
那正是本项目已经修过一次的老毛病（`create_ticket` 的 store_id 形参）。
"""

import json
from typing import Callable, Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.side_effects import READ_ONLY_METADATA, SIDE_EFFECT_METADATA

from core.logger import get_logger
from modules.trade import service as trade_service

_log = get_logger("modules.trade.tools")

# 由绑定方注入的店铺取值器（返回 str 或 None）
_shop_id_resolver: Optional[Callable[[], Optional[str]]] = None


def set_shop_id_resolver(resolver: Callable[[], Optional[str]]) -> None:
    """绑定方（Agent）在构造工具调用链之前把「当前店铺」取值器交进来。

    ★ 为什么用注入而不是直接 import 客服的 ContextVar：
      本模块可能被多个 Agent 复用；若反向 import `modules.customer_service.agent_cs`
      会形成 `agent → tools → agent` 的环（customer_service/tools.py 里就有这个注释）。
    """
    global _shop_id_resolver
    _shop_id_resolver = resolver


def _require_shop_id() -> str:
    """取当前店铺；取不到 ⇒ 抛错（fail-closed，不落到「全店数据」）。"""
    shop_id = (_shop_id_resolver() if _shop_id_resolver else None) or ""
    if not shop_id:
        raise PermissionError(
            "缺少店铺上下文（X-Shop-ID），拒绝执行 —— "
            "订单/物流/差评都是租户隔离数据，不允许跨店查询"
        )
    return shop_id


def _dump(resp) -> str:
    return json.dumps(resp, ensure_ascii=False, default=str)


# ============================================================ 工具实现

async def _fetch_order_tracking_tool(order_id: str) -> str:
    """按订单号查询订单 + 商品明细 + 物流轨迹 + 关联差评。

    ★ 演示场景第一步（定位订单与商品）就是这个工具的产出：
      一次调用即拿到「订单 → SKU → 运单 → 迟到天数 → 关联差评」整条链。

    Args:
        order_id: 平台订单号（如 AMZN123456789）或内部订单 id。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        ctx = await trade_service.get_order_context(session, shop_id, order_id)
        if not ctx.get("found"):
            return _dump(ctx)
        # ★ 数据是 seed 造的演示数据还是真同步来的，必须让模型看得见
        ctx["is_mock_data"] = trade_service.is_mock_source(ctx.get("data_source"))
        return _dump(ctx)


async def _list_customer_reviews_tool(
    max_rating: int = 3,
    days: int = 30,
    sku: str = "",
    limit: int = 20,
) -> str:
    """列出本店铺近期的买家评价（默认只看中差评）。

    Args:
        max_rating: 评分上限（默认 3，即中差评；传 5 可看全部）。
        days: 只看最近 N 天（默认 30）。
        sku: 只列某个 SKU 的评价（留空看全部）。
        limit: 返回条数上限（默认 20）。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        rows = await trade_service.list_recent_negative_reviews(
            session, shop_id, max_rating=max_rating, limit=limit, days=days,
        )
        if sku:
            rows = [r for r in rows if r.get("sku") == sku]
        return _dump({"count": len(rows), "items": rows,
                      "is_mock_data": any(
                          trade_service.is_mock_source(r.get("source")) for r in rows)})


async def _get_customer_review_context_tool(review_id: str) -> str:
    """取一条买家评价的完整处置上下文：评价原文 + 关联订单/物流 + 归因 + 处置。

    ★ 这是「差评处置」这活儿的原料：没有它，Agent 只能对着一句评论文本
      即兴发挥 —— 那正是 `cs-refund-playbook` 技能要求「引用订单/物流证据」
      却拿不到任何取数手段时的处境。

    Args:
        review_id: 评价 id（如 crev-amazon-R1DEMO0001）或平台侧评价 id。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        ctx = await trade_service.get_review_context(session, shop_id, review_id)
        if not ctx.get("found"):
            return _dump(ctx)
        cause = (ctx.get("attribution") or {}).get("primary_cause")
        if cause:
            rep = await trade_service.count_repeat_issues(
                session, shop_id, ctx["review"].get("sku", ""), cause,
            )
            ctx["repeat_issue"] = rep
        ctx["is_mock_data"] = trade_service.is_mock_source(ctx.get("data_source"))
        return _dump(ctx)


async def _get_sku_health_score_tool(sku: str) -> str:
    """取某个 SKU 的**买家反馈维度**健康分（最近一期）。

    ★ 注意：这是「买家怎么说」，与广告分析里广告活动的 health_score 不是一回事。

    ★★ 第 294 轮：查询已搬进 `service.get_sku_health_score` —— HTTP 端点
      （`GET /api/v1/trade/skus/{sku}/health`）也要这个数。在工具里再留一份
      查询语句就是**同一判定两份实现**（本仓铁律），改一处漏一处。
      工具层自此只做「取租户 → 调 service → 序列化」。

    Args:
        sku: SKU 编码（如 SKU-KC-002）。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        return _dump(await trade_service.get_sku_health_score(session, shop_id, sku))


async def _plan_compensation_tool(review_id: str) -> str:
    """按归因查**可配置的补偿规则**，给出「建议赔什么」（**不发券、不写库**）。

    ★ 为什么只「建议」不「发放」：发券/退款是不可逆动作，必须过 HITL 审批。
      本工具只把「命中了哪条规则、赔多少、上限多少」摆出来，让人来判断。

    Args:
      review_id: 评价 id。会先用它的归因去匹配规则。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        ctx = await trade_service.get_review_context(session, shop_id, review_id)
        if not ctx.get("found"):
            return _dump(ctx)
        attribution = ctx.get("attribution")
        if not attribution or not attribution.get("primary_cause"):
            return _dump({"review_id": review_id, "compensation_ready": False,
                          "reason": "这条评价还没有归因，无法匹配补偿规则"})
        cause = attribution["primary_cause"]
        review = ctx["review"]
        shipment = ctx.get("shipment") or {}
        rule = await trade_service.match_compensation_rule(
            session, shop_id, cause,
            rating=review.get("rating"),
            delay_days=shipment.get("delay_days"),
            verified_purchase=review.get("verified_purchase"),
        )
        if rule is None:
            # ★ 与 `build_disposition_draft` 同口径：无规则 / 有规则但条件不符
            #   是**两件事**，不能合并（否则同一句假陈述会在两条通道上各说一遍）。
            cands = await trade_service.list_enabled_rules_for_cause(session, shop_id, cause)
            if cands:
                codes = " / ".join(r.code for r in cands)
                return _dump({"review_id": review_id, "cause": cause,
                              "compensation_ready": False,
                              "reason_code": "rule_conditions_unmet",
                              "rule_codes": [r.code for r in cands],
                              "reason": f"「{cause}」已有 {len(cands)} 条启用规则（{codes}），"
                                        f"但这条评价不满足它的条件"})
            return _dump({"review_id": review_id, "cause": cause,
                          "compensation_ready": False, "reason_code": "no_rule",
                          "reason": f"「{cause}」这一类还没有任何补偿规则"})
        try:
            plan = trade_service.apply_compensation_rule(rule)
        except trade_service.CompensationOverBudget as e:
            # ★ 超限显式报出来，不悄悄按上限赔
            return _dump({"review_id": review_id, "cause": cause,
                          "compensation_ready": False, "rule_code": rule.code,
                          "over_budget": True, "reason": str(e)})
        return _dump({"review_id": review_id, "cause": cause,
                      "compensation_ready": True, **plan})


async def _propose_review_disposition_tool(review_id: str, notes: str = "") -> str:
    """为一条差评生成**待批准**的处置草稿并落库（`status=proposed`）。

    ★★ 这是 `review_dispositions` **唯一的 Agent 侧写入点**。此前全仓
      `ReviewDispositionRecord(...)` 的构造次数是 **0** —— 那正是这张表
      全库 0 行的根因：有模型、有状态机、有双语回复字段，却没有任何代码
      往里写一行。

    ★ 为什么只写到 `proposed`：发券/退款是**不可逆的外部动作**，
      本仓既有口径（`plan_compensation`）就是「只摆规则让人判断」。
      approved（批准）与 issued（发放）两步留给**人**，走 REST 端点，
      不在 Agent 工具里 —— Agent 若能自己发券，HITL 就被架空了。

    ★ 内容字段不传 ⇒ 由 `service.build_disposition_draft` 按
      「归因 + 命中规则 + 补偿金额」现算一份（响应里 `draft_filled=True`）。

    Args:
        review_id: 评价 id（如 crev-amazon-R1DEMO0001）或平台侧评价 id。
        notes: 备注（可选）。
    """
    from core.database import async_session_factory

    shop_id = _require_shop_id()
    async with async_session_factory() as session:
        try:
            row = await trade_service.propose_disposition(
                session, shop_id, review_id, notes=notes,
            )
        except trade_service.DispositionNotFound as e:
            return _dump({"ok": False, "review_id": review_id, "error": str(e)})
        except trade_service.DispositionError as e:
            # ★ 拒绝必须分开报：已批准/已核准/已执行不可覆盖、没归因、没规则、超预算
            return _dump({"ok": False, "review_id": review_id, "error": str(e)})
        return _dump({"ok": True, **row})


# ============================================================ 工具表

trade_tools = [
    StructuredTool.from_function(
        coroutine=_fetch_order_tracking_tool,
        name="fetch_order_tracking",
        description=(
            "按订单号查订单 + 商品明细 + 物流轨迹 + 关联差评（含迟到天数）。"
            "当用户问「我的订单到哪了/物流怎么还没到/这笔订单买了什么」时使用，"
            "或需要查某笔订单的履约情况时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_list_customer_reviews_tool,
        name="list_customer_reviews",
        description=(
            "列出本店铺近期买家评价（默认中差评）。"
            "当用户想看差评/买家反馈/某个 SKU 的评论时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_get_customer_review_context_tool,
        name="get_customer_review_context",
        description=(
            "取一条买家评价的完整上下文：原文 + 关联订单/物流 + 归因 + 是否重复问题 + 处置。"
            "当要处理某条差评、判断责任归属、写回复草稿时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_get_sku_health_score_tool,
        name="get_sku_health_score",
        description=(
            "取某 SKU 的买家反馈健康分（含环比 delta 与主要失分项）。"
            "当用户问某个产品健康不健康/评分趋势/该不该改进时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_plan_compensation_tool,
        name="plan_compensation",
        description=(
            "按差评归因匹配补偿规则，给出建议方案（不发券不写库）。"
            "当用户问该赔多少/能不能补券/怎么处理这个差评时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_propose_review_disposition_tool,
        name="propose_review_disposition",
        description=(
            "为一条差评生成待批准的处置草稿并落库（含补偿方案与中英双语回复）。"
            "当已经判明差评归因、要给出处理方案时使用。"
            "注意：本工具只写到「待批准」，发券/退款须由人在处置列表里批准并发放。"
        ),
        # ★ 显式声明有副作用：它真的写 `review_dispositions` 一行。
        #   不声明也会按 fail-closed 判成「需审批」，但显式写出可自文档化，
        #   且 `write_verb_violations()` 的写动词名单里加了 `propose_`
        #   ⇒ 即使有人把它改成只读，门禁也会红。
        metadata=SIDE_EFFECT_METADATA,
    ),
]
