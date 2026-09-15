"""
Sentry 错误上报（observability/sentry.py）

设计原则（★ 与项目「异常显式降级、禁静默 mock」的约定一致）：
    - **没配 DSN 就完全跳过**：不 import sentry_sdk、不打网络、零开销。
    - **配了 DSN 但没装包 = 显式报错**：这是「配置了却没生效」的典型静默失效，
      必须打 WARNING 说清「装了哪个包」，而不是悄悄降级成无上报。
    - **上报失败绝不影响业务**：sentry_sdk 自身是后台线程异步发送，这里只包
      初始化；对已经初始化的 SDK，调用点是 no-op。

为什么单独抽一个模块：
    main.py 只调一次 `init_sentry()`，其余模块不需要知道 Sentry 存在 ——
    未捕获异常由 FastAPI 全局处理器 / 中间件冒泡到 SDK 的 ASGI 集成自动捕获。
"""

from core.config import config
from core.logger import get_logger

_log = get_logger("observability.sentry")

_initialized = False


def init_sentry() -> bool:
    """
    按配置初始化 Sentry。

    Returns:
        True  = 已启用并初始化成功
        False = 未配置 / 未安装依赖（原因已写日志）
    """
    global _initialized

    if _initialized:
        return True

    dsn = (getattr(config, "sentry_dsn", "") or "").strip()
    if not dsn:
        # 安静跳过：这是默认状态，不是问题
        _log.debug("SENTRY_DSN 未配置，跳过 Sentry 初始化")
        return False

    try:
        import sentry_sdk
    except ImportError:
        # ★ 配了却装不上 —— 必须吵，否则「以为有错误上报，其实一条都没有」
        _log.warning(
            "已配置 SENTRY_DSN 但未安装 sentry-sdk，错误不会上报。"
            "请执行：pip install 'sentry-sdk[fastapi]'"
        )
        return False

    from core.observability.context import current_request_id

    def _before_send(event, hint):  # noqa: ANN001
        """把 request_id 挂到 Sentry 事件上，便于与日志/网关日志对齐"""
        rid = current_request_id()
        if rid:
            event.setdefault("tags", {})["request_id"] = rid
        return event

    try:
        sentry_sdk.init(
            dsn=dsn,
            environment=config.environment,
            release=f"{config.app_name}@{config.app_version}",
            # 采样率：错误全采，性能追踪默认关（开了会显著增加配额消耗）
            traces_sample_rate=float(getattr(config, "sentry_traces_sample_rate", 0.0) or 0.0),
            # 只在 debug 下带上请求体等敏感上下文
            send_default_pii=bool(config.debug),
            before_send=_before_send,
        )
    except Exception as exc:  # noqa: BLE001 —— 初始化失败不能拖垮启动
        _log.warning("Sentry 初始化失败，错误将不会上报：{}", exc)
        return False

    _initialized = True
    _log.info(
        "Sentry 已启用：environment={} release={}@{}",
        config.environment, config.app_name, config.app_version,
    )
    return True


def is_enabled() -> bool:
    """Sentry 是否已成功初始化（供 /health 与自检脚本读取）"""
    return _initialized
