"""
运营复盘师模块 → 主 Agent 工具注册表

把 ReviewAnalystService 的六大复盘能力包装成 langchain 工具，供店秘书（主 Agent）
通过 bind_tools 自主选择调用。

设计要点（与 product_research/tools.py 一致）：
- 只包「语义明确」的 6 个复盘能力（周报 / 月报 / 广告归因 / 商品表现 / 库存健康 /
  利润审计），不包粗粒度 chat 入口。
- 参数扁平化，工具函数内自构造 Pydantic request。
- 工具层只做「调用 service + 序列化」，不碰数据源本体。
- ★ 第 251 轮新增第 7 个：`list_reviews`（读**复盘库**里已归档的历史复盘）。
  它不是「第 7 项复盘能力」（那 6 项是**算**，它是**读**）——
  存在理由是让「下一期复盘能读到上期做对比」在**数据层**成立。
  详见文件尾该工具处的说明。

★★★ 第 143 轮 A4：`store_id` 从「`int = 1` 默认值」改成**必填、无默认值**。
    修复前 6 个工具都写着 `store_id: int = 1`：忘传就**静默**复盘 1 号店 ——
    错得完全没有声音。改成必填后，忘传直接 `TypeError`（签名即门禁）。
    ★ 并且类型统一成 `str`：归属的真源是 `stores_store.id`（形态 `store_xxx`），
      与 `X-Shop-ID` 同一个 ID 空间；旧口径声明 `int` 与真源不符
      （`competitor_intel` 早就在传字符串，只是 Mock 只做等值过滤，一直没暴露）。

★★★ 第 166 轮 `#726` 第 2 条：**接线已完成**（装配点是
    `modules/review_analyst/agent.py::ReviewAnalystAgent._build_router()`）。

接线时做掉的那件事 —— `store_id` 不再是对 LLM 可见的入参：
原先 6 个工具都写着 `store_id: str` 作为**必填形参**，那是「客户端可控」的
同一个坑（LLM 会照着自己编一个，而它编出来的值可能正好是别人的店铺）。
现在改为 `modules/product_research/agent_product_research.py::_current_shop_id`
那条范式：`agent.invoke()` 在**入口处**把**已校验归属**的 shop_id 写进
ContextVar，工具侧 `_store_id()` 读回。

★ 缺归属时**硬拒绝**（返回 `{"found": false, "error": ...}`），不兜任何默认店铺：
   Mock 数据源对任意 store_id 都返回同一批数据 ⇒ 兜一个默认值等于给出一份
   「看起来正常、其实不知属于谁」的报表，那是归因错误。
"""

from typing import Optional

from langchain_core.tools import StructuredTool
from ai_infra.tools.serialization import dump_result as _dump
from ai_infra.tools.side_effects import READ_ONLY_METADATA
from core.library_query import LibraryQueryError

from .service import ReviewAnalystService
from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
)

_service = ReviewAnalystService()

#: 列表类工具的单次返回上限（模型上下文有限，必须封顶）。
#: ★ 与 `modules/library/tools.py::MAX_ITEMS` 取同一个数（50）——
#:   两处都是「列表进模型上下文」的同一类约束，值不一致会让老板发现
#:   「同样是列表，这个库能返回 50 条、那个只给 20 条」。
MAX_LIST_ITEMS = 50


def _store_id() -> str:
    """读**服务端注入**的店铺归属（ContextVar），返回空串表示没有。

    ★ 为什么不放进工具入参：入参是给 LLM 看的，它**会**自己编一个值，
      而编出来的值可能正好是别人的店铺（BOLA 的 LLM 版本）。
      写入点只有一处：`agent.ReviewAnalystAgent.invoke()` 的入口。
    """
    from .agent import _current_shop_id

    return (_current_shop_id.get() or "").strip()


