"""
Amazon SP-API 数据源层

提供统一工厂 `get_data_source()`：
    - 已配置 SP-API 凭据 → SpApiDataSource（真实数据）
    - 未配置凭据         → MockAmazonDataSource（演示数据，并打警告）

上层（Agent / ingest 脚本）只需依赖 AmazonDataSource 接口，
切换数据源不改业务代码。
"""

import logging

from .base import AmazonDataSource
from .mock_source import MockAmazonDataSource
from .sp_api_source import SpApiDataSource

logger = logging.getLogger(__name__)

__all__ = [
    "AmazonDataSource",
    "MockAmazonDataSource",
    "SpApiDataSource",
    "get_data_source",
]


def get_data_source(prefer: str = "auto", **kwargs) -> AmazonDataSource:
    """
    数据源工厂。

    Args:
        prefer: "auto" | "sp_api" | "mock"
            - auto  : 有 SP-API 凭据则用真实源，否则回退 Mock（默认）
            - sp_api: 强制真实源（凭据缺失时抛 RuntimeError）
            - mock  : 强制模拟源
        **kwargs: 透传给具体数据源构造（如 seed=42 / max_orders=100）

    Returns:
        AmazonDataSource 实例
    """
    if prefer == "mock":
        return MockAmazonDataSource(**{k: v for k, v in kwargs.items() if k == "seed"})

    if prefer == "sp_api":
        ok, reason = SpApiDataSource.is_available()
        if not ok:
            raise RuntimeError(f"SP-API 数据源不可用: {reason}")
        return SpApiDataSource(
            **{k: v for k, v in kwargs.items() if k in ("config", "marketplace", "max_orders")}
        )

    # auto
    ok, reason = SpApiDataSource.is_available()
    if ok:
        logger.info("数据源: SpApiDataSource（真实 SP-API）")
        return SpApiDataSource(
            **{k: v for k, v in kwargs.items() if k in ("config", "marketplace", "max_orders")}
        )

    logger.warning("数据源回退到 MockAmazonDataSource —— %s", reason)
    return MockAmazonDataSource(**{k: v for k, v in kwargs.items() if k == "seed"})
