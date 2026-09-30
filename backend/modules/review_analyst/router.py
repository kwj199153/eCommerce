"""
运营复盘师 - API 路由

第 143 轮 A4 补齐。此前本模块**只有** `__init__.py` / `schemas.py` / `service.py` /
`tools.py`，**没有 router、也没有挂到 `main.py`** —— 于是：
  · 前端「运营复盘师」的右侧看板与快捷卡片一直吃
    `frontend/src/mock/reviewDashboard.ts`（282 行假数据）；
  · 六大复盘能力在后端**一个 HTTP 入口都没有**（service 写好了没人调）。

★ 归属口径（本文件是 A4 的正题）
--------------------------------
本文件取店铺的**唯一通道**是 `Depends(get_current_shop_id)`（strict 版）：

    · 缺 / 空 / 纯空白 `X-Shop-ID` 且是写方法 ⇒ **400**（守卫在依赖解析阶段拦下，
      零数据库往返，绝不会出现「先写后报错」）；
    · 带了真 token ⇒ 强制校验 `stores_store.account_id ∈ 当前用户可见账户集合`，
      不符 **403**（选 403 不选 404：404 会泄露「该店铺是否存在」，帮人枚举）；
    · 完全匿名 + 演示模式 ⇒ 放行本地联调（`auth_required=False` 且不带凭据）。

★ 为什么用 strict 版而不是豁免成 `get_current_shop_id_optional`
    本模块的 6 个能力**没有店铺就取不到数**（数据源按 `store_id` 取）。若豁免，
    「还没选店铺」的用户会拿到一份**看起来正常、其实不知属于谁**的报告
    （实测：Mock 数据源对任意 store_id 都返回同一批 35 行数据）——
    那是归因错误，比一句可行动的「请先选店铺」糟得多。
    前端两条通道都会自动带该头（`api/request.ts` axios 拦截器、
    `api/stream.ts` fetch SSE），所以真实用户不会被挡。

★ 请求体里**没有** `store_id`（见 `schemas.ReviewRequest`）
    修复前 `ReviewRequest.store_id` 是 `int = Field(1)`：客户端可控 + 有默认值 ⇒
    改一下 body 就能读任意店铺、不传就静默读 1 号店（BOLA）。现在归属只能由
    上面的守卫注入；body 里发 `store_id` 会被 pydantic 忽略（不会 422），但
    **物理上没有字段可落** ⇒ 结构上不可能被采纳。

★ 第 166 轮 `#726` 第 2 条：新增 `POST /review/chat` —— 本模块此前
    是全仓唯一**没有 chat 端点**的业务模块（其余 7 家都有），于是前端只能靠
    `@/mock/reviewDashboard` 的 mock 分支兜着。

★ 路径命名与前端 `toolDefinitions.ts` 的 6 个工具 id 一一对应
    （weekly-report / monthly-review / ad-review / product-performance /
      inventory-health / profit-audit）—— 这样前端把 mock 换成真调用时，
    映射关系是 1:1，不需要在中间层做名字翻译。

★ 本轮新增「复盘库」三个端点（`POST/GET /review/reports`、
    `GET /review/reports/{id}`）
    上面 6 项能力是**计算**（算完不落库），复盘库是**存储**
    （存老板确认满意的那一份）。两者共用同一个 strict 归属守卫与同一个
    异常映射点（`_guard`），不走两条实现。详见文件尾那一节。
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from core.library_query import LibraryQueryError
from core.tenant.middleware import get_current_shop_id
from ai_infra.skills import bind_requested_skill

from . import service
from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest, AdReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
    ReviewChatRequest, ReviewChatResponse, ReviewResponse,
)

router = APIRouter(prefix="/review", tags=["运营复盘师"])


async def _guard(fn, label: str, *args, **kwargs):
    """统一异常映射（**唯一**的异常映射点，两个族共用：6 项能力 + 复盘库）。

    ★ 为什么必须收成一处：第 218 轮加复盘库时若在下面各写一遍 `try/except`，
      就会出现「6 项能力把 `MissingShopContext` 映射成 400、复盘库映射成 500」
      这类分叉 —— 而分叉只在特定失败下才暴露（本仓：同一判定两份实现 ⇒
      至少一份永远测不到）。改前这段逻辑住在 `_report` 里，本轮上提为 `_guard`。

    `store_id` 到这里已经是 strict 守卫解析并校验过归属的值（POST ⇒ 缺头必 400）。
    仍然把 `MissingShopContext` 单独映射成 400 而不是 500：直接调用 service
    （工具层 / 脚本）时它是**请求形状问题**，不是服务端故障 —— 混进 500 会让人
    去查日志找一个根本不存在的异常（本仓「失败必须能归因」那条）。
    """
    try:
        return await fn(*args, **kwargs)
    except service.MissingShopContext as e:
        raise HTTPException(status_code=400, detail=str(e))
    except service.ReviewLibraryError as e:
        # 写口取值/形状不合法 ⇒ 422（与 pydantic 校验失败同一个语义档）
        raise HTTPException(status_code=422, detail=str(e))
    except LibraryQueryError as e:
        # 读口的排序维度 / 过滤取值不在值域内 ⇒ 400。
        # ★ 与 422 分开是有意的：这两个值来自 URL 查询串与 LLM 工具参数，
        #   「你传错了」必须与「服务端坏了」可区分（否则模型会把
        #   「order_by 写错了」转述成「复盘库读不出来」）。
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover - 兜底，正常路径不会走到
        raise HTTPException(status_code=500, detail=f"{label}失败: {str(e)}")


async def _report(fn, request, store_id: Optional[str], label: str) -> ReviewResponse:
    """六大复盘能力的统一包装。"""
    data = await _guard(fn, label, request, store_id)

    # ★ `message` 只承载**短回执**（「周报已生成」），业务结论一律由 `data.summary`
    #   承载 —— 第 268 轮 B 档。
    #   这里原先是 `data.get("summary") or f"{label}已生成"`：把**结论**当**回执**用。
    #   前端拦截器（以及任何按 `message` 弹提示的实现）会把整段结论当成功提示弹上屏，
    #   于是点一下「运营复盘师」，屏幕顶部就飘一整段报告结论（第 266 轮老板报障的链1）。
    #   ⇒ 口径对齐 `ad_analysis` 的既定范式：成功路径 `message` 恒为「<能力>已生成」式
    #     短句；失败说明走 4xx/5xx 的 `detail`（本模块 6 个端点的失败由 `_guard` 抛）。
    return ReviewResponse(
        success=True,
        data=data,
        message=f"{label}已生成",
    )


# ==================== 六大复盘能力 ====================

@router.post("/weekly-report", response_model=ReviewResponse, summary="经营概览（周报）")
async def weekly_report(
    request: WeeklyReportRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    经营概览周报：汇总销售、广告、库存、退款数据

    - **days**: 复盘周期天数（1-90，默认 7）

    返回：GMV / 订单数 / 净收入 / 预估利润 / ACoS / ROAS + 明细与风险计数
    """
    return await _report(service.weekly_report, request, store_id, "周报")


