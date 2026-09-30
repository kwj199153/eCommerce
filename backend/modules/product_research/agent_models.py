# -*- coding: utf-8 -*-
"""选品 Agent 的**数据结构层**（P0-6 第二刀：从 `agent_product_research.py` 外移）。

## 为什么单独成层

这 5 个 pydantic 模型原先定义在 `agent_product_research.py` 里（原 L88-143），
于是「蓝海机会长什么样」这种**跨层契约**被钉在 2375 行的 God Class 上：
`agent_analyzers.py`（分析编排层）要构造 `BlueOceanOpportunity`，
就只能反向 import 主文件 —— 那是个环。

## 归位后的四层

    agent_models.py            数据结构（本文件）
    agent_helpers.py           领域纯逻辑（类目映射 / 评分公式 / ASIN 解析）
    agent_analyzers.py         分析编排（取数 → 计算 → 组结果）
    agent_product_research.py  Agent 本体（路由 / HIL / 会话 / 落库）

依赖方向单向下行：`本体 → 编排 → {纯逻辑, 数据}`，无环。

## 主文件仍 re-export 全部 5 个名字

`tests/test_hitl_approval_flow.py` 与 `tests/test_skill_shortcut_compat.py`
按**原模块路径**导入 `AgentResponse`；本仓既有约定是
「改测试的导入路径等于替第三方改契约」，所以外移必须配 re-export
（形态由 `tests/test_product_research_analyzer_layer.py` 钉住）。
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from platforms.base import CompetitorAnalysis, FeeStructure


class AgentResponse(BaseModel):
    """Agent 响应包装"""
    content: str  # 文本回复
    data: Optional[Dict[str, Any]] = None  # 结构化数据
    display_type: str = "text"  # 展示类型：table/chart/text/report


class BlueOceanOpportunity(BaseModel):
    """蓝海机会"""
    category: str = Field(..., description="品类名称")
    search_volume: int = Field(..., description="月搜索量")
    competition: float = Field(..., description="竞争指数（0-1）")
    trend: str = Field(default="", description="趋势方向")
    opportunity_score: float = Field(..., description="机会评分（0-100）")
    reason: str = Field(default="", description="推荐理由")
    suggested_price_range: str = Field(default="", description="建议售价区间")
    estimated_margin: str = Field(default="", description="预估利润率")


class ProfitAnalysis(BaseModel):
    """利润分析结果"""
    product_name: str
    cost_price: float  # 采购成本
    selling_price: float  # 售价
    fees: FeeStructure
    total_cost: float
    net_profit: float
    roi_percentage: float
    break_even_quantity: int  # 盈亏平衡销量


class PainPointAnalysis(BaseModel):
    """痛点分析结果"""
    product_asin: str
    total_reviews_analyzed: int
    negative_review_count: int
    pain_points: List[Dict[str, Any]]  # [{pain_point, count, percentage}]
    improvement_suggestions: List[str]
    market_gap_score: float  # 市场空白度评分


class ResearchReport(BaseModel):
    """选品研究报告"""
    report_id: str
    created_at: str
    query: str
    platform: str
    summary: str
    opportunities: List[BlueOceanOpportunity] = []
    profit_analysis: Optional[ProfitAnalysis] = None
    pain_point_analysis: Optional[PainPointAnalysis] = None
    competitor_analysis: List[CompetitorAnalysis] = []
    recommendations: List[str] = []
    confidence_level: str  # high / medium / low
