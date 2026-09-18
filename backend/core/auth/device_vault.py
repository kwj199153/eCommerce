"""
本机免密切换的凭据托管（第 119 轮，2026-09-17）

==============================================================================
需求
==============================================================================
「切换账号时，一段时间内不用重复输密码」。

══════════════════════════════════════════════════════════════════════════════
★★★ 为什么凭据放在**服务端**，而不是加密后放浏览器
══════════════════════════════════════════════════════════════════════════════
免密有一个绕不过去的死结：

    要免密 ⇒ 解密密钥必须自动可得
    ⇒ 密钥必须落在本机某处
    ⇒ 能在本机运行的脚本也能拿到它

所以「前端加密」只能提高门槛，做不到「本机不可解」。实测过两条路都成立，
但收益方向不对：
    · WebCrypto 不可导出密钥（`exportKey` 抛 InvalidAccessException）**确实**
      导不出来，但应用自己必须能解 ⇒ 本机 JS 仍可调用解密；
    · 且 `CryptoKey` **无法 JSON 序列化**（`JSON.stringify` 得到 `{}`），
      只能存 IndexedDB ⇒ 项目首次引入 IndexedDB，而 CI 环境没有它，
      门禁只能打桩 ⇒ 那段代码在 CI 里等于没被真跑过。

⇒ 最终形态：**本机不持有凭据**。浏览器只留一个 `device_id`（httpOnly Cookie，
   JS 读不到），真正的 refresh token 由服务端加密托管。
   F12 里既没有 JWT、也没有可解出 JWT 的东西。

══════════════════════════════════════════════════════════════════════════════
Redis 结构
══════════════════════════════════════════════════════════════════════════════
    auth:device:<device_id>   →  HASH
        field = user_id
        value = "enc:v1:..."      （Fernet 密文，明文是 {"refresh_token": "..."}）
    TTL = jwt_refresh_token_expire_days 天（默认 7），每次读写都续期

★ 为什么用 HASH 而不是「一个 key 一个账号」：
  免密的粒度是**设备 × 账号**。一个人在开发机上切 3 个账号，就应该只有
  一个 device_id、一个 key，里面 3 个 field —— 退出某个账号只 HDEL 一个 field，
  不会误伤另外两个。
  反过来若用 `auth:device:<id>:<user_id>` 这种扁平 key，删账号与删设备
  就得靠 SCAN 前缀，既慢又容易漏。

★ TTL 为什么续期而不是固定：refresh token 每次刷新都会**签发新的一枚**
  （`/auth/refresh` 不拉黑旧的），其 7 天窗口是从签发时刻重新计时的。
  容器若不续期，就会出现「凭据还活着、容器先过期」= 免密凭空失效。

══════════════════════════════════════════════════════════════════════════════
★★★ 读写失败语义**故意不对称**（与 core/auth/revocation.py 同一条判据）
══════════════════════════════════════════════════════════════════════════════
    · **读**（列账号 / 取凭据）：Redis 不可达 ⇒ 视为「本机没记住任何账号」。
      结果是用户被要求**输一次密码** —— 这是**安全**的降级
      （不是 fail-open，是 fail-closed-to-password），且用户自己就能恢复。
      绝不能因为 Redis 抖动回 500，让「切换账号」整个功能炸掉。

    · **写**（记住凭据）：Redis 不可达 / 缺密钥 ⇒ **抛异常** ⇒ 端点回 503。
      理由与 `/auth/logout` 相同：这是「声称做了一件事」的接口。
      做不到却回「已记住」，用户下次切换时才发现要输密码，
      中间这段时间界面上一直挂着「免密」标记 —— **静默的假承诺**。

    一句话：**读侧保可用，写侧保诚实。**

══════════════════════════════════════════════════════════════════════════════
★ 复用而非新造（这两条是刻意的，改回去就等于把缺陷请回来）
══════════════════════════════════════════════════════════════════════════════
1. 加密走 `core.security.credentials`（已有 `enc:v1:` 版本前缀、缺密钥拒绝写入、
   密文不含明文的断言）。**不新造第二套加解密** —— 否则又是一处
   「同一能力两份实现 ⇒ 至少一份永远测不到」。
   ⚠️ 共用同一把密钥的后果要认下来：轮换 `SHOP_CREDENTIALS_ENCRYPTION_KEY`
      会让免密凭据一起失效。此处**优雅降级**（删掉解不开的条目 ⇒ 用户输一次
      密码即重建），不是报错，也不会静默。设备凭据本就是 7 天短命数据，
      与「店铺凭证丢了要重新接平台」的代价不对称，故不为此单开一把密钥。

2. Redis 客户端复用 `core.auth.revocation` 的共享连接（已提升为公共别名）。
   此前「从配置建 async Redis 客户端」全仓已有 3 处实现，**不允许出现第 4 处**。
   共用还带来一个正确性收益：Redis 故障时，jti 黑名单与免密容器的降级判定
   **一致**，不会出现「黑名单已放行、免密还在苦等超时」的分裂行为。
"""

