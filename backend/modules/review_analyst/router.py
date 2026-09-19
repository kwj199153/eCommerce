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

★ 路径命名与前端 `toolDefinitions.ts` 的 6 个工具 id 一一对应
    （weekly-report / monthly-review / ad-review / product-performance /
      inventory-health / profit-audit）—— 这样前端把 mock 换成真调用时，
    映射关系是 1:1，不需要在中间层做名字翻译。
"""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional

from core.tenant.middleware import get_current_shop_id

from . import service
from .schemas import (
    WeeklyReportRequest, MonthlyReviewRequest, AdReviewRequest,
    ProductPerformanceRequest, InventoryHealthRequest, ProfitAuditRequest,
    ReviewResponse,
)

router = APIRouter(prefix="/review", tags=["运营复盘师"])


async def _report(fn, request, store_id: Optional[str], label: str) -> ReviewResponse:
    """六大复盘能力的统一包装（**唯一**的异常映射点，避免 6 份各写一遍）。

    `store_id` 到这里已经是 strict 守卫解析并校验过归属的值（POST ⇒ 缺头必 400）。
    仍然把 `MissingShopContext` 单独映射成 400 而不是 500：直接调用 service
    （工具层 / 脚本）时它是**请求形状问题**，不是服务端故障 —— 混进 500 会让人
    去查日志找一个根本不存在的异常（本仓「失败必须能归因」那条）。
    """
    try:
        data = await fn(request, store_id)
    except service.MissingShopContext as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # pragma: no cover - 兜底，正常路径不会走到
        raise HTTPException(status_code=500, detail=f"{label}生成失败: {str(e)}")

    # 信封只复述 data 的真实结论：`summary` 就是这一份报告的一句话结论，
    # 不复用固定文案（A3 的教训：固定文案在「另一种形态」和「失败」下都会撒谎）。
    return ReviewResponse(
        success=True,
        data=data,
        message=data.get("summary") or f"{label}已生成",
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
