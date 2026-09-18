"""
本机免密切换端点（第 119 轮，2026-09-17）

══════════════════════════════════════════════════════════════════════════════
为什么另起一个文件
══════════════════════════════════════════════════════════════════════════════
`core/identity/router.py`  = 会话建立（注册 / 登录 / 刷新 / 取当前用户）
`core/identity/security_router.py` = 凭据生命周期（验证邮箱 / 改密 / 撤销）
本文件 = **本机凭据托管**（记住 / 切换 / 忘记）

三者失败语义不同：本文件的多数端点在 Redis 不可达时**降级而不报错**
（读侧保可用），而 `security_router` 的登出必须报 503（写侧保诚实）。
混在一起会让"这个端点 Redis 挂了会怎样"难以回答。

══════════════════════════════════════════════════════════════════════════════
★★★ 鉴权档位的**刻意不对称**（这是本文件最需要理解的一点）
══════════════════════════════════════════════════════════════════════════════
| 端点 | 要求真身份 | 理由 |
|------|-----------|------|
| `POST /enroll`       | ✅ 必须 | 要知道"这枚 refresh token 属于谁"，且不能让别人替我记 |
| `GET  /accounts`     | ✅ 必须 | 未登录者不该能读到"这台机器记住了哪些账号" |
| `POST /forget`       | ✅ 必须 | 删除动作，必须知道执行者 |
| `POST /forget-all`   | ✅ 必须 | 同上 |
| `POST /switch`       | ❌ **不要求** | 见下 |

`switch` 不要求真身份，是因为它**正是在"当前身份已经不能用"时才需要**：
access token 过期且刷新失败、当前账号在别处被登出、凭据被撤销 ——
这些正是用户最需要切到另一个账号的时刻。若在这里要求真身份，
就会出现「想切账号，但必须先有一个能用的账号」这种死锁。

⇒ 它靠 **httpOnly Cookie 里的 `device_id`** 作为凭据。该值是
  `secrets.token_urlsafe(32)`（256 bit），且只在服务端容器里有对应记录。
  这与 `/auth/refresh` 拿 refresh token 作凭据是同一档语义。

══════════════════════════════════════════════════════════════════════════════
★★★ switch 是「签发新凭据的入口」，撤销两道门**必须复刻**
══════════════════════════════════════════════════════════════════════════════
项目已有判据：**撤销的实现必须覆盖所有签发新凭据的入口，漏一个等于没有。**

`/auth/refresh` 上有两道门（`tv` 比对 + `jti` 黑名单），
`/auth/device/switch` 同样会签发全新的 access + refresh 对
⇒ 少写一道，就等于在 `/auth/refresh` 旁边开了一个**绕过撤销的后门**
（改密后旧凭据仍能通过免密换出新 token）。故此处逐条复刻，
并由 `backend/tests/test_device_vault.py::test_switch_is_not_a_revocation_bypass` 钉住。

══════════════════════════════════════════════════════════════════════════════
Cookie 参数
══════════════════════════════════════════════════════════════════════════════
    name    = wb_device_id
    path    = /api/v1/auth        （收窄：业务接口不需要它）
    httpOnly= True                （★ JS 读不到 —— "本机不持有凭据"的落点）
    sameSite= lax                 （跨站 POST 不带 cookie ⇒ 足够防 CSRF）
    secure  = environment == "production"

★ 为什么 `secure` 要跟环境走而不是恒为 True：
  本地开发是 http://localhost，带 `Secure` 的 Cookie 会被浏览器**直接丢弃**，
  现象是"后端说 Set-Cookie 了、前端就是没有" —— 那种失败极难定位。
  生产（https）必须带，防止明文链路泄露。
★ 为什么 `sameSite=lax` 就够：本服务前后端同源（开发走 Vite proxy，
  生产走同一 Nginx）。跨站发起的 POST 不会带上 Lax Cookie ⇒ CSRF 不成立。
  若将来改成前后端**不同站**部署，需要改 `none` + `secure`，
  并补 CSRF token —— 那时拦不住的就是真漏洞了，别只改这一行。
"""