from __future__ import annotations

import logging
import secrets
from typing import List, Optional

from core.auth.jwt_handler import verify_token
from core.auth.revocation import get_shared_client
from core.config import config
from core.security.credentials import (
    CredentialsKeyMissing,
    decrypt_credentials,
    encrypt_credentials,
)

logger = logging.getLogger(__name__)

# Redis key 前缀。带 "auth:device:" 便于 redis-cli 里一眼认出。
_DEVICE_KEY_PREFIX = "auth:device:"

# 浏览器侧只持有这个 Cookie 的值 —— 它**不是凭据**：
# 单独拿到它，还必须能打到本服务、且该 user_id 仍在本设备容器里。
DEVICE_COOKIE_NAME = "wb_device_id"

# Cookie 作用域收到 auth 路由下：其他业务接口根本不需要它，
# 收窄之后即使被中间件/日志打印，暴露面也更小。
DEVICE_COOKIE_PATH = "/api/v1/auth"


class DeviceVaultUnavailable(RuntimeError):
    """Redis 不可达 / 写入失败 —— 调用方必须据此回 503，不得假装成功。"""


class DeviceVaultRejected(RuntimeError):
    """入参不满足不变量（例如凭据不属于声称的账号）—— 属调用方错误，回 4xx。"""


def new_device_id() -> str:
    """
    生成一枚新的设备标识。

    ★ `secrets.token_urlsafe(32)` = 256 bit 熵。用 `uuid4` 也行，
      但这里**故意避开 UUID 的可读格式**：一串看起来像 ID 的东西
      容易被人当成"可以手写/可以猜"的标识，而它实质上是一枚 bearer 句柄。
    """
    return secrets.token_urlsafe(32)


def _key(device_id: str) -> str:
    return _DEVICE_KEY_PREFIX + device_id


def _ttl_seconds() -> int:
    """
    容器存活时长 = refresh token 的有效期。

    ★ 贴着 `jwt_refresh_token_expire_days` 取值，不另设常量：
      两处若各写各的，改了后端配置而忘了改这里，就会变成
      「容器比凭据长命」⇒ 读出来一枚注定 401 的 token，
      或者「容器比凭据短命」⇒ 凭据还有效但免密已经不能用。
    ★ 下限 1 秒：配置被误设成 0 或负数时，TTL=0 在 Redis 里是"立即删除"，
      会让写成功而读不到 —— 那种失败极难排查，故夹一个下限。
    """
    days = int(getattr(config, "jwt_refresh_token_expire_days", 7) or 7)
    return max(1, days * 24 * 60 * 60)


