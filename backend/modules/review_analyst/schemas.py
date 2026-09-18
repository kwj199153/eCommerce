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
    """复盘请求基类"""
    store_id: int = Field(1, description="店铺 ID")
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
    store_id: int
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
