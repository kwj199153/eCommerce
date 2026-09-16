"""
账号安全端点（P1-b，2026-09-16）

包含：邮箱验证 / 重发验证 / 忘记密码 / 重置密码 / 修改密码 /
      登出（真撤销）/ 登出所有设备

==============================================================================
★ 为什么另起一个文件，而不是塞进 core/identity/router.py
==============================================================================
`router.py` 负责的是**会话建立**（注册/登录/刷新/取当前用户）；
本文件负责**凭据生命周期**（验证邮箱、改密、撤销）。
两者的入参、失败语义、审计需求都不同（例如本文件大量使用一次性 token
与 Redis 黑名单，而 router.py 不碰）。混在一起会让 router.py 里
"哪些端点会写 token_version"这类问题变得难以回答。

==============================================================================
★★ 一处必须理解的设计取舍：忘记密码接口的"统一响应"
==============================================================================
`POST /auth/forgot-password` **无论邮箱是否存在，都返回同一句话**。
理由：若"存在的邮箱"回 200、"不存在的邮箱"回 404（或不同的 message），
本接口就变成了**邮箱枚举器** —— 攻击者拿一批邮箱跑一遍，就能筛出
哪些是本站用户，再对这些账号做定向爆破。

代价是：**发信失败时无法直接告诉用户**（一告诉他，就等于确认了该邮箱存在）。
⇒ 这里的处理是：响应保持统一，但服务端**用 ERROR 级别日志明确记录**
   「该邮箱确实存在，但邮件没发出去」，供告警与人工排查。
   这是在"不泄露账号存在性"和"不静默失败"两条规则冲突时，
   把"静默"限制在**用户可见层**、同时把它**升级到运维可见层**的做法。
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.auth.jwt_handler import create_token_pair, verify_token
# ★ P0-2（2026-09-16）：客户端 IP 提取去重（原先本文件自带一份拷贝）
from core.middleware.client_ip import client_ip
from core.auth.revocation import revoke_jti
from core.database import get_db
from core.identity.auth_models import EmailTokenPurpose
from core.identity.email_tokens import (
    consume_token,
    issue_token,
    send_reset_email,
    send_verify_email,
)
from core.identity.mailer import DisabledMailer, MailDisabled, MailSendFailed, get_mailer
from core.identity.models import User
from core.identity.router import (
    get_user_by_email,
    get_user_by_id,
    hash_password,
    user_to_dict,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["账号安全"])


# ====== 请求模型 ======

class TokenRequest(BaseModel):
    """只带一枚一次性 token 的请求"""
    token: str = Field(..., description="邮件里带的一次性 token")


class ForgotPasswordRequest(BaseModel):
    email: str = Field(..., description="注册邮箱")


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="邮件里带的一次性 token")
    new_password: str = Field(..., min_length=6, description="新密码（至少 6 位）")


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., description="当前密码")
    new_password: str = Field(..., min_length=6, description="新密码（至少 6 位）")


class LogoutRequest(BaseModel):
    """登出请求。

    ★ refresh_token 可选，但**强烈建议带上**：
      只撤销 access token 的话，那枚 refresh token 仍能在有效期内
      换出全新的 access token ⇒ "登出"被绕过。
      不带也能工作（只是撤销得没那么彻底），因此不设为必填 ——
      避免把老客户端的调用打挂。
    """
    refresh_token: Optional[str] = Field(None, description="同时撤销这枚 refresh token")


# ====== 辅助 ======

# 忘记密码的统一话术（存在/不存在、发信成/败，对外都是这一句）
_FORGOT_GENERIC_MESSAGE = (
    "如果该邮箱已注册，我们已发送一封重置密码的邮件，请在 30 分钟内按邮件提示操作"
)

_RESET_INVALID_DETAIL = "重置链接无效或已过期，请重新申请"


def _bump_token_version(user: User) -> int:
    """
    `token_version += 1` —— 让该用户**全部**已有 token 结构性失效。

    ★ 这是「改密后把该用户所有 token 加黑名单」的正确实现：
      无需知道有哪些 token 在飞，也不依赖 Redis（详见 core/auth/revocation.py）。
    """
    user.token_version = int(user.token_version or 1) + 1
    return user.token_version


async def _try_send(fn, *args) -> tuple[bool, str]:
    """
    发信并**如实回报结果**（不吞异常）。

    返回 (是否成功, 失败原因可读文本)。
    ★ 为什么返回而不是抛：调用点对失败的处理各不相同
      （verify/resend 可以直接告诉用户；forgot-password 不能，
       否则泄露账号存在性），所以把"怎么说"留给调用点。
    """
    try:
        await fn(*args)
        return True, ""
    except MailDisabled as exc:
        return False, str(exc)
    except MailSendFailed as exc:
        return False, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, f"发送邮件时发生未知错误：{exc}"


# ====== 邮箱验证 ======

@router.post("/verify-email", response_model=dict)
async def verify_email(
    payload: TokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    用邮件里的 token 完成邮箱验证（置 `is_verified = True`）。

    ★ 消费 token 与置位必须在**同一事务**：否则会出现
      「token 已被消费（一次性用掉了）但 is_verified 没置上」——
      此时用户手里的链接已失效、状态却没变，只能重新申请，无处申辩。
      本函数中两者之间没有任何 await 之外的失败点，且由 get_db 统一 commit。
    """
    user_id = await consume_token(db, payload.token, EmailTokenPurpose.VERIFY_EMAIL)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="验证链接无效或已过期，请重新获取",
        )

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="用户不存在")

    user.is_verified = True
    user.updated_at = datetime.utcnow()
    await db.flush()

    return {"message": "邮箱验证成功", "user": user_to_dict(user)}