def ttl_seconds() -> int:
    """
    容器存活秒数（公共别名）。

    ★ 端点层要用它给设备 Cookie 设 `max_age`。私有名 `_ttl_seconds` 不对外，
      而**另抄一份天数换算**就是第二处实现 —— 两处一旦不同步，
      就会出现「容器续期了、Cookie 先过期」这种免密凭空失效的形态。
    """
    return _ttl_seconds()


async def _client_or_none():
    """拿共享 Redis 客户端；不可达时返回 None（不抛，由调用方决定语义）。"""
    return await get_shared_client()


async def _client_or_raise():
    client = await _client_or_none()
    if client is None:
        raise DeviceVaultUnavailable(
            "Redis 不可达，本机免密凭据无法写入。"
            "请确认 Redis 已启动，然后重新登录一次以重新记住本机。"
        )
    return client


async def remember(device_id: str, user_id: str, refresh_token: str) -> int:
    """
    把一枚 refresh token 记进本设备的容器（同账号覆盖）。

    ★★★ 归属校验在**这一层**做，不是在路由层。
      这样任何调用方都不可能把"别人的 token"写进"我的设备" ——
      判定只有一份实现，新加端点也绕不过去。

    ★ 先加密再写 Redis（顺序不变量）：反过来的话，一旦加密抛错
      （例如没配密钥），容器里已经躺了一条**明文** refresh token。

    Returns:
        写入后本设备记住的账号数。

    Raises:
        DeviceVaultRejected: 凭据无效 / 已过期 / 不属于 `user_id`
        CredentialsKeyMissing: 未配置加密密钥（**拒绝写入，绝不退回明文**）
        DeviceVaultUnavailable: Redis 不可达
    """
    if not device_id:
        raise DeviceVaultRejected("缺少设备标识")
    if not user_id:
        raise DeviceVaultRejected("缺少账号标识")

    data = verify_token(refresh_token, expected_type="refresh")
    if data is None:
        raise DeviceVaultRejected(
            "无法记住登录状态：凭据无效或已过期，请重新登录后再试"
        )
    if data.user_id != user_id:
        # 与 /auth/logout 里那条 user_id 比对同一判据：登录凭据的副作用
        # 不该跨账号。这里必须**拒绝**（那边是静默跳过，因为登出本身已成功）。
        raise DeviceVaultRejected("凭据与账号不匹配，已拒绝写入")

    # ★ 先加密（可能抛 CredentialsKeyMissing）—— 异常发生在任何 Redis 写之前
    blob = encrypt_credentials({"refresh_token": refresh_token})

    client = await _client_or_raise()
    key = _key(device_id)
    try:
        await client.hset(key, user_id, blob)
        await client.expire(key, _ttl_seconds())
        return int(await client.hlen(key))
    except DeviceVaultUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DeviceVaultUnavailable(f"写入本机凭据失败：{exc}") from exc


async def list_user_ids(device_id: str) -> List[str]:
    """
    本设备记住了哪些账号（**只返回标识，不含任何凭据**）。

    ★ Redis 不可达 ⇒ 返回空列表（fail-closed-to-password，见模块 docstring）。
      返回空只会让用户多输一次密码；抛错会让「切换账号」按钮直接点不动。
    """
    if not device_id:
        return []
    client = await _client_or_none()
    if client is None:
        return []
    try:
        ids = await client.hkeys(_key(device_id))
        return sorted(str(i) for i in (ids or []))
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取本机凭据清单失败，本次按「未记住任何账号」处理：%s", exc)
        return []


