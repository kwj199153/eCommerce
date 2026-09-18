"""用户自助管理 API：个人资料 / 头像 / API 密钥 / 通知偏好

==============================================================================
★ 本模块补的是什么洞
==============================================================================
`frontend/src/views/Settings.vue` 一直在请求 7 个 `/users/*` 路径，
而后端**从来没有 `/users` 路由** —— 运行时枚举 `app.routes`（212 条）实测
`/users` 命中数 = **0**。后果是用户点「保存资料」「上传头像」
「创建 API 密钥」「保存通知偏好」**一律 404**（`core/database.py` 里那行
`@app.get("/users")` 只是 docstring 示例，grep 会把它误判成"端点存在"）。

==============================================================================
★★ 为什么这些响应**不带 `message` 字段**
==============================================================================
本项目前端拦截器有一条：`if (data?.message && method !== 'get') message.success(...)`
—— 会自动弹一次后端给的 `message`。而 `Settings.vue` 在这些操作里**自己也弹**。

两边都弹 ⇒ 用户看到两条一样的提示。所以约定：

    「谁负责提示」只能有一边。本模块的调用方（Settings.vue）已自带提示 ⇒
    本模块**一律不返回 `message`**，只返回数据。

★ 后来人别"顺手补个 message" —— 那会让这四个操作各弹两次。

==============================================================================
★★ 两条安全判据
==============================================================================
1. **API 密钥只存 sha256 哈希**（同 `EmailToken` 的判据）：
   key 是「持有即有权」的凭据，库里留原文 = 拖库即沦陷。
   ⇒ 完整明文**只在创建响应里出现这一次**；列表返回的是后端生成的掩码串。
   ★ 掩码逻辑放在**后端**（而不是让前端截字符串）：
     库里只有哈希，后端才知道怎么给出稳定、可比对的前缀/后缀。

2. **越权一律 404，不是 403**：
   403 等于告诉对方「这个 id 存在、只是不属于你」—— 那是资源枚举的信标。
   本项目统一口径：越权返回 404。

==============================================================================
★ 本批**没有**做的事（别误以为已经能用）
==============================================================================
本模块只做 API 密钥的**管理面**（增 / 查 / 删）。
「用一枚 API key 去调用业务接口」的**鉴权面尚未接入**
（`get_current_user` 目前只认 JWT）。
⇒ 现在创建的密钥**还不能真的用来调用接口**，`last_used_at` 会一直是空。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import get_current_user
from core.database import get_db
from core.identity.auth_models import UserApiKey
from core.identity.models import User, merge_notification_prefs
from core.identity.router import user_to_dict
from core.storage.paths import IMAGE_EXT, STATIC_PREFIX, upload_root


router = APIRouter(prefix="/users", tags=["用户自助"])


# ====== 常量 ======

#: 头像大小上限（与全局 `MAX_UPLOAD_SIZE_MB` 解耦：头像不该有 10MB 的体量）
_AVATAR_MAX_BYTES = 2 * 1024 * 1024

# ★ 通知偏好的**默认值真源与合并逻辑**放在 `core/identity/models.py`：
#   `core/identity/router.py::user_to_dict()` 也要用同一份 —— 若定义在本模块，
#   就会与「本模块 import user_to_dict」构成**循环 import**。
#   调用 `merge_notification_prefs()` 即可（见下方 update_notifications）。


# ====== 依赖说明（★ 为什么这里不用 fail-closed）======
#
# 本模块一律用 `Depends(get_current_user)`：**要求一枚有效 token**，
# 但不额外要求"环境已启用强制鉴权"。
#
# ★ 与 `core/auth/accounts_router.py` 的差异是**刻意的**：
#   - accounts 管的是团队账户 / 成员 / 角色 —— **授权数据**，
#     它决定"谁能碰哪些店铺"。说不清"你是谁"就不该能改，
#     所以那边用 `require_authenticated_user`（fail-closed，演示模式整体不开放）。
#   - users 管的是**自己的**资料 / 密钥 / 偏好。判定依据就是
#     "这枚 token 是不是你"，`get_current_user` 正是这个语义。
#
# ★ 实测教训（别改回去）：本地 `.env` 是 `AUTH_REQUIRED=false`，而
#   `require_auth_if_enabled` 在该模式下**直接返回 None —— 连有效 token 都不看**。
#   若这里也用 fail-closed，已登录用户点"保存资料"会收到 401
#   （文案还写着"当前环境未启用强制鉴权"，把人引向完全错误的方向）。
#   ⇒ 断链会从 404 变成 401，功能依旧不可用。

# ====== 请求体 ======

class ProfileUpdateRequest(BaseModel):
    """
    更新个人资料。

    ★ 没有 `email` 字段是**刻意的**：邮箱是账号主键的一部分，
      也是找回密码的投递地址。允许改邮箱 ⇒ 得先有一整套「新邮箱验证」流程，
      否则改成一个打不通的邮箱就等于把自己锁在门外。
      本批不做这一流程，所以字段层面直接不接受（而不是收了再拒绝）。
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    phone: Optional[str] = Field(None, max_length=32)
    company: Optional[str] = Field(None, max_length=120)


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="便于识别的名称")