import logging
import re

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import device_vault
from core.auth.device_vault import (
    DEVICE_COOKIE_NAME,
    DEVICE_COOKIE_PATH,
    DeviceVaultRejected,
    DeviceVaultUnavailable,
)
from core.auth.dependencies import get_current_user
from core.auth.jwt_handler import create_token_pair, verify_refresh_token
from core.auth.revocation import is_jti_revoked, token_version_matches
from core.config import config
from core.database import get_db
from core.identity.models import User
from core.identity.router import get_user_by_id, user_to_dict
from core.security.credentials import CredentialsKeyMissing

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/device", tags=["本机免密"])

# `device_id` 的合法形态（`secrets.token_urlsafe(32)` 产出 ≈43 个 URL-safe 字符）。
#
# ★ 为什么要校验形态而不是照单全收：Cookie 是用户可随意编辑的。
#   一个含换行/超长的值会被拼进 Redis key —— Redis 本身不介意，
#   但日志、`redis-cli KEYS` 输出、以及"能不能拿它探 key 空间"都会变得难看。
#   形态校验把这一类噪音挡在门外，且不需要任何额外成本。
_DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")


class EnrollRequest(BaseModel):
    """把当前登录凭据记进本设备"""
    refresh_token: str = Field(..., description="登录/刷新拿到的 refresh token")


class SwitchRequest(BaseModel):
    """切到本设备记住的某个账号"""
    user_id: str = Field(..., description="目标账号的 user.id")


class ForgetRequest(BaseModel):
    """忘掉本设备上的某个账号"""
    user_id: str = Field(..., description="要忘掉的账号 user.id")


def _read_device_id(request: Request) -> str:
    """从 Cookie 读 `device_id`；形态不合法一律当没有（不抛错）。"""
    raw = ""
    try:
        raw = request.cookies.get(DEVICE_COOKIE_NAME) or ""
    except Exception:  # noqa: BLE001 — 无 Cookie 支持的测试客户端
        return ""
    return raw if _DEVICE_ID_RE.fullmatch(raw) else ""


def _set_device_cookie(response: Response, device_id: str) -> None:
    """
    下发/续期设备 Cookie。

    ★ 每次 enroll / switch 都重设一遍，顺带把 `max_age` 续上 ——
      否则容器（Redis）续期了、Cookie 却先过期，表现是
      "免密凭据还在服务端，但浏览器不再发 device_id" ⇒ 免密莫名失效。
    """
    response.set_cookie(
        key=DEVICE_COOKIE_NAME,
        value=device_id,
        max_age=device_vault.ttl_seconds(),
        path=DEVICE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=(config.environment == "production"),
    )


def _clear_device_cookie(response: Response) -> None:
    """清 Cookie。★ path 必须与下发时一致，否则浏览器不会删掉它。"""
    response.delete_cookie(
        key=DEVICE_COOKIE_NAME,
        path=DEVICE_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=(config.environment == "production"),
    )


def _key_missing_detail(exc: Exception) -> str:
    """
    密钥未配置时的对外文案。

    ★ 不直接透传 `CredentialsKeyMissing` 的原文：那句话是写给
      "店铺平台凭证" 场景的（"已拒绝写入平台凭证"），用在这里会让用户
      和运维都找错方向。但**必须保留"是哪一个环境变量"** ——
      否则运维拿到一句"加密不可用"无从下手。
    """
    return (
        "本机免密暂不可用：服务端未配置加密密钥，已拒绝写入任何凭据"
        "（本项目不允许把登录凭据明文落盘）。"
        "请配置 SHOP_CREDENTIALS_ENCRYPTION_KEY 后重新登录一次。"
        f"（原因：{exc}）"
    )


