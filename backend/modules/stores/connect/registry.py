"""连接器注册表（平台名 → 连接器实例）。

★★★ 为什么用「注册表 + 前缀匹配」而不是一张 `family` 映射表

  店铺的 `platform` 是**带站点后缀**的形态（`amazon_us`、`shopee_my`），
  而连接器是**平台家族**级的。若这里再维护一张
  `{"amazon_us": "amazon", "amazon_uk": "amazon", ...}` 的映射表，
  那就是**第二份平台家族判定**（`Store.platform_family` 已经是第一份）。
  两份判定的必然结局是漏改一处 —— 新增 `amazon_sg` 时只改了一份，
  于是那家店「连接不了」，且不报错，只是查不到连接器。

  ⇒ 前缀匹配：注册表的**键本身就是**唯一的家族清单，加平台只改一处。

★ 延迟导入

  连接器模块会 import `platforms.amazon.sp_api.auth`（它又 import
  `core.config`）。放在模块顶层，会让「只是想读一下 schema」的调用方
  把整条 Amazon 依赖链拉起来。改成取用时导入，边界更干净。
"""

from __future__ import annotations

import importlib
from typing import Dict, List, Optional, Type

from modules.stores.connect.base import PlatformConnector, PlatformSchema


#: 平台家族键 → 连接器类路径。**这是唯一的家族清单**。
_CONNECTOR_PATHS: Dict[str, str] = {
    "amazon": "modules.stores.connect.platforms.amazon:AmazonConnector",
    "shopee": "modules.stores.connect.platforms.shopee:ShopeeConnector",
    "shopify": "modules.stores.connect.platforms.shopify:ShopifyConnector",
    "tiktok": "modules.stores.connect.platforms.tiktok:TikTokConnector",
}

_cache: Dict[str, PlatformConnector] = {}


class UnknownPlatform(ValueError):
    """`Store.platform` 不属于任何已注册平台（如脏数据 / 新增平台未登记）。"""

    def __init__(self, platform: str):
        self.platform = platform
        super().__init__(
            f"未注册的平台：{platform!r}。已登记：{sorted(_CONNECTOR_PATHS)}。"
            "请在 modules/stores/connect/registry.py 登记后重试"
        )


def resolve_family(platform: str) -> str:
    """`amazon_us` → `amazon`。

    ★ 只做前缀匹配，**不复制** `Store.platform_family` 的映射表：
      家族的唯一定义就是上面那张注册表。
    """
    p = (platform or "").strip().lower()
    if not p:
        raise UnknownPlatform(platform)
    if p in _CONNECTOR_PATHS:
        return p
    for family in _CONNECTOR_PATHS:
        if p.startswith(family + "_"):
            return family
    raise UnknownPlatform(platform)


def connector_class(family: str) -> Type[PlatformConnector]:
    path = _CONNECTOR_PATHS[family]
    module_name, _, attr = path.partition(":")
    module = importlib.import_module(module_name)
    return getattr(module, attr)


def get_connector(platform: str) -> PlatformConnector:
    """按 `Store.platform` 取连接器（自动按家族归并，实例按家族缓存）。

    Raises:
        UnknownPlatform: 平台未登记
    """
    family = resolve_family(platform)
    if family not in _cache:
        _cache[family] = connector_class(family)()
    return _cache[family]


def list_schemas() -> List[PlatformSchema]:
    """全部平台的连接表单规格（供前端通用渲染）。"""
    return [get_connector(f).schema() for f in _CONNECTOR_PATHS]


def supported_platforms() -> List[str]:
    return sorted(_CONNECTOR_PATHS)


def schema_for(platform: Optional[str]) -> Optional[PlatformSchema]:
    """按店铺平台取规格；未登记的返回 None（由调用方决定怎么报错）。"""
    try:
        return get_connector(platform or "").schema()
    except UnknownPlatform:
        return None
