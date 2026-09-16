"""
认证 API 路由

提供用户注册、登录、Token 刷新等接口。
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Request, status, Depends
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import config
from core.database import get_db
from core.auth.dependencies import get_current_user
from core.auth.jwt_handler import (
    create_token_pair,
    verify_token,
    verify_refresh_token,
    decode_expired_token,
    TokenPair,
)
from core.auth.revocation import is_jti_revoked, token_version_matches
from core.identity import login_guard
from core.identity.models import User, UserRole, merge_notification_prefs
# ★ P0-2（2026-09-16）：客户端 IP 提取去重（原先本文件自带一份拷贝）
from core.middleware.client_ip import client_ip


router = APIRouter(prefix="/auth", tags=["认证"])


# ====== 请求/响应 Schema ======

class UserRegisterRequest(BaseModel):
    """注册请求（JSON body）"""
    email: str = Field(..., description="邮箱地址（唯一）")
    password: str = Field(..., min_length=6, description="密码（至少 6 位）")
    name: str | None = Field(None, description="用户名（可选）")


class UserLoginResponse:
    """登录响应"""
    def __init__(
        self,
        access_token: str,
        refresh_token: str,
        token_type: str,
        user: dict,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.token_type = token_type
        self.user = user


class RefreshTokenRequest(BaseModel):
    """
    刷新 Token 请求（**JSON body**）

    ★ 从「裸标量形参」改成 Pydantic 模型的理由（P0 修复 2026-09-16）：
      FastAPI 对**没有默认值的标量形参**（`refresh_token: str`）默认按 **query**
      解析。而前端 `user.ts` 发的是 `post('/auth/refresh', { refresh_token })`
      ——JSON body ⇒ 服务端永远读不到 ⟹ 稳定 422
      （日志实证：`POST /api/v1/auth/refresh -> 422` 与 200 成对出现）。
      前端拦截器于是判定"刷新失败"→ `logout()` + 跳登录页：
      **access token 一到期就被踢回登录页，「自动刷新」从未生效过。**
      改成模型后按 body 解析，与前端既有调用对齐（**前端无需改动**），
      同时也让 token 不再出现在 query string 里（Nginx access log / 浏览器
      历史 / Referer 都会留痕）。
    """
    refresh_token: str = Field(..., description="Refresh Token")


class UserInfoResponse:
    """用户信息响应"""
    def __init__(self, user: dict):
        self.user = user


# ====== 辅助函数 ======

async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    """根据邮箱查询用户"""
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """根据 ID 查询用户"""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


def _password_bytes(password: str) -> bytes:
    """
    把密码编码为 bcrypt 可接受的字节串

    bcrypt 算法本身只取前 72 字节，且 bcrypt>=4.1 遇到超长输入会直接抛
    ValueError（不再静默截断）。这里显式截断，保证 hash 与 verify 行为一致。
    """
    return password.encode("utf-8")[:72]


def hash_password(password: str) -> str:
    """
    密码哈希（直接使用 bcrypt）

    说明：原先走 passlib.CryptContext，但 passlib 1.7.4（2020 年后未更新）
    读取已被 bcrypt>=4.1 移除的 `bcrypt.__about__.__version__`，导致
    注册/登录直接 500。此处改为直接调用 bcrypt，去掉对 passlib 的依赖。
    生成的哈希仍是标准 bcrypt 格式（$2b$...），与历史数据兼容。
    """
    import bcrypt

    # ★ 轮数走配置（默认 12）。测试里由 tests/conftest.py 覆写成 4：
    #   rounds=12 时单次 hash ≈209ms，而每条走 `user` 夹具的用例都要
    #   register+login 一次 ⇒ 每例白花 ≈416ms；全量 25 项合计 ≈10.4s。
    #   口令强度应当由**部署**决定，不该由**测试时长**决定 ——
    #   所以只调测试进程里的值，默认值一动不动。
    # ★ 必须**调用时**读取（不能在 import 期固化成常量），
    #   否则 conftest 的覆写不生效、测试看起来「没变快」却查不出原因。
    rounds = int(getattr(config, "password_hash_rounds", 12) or 12)
    return bcrypt.hashpw(
        _password_bytes(password), bcrypt.gensalt(rounds=rounds)
    ).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码（直接使用 bcrypt，兼容历史 passlib 生成的哈希）"""
    import bcrypt

    try:
        return bcrypt.checkpw(
            _password_bytes(plain_password),
            hashed_password.encode("utf-8"),
        )
    except (ValueError, TypeError):
        # 哈希格式非法（脏数据）时按验证失败处理，不抛 500
        return False