@router.post("/enroll", response_model=dict)
async def enroll(
    payload: EnrollRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """
    把当前账号的 refresh token 交给服务端托管，供本机下次免密切换。

    ★ 与登录**解耦**：本端点是独立的一次调用，失败**不影响登录结果**。
      登录接口不该因为 Redis 抖动或密钥没配就 503 —— 那会把
      "免密不可用"放大成"整个系统登不进去"。所以由前端在登录成功后
      额外调一次本端点，失败只降级为"这次没记住"。

    ★ 归属校验在 `device_vault.remember` 里做（唯一实现），本端点不做第二遍。

    Returns:
        `{"ok": true, "accounts": [...], "total": n}`
        —— `accounts` 是**这台设备当前记住的全部 user_id**，
        前端据此渲染「免密」标记（不需要再发一次 `GET /accounts`）。
    """
    device_id = _read_device_id(request)
    if not device_id:
        # ★ 首次 enroll（或 Cookie 被清）⇒ 新建一枚。
        #   注意只在**本机还没有身份时**新建：只要它存在就绝不替换，
        #   否则每次 enroll 都换 id，等于把之前记住的账号全部甩掉。
        device_id = device_vault.new_device_id()

    try:
        await device_vault.remember(device_id, current_user.id, payload.refresh_token)
    except DeviceVaultRejected as exc:
        # 入参问题（凭据无效/不属于该账号）—— 4xx，且**不**下发 Cookie：
        # 若这里也下发，就等于用一个非法请求给浏览器种了个空设备。
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except CredentialsKeyMissing as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=_key_missing_detail(exc),
        )
    except DeviceVaultUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        )

    _set_device_cookie(response, device_id)
    ids = await device_vault.list_user_ids(device_id)
    return {"ok": True, "accounts": ids, "total": len(ids)}


@router.get("/accounts", response_model=dict)
async def list_remembered_accounts(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """
    本设备记住了哪些账号（**只有 user_id，没有任何凭据**）。

    ★ 需要真身份：未登录者不该能读到"这台机器上有哪些账号"。
      这不是凭据泄露，但仍属账号信息，没有必要对外开放。

    ★ Redis 不可达时返回空列表而不是报错：见 `device_vault.list_user_ids`。
      空列表的后果只是「界面上不显示免密标记」，用户走输密码路径即可。
    """
    device_id = _read_device_id(request)
    ids = await device_vault.list_user_ids(device_id) if device_id else []
    return {"accounts": ids, "total": len(ids)}


@router.post("/switch", response_model=dict)
async def switch_account(
    payload: SwitchRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """
    切换到本设备记住的某个账号 —— **免密**。

    ★ 不要求真身份（理由见模块 docstring 的鉴权档位表）。

    ★★★ 撤销两道门（`tv` 比对 + `jti` 黑名单）必须与 `/auth/refresh` 一致。
      本端点是"签发新凭据的入口"，漏掉任何一道都等于绕过撤销。

    ★ 失败一律是 401 + 可读文案，并**顺手忘掉**这个坏凭据：
      否则前端会一直显示「免密」标记，而每次点都是 401 ——
      用户看到的是"这个按钮坏了"，而不是"需要重新输一次密码"。

    Returns:
        `{message, access_token, refresh_token, token_type, user, remembered}`
        `remembered=False` 表示"切换成功了，但新凭据没能记进本机"，
        下次切换还需要输密码 —— 这必须让前端知道（见下）。
    """
    device_id = _read_device_id(request)
    if not device_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="本机没有记住任何登录状态，请输入密码登录",
        )

    token = await device_vault.recall(device_id, payload.user_id)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="本机未记住该账号的登录状态（或它已过期），请输入密码登录",
        )

    # ---- 第 1 道：签名 + 类型 + **过期时间**（verify_refresh_token 三项全过）----
    data = verify_refresh_token(token)
    if data is None:
        await device_vault.forget(device_id, payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该登录凭据已过期，请输入密码登录",
        )

    # ---- 第 2 道：用户仍然存在且启用 ----
    user = await get_user_by_id(db, data.user_id)
    if not user or not user.is_active:
        await device_vault.forget(device_id, payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="账号不存在或已被禁用",
        )

    # ---- 第 3 道：整批撤销（改密 / 重置密码 / 登出所有设备）----
    if not token_version_matches(data.token_version, user.token_version):
        await device_vault.forget(device_id, payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭据已失效（密码已变更或已登出所有设备），请重新登录",
        )

    # ---- 第 4 道：单枚撤销（jti 黑名单）----
    if await is_jti_revoked(data.jti):
        await device_vault.forget(device_id, payload.user_id)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该登录凭据已登出",
        )

    # ---- 签发：token_version 取**库里当前的值**（不是请求里那枚的 tv）----
    # ★ 与 `/auth/refresh` 同一条理由：用旧值会让"改密前"的凭据换出 tv=旧值 的
    #   access token，于是撤销看起来正常、实际失效。
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        token_version=user.token_version,
    )

    # ---- 回写：/auth/refresh 会签发**新的一枚** refresh token，容器必须跟着更新 ----
    #
    # ★ 这里失败**不能让整个切换失败** —— 用户已经拿到可用的 token 对了，
    #   主目标已达成；回写只是"给下次省一步"。
    #   但也不能静默：用 `remembered` 字段把事实告诉前端。
    #   （写侧保诚实 ≠ 写侧必须抛错；判据是"不许假装成功"。）
    remembered = True
    try:
        await device_vault.remember(device_id, user.id, tokens.refresh_token)
    except (DeviceVaultRejected, DeviceVaultUnavailable, CredentialsKeyMissing) as exc:
        remembered = False
        logger.warning(
            "免密已切换成功，但新凭据未能记入本机（下次切换需输密码）：%s", exc
        )

    _set_device_cookie(response, device_id)
    return {
        "message": "已切换",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
        "user": user_to_dict(user),
        "remembered": remembered,
    }


