"""
全局日志配置

基于 loguru 的统一日志管理。

★ 2026-09-15 增强（可观测性 P1-8）：
    1. **request_id 贯穿**：新增 patcher，从 `core/observability/context.py` 的
       ContextVar 里取 request_id / shop_id 注入每一条日志的 extra。
       修复前 request_id 只出现在中间件那一行访问日志里 —— 业务代码
       `logger.info("生成图片失败")` 打出来的日志与请求无法关联，线上排障只能靠时间猜。
    2. **异常带完整回溯**：`backtrace=True`（跨帧变量）常开；
       `diagnose=True`（显示局部变量值）仅在 debug 打开 —— 它会把变量值写进日志，
       线上开等于泄露用户数据。
    3. **JSON 结构化输出可选**：`LOG_JSON=true` 时控制台/文件改为逐行 JSON，
       便于 Filebeat / Promtail / 阿里云 SLS 采集；本地开发保持彩色单行。
    4. **日志目录可配**：`LOG_DIR`（默认 logs）。容器里 CWD 未必是项目根，
       写死相对路径会导致日志落到意料之外的位置甚至因权限失败。
"""

import logging
import sys
from pathlib import Path

from loguru import logger

from core.config import config


# ====== 标准库 logging 接管 ======
#
# ★ 为什么必须做（2026-09-15 发现）：
#   项目里**两套日志栈并存** —— 全局是 loguru，但还有 16 个模块用
#   `logging.getLogger(__name__)`：aigc_media/service、aigc_media/router、
#   competitor_intel/service、ad_analysis/service、listing_generator/service、
#   review_analyst/service、platform_rules/ai_split、core/metering/usage_tracker、
#   core/middleware/rate_limit、core/checkpoint、platforms/amazon/sp_api/*、
#   modules/amazon_sp/data_sources/*、secretary/shop_tools …
#
#   而标准库 logging **没有任何 handler**（全项目搜不到 basicConfig / dictConfig），
#   于是这批日志只会落到 `logging.lastResort`：stderr、无时间戳、无模块名、
#   WARNING 以下直接丢弃，且 **不进 logs/*.log 文件**。
#   后果：配额超限告警（usage_tracker）、限流触发（rate_limit）、
#        SP-API 调用失败（sp_api/*）这些真正要排查的东西，日志文件里一条都没有。
#
#   加上本 handler 后，两套栈统一出口：同格式、同文件、同样带 request_id。

class InterceptHandler(logging.Handler):
    """
    把标准库 logging 的记录转发给 loguru。

    ★ 为什么不用官方文档那段 `depth` 数帧写法（实测在 Python 3.13 下失效）：
        官方 recipe 靠 `logging.currentframe()` 起算，再数「还有几层是 logging
        自己的帧」。但 `logging.currentframe` 是 `sys._getframe` 的 staticmethod
        包装 —— 它返回的是**调用它的那个帧**（也就是本 emit），根本不是 logging
        的帧，于是循环第一次就退出，depth 偏小，日志里的定位全部落到
        `logging:callHandlers:1706`（实测结果），而不是真正的业务代码行。
        更麻烦的是这条链的长度随 CPython 版本变化，用 depth 就是在赌版本。

    ★ 改用「显式带上 LogRecord 自带的定位信息，由 patcher 覆盖 record」：
        LogRecord 里本来就有 name / funcName / lineno（标准库自己 walked 好的），
        直接拿来用，与调用栈形态和 Python 版本都无关。
    """

    #: 传给 patcher、用于覆盖 record 定位信息的 extra key
    ORIGIN_KEY = "_stdlib_origin"

    def emit(self, record: logging.LogRecord) -> None:
        # 级别名优先用 loguru 里注册过的名字，取不到就用原始数值
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        # ⚠️ 必须传已经格式化好的字符串（record.getMessage()），
        #    并且**不传 args/kwargs** —— loguru 只在给了参数时才做 str.format，
        #    否则「消息里本身带 {} 的标准库日志」会被当成占位符而抛 KeyError。
        origin = (record.name, record.funcName, record.lineno)
        logger.bind(**{self.ORIGIN_KEY: origin}).opt(
            exception=record.exc_info
        ).log(level, record.getMessage())