@router.post("/verify-email/resend", response_model=dict)
async def resend_verify_email(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    重新发送验证邮件（需登录）。

    ★ 已认证的接口可以如实回报结果：这里知道"你是谁"，不存在枚举问题。
      发信失败时明确回 `email_sent: false` + 原因，**不谎报成功**。
      接口本身仍返回 200 —— 因为"用户已登录"这件事成功了，
      失败的是邮件；用 5xx 会让前端误以为会话出了问题。
    """
    if current_user.is_verified:
        return {"message": "邮箱已验证，无需重复发送", "email_sent": False, "email_sent_already": True}

    raw = await issue_token(db, current_user.id, EmailTokenPurpose.VERIFY_EMAIL)
    ok, err = await _try_send(send_verify_email, current_user.email, raw)

    if not ok:
        logger.error(
            "验证邮件发送失败 user=%s email=%s 原因=%s",
            current_user.id, current_user.email, err,
        )
    return {
        "message": "验证邮件已发送" if ok else f"验证邮件发送失败：{err}",
        "email_sent": ok,
    }


# ====== 忘记密码 / 重置密码 ======

@router.post("/forgot-password", response_model=dict)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    申请密码重置邮件。

    ★ **无论邮箱是否存在，响应完全一致**（见模块 docstring 的取舍说明）。
    ★ provider=disabled 时回 503：这是**全局配置状态**，与具体邮箱无关，
      因此不构成枚举通道 —— 而且必须让用户知道"这个功能现在不可用"，
      否则他会一直等一封永远不会来的信。
    """
    mailer = get_mailer()
    if isinstance(mailer, DisabledMailer):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="邮件服务未启用，暂时无法找回密码，请联系管理员",
        )

    email = (payload.email or "").strip().lower()
    user = await get_user_by_email(db, email)

    if user and user.is_active:
        raw = await issue_token(
            db, user.id, EmailTokenPurpose.RESET_PASSWORD, requested_ip=client_ip(request)
        )
        ok, err = await _try_send(send_reset_email, user.email, raw)
        if not ok:
            # ★ 对用户保持统一话术；但对运维必须响亮（否则这封信永远不到、
            #   用户永远等，而系统里查不出任何痕迹）
            logger.error(
                "重置密码邮件发送失败（用户确实存在，但信没发出去）"
                " user=%s email=%s 原因=%s",
                user.id, user.email, err,
            )
    else:
        # 邮箱不存在（或已禁用）：不建 token、不发信，但**响应与成功时一致**。
        # 这里刻意不写审计表 —— forgot-password 不是登录，混进 login_attempts
        # 会污染"爆破"这条信号。
        logger.info("忘记密码请求：邮箱不存在或已禁用，按统一话术响应")

    return {"message": _FORGOT_GENERIC_MESSAGE}