class NotificationPrefsRequest(BaseModel):
    """
    通知偏好（**部分更新**：只传要改的项）。

    ★ 字段名用 camelCase 是为了与前端表单一一对应 —— 零映射层，
      少一层就少一个"两边拼错且不报错"的机会。
    """
    usageAlert: Optional[bool] = None
    billingAlert: Optional[bool] = None
    weeklyReport: Optional[bool] = None
    systemUpdate: Optional[bool] = None
    taskComplete: Optional[bool] = None
    agentError: Optional[bool] = None


# ====== 辅助 ======

def _sniff_image_ext(content: bytes) -> Optional[str]:
    """
    按**魔数**嗅探图片类型（不信扩展名，也不信 Content-Type）。

    ★ 只校验扩展名会被"改名绕过"：把任意文件命名成 `a.png` 就能落盘。
      本项目把 uploads 目录挂在 `/static` 下对外提供，落一个可执行/HTML 文件
      进去就不是"图片丑"的问题了。所以这里看文件头。
    """
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if content.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return ".webp"
    return None


def _generate_api_key() -> tuple[str, str, str]:
    """
    生成一枚 API key，返回 `(完整明文, sha256 哈希, 掩码串)`。

    ★ 明文用 `secrets`（CSPRNG）而不是 `random` / `uuid4`：
      密钥必须不可预测，`random` 是可推的 PRNG。

    ★ 掩码串在**后端**生成并落库：
      列表接口每次读都要给出稳定一致的掩码，前端不该自己截字符串
      （库里只有哈希，前端拿不到"前 7 位"这种信息）。
    """
    raw = "sk-" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    masked = f"{raw[:7]}****{raw[-4:]}"
    return raw, digest, masked


def _key_to_dict(key: UserApiKey) -> Dict[str, Any]:
    return {
        "id": key.id,
        "name": key.name,
        # ★ 字段名沿用前端的 `key`，但值是**掩码串** ——
        #   完整的明文只在创建那一刻的响应里给过一次。
        "key": key.key_masked,
        "is_active": key.is_active,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked_at": key.revoked_at.isoformat() if key.revoked_at else None,
    }


def _read_prefs(user: User) -> Dict[str, bool]:
    """读出补齐后的通知偏好（真源见 `models.merge_notification_prefs`，此处只是取参）。"""
    return merge_notification_prefs(user.notification_prefs)


# ====== 个人资料 ======

@router.put("/profile", response_model=dict)
async def update_profile(
    payload: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    更新个人资料（只更新请求里出现的字段）。

    ★ 只写白名单列：`name` / `phone` / `company`。
      不接收 `role` / `is_active` / `is_verified` / `email` ——
      否则这就是一条**自助提权**接口（把 `role` 改成 admin 即可越权）。
    """
    changed: List[str] = []

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="用户名不能为空")
        current_user.name = name
        changed.append("name")

    if payload.phone is not None:
        current_user.phone = payload.phone.strip() or None
        changed.append("phone")

    if payload.company is not None:
        current_user.company = payload.company.strip() or None
        changed.append("company")

    if changed:
        current_user.updated_at = datetime.utcnow()
        await db.flush()
        logger.info("用户资料已更新 user=%s fields=%s", current_user.id, ",".join(changed))

    return {"updated": changed, "user": user_to_dict(current_user)}


# ====== 头像 ======

@router.post("/avatar", response_model=dict)
async def upload_avatar(
    file: UploadFile = File(..., description="头像图片：png / jpg / jpeg / webp，≤2MB"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    上传头像。

    落盘到 ``uploads/avatars/<内容sha1前16位>.<ext>``，返回 ``/static/avatars/...``。

    ★ 文件名用**内容哈希**（不是 user_id、也不是原名）：
      ① 同一张图重复上传不堆垃圾（幂等）；
      ② 不把用户可控的字符串（原文件名）拼进路径 —— 那是目录穿越的入口。

    ★ 旧头像文件**不删**：它可能正被浏览器缓存 / 被其他页面引用。
      单张图几十 KB，留着比制造 404 便宜。真要做回收，是定时任务的事。
    """
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="上传内容为空")
    if len(content) > _AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"头像不能超过 {_AVATAR_MAX_BYTES // 1024 // 1024}MB"
            f"（当前 {len(content) / 1024 / 1024:.1f}MB）",
        )

    sniffed = _sniff_image_ext(content)
    if sniffed is None:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的图片格式（仅支持 {'/'.join(sorted(IMAGE_EXT))}）",
        )

    # ★ 以**嗅探结果**为准，不看 filename 的扩展名（前者不可伪造）
    ext = ".jpg" if sniffed == ".jpg" else sniffed
    # 内容寻址用（非安全用途）；usedforsecurity=False 让 FIPS 环境也放行
    name = hashlib.sha1(content, usedforsecurity=False).hexdigest()[:16] + ext

    target_dir = upload_root() / "avatars"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / name
    if not target.exists():
        target.write_bytes(content)

    url = f"{STATIC_PREFIX}/avatars/{name}"
    current_user.avatar_url = url
    current_user.updated_at = datetime.utcnow()
    await db.flush()

    logger.info("头像已更新 user=%s -> %s（%d 字节）", current_user.id, url, len(content))
    return {"avatar_url": url, "size": len(content)}


