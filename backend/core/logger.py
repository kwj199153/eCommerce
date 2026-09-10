"""
全局日志配置

基于 loguru 的统一日志管理。
"""

import sys
from pathlib import Path

from loguru import logger

from core.config import config


# ====== 日志格式 ======
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


def setup_logger():
    """配置全局日志"""
    # 移除默认 handler
    logger.remove()

    # 控制台输出
    logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        level="DEBUG" if config.debug else "INFO",
        colorize=True,
    )

    # 文件输出（按天轮转）
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    logger.add(
        log_dir / "{time:YYYY-MM-DD}.log",
        format=LOG_FORMAT,
        level="DEBUG" if config.debug else "INFO",
        rotation="00:00",  # 每天轮转
        retention="30 days",  # 保留30天
        compression="gz",  # 压缩旧日志
        encoding="utf-8",
    )


# 初始化日志
setup_logger()


# 提供给其他模块使用的 get_logger 函数
def get_logger(name: str):
    """获取带名称的 logger 实例"""
    return logger.bind(name=name)