@router.post("/reset-password", response_model=dict)
async def reset_password(
    payload: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    凭邮件里的 token 重置密码。

    ★ 成功后必须做三件事（缺一件都留下后门）：
      ① 换口令哈希
      ② `token_version += 1` ⇒ **全部旧 token 失效**（含攻击者已窃取的那些）
      ③ 清掉失败计数与锁定 ⇒ 用户拿到新密码后能立刻用
          （否则若账号正被爆破锁定中，改完密码仍登不上，而原因完全不可见）
    ★ 不在这里自动登录/发新 token：重置密码往往是"账号可能已失窃"的场景，
      让用户用新密码主动登一次，是更清晰的边界。
    """
    user_id = await consume_token(db, payload.token, EmailTokenPurpose.RESET_PASSWORD)
    if not user_id:
        # 无效 / 过期 / 已用过，三者统一话术（不帮攻击者做区分）
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=_RESET_INVALID_DETAIL
        )

    user = await get_user_by_id(db, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_RESET_INVALID_DETAIL)

    user.hashed_password = hash_password(payload.new_password)
    _bump_token_version(user)
    user.failed_login_count = 0
    user.locked_until = None
    user.updated_at = datetime.utcnow()
    await db.flush()

    logger.info("密码已重置 user=%s（全部旧 token 因 token_version 提升而失效）", user.id)
    return {"message": "密码已重置，请用新密码登录"}


# ====== 修改密码 ======

@router.post("/change-password", response_model=dict)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    登录状态下修改密码。

    ★ 必须校验 current_password：本接口是"我在已登录状态下改密"，
      若不校验，一枚被盗的 access token 就能把主人锁在门外
      （改掉密码 → 真主人再也进不来）。

    ★ 改完**返回一对新 token**：
      token_version 提升会让**当前这枚**token 也失效，
      若只返回"成功"，用户立刻掉线、得重新登录 —— 体验差且容易被当成 bug。
      返回新 token 后：当前设备无感续用，其他设备全部下线。
    """
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码不正确",
        )

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="新密码不能与当前密码相同",
        )

    current_user.hashed_password = hash_password(payload.new_password)
    tv = _bump_token_version(current_user)
    current_user.updated_at = datetime.utcnow()
    await db.flush()

    tokens = create_token_pair(
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role.value,
        token_version=tv,
    )
    logger.info("密码已修改 user=%s（其他设备全部下线，当前设备换发新 token）", current_user.id)
    return {
        "message": "密码修改成功，其他设备的登录已失效",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
    }


# ====== 登出 ======

@router.post("/logout", response_model=dict)
async def logout(
    payload: Optional[LogoutRequest] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """
    登出：把当前这枚 token（及其 refresh token）加入撤销名单。

    ★★★ 为什么必须回 503 而不是"登出成功"：
      本接口**声称**做了一件有安全后果的事（撤销凭据）。做不到却说成功，
      用户会以为自己已经安全退出（例如在公共电脑上），而 token 其实还能用。
      **静默的假成功，比明确的失败危险得多。**
      ⇒ Redis 不可达 / token 无 jti / 写失败，一律 503 + 原因。
      ⇒ 同时提供不依赖 Redis 的 `/auth/logout-all` 作为兜底出路。

    ★ 为什么用 auth0 `Authorization` 头取 token 而不是形参：
      从请求头取到原始 JWT 才能拿到它的 jti；解出 jti 需要重新 verify，
      所以这里显式做一次（`require_auth_if_enabled` 已经验过一次，
      多解一次是为了拿 jti，不是重复鉴权）。
    """
    auth_header = (request.headers.get("Authorization") if request else "") or ""
    _, _, raw_access = auth_header.partition(" ")
    raw_access = raw_access.strip()

    data = verify_token(raw_access, expected_type="access") if raw_access else None
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无法识别当前凭据，请重新登录",
        )

    targets = [(data.jti, data.exp)]
    if payload and payload.refresh_token:
        rd = verify_token(payload.refresh_token, expected_type="refresh")
        # ★ 只撤销**属于当前用户**的那枚 refresh token（`rd.user_id` 比对）。
        #   否则任何一枚签名有效的 refresh token（例如别人的）都能被塞进来
        #   写进黑名单 —— 虽然攻击者得先拿到它才有意义，但"登出我的设备"
        #   这个动作不该有跨账号的副作用，多一行比对把语义收干净。
        #   user_id 不匹配时**静默跳过**：这是客户端传错了东西，
        #   而登出本身已经成功了，为此回 4xx 只会让用户以为没登出。
        if rd is not None and rd.user_id == current_user.id:
            targets.append((rd.jti, rd.exp))

    for jti, exp in targets:
        try:
            await revoke_jti(jti, exp)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"登出未生效：{exc}",
            ) from exc

    return {"message": "已登出", "revoked": len(targets)}


@router.post("/logout-all", response_model=dict)
async def logout_all(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    登出所有设备（走 `token_version`，**不依赖 Redis**）。

    ★ 存在的意义不是"功能更全"，而是**给用户一条永远可用的出路**：
      当 Redis 故障导致 `/auth/logout` 返回 503 时，用户需要一个
      "我就是要把所有登录都踢掉"的手段。走 DB 的版本号在 Redis 全挂时依然生效。
    """
    tv = _bump_token_version(current_user)
    current_user.updated_at = datetime.utcnow()
    await db.flush()
    logger.info("用户 %s 已登出所有设备（token_version -> %s）", current_user.id, tv)
    return {"message": "已登出所有设备，请重新登录", "token_version": tv}