# ====== API 密钥 ======

@router.get("/api-keys", response_model=dict)
async def list_api_keys(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    我的 API 密钥列表（**只返回掩码**，且不含已撤销的）。

    ★ 按 `current_user.id` 过滤，不接受任何 id 参数 ——
      想「查看别人的密钥」在这条路径上**没有入口**（不是靠判断拦住，而是没有参数）。
    """
    rows = (
        await db.execute(
            select(UserApiKey)
            .where(
                UserApiKey.user_id == current_user.id,
                UserApiKey.is_active.is_(True),
            )
            .order_by(UserApiKey.created_at.desc(), UserApiKey.id)
        )
    ).scalars().all()

    # ★ `total` 不是可有可无的装饰：本项目**所有**列表端点都是
    #   `{"<集合名>": [...], "total": n}`（同域的 accounts_router 即
    #   `{"accounts": [...], "total": len(accounts)}`，assets / monitors /
    #   products / candidates / platform_rules 亦然）。
    #   少这一个键，前端要为空态多写一条 `|| []`（已写在 Settings.vue），
    #   测试也无法用一个统一的形状断言"条数"。
    return {"api_keys": [_key_to_dict(k) for k in rows], "total": len(rows)}


@router.post("/api-keys", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_api_key(
    payload: ApiKeyCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    创建 API 密钥。

    ★ ``key`` 字段里的**完整明文只会出现这一次**（响应体）。
      库里只有 sha256 与掩码串 ⇒ 丢了就只能重建，找不回来。
      这是刻意的，不是缺陷：能找回来就意味着库里有原文。
    """
    raw, digest, masked = _generate_api_key()
    row = UserApiKey(
        id=secrets.token_hex(18),
        user_id=current_user.id,
        name=payload.name.strip(),
        key_hash=digest,
        key_masked=masked,
        is_active=True,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()

    logger.info("API 密钥已创建 user=%s name=%s", current_user.id, row.name)

    data = _key_to_dict(row)
    data["key"] = raw  # ★ 唯一一次给出明文
    return data


@router.delete("/api-keys/{key_id}", response_model=dict)
async def revoke_api_key(
    key_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    撤销 API 密钥（**软删**：置 `is_active=False` + 记 `revoked_at`）。

    ★ 为什么不物理 DELETE：密钥可能已被写进客户的 CI/CD、服务器环境变量、
      第三方集成。真删掉这行之后，「这枚 key 存在过吗 / 什么时候被撤的」
      就再也查不到了 —— 出事时排查成本远高于留一行的成本。

    ★ 越权（他人的 key_id）返回 **404**：403 会确认"这个 id 存在"。
    """
    row = (
        await db.execute(
            select(UserApiKey).where(
                UserApiKey.id == key_id,
                UserApiKey.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        raise HTTPException(status_code=404, detail="密钥不存在")

    if not row.is_active:
        # 幂等：重复撤销不报错，但也不再改时间（否则 revoked_at 会被反复刷新）
        return {"id": row.id, "is_active": False, "revoked_at": _iso(row.revoked_at)}

    row.is_active = False
    row.revoked_at = datetime.utcnow()
    await db.flush()
    logger.info("API 密钥已撤销 user=%s key=%s", current_user.id, row.id)

    return {"id": row.id, "is_active": False, "revoked_at": _iso(row.revoked_at)}


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value else None


# ====== 通知偏好 ======

@router.put("/notifications", response_model=dict)
async def update_notifications(
    payload: NotificationPrefsRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    保存通知偏好（部分更新，返回补齐后的**完整**偏好对象）。

    ★ 返回完整对象而不是"只回显改的那几项"：前端保存后要立刻用同一份数据
      重绘全部开关，回一份局部会让人以为其他项被重置了。
    """
    prefs = _read_prefs(current_user)
    patch = payload.model_dump(exclude_none=True)
    prefs.update({k: bool(v) for k, v in patch.items() if k in prefs})

    current_user.notification_prefs = prefs
    current_user.updated_at = datetime.utcnow()
    await db.flush()

    logger.info("通知偏好已更新 user=%s keys=%s", current_user.id, ",".join(patch) or "-")
    return {"prefs": prefs}