def _deny_missing_shop() -> str:
    """没有店铺归属时的**显式拒绝**（不兜默认店铺，不返回空壳）。"""
    return _dump(
        {
            "found": False,
            "error": "缺少店铺归属：请先在界面左上角选一个店铺再重试。",
            "reason": "missing_shop_context",
        }
    )


async def _weekly_report_tool(days: int = 7) -> str:
    """经营概览（周报）：汇总销售、广告、库存、退款数据，生成结构化周报。

    Args:
        days: 复盘周期天数（默认 7）。
    """
    store_id = _store_id()
    if not store_id:
        return _deny_missing_shop()
    req = WeeklyReportRequest(days=days)
    resp = await _service.weekly_report(req, store_id)
    return _dump(resp)


async def _monthly_review_tool(days: int = 30) -> str:
    """月度复盘：GMV/ACoS/转化率/退货率趋势对比 + SKU 贡献排名。

    Args:
        days: 复盘周期天数（默认 30）。
    """
    store_id = _store_id()
    if not store_id:
        return _deny_missing_shop()
    req = MonthlyReviewRequest(days=days)
    resp = await _service.monthly_review(req, store_id)
    return _dump(resp)


async def _product_performance_tool(
    days: int = 7,
    asins: Optional[list[str]] = None,
) -> str:
    """商品表现分析：SKU 级销量/利润/评分/BSR/周转排名，识别爆款与滞销品。

    Args:
        days: 复盘周期天数（默认 7）。
        asins: 指定 ASIN 列表（可选，为空分析全部）。
    """
    store_id = _store_id()
    if not store_id:
        return _deny_missing_shop()
    req = ProductPerformanceRequest(days=days, asins=asins)
    resp = await _service.product_performance(req, store_id)
    return _dump(resp)


async def _inventory_health_tool(days: int = 7) -> str:
    """库存健康分析：滞销预警/断货风险/周转天数/补货建议。

    Args:
        days: 复盘周期天数（默认 7，仅用于标注）。
    """
    store_id = _store_id()
    if not store_id:
        return _deny_missing_shop()
    req = InventoryHealthRequest(days=days)
    resp = await _service.inventory_health(req, store_id)
    return _dump(resp)


async def _profit_audit_tool(days: int = 30) -> str:
    """利润审计：销售额 - 佣金 - 广告 - 退货等全链路核算净利润与净利率。

    Args:
        days: 复盘周期天数（默认 30）。
    """
    store_id = _store_id()
    if not store_id:
        return _deny_missing_shop()
    req = ProfitAuditRequest(days=days)
    resp = await _service.profit_audit(req, store_id)
    return _dump(resp)


async def _list_reviews_tool(
    limit: int = 20,
    report_type: Optional[str] = None,
    order_by: Optional[str] = None,
) -> str:
    """列出本店**复盘库**里已归档的历史复盘（默认按周期末日倒序，最近的在最前）。

    Args:
        limit: 最多返回多少条（默认 20，上限 50）。
        report_type: 只看某一类复盘，不传则返回全部。
        order_by: 排序维度，不传则按 period_end（周期末日）倒序。
    """
    store_id = _store_id()
    if not store_id:
        # ★ 出参形状照 `modules/library/tools.py` 的 `_fallback`：**只给 type + error**，
        #   不回 `items: []`。回空列表会让「没有店铺归属」与「复盘库确实是空的」
        #   在模型看来一模一样 —— 前者该让老板去选店铺，后者该让他先去归档
        #   （处置完全不同，本仓：空状态不得与失败态混同）。
        return _dump(
            {
                "type": "library_read_failed",
                "error": "缺少店铺归属：请先在界面左上角选一个店铺再重试。",
                "reason": "missing_shop_context",
            }
        )
    try:
        n = max(1, min(int(limit or 20), MAX_LIST_ITEMS))
        items = await _service.list_saved_reports(
            store_id, order_by=order_by, report_type=report_type, limit=n
        )
        total = await _service.count_saved_reports(store_id, report_type=report_type)
    except LibraryQueryError as e:
        # 排序维度 / 过滤取值不在值域内 ⇒ 与「读不到」分开，让模型**改参数重试**
        return _dump({"type": "invalid_argument", "error": str(e)})
    except (TypeError, ValueError) as e:
        return _dump({"type": "invalid_argument", "error": f"参数类型不对：{e}"})
    return _dump(
        {"type": "review_list", "total": total, "returned": len(items), "items": items}
    )


