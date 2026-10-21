"""新手引导（注册即播种 / 加载示例数据）模块门面（第 387 轮）。

★ 本包判 **PLUGIN**（见 `tests/test_module_layering.py`）：
  它是面向用户的功能（"注册完给你一家店，想看点东西就点加载示例"），
  没有任何模块在顶层 import 它 —— 唯一的消费方是组合根 `main.py`
  （注册钩子 + 路由装配）。顶层只依赖 `core.*` 与 `modules.stores`（KERNEL），
  方向合法；9 个 seed 宿主全是 PLUGIN/SHARED，一律**函数内**延迟 import。
"""

from modules.onboarding.router import router as onboarding_router
from modules.onboarding.service import (
    SAMPLE_DATA_LABEL,
    SAMPLE_STORE_NAME,
    SampleTargetMissing,
    bootstrap_new_user,
    load_sample_data,
)

__all__ = [
    "onboarding_router",
    "bootstrap_new_user",
    "load_sample_data",
    "SampleTargetMissing",
    "SAMPLE_DATA_LABEL",
    "SAMPLE_STORE_NAME",
]