def setup_stdlib_interception() -> None:
    """
    把标准库 logging 接到 loguru 上。

    三个细节：
      1. `force=True` —— 清掉已有 root handler。SQLAlchemy 在 `echo=True` 时
         会偷偷调 basicConfig 装一个 StreamHandler，不清就会 SQL 双份输出。
      2. root level = 0（NOTSET）—— 由 loguru 的 sink level 决定过滤，
         避免 stdlib 侧再拦一次导致「loguru 配了 DEBUG 却看不到 debug 日志」。
      3. 第三方库降噪 —— httpx/httpcore 每发一个 HTTP 请求打一条 INFO，
         asyncio 在启动期打 "Using selector: ..."。这些在生产环境只会
         把日志文件刷满且带不出有用信息，统一压到 WARNING。
      4. 摘掉 SQLAlchemy 自装的 handler —— `create_async_engine(echo=debug)`
         会往**叶子 logger `sqlalchemy.engine.Engine`** 上直接 addHandler
         （实测：format=`%(asctime)s %(levelname)s %(name)s %(message)s`，
         输出到 stdout）。它加在我们之前的 import 阶段，且不在 root 上，
         所以 `basicConfig(force=True)` 清不掉 —— 结果每条 SQL 打两遍：
         一遍走它的 stdout、一遍经 propagate 走 loguru。
    """
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    quiet_sqlalchemy_echo_handlers()

    # uvicorn 的 access 日志与 RequestLogMiddleware 完全重复，且后者信息更全
    # （带 request_id / shop / 慢请求告警）→ 关掉 uvicorn 自己那份。
    # 前提：启动 uvicorn 时必须传 log_config=None，否则它会重新装回 handler。
    for name in ("uvicorn.access",):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = False

    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True

    # 第三方库降噪（保留 ERROR/CRITICAL）
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def quiet_sqlalchemy_echo_handlers() -> None:
    """
    摘掉 SQLAlchemy echo 自己装的 stdout handler，保留 level 由 config 决定。

    ⚠️ 必须**在 engine 创建之后**调用才有效，而 engine 在 `core/database.py`
      被 import 时就创建了。因此本函数是幂等的，除了 `setup_stdlib_interception()`
      里调一次，app 启动（lifespan）时还会再调一次兜底 —— 不依赖 import 顺序。
    """
    for name in (
        "sqlalchemy",
        "sqlalchemy.engine",
        "sqlalchemy.engine.Engine",
        "sqlalchemy.pool",
        "sqlalchemy.orm",
    ):
        lg = logging.getLogger(name)
        if lg.handlers:
            lg.handlers = []
        lg.propagate = True


# ====== 日志格式 ======

# 单行文本格式（含 request_id / shop_id 两列，排障时一眼对齐）
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{extra[request_id]}</cyan> | "
    "<cyan>{extra[shop_id]}</cyan> | "
    "<cyan>{extra[user_id]}</cyan> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)


# ====== 上下文注入 ======

def _inject_context(record) -> bool:
    """
    loguru patcher：给每条日志补上请求级字段，并修正标准库日志的定位信息。

    规则：**显式 bind 的值优先**。中间件 `logger.bind(request_id=...)` 已经设过的，
    这里不覆盖 —— 否则「手工指定的追踪 ID」（例如从上游网关透传进来的）会被抹掉。

    Returns:
        必须是 bool/None（loguru 要求 patcher 返回 falsy 或 True）；返回 False
        会让该条日志被丢弃，这里永远返回 True。
    """
    from core.observability.context import (
        EMPTY,
        current_account_id,
        current_client_ip,
        current_request_id,
        current_shop_id,
        current_user_id,
    )

    extra = record["extra"]

    # ① 标准库 logging 转发过来的记录：用 LogRecord 的定位覆盖 loguru 的。
    #    pop 而不是 get —— 这是内部传递用的 key，不该出现在 extra 里被采集走。
    origin = extra.pop(InterceptHandler.ORIGIN_KEY, None)
    if origin:
        name, function, line = origin
        record.update(name=name, function=function, line=line)

    # ② 请求级上下文 —— 统一 Context 的五个字段（★ P0-2）
    #    request_id(trace) / user_id / account_id(tenant) / shop_id / client_ip
    #    仍是"显式 bind 优先"：调用方手工 bind 过的值不被覆盖。
    #    ★ 五个字段全部落进 extra：JSON 日志（LOG_JSON=true）会整份带出；
    #      文本格式只渲染其中三列（见 LOG_FORMAT），另两个留给采集端。
    for key, getter in (
        ("request_id", current_request_id),
        ("shop_id", current_shop_id),
        ("user_id", current_user_id),
        ("account_id", current_account_id),
        ("client_ip", current_client_ip),
    ):
        if not extra.get(key):
            extra[key] = getter() or EMPTY
    return True


def _add_sinks() -> None:
    """注册控制台 + 文件两个 sink"""
    level = "DEBUG" if config.debug else (getattr(config, "log_level", "") or "INFO")

    # --- 控制台 ---
    logger.add(
        sys.stdout,
        format=LOG_FORMAT,
        level=level,
        colorize=not bool(getattr(config, "log_json", False)),
        serialize=bool(getattr(config, "log_json", False)),
        enqueue=True,          # 异步写，避免日志 IO 阻塞事件循环
        backtrace=True,
        diagnose=bool(config.debug),
    )

    # --- 文件（按天轮转 + gz 压缩 + 30 天保留）---
    log_dir = Path(getattr(config, "log_dir", "logs") or "logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # 目录不可写（容器只读挂载等）→ 退化为仅控制台
        logger.warning("日志目录 {} 不可用（{}），本次仅输出到控制台", log_dir, exc)
        return

    logger.add(
        log_dir / "{time:YYYY-MM-DD}.log",
        format=LOG_FORMAT,
        level=level,
        rotation="00:00",      # 每天轮转
        retention="30 days",   # 保留30天
        compression="gz",      # 压缩旧日志
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=bool(config.debug),
        serialize=bool(getattr(config, "log_json", False)),
    )


def setup_logger() -> None:
    """配置全局日志"""
    logger.remove()              # 移除默认 handler（默认 handler 的格式不含 request_id）
    logger.configure(patcher=_inject_context)
    setup_stdlib_interception()  # 接管标准库 logging（见本节顶部说明）
    _add_sinks()


# 初始化日志
setup_logger()


# 提供给其他模块使用的 get_logger 函数
def get_logger(name: str):
    """获取带名称的 logger 实例"""
    return logger.bind(name=name)