# ====== 工具注册表 ======

review_analyst_tools = [
    StructuredTool.from_function(
        coroutine=_weekly_report_tool,
        name="weekly_report",
        description=(
            "经营概览周报：汇总销售、广告、库存、退款数据，生成结构化周报。"
            "当老板要看本周经营情况/周报/经营大盘/业绩概览时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_monthly_review_tool,
        name="monthly_review",
        description=(
            "月度复盘：GMV/ACoS/转化率/退货率趋势对比 + SKU 贡献排名。"
            "当老板要看月度数据/月报/月度总结/月度复盘时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_product_performance_tool,
        name="product_performance",
        description=(
            "商品表现分析：SKU 级销量/利润/评分/BSR/周转排名，识别爆款与滞销品。"
            "当老板要看商品表现/SKU 排名/哪个品卖得好/滞销时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_inventory_health_tool,
        name="inventory_health",
        description=(
            "库存健康分析：滞销预警/断货风险/周转天数/补货建议。"
            "当老板要看库存/断货风险/滞销/补货建议时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    StructuredTool.from_function(
        coroutine=_profit_audit_tool,
        name="profit_audit",
        description=(
            "利润审计：销售额 - 佣金 - 广告 - 退货全链路核算净利润与净利率。"
            "当老板要看利润/净利润/赚了多少/成本结构时使用。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
    # ★ 第 251 轮：复盘库读口（资料库 → 复盘库）。
    #   ★ 为什么它挂在**复盘师自己**名下、而不是 `modules/library/tools.py`
    #     那 6 个资料库工具里：那 6 个是「读当前店铺的某个资料库」，
    #     挂给选品分析师 + 店秘书；而本工具的存在理由是老板那句
    #     「**下一期复盘自动读到上期**做对比」—— 消费者是复盘师本人。
    #     挂到别家去，本模块的复盘就永远读不到自己的历史。
    StructuredTool.from_function(
        coroutine=_list_reviews_tool,
        name="list_reviews",
        description=(
            "列出本店**复盘库**里已归档的历史复盘（老板点过「归档到复盘库」的那些）。"
            "当老板问「上期/上次复盘结论是什么」「和上个月比怎么样」「我归档过哪些复盘」"
            "「上个月的净利率是多少」时使用；也是**做本期复盘前的对比动作**。"
            "返回每份已归档复盘的 id / 类型 / 周期长度 / 周期末日 / 一句话结论 / 归档时间"
            "（**不含**明细快照；要看某一份的完整内容请让老板在「资料库 → 复盘库」里打开）。"
            "排序维度 order_by 可选：period_end（默认，周期末日倒序 = 最近几期在前）/ "
            "created_at（归档时间倒序）/ period_days；"
            "过滤维度 report_type 可选：weekly_report / monthly_review / ad_review / "
            "product_performance / inventory_health / profit_audit。"
            "传了值域外的值会返回 type=invalid_argument，请换个值重试。"
            "出参含 total（本店**真实**归档份数）与 returned（本次实际返回条数，"
            "受 limit 与上限 " + str(MAX_LIST_ITEMS) + " 约束）；"
            "老板问「归档了几份」时答 total，不要答 returned。"
            "★ 库里没有归档记录时会返回 total=0 与空 items —— 那是**正常空状态**"
            "（老板还没归档过），不要把它说成「读取失败」。"
        ),
        metadata=READ_ONLY_METADATA,
    ),
]
