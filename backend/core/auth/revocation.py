"""
Token 撤销（P1-b，2026-09-16）

==============================================================================
★★★ 先说清一件事：无状态 JWT 无法「把该用户所有 token 加进黑名单」
==============================================================================
需求原文是「改密后把当前用户所有 token 加入黑名单」。这句话**无法字面实现**，
不是偷懒，而是前提不成立：

    无状态 JWT 的整个意义就在于**服务端不保存已签发 token 的清单**。
    要「逐个加黑名单」，先得有一份"该用户此刻有哪些 token 在飞"的清单 ——
    而这份清单一旦存在，JWT 就不再无状态了（等于自建一套更差的 session 表，
    还得解决"清单本身怎么同步、怎么清理"）。

⇒ 正确实现是**版本号**（`users.token_version`）：
    签发 token 时把当前版本写进 `tv` 声明；
    改密 / 重置密码 / 「登出所有设备」 ⇒ `token_version += 1`
    ⇒ 全部旧 token 的 `tv` 不再匹配 ⇒ **结构性失效**。
    不需要知道它们分别是什么，也不依赖 Redis。

==============================================================================
两级撤销（分工必须分清，别混着用）
==============================================================================
| 级别 | 机制 | 载体 | 粒度 | 谁在用 |
|------|------|------|------|--------|
| ① 整批 | `users.token_version` | **DB**（权威） | 该用户全部 token | 改密 / 重置密码 / 登出所有设备 |
| ② 单枚 | `jti` 黑名单 | Redis | 一枚 token = 一台设备 | `POST /auth/logout` |

★ 为什么①必须放 DB 而不是 Redis：
    锁定与撤销是**安全判定**。Redis 抖一下不能让「改密后旧 token 依然可用」
    这种事发生 —— 那是静默的安全退化。DB 是这类判定的唯一可靠载体。

==============================================================================
★ ② 的读写语义**故意不对称**（这是本模块最需要理解的一点）
==============================================================================
    · **读**（校验每枚 token）：Redis 不可达 ⇒ 记 WARNING 后**放行**（fail-open）。
      理由：jti 只承担「单设备登出」这一低危能力，而整批撤销（①）始终有效。
      Redis 一抖就让**全站所有用户 401** 的代价，远大于
      「某次登出在 Redis 故障窗口内没生效」。

    · **写**（/auth/logout 端点）：Redis 不可达 ⇒ **抛异常** ⇒ 端点回 503。
      理由：这是「声称做了某事」的端点。做不到却回「登出成功」，
      用户会以为自己已经安全退出，而 token 其实还能用 ——
      **静默的假成功比明确的失败危险得多**。
      （端点侧还提供不需要 Redis 的兜底：`/auth/logout-all` 走版本号，永远可用。）

    一句话判据：**读侧保可用性，写侧保诚实性。**
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from core.config import config

logger = logging.getLogger(__name__)

# 缺 `tv` 声明时按这个值处理。
#
# ★ 为什么不直接拒绝（那才是更"安全"的默认）：
#   本功能上线时，所有**存量 token 都没有 `tv` 声明**，而库里的
#   token_version 刚加上、默认就是 1。此时把"缺 tv"当成"版本 1"是**准确**的
#   —— 因为迁移前根本不存在"改过密码"这个概念。
#   于是：老 token 继续可用（不需要全体用户重新登录），
#   而**一旦有人改密**，其 token_version 变成 2，那些缺 tv 的老 token 与
#   带 tv=1 的 token 会**一起**被拒 ⇒ 安全属性完整保留。
#   （若直接拒绝缺 tv 的 token，代价是上线瞬间把所有人踢下线，收益为零。）
LEGACY_TOKEN_VERSION = 1

# Redis key 前缀。带上 "revoked:" 便于在 redis-cli 里一眼认出来。
_JTI_KEY_PREFIX = "auth:revoked:jti:"

_client = None
_client_failed = False


def _reset_client_cache() -> None:
    """清掉缓存的 Redis 客户端（仅测试用于模拟「Redis 不可达/恢复」）"""
    global _client, _client_failed
    _client = None
    _client_failed = False


async def _get_client():
    """
    懒加载一个共享的 Redis 客户端。

    ★ 缓存失败标记：Redis 不可达时不要**每个请求**都去重试一次连接 ——
      那会把 2 秒的 connect 超时叠加到每一个请求上（正是 core/config.py
      里 redis_url 注释记录的那个 IPv6/超时坑的放大版）。
    """
    global _client, _client_failed
    if _client is not None:
        return _client
    if _client_failed:
        return None
    url = (getattr(config, "redis_url", "") or "").strip()
    if not url:
        _client_failed = True
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1,   # 见 rate_limit.py 的注释：1s 够区分「慢」与「挂」
            socket_timeout=2,
        )
        await client.ping()
        _client = client
        return _client
    except Exception as exc:  # noqa: BLE001
        _client_failed = True
        logger.warning(
            "Redis 不可达，单枚 token 黑名单（jti）校验将降级为放行；"
            "整批撤销（token_version）不受影响，仍按 DB 生效。原因：%s", exc
        )
        return None


def _remaining_ttl_seconds(exp: Optional[datetime]) -> int:
    """
    算出「这枚 token 还有多久过期」= 黑名单条目该保留多久。

    ★ 必须给 TTL，且必须**贴着 token 自己的 exp**：
      若写成固定 TTL（例如 7 天），而 token 只活 60 分钟，则黑名单会在 Redis 里
      堆积 6 天多的无用条目；若 TTL 短于 token 剩余寿命，键一过期黑名单就失效 ——
      **登出过的 token 会"复活"**，且没有任何报错。
      贴着 exp 是最省空间且不会提前失效的做法。

    ★ 下限取 1 秒：exp 已过或缺失时也要写进去（此时 exp 校验本身就会拒绝，
      TTL=1 只是保证键会被清掉，不留永久垃圾）。
    """
    if exp is None:
        return 60
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = (exp - now).total_seconds()
    return max(1, int(delta))


async def revoke_jti(jti: Optional[str], exp: Optional[datetime] = None) -> None:
    """
    把一枚 token 的 jti 写进 Redis 黑名单。

    Raises:
        RuntimeError: Redis 不可达或写入失败 —— **必须让调用方知道撤销没成功**。
            `/auth/logout` 据此返回 503，而不是假报「登出成功」。
    """
    if not jti:
        # 没有 jti 的 token（本功能上线前的存量）无法单独撤销。
        # 这不是错误，但**必须说出来** —— 静默 return 会让调用方以为撤销成功了。
        raise RuntimeError(
            "该 token 不含 jti（签发于本功能上线前），无法单独撤销。"
            "如需强制下线，请使用「登出所有设备」（走 token_version，不依赖 Redis）"
        )

    client = await _get_client()
    if client is None:
        raise RuntimeError(
            "Redis 不可达，无法写入 token 黑名单 ⇒ 本次登出**未生效**。"
            "请稍后重试，或改用「登出所有设备」强制下线"
        )
    try:
        await client.setex(
            _JTI_KEY_PREFIX + jti, _remaining_ttl_seconds(exp), "1"
        )
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"写入 token 黑名单失败 ⇒ 本次登出未生效：{exc}") from exc


async def is_jti_revoked(jti: Optional[str]) -> bool:
    """
    查询 jti 是否已被撤销。

    ★ **fail-open**（Redis 不可达 ⇒ 返回 False 并记 WARNING）：
      理由见模块 docstring「读写语义故意不对称」。简言之：
      整批撤销始终由 DB 生效，单枚登出在 Redis 故障窗口内失效是可接受的降级；
      而"Redis 一抖全站 401"不可接受。
    """
    if not jti:
        return False
    client = await _get_client()
    if client is None:
        return False
    try:
        return bool(await client.exists(_JTI_KEY_PREFIX + jti))
    except Exception as exc:  # noqa: BLE001
        logger.warning("查询 token 黑名单失败，本次按「未撤销」处理：%s", exc)
        return False


def token_version_matches(token_version: Optional[int], user_token_version: int) -> bool:
    """
    比对 token 里的 `tv` 与库里的 `users.token_version`。

    ★ 缺 `tv` 时按 `LEGACY_TOKEN_VERSION` 处理（见该常量注释）——
      而不是拒绝，否则上线瞬间会把所有存量会话踢下线。
    """
    effective = LEGACY_TOKEN_VERSION if token_version is None else int(token_version)
    return effective == int(user_token_version)
