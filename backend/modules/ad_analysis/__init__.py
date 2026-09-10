"""
广告分析模块 (Ad Analysis Module)

Phase 4 核心模块，提供 Amazon PPC 广告全链路分析与优化能力。

子模块：
- agent_ad.py: AdAnalysisAgent 核心逻辑
- schemas.py: 数据模型定义
- service.py: 业务逻辑层
- router.py: API 路由端点
"""

from .agent_ad import AdAnalysisAgent
from .service import AdAnalysisService, get_agent
from .router import router as ad_analysis_router

__all__ = [
    "AdAnalysisAgent",
    "AdAnalysisService",
    "get_agent",
    "ad_analysis_router",
]
