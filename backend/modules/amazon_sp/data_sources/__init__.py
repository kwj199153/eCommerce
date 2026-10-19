"""
Amazon SP-API 数据源层

唯一入口：`open_data_source(store_id)`

    ============================   ===================================
    情形                            返回
    ============================   ===================================
    该店有可用凭据                  SpApiDataSource（按店配置，真实取数）
    DEMO_MODE 且该店是演示店        MockAmazonDataSource（**显式**打日志）
    该店没有凭据（真实客户）        raise StoreNotConnected（HTTP 409）
    ============================   ===================================

==============================================================================
★ 为什么把旧的 `get_data_source()` **删掉**，而不是留着兼容
==============================================================================
旧工厂的签名是 `get_data_source(prefer="auto", **kwargs)` —— **没有 `store_id`**。
它问的问题不是「这家店能用什么」，而是「这个进程有没有凭据」：

    ok, reason = SpApiDataSource.is_available()   # 读 .env
    if ok: 返回 SpApiDataSource()                 # ← 全局那一把钥匙
    else:  返回 MockAmazonDataSource()            # ← 静默降级

于是出现两层静默：配了凭据时所有店共用同一个 refresh_token（`fetch_daily_sales`
收了 `store_id` 却全程不用，只给结果行打标签）；没配凭据时**真实客户**拿到
编造的销售额，而界面上看不出任何区别。

★ 保留双入口 = 保留两条行为路径 = 必然漂移。本仓已经踩过「条件挂载 ⇒ 门禁
  根本没挂」：只要旧入口还在，任何一个漏改的调用点都会**静默**继续拿 mock，
  而且没有任何测试会红。
  ⇒ 删掉它，让漏改的调用点当场 `ImportError`。这是**故意**的破坏性改动。

★ 也不加 `STORE_DATA_SOURCE=global|per_store` 这类运行期开关 —— 双行为并存的
  回滚手段是 `git revert`，不是开关（开关一多，总有一处读不到而退回旧行为）。

上层（Agent / Celery 任务 / 脚本）只依赖 `AmazonDataSource` 接口与
`open_data_source()` 一个函数。
"""

import logging
from typing import Optional

from .base import AmazonDataSource
from .mock_source import MockAmazonDataSource
from .sp_api_source import SpApiDataSource

from modules.amazon_sp.store_credentials import (  # noqa: F401  (对外导出异常类型)
    StoreCredential,
    StoreCredentialError,
    StoreNotConnected,
    UnsupportedMarketplace,
    load_store_credential,
)

logger = logging.getLogger(__name__)

__all__ = [
    "AmazonDataSource",
    "MockAmazonDataSource",
    "SpApiDataSource",
    "StoreCredential",
    "StoreCredentialError",
    "StoreNotConnected",
    "UnsupportedMarketplace",
    "open_data_source",
    "load_store_credential",
]


async def open_data_source(
    store_id: str,
    *,
    prefer: str = "auto",
    seed: int = 42,
    max_orders: Optional[int] = None,
) -> AmazonDataSource:
    """打开**这一家店**的数据源（唯一入口）。

    Args:
        store_id: `stores_store.id`。**必填** —— 没有「全局数据源」这种东西了。
        prefer:
            - "auto"（默认）：有凭据用真实源；演示店在 DEMO_MODE 下用 mock；
              其余情况抛 `StoreNotConnected`
            - "mock"：显式要演示数据（脚本 / 单测 / 演示灌数用）
            - "sp_api"：强制真实源，拿不到凭据**抛错**，绝不落 mock
            - "oauth" / "form"：只认某一条凭据通道（诊断/切换期用）
        seed: 仅 `prefer="mock"` 时生效；让演示数据可复现。
            ★ 每个 mock 实例都是独立的 `random.Random(seed)` —— 不要把它做成
              模块级单例，那会让 RNG 状态跨请求累积（同一请求调第二次数就变了，
              `review_analyst/service.py` 的注释记录过这个坑）。
        max_orders: 透传给真实源的单次拉取上限。

    Raises:
        StoreNotConnected: 没有可用凭据（或店铺不存在 / 为空 id）。
            ★ 调用方必须把它翻成 HTTP 409 + `code=STORE_NOT_CONNECTED` 的空态，
              **不许** catch 后返回空列表 —— 「没授权」与「有授权但没数据」
              是两句完全不同的话，压成一句会让客户去查调度而不是去授权。
        UnsupportedMarketplace: 站点不在 `Marketplace` 枚举内。
        CredentialsKeyMissing / CredentialsDecryptError / CredentialsNotEncryptedError:
            凭据层故障，原样上抛（见 `store_credentials` 模块说明）。
    """
    if prefer == "mock":
        logger.info("数据源: MockAmazonDataSource（调用方显式 prefer=mock，store=%s）", store_id)
        return MockAmazonDataSource(seed=seed)

    if prefer not in {"auto", "sp_api", "oauth", "form"}:
        raise ValueError(f"未知的 prefer={prefer!r}（只接受 auto / mock / sp_api / oauth / form）")

    try:
        credential = await load_store_credential(
            store_id,
            prefer="auto" if prefer == "sp_api" else prefer,
        )
    except StoreNotConnected as exc:
        # ---- 强制真实源：一律上抛，连演示店也不例外 ----
        if prefer == "sp_api":
            logger.error("数据源: 强制 sp_api 但店铺 %s 无凭据 —— %s", store_id, exc)
            raise

        # ---- 演示店 + DEMO_MODE：显式落 mock，并**每次都打日志** ----
        #
        # ★ 两个条件缺一不可：
        #   · `store.is_demo`  —— 这家店本来就是演示店（客户自己建的店不是）
        #   · `demo_mode`      —— 部署声明了自己是演示态
        #   只看 is_demo 会在「关了 DEMO_MODE 但库里还留着演示店」时继续喂假数据
        #   （r385 的种子守卫用的是同一个真源，两处必须一致）。
        if exc.store_is_demo and _demo_mode_enabled():
            logger.warning(
                "数据源: 店铺 %s 是演示店且 DEMO_MODE 开启 —— 使用 MockAmazonDataSource"
                "（真实客户不会走到这里；看到这条日志说明当前是演示档）",
                store_id,
            )
            return MockAmazonDataSource(seed=seed)

        # ---- 真实客户没授权：硬失败 ----
        logger.warning("数据源: 店铺 %s 无可用凭据，拒绝回退 mock —— %s", store_id, exc)
        raise

    src = SpApiDataSource(
        credential,
        **({"max_orders": max_orders} if max_orders else {}),
    )
    logger.info(
        "数据源: SpApiDataSource（store=%s 通道=%s 站点=%s 复用token=%s）",
        credential.store_id,
        credential.source,
        getattr(credential.marketplace, "name", "?"),
        bool(credential.access_token),
    )
    return src


def _demo_mode_enabled() -> bool:
    """运行期读 DEMO_MODE（**不是** import 期固化成常量）。

    ★ 固化成模块级常量的后果是「改 .env 再重启也不生效」——而演示开关
      恰恰是靠重启生效的东西。与 `core/bootstrap.py` 里那条判据同源。
    """
    try:
        from core.config import config as settings
    except Exception:  # pragma: no cover
        return False
    return bool(getattr(settings, "demo_mode", False))