async def recall(device_id: str, user_id: str) -> Optional[str]:
    """
    取回本设备为 `user_id` 记住的 refresh token（已解密）。

    ★ 解不开（密钥轮换过 / 值被破坏）⇒ **删掉该条目**并返回 None。
      不删的话每次切换都失败，而且用户永远不知道该怎么办；
      删了则退化成"需要输一次密码"，下一次登录会自动重建。
      这与 `dek` 语义一致：宁可多让用户输一次，也不要留一个每次都报错的假入口。
    ★ 存的不是本模块写的密文（历史明文）⇒ `decrypt_credentials` 会显式抛
      `CredentialsNotEncryptedError`。这里同样按"坏条目"处理并删除 ——
      它绝不可能是本模块写下的，留着只会在每次切换时抛异常。

    ★ Redis 不可达 ⇒ 返回 None（同 list_user_ids 的理由）。
    """
    if not device_id or not user_id:
        return None
    client = await _client_or_none()
    if client is None:
        return None
    key = _key(device_id)
    try:
        blob = await client.hget(key, user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取本机凭据失败，本次按「未记住」处理：%s", exc)
        return None
    if not blob:
        return None

    try:
        payload = decrypt_credentials(blob)
    except CredentialsKeyMissing as exc:
        # ★★★ 与「数据坏了」必须分开处置：密钥未配置 / 被临时摘掉是
        #   **配置问题不是数据问题** —— 密钥恢复后这些条目本可以重新解开。
        #   此处若也去 forget()，就等于"密钥一抖动就把用户的免密全清掉"，
        #   而且用户看不出发生了什么。正确做法是只降级这一次。
        logger.warning(
            "加密密钥当前不可用，本机免密暂时降级为需输密码（凭据未删除）：%s", exc
        )
        return None
    except Exception as exc:  # noqa: BLE001
        # 除「密钥暂时不可用」之外的**任何**解不开的条目，一律按坏条目清掉：
        #   · CredentialsDecryptError     —— 密钥轮换过 / 值被破坏
        #   · CredentialsNotEncryptedError —— 存的竟不是本模块写的密文（历史明文）
        # 这些都不可能靠等待自愈，留着只会在每次切换时抛异常，
        # 而用户完全看不到"为什么这个账号的免密坏了"。
        # 清掉 ⇒ 退化成"需要输一次密码"，下一次登录会自动重建。
        logger.warning(
            "本机凭据无法解密（多为加密密钥已轮换 / 值被破坏 / 不是本模块写的密文），"
            "已删除该条目，该账号需重新登录一次：%s", exc
        )
        await forget(device_id, user_id)
        return None

    token = (payload or {}).get("refresh_token") if isinstance(payload, dict) else None
    if not token:
        await forget(device_id, user_id)
        return None
    return str(token)


async def forget(device_id: str, user_id: str) -> int:
    """
    忘掉本设备上的某一个账号（退出登录 / 从列表移除 / 凭据已失效时调用）。

    ★ 与 `list_user_ids` 的宽容语义一致：Redis 不可达时**不抛错**。
      调用方（登出流程）已经完成了真正的撤销，这里删不掉只是
      「下次切换还得输密码」，不该让登出报错。
    ★ 清空整个设备归 `forget_device` —— 两者的差别正是
      「退出这个账号」与「清空记录」的差别，不要混用。

    Returns:
        删除后剩余条目数；不可达时返回 -1（调用方不应依赖它做判断）。
    """
    if not device_id or not user_id:
        return -1
    client = await _client_or_none()
    if client is None:
        return -1
    key = _key(device_id)
    try:
        await client.hdel(key, user_id)
        remaining = int(await client.hlen(key))
        if remaining <= 0:
            # 空了就把 key 一并删掉，不留一个空 hash 占着 Redis
            await client.delete(key)
        return remaining
    except Exception as exc:  # noqa: BLE001
        logger.warning("删除本机凭据失败（不影响本次登出）：%s", exc)
        return -1


async def forget_device(device_id: str) -> bool:
    """
    忘掉本设备上的**全部**账号（「清空记录」走这条）。

    Returns:
        True = 已清空（或本来就没有）；False = Redis 不可达，**没清掉**。
    """
    if not device_id:
        return True
    client = await _client_or_none()
    if client is None:
        return False
    try:
        await client.delete(_key(device_id))
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("清空本机凭据失败：%s", exc)
        return False