@router.post("/monthly-review", response_model=ReviewResponse, summary="月度复盘")
async def monthly_review(
    request: MonthlyReviewRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    月度复盘：GMV / 净利率 / 退货率 / 广告占比 + SKU 贡献排名

    - **days**: 复盘周期天数（1-90，默认 7；看整月请传 30）
    """
    return await _report(service.monthly_review, request, store_id, "月度复盘")


@router.post("/ad-review", response_model=ReviewResponse, summary="广告归因")
async def ad_review(
    request: AdReviewRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    广告归因分析：ROAS / ACoS / CPC / CTR 多维回顾 + campaign 评级（S/B/C）

    - **days**: 复盘周期天数（1-90，默认 7）
    """
    return await _report(service.ad_review, request, store_id, "广告归因")


@router.post("/product-performance", response_model=ReviewResponse, summary="商品表现")
async def product_performance(
    request: ProductPerformanceRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    商品表现分析：SKU 级销量 / 利润 / 评分 / BSR / 周转天数排名

    - **days**: 复盘周期天数（1-90，默认 7）
    - **asins**: 指定 ASIN 列表（可选，为空分析全部）
    """
    return await _report(service.product_performance, request, store_id, "商品表现")


@router.post("/inventory-health", response_model=ReviewResponse, summary="库存健康")
async def inventory_health(
    request: InventoryHealthRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    库存健康：滞销预警 / 断货风险 / 周转天数（`days` 只用于标注周期）
    """
    return await _report(service.inventory_health, request, store_id, "库存健康")


@router.post("/profit-audit", response_model=ReviewResponse, summary="利润审计")
async def profit_audit(
    request: ProfitAuditRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    利润审计：销售额 - 平台佣金 - 广告 - 退款 ⇒ 净利润与净利率

    - **days**: 复盘周期天数（1-90，默认 7）
    """
    return await _report(service.profit_audit, request, store_id, "利润审计")
# ==================== 复盘对话（第 166 轮 · #726 第 2 条补齐）====================

@router.post("/chat", response_model=ReviewChatResponse, summary="复盘对话")
async def chat(
    request: ReviewChatRequest,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """
    运营复盘师对话入口（工具路由：LLM 自主选 6 个复盘工具之一）。

    ★ 与上面 6 个结构化端点**共用同一个 strict 归属守卫**：POST + 缺/空
      `X-Shop-ID` ⇒ 400。这不是照抄，而是同一条理由 —— 6 项能力都按店铺取数，
      缺归属时数据源对任意店铺返回同一批数据，老板会拿到一份
      「看起来正常、其实不知属于谁」的报告。

    ★ `session_id` 非空时透传给路由子层当 checkpointer 的 `thread_id`
      ⇒ 同一会话的第二轮能看见第一轮；为空则**不留记忆**（不拿默认值兜底）。
    """
    from .agent import get_review_analyst_agent

    agent = get_review_analyst_agent()
        # ★ 点名通道（第 188 轮）：本次对话若指定了技能名，把它置进
        #   调用链上下文，由 `skills_selected` 段落把该技能正文注入
        #   system prompt（与 `load_skill` 共用同一个解析实现）。
    async with bind_requested_skill(request.skill):
        result = await agent.invoke(
            request.query,
            context=request.context,
            session_id=request.session_id,
            shop_id=store_id,
        )
    # ★ 同上（第 268 轮 B 档）：`message` 只放短回执，回复正文在 `data.reply`
    #   —— 消费方（前端 `replies/review.ts`）本来也只读 `data.reply`，从不读 `message`。
    #   这里原先是 `message=result.reply`：降级时前端若按 `message` 弹提示，
    #   会把**整篇回复**当红字提示弹出来。
    #   ★ 降级时**不复述 `degraded_reason`**：它是机器码（`missing_shop_context` /
    #     `unparsable_report` / `report_error` / `skill_channel_unavailable`），
    #     不是给人看的话；可读的那句在对话卡里（前端按 `degraded_reason` 分支）。
    return ReviewChatResponse(
        success=not result.degraded,
        data=result,
        message="复盘未取到数据" if result.degraded else "复盘完成",
    )


# ==================== 复盘库（资料库 → 复盘库）====================
#
# ★ 这三个端点是「人工确认才入库」这条链路的落地点：6 项能力**算完不落库**，
#   老板点「归档到复盘库」才走 `POST /review/reports`。
#   范式照抄本仓既有先例（AIGC 出图 → `AssetArchiveModal` → 营销素材库）。
#
# ★ 路径用 `/review/reports`（而不是 `/review/library`）：
#   资源就是「复盘报告」，复数 + 子资源 id 是本仓 REST 的既有写法
#   （`/platform-rules`、`/monitors` 同族）。
#
# ★★ 为什么请求体是**裸 dict** 而不是 pydantic 模型：
#   写口的取值校验（report_type 值域 / period_days 范围 / 快照类型与体量）
#   唯一实现是 `service.validate_save_payload` —— 它是 REST / Agent 工具 / 脚本
#   三条入口**共用**的那一份。若再在 pydantic 模型上写一遍 `Literal[...]` 与
#   `Field(ge=1, le=90)`，两份校验必然有一份先漂移，而 HTTP 那条会把 service
#   里那份变成**永远测不到**（本仓铁律）。同族先例：
#   `modules/platform_rules/router.py`（校验走 `service.missing_required_fields`）。


@router.post("/reports", summary="归档一份复盘到复盘库")
async def save_review_report(
    payload: dict,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """把一份**已确认满意**的复盘结果归档进复盘库（幂等）。

    请求体：
    - **report_type**: 六选一（weekly_report / monthly_review / ad_review /
      product_performance / inventory_health / profit_audit）
    - **period_days**: 1~90（与 6 项能力同一值域）
    - **data**: 后端刚返回的那份 `ReviewReport` 对象**原样回传**

    ★ 为什么**回传快照**而不是只回传 report_type 让后端重算：入库的语义是
      「留档老板确认的那一份」，重算会拿到另一批数字（详见 `db_model` 的说明）。

    ★ 归属与周期由服务端覆盖（快照里的 `store_id` 会被改成已校验的店铺、
      `period_end` 取服务端当天）⇒ 请求体在结构上影响不了归属与幂等键。

    返回 `{"created": bool, "item": {...}}`：`created=False` 表示覆盖了同一
    (类型, 周期长度, 周期末日) 的既有记录（当天重复归档），前端据此说清是
    「新增一条」还是「更新了今天那条」。
    """
    return await _guard(service.save_report, "归档复盘", payload, store_id)


@router.get("/reports", summary="列出已归档的复盘")
async def list_review_reports(
    order_by: Optional[str] = None,
    report_type: Optional[str] = None,
    limit: Optional[int] = None,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """列出当前店铺已归档的复盘（**不含** `data` 快照，详情走单条端点）。

    查询参数：
    - **order_by**: `period_end`（默认，周期末日倒序）/ `created_at` / `period_days`
    - **report_type**: 只看某一类复盘（可选）
    - **limit**: 最多返回多少条（可选）

    ★ 排序/过滤取值非法 ⇒ **400**（不是静默退化成默认排序）：
      「按创建时间排」与「你参数写错了」必须可区分（第 216 轮 ③ 的归因错方向）。

    ★ `total` 是**真实条数**（与列表同口径、不受 limit 截断）——
      前端要显示「共 N 份」，答 `len(items)` 会给出被截断的数。
    """
    items = await _guard(
        service.list_saved_reports, "读取复盘库",
        store_id, order_by=order_by, report_type=report_type, limit=limit,
    )
    total = await _guard(
        service.count_saved_reports, "统计复盘库", store_id, report_type=report_type,
    )
    return {"items": items, "total": total}


@router.get("/reports/{report_id}", summary="复盘详情（含完整快照）")
async def get_review_report(
    report_id: str,
    store_id: Optional[str] = Depends(get_current_shop_id),
):
    """取一份已归档复盘的完整内容（含 `data` 快照）。

    ★ 「不存在」与「不属于当前店铺」**回同一句 404** —— 两者可区分就等于
      可以拿 id 逐位枚举别家店铺的报告（同族判据见 conversation 的会话归属收口）。
      `service.get_saved_report` 的归属过滤走 `scoped()` ⇒ 两种情形都返回 None。
    """
    item = await _guard(service.get_saved_report, "读取复盘详情", report_id, store_id)
    if item is None:
        raise HTTPException(status_code=404, detail="复盘不存在")
    return item
