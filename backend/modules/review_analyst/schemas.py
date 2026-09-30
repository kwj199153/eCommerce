"""
运营复盘师 - 数据模型定义

复盘能力基于 amazon_sp 数据源工厂（get_data_source：真实 SP-API 或 Mock 回退）的
8 张表数据做聚合分析，产出周报/月报/广告归因/商品表现/库存健康/利润审计
六大类复盘结果。
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ==================== 请求模型 ====================

class ReviewRequest(BaseModel):
    """复盘请求基类。

    ★★★ 这里**故意没有** `store_id` 字段（第 143 轮 A4，安全修复）。

    修复前的形态是：

        store_id: int = Field(1, description="店铺 ID")

    —— 两个问题同时成立：**客户端可控**（请求体里带什么就是什么）+ **有默认值**
    （不传就静默读 1 号店）。service 直接拿它去数据源取数 ⇒ 改一下 body 就能
    读任意店铺的复盘数据（OWASP API Security #1，BOLA）。

    修复口径 = 本仓「归属只能服务端注入」的通用做法：
      · 归属由 router 的 `Depends(get_current_shop_id)`（strict 版）解析 ——
        缺/空 `X-Shop-ID` ⇒ 400；带真 token ⇒ 强制校验店铺 ∈ 当前用户可见账户
        （不符 403）；探针实测见 `tests/test_review_analyst_api.py`。
      · **从请求体删字段**（而不是"接收了但忽略"）：pydantic 默认
        `extra="ignore"` ⇒ 老客户端照发 `store_id` 不会 422，
        但那个值**物理上没有字段可落** ⇒ 结构上不可能被采纳。

    `days` 留在请求体是对的：它是**业务参数**（看哪一段周期），不是归属，
    客户端本来就有权决定。
    """
    days: int = Field(7, ge=1, le=90, description="复盘周期（天）")


class WeeklyReportRequest(ReviewRequest):
    """周报（经营概览）请求"""
    pass


class MonthlyReviewRequest(ReviewRequest):
    """月度复盘请求"""
    pass


class AdReviewRequest(ReviewRequest):
    """广告归因分析请求"""
    pass


class ProductPerformanceRequest(ReviewRequest):
    """商品表现分析请求"""
    asins: Optional[List[str]] = Field(None, description="指定 ASIN 列表，为空分析全部")


class InventoryHealthRequest(ReviewRequest):
    """库存健康分析请求"""
    pass


class ProfitAuditRequest(ReviewRequest):
    """利润审计请求"""
    pass


# ==================== 响应模型 ====================

class MetricSummary(BaseModel):
    """指标摘要"""
    label: str
    value: float
    unit: str = ""
    delta_pct: Optional[float] = None  # 环比变化（%）
    status: str = "normal"  # normal / good / warning / critical


class ReviewReport(BaseModel):
    """复盘报告通用结构"""
    report_type: str
    period_days: int
    # ★ A4：由 `int` 改为 `str` —— 它回显的是**服务端注入的** `stores_store.id`
    #   （形态 `store_xxx`），与 `X-Shop-ID` 同一 ID 空间。旧口径声明成 int 却
    #   收到字符串，是「类型与真源不符」的遗留（competitor_intel 已在传字符串，
    #   只是 Mock 只做等值过滤所以一直没暴露）。
    store_id: str
    summary: str = ""
    metrics: List[MetricSummary] = []
    details: Dict[str, Any] = {}
    insights: List[str] = []
    actions: List[Dict[str, Any]] = []  # 行动项 [{priority, content}]


class ReviewResponse(BaseModel):
    """复盘响应（统一包装）"""
    success: bool = True
    data: ReviewReport = None  # type: ignore
    message: str = ""
# ==================== 对话（第 166 轮 · #726 第 2 条补齐）====================

class ReviewChatRequest(BaseModel):
    """复盘对话请求。

    ★ 与 `ReviewRequest` 同一口径：**没有** `store_id` 字段。
      归属只能由 router 的 `Depends(get_current_shop_id)`（strict 版）注入 ——
      客户端在 body 里发 `store_id` 会被 pydantic 忽略（不会 422），
      但**物理上没有字段可落** ⇒ 结构上不可能被采纳。
    """

    query: str = Field(..., min_length=1, max_length=2000, description="老板的提问")
    session_id: Optional[str] = Field(
        None, max_length=128, description="会话 ID；非空则同一会话第二轮能看见第一轮"
    )
    context: Optional[Dict[str, Any]] = Field(
        None, description="附加上下文（如右侧看板当前周期 days / asins）"
    )

    # ★ 点名通道（第 188 轮）：用户点名本次对话要用的技能名（可选）。
    #   留空 ⇒ 只注入技能目录，仍由模型自己判断用哪条（渐进披露的原路径）。
    #   ★ 归属校验不在这里：技能名由服务端在 `read_skill_text` 里按
    #     身份 + 启用 + 对本 Agent 启用 三重过滤，请求体只负责**传递名字**。
    skill: Optional[str] = Field(default=None, description="本次对话指定使用的技能名（可选）")


class ReviewChatResult(BaseModel):
    """一次复盘对话的结果。

    `reply` + `display_type` 与前端既有 mock（`buildReviewReply`）的返回契约
    **逐字一致**，因此前端把 mock 换成真调用时不需要改渲染分支；
    `data` 是给右侧看板用的结构化报告（可为空）。
    """

    reply: str
    display_type: str = "text"
    data: Optional[Dict[str, Any]] = None
    #: 是否降级/未拿到数据。★ 前端必须据此显示提示 ——
    #: 否则「查不到」与「数据就是很差」在界面上不可区分。
    degraded: bool = False
    degraded_reason: str = ""


class ReviewChatResponse(BaseModel):
    """复盘对话响应（统一包装）。"""

    success: bool = True
    data: Optional[ReviewChatResult] = None
    message: str = ""