def user_to_dict(user: User) -> dict:
    """
    将 User 对象转换为字典（不包含敏感信息）。

    ★ 本函数是 `/auth/me`、`/auth/login`、`/auth/register` **共用的唯一序列化点**
      ⇒ 新增字段只改这一处，三个入口一起生效（否则典型症状是
      "改完资料、刷新页面又变回去了"：写进去了，但读的入口没带上）。
    """
    return {
        "id": user.id,
        "email": user.email,
        "name": user.name,
        "role": user.role.value if user.role else "user",
        "is_active": user.is_active,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        # ★ 第 100 轮：自助管理资料（Settings 页要显示/回填）
        "phone": user.phone,
        "company": user.company,
        "avatar_url": user.avatar_url,
        # 补齐后的完整偏好对象（绝不返回 None —— 前端拿到 None 就没法判断
        # 是"没设置过"还是"后端出问题了"）
        "notification_prefs": merge_notification_prefs(user.notification_prefs),
    }


# ====== API 端点 ======

@router.post("/register", response_model=dict, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    用户注册

    - **email**: 邮箱地址（唯一）
    - **password**: 密码（至少 6 位）
    - **name**: 用户名（可选）
    """
    email = payload.email
    password = payload.password
    name = payload.name

    # 1. 检查邮箱是否已存在
    existing_user = await get_user_by_email(db, email)
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该邮箱已被注册",
        )

    # 2. 验证密码强度
    if len(password) < 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="密码长度不能少于 6 位",
        )

    # 3. 创建用户
    import uuid
    new_user = User(
        id=str(uuid.uuid4()),
        email=email.lower().strip(),
        hashed_password=hash_password(password),
        name=name or email.split("@")[0],
        role=UserRole.USER,
        is_active=True,
        is_verified=False,  # 需要后续邮件验证
    )

    db.add(new_user)

    # 4. 创建默认订阅（免费版）
    from modules.billing.models import Subscription
    default_subscription = Subscription(
        id=str(uuid.uuid4()),
        user_id=new_user.id,
        plan_id=1,  # free plan id
        status="active",
        current_period_start=datetime.utcnow(),
    )
    db.add(default_subscription)

    await db.commit()
    await db.refresh(new_user)

    # 5. 发送验证邮件（★ P1-b 2026-09-16）
    #
    #   ★ 发信失败**不阻断注册**：用户已经建好了（200/201 语义是"注册成功"），
    #     把注册回滚掉只因为他一时收不到信，是过度反应。
    #   ★ 但必须在响应里**如实说出** `email_sent` 与原因 —— 否则用户会以为
    #     "验证邮件已发出"而一直等；这正是本项目最忌讳的"假成功"。
    #     登录后还有 `/auth/verify-email/resend` 可以重发。
    email_sent, email_error = False, ""
    try:
        from core.identity.auth_models import EmailTokenPurpose
        from core.identity.email_tokens import issue_token, send_verify_email

        raw = await issue_token(db, new_user.id, EmailTokenPurpose.VERIFY_EMAIL)
        await db.commit()
        await send_verify_email(new_user.email, raw)
        email_sent = True
    except Exception as exc:  # noqa: BLE001
        email_error = str(exc)
        from core.logger import get_logger as _get_logger

        _get_logger("core.identity.router").warning(
            "注册成功但验证邮件未发出 user=%s email=%s 原因=%s",
            new_user.id, new_user.email, email_error,
        )

    # 6. 生成 Token
    tokens = create_token_pair(
        user_id=new_user.id,
        email=new_user.email,
        role=new_user.role.value,
        token_version=new_user.token_version,
    )

    return {
        "message": "注册成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
        "user": user_to_dict(new_user),
        # ★ 如实回报邮件结果。`email_verification_required=false` 时它只是信息；
        #   为 true 时它决定了用户能不能登录，前端据此提示"点这里重发"。
        "email_sent": email_sent,
        "email_error": email_error,
    }


@router.post("/login", response_model=dict)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    request: Request = None,
):
    """
    用户登录（OAuth2 Password 模式）

    - **username**: 邮箱地址
    - **password**: 密码

    ★★★ P1-b（2026-09-16）四道判定，**顺序不可调换**：

      ① **锁定检查** —— 必须在密码校验**之前**。
         若"密码对了就放行"，攻击者只要持续猜，猜对的那一次就直接进，
         锁定窗口对攻击者零成本。
      ② **密码校验** —— 邮箱不存在与密码错误用**同一句话术**，
         否则本接口成了邮箱枚举器（详见 login_guard.py 的说明）。
      ③ **账号状态**（is_active）
      ④ **邮箱验证**（仅当 EMAIL_VERIFICATION_REQUIRED=true）

      ★ 每一次尝试（成功与失败都算）都落一条 `login_attempts` 审计；
        "当前错了几次"则记在 `users.failed_login_count`（判定用，见 login_guard）。

    ⚠️ 一处**有意的轻微存在性泄露**（记录在案，不是疏漏）：
      锁定期内返回 429 并说明"账号已锁定"，而不存在的邮箱永远不会走到这个分支
      ⇒ 攻击者理论上可据此判断邮箱是否存在。代价是他必须先对同一邮箱失败
      N 次（且受 IP 限流约束），收益远低于成本；而收益是**合法用户**在
      输对密码却进不去时能得到一句可读的原因（否则他只会看到"密码错误"，
      从而去重置密码、把锁定当成 bug）。
    """
    email = (form_data.username or "").strip().lower()
    ip = client_ip(request)
    user_agent = request.headers.get("User-Agent") if request else None

    # 1. 查找用户
    user = await get_user_by_email(db, email)

    # 2. 锁定检查（★ 先于密码校验）
    if user is not None:
        remaining = await login_guard.check_lockout(db, user)
        if remaining is not None:
            await login_guard.record_attempt(
                db, email=email, user=user, success=False,
                reason=login_guard.REASON_LOCKED, ip=ip, user_agent=user_agent,
            )
            await db.commit()
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"账号因连续登录失败已被暂时锁定，请 {remaining} 秒后重试"
                    "（也可通过「忘记密码」重置以立即解锁）"
                ),
                headers={"Retry-After": str(remaining)},
            )

    # 3. 验证密码（不存在 / 密码错 → 同一话术）
    if user is None or not verify_password(form_data.password, user.hashed_password):
        locked_until = await login_guard.register_failure(db, user)
        await login_guard.record_attempt(
            db, email=email, user=user, success=False,
            reason=login_guard.REASON_BAD_PASSWORD if user else login_guard.REASON_UNKNOWN_EMAIL,
            ip=ip, user_agent=user_agent,
        )
        await db.commit()
        if locked_until is not None:
            # 刚刚触发锁定：明确说出来，否则用户下一次尝试会看到 429 却不知道为什么
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"连续登录失败 {config.login_max_failures} 次，账号已锁定 "
                    f"{config.login_lockout_minutes} 分钟"
                ),
                headers={"Retry-After": str(config.login_lockout_minutes * 60)},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="邮箱或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 4. 检查账号状态
    if not user.is_active:
        await login_guard.record_attempt(
            db, email=email, user=user, success=False,
            reason=login_guard.REASON_INACTIVE, ip=ip, user_agent=user_agent,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用，请联系管理员",
        )

    # 5. 邮箱验证（★ P1-b：仅在显式开启时生效，默认关闭 ⇒ 不影响既有行为）
    if config.email_verification_required and not user.is_verified:
        await login_guard.record_attempt(
            db, email=email, user=user, success=False,
            reason=login_guard.REASON_UNVERIFIED, ip=ip, user_agent=user_agent,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="邮箱尚未验证。请查收验证邮件，或调用 /auth/verify-email/resend 重新发送",
        )

    # 6. 登录成功：清计数、清锁定、更新最后登录时间 + 审计
    await login_guard.register_success(db, user)
    await login_guard.record_attempt(
        db, email=email, user=user, success=True,
        reason=login_guard.REASON_OK, ip=ip, user_agent=user_agent,
    )
    await db.commit()

    # 7. 生成 Token（带凭据版本，供改密后整批失效）
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        token_version=user.token_version,
    )

    return {
        "message": "登录成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
        "user": user_to_dict(user),
    }


@router.post("/refresh", response_model=dict)
async def refresh_token(
    payload: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    刷新 Access Token

    请求体：`{"refresh_token": "..."}`

    ★★ 两处 P0 修复（2026-09-16），都是"门禁写着但没在执行"：

    1. **过期时间必须真的校验**。修复前这里用 `decode_expired_token()` 放行，
       而它内部是 `options={"verify_exp": False}` ⇒ 过期这一项从未被检查；
       实测"过期 30 天"的 refresh token 仍返回 **200** 并换回全新的
       access + refresh 对，`jwt_refresh_token_expire_days=7` 沦为装饰性配置
       （且每次刷新都续期 = 永久会话）。现在改用 `verify_refresh_token()`
       （签名 + 类型 + exp 三项全过）。
    2. **入参从 query 改到 body**，修好前端一直失效的自动刷新 —— 详见
       `RefreshTokenRequest` 的 docstring。

    ★ 两个失败原因分开报（"已过期" vs "无效"）只为给用户一句可读的话，
      拒绝本身不打折；只有在签名有效的前提下才会被判成"已过期"。

    ★★★ P1-b 补的第 3 项（2026-09-16）：**撤销校验**。
      refresh token 里带了 `tv` 与 `jti`，但本端点此前既不比对 `tv`、也不查
      jti 黑名单 ⇒「改密后所有 token 失效」与「登出」在这条路上都是假的
      （详见第 2.5 步的注释）。现与 `get_current_user` 用同一套两道门。
    """
    # 1. 校验签名 + 类型 + **过期时间**
    token_data = verify_refresh_token(payload.refresh_token)
    if token_data is None:
        stale = decode_expired_token(payload.refresh_token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Refresh Token 已过期，请重新登录"
                if stale and stale.get("type") == "refresh"
                else "无效的 Refresh Token"
            ),
        )

    # 2. 提取用户 ID 并查找用户
    user_id = token_data.user_id
    user = await get_user_by_id(db, user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已被禁用",
        )

    # 2.5 撤销校验（★ P1-b 补齐 2026-09-16）—— 与 `get_current_user` 同一套两道门
    #
    # ★★★ 为什么必须有这一步（此前是真漏洞，两端都"写着但没在执行"）：
    #
    #   `refresh token` 里**带了** `tv` 声明（见 jwt_handler.create_refresh_token
    #   的注释："否则改密让 token 失效会留下一个绕过的口子"），也**带了** jti；
    #   但本端点从来没有比对过 `tv`、也从不查 jti 黑名单。后果是两条都断：
    #
    #     · 改密 / 重置密码后，旧 refresh token 仍能换出**全新**的 access token
    #       —— 而且新 token 带的是库里**当前**的 tv（第 3 步的写法本身就"很对"），
    #       于是换出来的凭据完全合法 ⇒「改密让所有 token 失效」对 refresh
    #       这条路彻底无效，攻击者只要握着旧 refresh token 就永远进得来。
    #     · `/auth/logout`（带 refresh_token 时）把它的 jti 写进了 Redis 黑名单，
    #       但这里不查 ⇒ 那枚 refresh token 照样可用，「已登出」是假的。
    #
    #   两者是同一个形态：字段写进 token 了、黑名单写进 Redis 了，缺的只是
    #   **读取侧的比对**，而这条路径不会报任何错。
    #   判据：撤销的实现必须覆盖**所有**签发新凭据的入口，漏一个等于没有。
    if not token_version_matches(token_data.token_version, user.token_version):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="登录凭据已失效（密码已变更或已登出所有设备），请重新登录",
        )
    if await is_jti_revoked(token_data.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="该登录凭据已登出",
        )

    # 3. 生成新的 Token 对
    #
    # ★ P1-b：必须带上**库里当前的** token_version —— 而不是沿用请求里那枚
    #   refresh token 的 `tv`。用旧值会让攻击者拿一枚"改密前"的 refresh token
    #   换出 `tv=旧值` 的新 access token，于是撤消失效（而此处看起来一切正常）。
    #   第 2 步已经确认用户当前有效，这里以库为准是唯一的正确取值。
    tokens = create_token_pair(
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        token_version=user.token_version,
    )

    return {
        "message": "Token 刷新成功",
        "access_token": tokens.access_token,
        "refresh_token": tokens.refresh_token,
        "token_type": "bearer",
    }


@router.get("/me", response_model=dict)
async def get_current_user_info(
    current_user: User = Depends(get_current_user),
):
    """
    获取当前登录用户信息

    需要 Bearer Token 认证。
    返回结构复用 user_to_dict（与 login/register 的 user 字段一致）。
    """
    return user_to_dict(current_user)


# ====== 登出已迁走 ======
# `POST /auth/logout` 与 `POST /auth/logout-all` 现在住在
# `core/identity/security_router.py`。
#
# ★ 为什么搬走：它们要做**真撤销**（Redis jti 黑名单 / token_version 提升），
#   与"会话建立"（注册/登录/刷新）是两套完全不同的失败语义 ——
#   登出失败必须回 503 而不是静默成功（见该文件 docstring）。
#   放在一起会让 router.py 里"哪些端点会写 token_version"难以回答。
#
# ⚠️ 路径保持不变（`/auth/logout`），前端无需改动。