@router.post("/forget", response_model=dict)
async def forget_account(
    payload: ForgetRequest,
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """
    忘掉本设备上的**某一个**账号（退出登录 / 从列表移除时调用）。

    ★ 语义边界（必须与 `/forget-all` 分清）：
      · 本端点 = 「退出这个账号」⇒ 只删它自己，其他账号的免密不受影响。
        `security_router.logout` 的语义也是"只撤销本账号"，两者对齐。
      · 清空整台机器归 `forget-all`。

    ★ 不做归属校验：任何登录用户都可以让自己这台机器忘掉某个账号。
      这不是越权 —— 效果仅限于"本机下次要多输一次密码"，
      且他本来就能用 `switch` 以那个账号身份进来。
    """
    device_id = _read_device_id(request)
    if device_id:
        await device_vault.forget(device_id, payload.user_id)
        remaining = await device_vault.list_user_ids(device_id)
        if not remaining:
            # 本机已经没有记住任何账号 ⇒ Cookie 也一并清掉，不留无用句柄
            _clear_device_cookie(response)
        return {"ok": True, "accounts": remaining, "total": len(remaining)}
    return {"ok": True, "accounts": [], "total": 0}


@router.post("/forget-all", response_model=dict)
async def forget_device(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
):
    """
    清空本设备记住的**全部**账号（「清空记录」走这条）。

    ★ 与前端 `knownAccounts.clearKnown()` 成对：那边清账号标识，这边清凭据。
      两边都清才叫"清空记录"；只清一边会留下"列表空了但服务端还记着"，
      或"列表还在但点了要输密码"的错位。

    ★ Redis 不可达 ⇒ `forget_device` 返回 False ⇒ **回 503**。
      这是"声称做了一件事"的接口：假装清空而实际没清，
      用户会以为凭据已经没了（可能因此把电脑借给别人），
      而服务端还留着 —— 属静默的假成功。
    """
    device_id = _read_device_id(request)
    if not device_id:
        _clear_device_cookie(response)
        return {"ok": True, "accounts": [], "total": 0}

    cleared = await device_vault.forget_device(device_id)
    if not cleared:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="清空本机登录状态失败（存储后端不可达），请稍后重试",
        )
    _clear_device_cookie(response)
    return {"ok": True, "accounts": [], "total": 0}
