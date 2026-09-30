"""演示身份解析 —— 把前端哨兵串解析成一个**真实用户**（第 182 轮）

==============================================================================
★ 这一版改了什么（需求变更，不是缺陷修复）
==============================================================================
第 181 轮及以前，`demo-token` 解析成 `None`（「匿名演示」）：它拿不到归属，
只能看见 `is_demo=True` 的行。那是一份**刻意的只读设计**。

第 182 轮老板的原文推翻了它：

    「演示模式也当作一个真实的账号，只是无需账号密码。也有全套功能。」

⇒ 演示身份必须**真的是一个人**：有 `User` 行、有 `Account`、有 `AccountMember`，
  于是 `ensure_default_account` / `filter_accessible_skills` / `can_access_skill`
  这些归属函数**一行都不用改**就能工作，演示模式因此拿到与真实账号**同等**的功能。

★ 与 `platform_rules` 的同形先例：
  `get_role_names()` / `_non_admin_role_name()` / `filter_accessible_docs` 早就写着
  「无身份 ⇒ 落到管理者身份」。本条是同一句话在另一种资源上的实例 ——
  区别只是：那边落到一个**有权限的角色**，这边落到一个**具体的人**。

==============================================================================
★★★ 谁来决定「那个人是谁」：服务端，绝对不是前端
==============================================================================
前端源码是公开的 —— `frontend/src/config/demoMode.ts` 里连哨兵串
`demo-token` 都明文写着。所以**绝不能让前端传 `user_id`**：
那等于「任何人改一行前端就能让后端以任意身份行事」，包括冒充某个真实客户。

正确分工只有一种切法：

    前端  —— 只表达「我要演演示账号」（一枚哨兵串，不含任何身份信息）
    服务端 —— 决定「演示账号是哪个人」（`config.demo_account_email`，住在 .env）

⇔ 这与 `jwt_handler` 的分工同构：token 只带 `user_id`，**权限由服务端现查**。
  身份信息的权威永远在服务端这一侧，客户端只能提出请求。

==============================================================================
★★★ 三重 fail-closed 守卫（缺任何一条都会静默放大可见范围）
==============================================================================
    ① `allow_demo` 为假 或 `config.demo_mode` 为假 ⇒ `None`
       生产（`demo_mode=False`）下哨兵与任意伪造串同等对待，落到 401。

    ② 查不到演示账号主人 ⇒ `None`
       **不能**退回「随便挑一个用户」：那会让演示身份命中一个与 .env 无关的人，
       而那个人的全部店铺/技能会因此对任何知道 `demo-token` 的人可见。
       返回 `None` 时的语义是**明确的**（只见 `is_demo` 行），副作用最小。

       ★ 注意查询里那个 `join(Account, …)`：本守卫的真实语义是
         「**查得到一个名下有容器的主人**」，不是「email 存在」。
         这不是巧合 —— 演示身份的核心用途就是「写东西时归属有地方落」，
         而归属的落点就是容器（`ensure_default_account` 会往这里放）。
         一个没有容器的用户当演示身份，写口会在外键处炸成
         「数据库不可用」（第 180 轮那类**归因错方向**的故障）。
         ⇒ 那条 join 是刻意的：**宁可在身份解析这一步就没有身份**
           （退回匿名、写口 403），也不要放一个"能登进来但存不下东西"的身份。

    ③ 那个人是**平台超管** ⇒ 拒绝
       这条最容易被漏掉，也最致命：`is_platform_admin` 在
       `accounts._matches`（`visible is None` 分支）与 `get_visible_account_ids`
       里都是**全库短路** —— 一旦演示账号恰好是管理员，
       演示模式就变成「整个平台的只读镜像」，而提示条上还写着"演示"。
       ⇒ 宁可让演示模式空掉，也不能让它变成全库浏览器。

==============================================================================
★ 为什么本模块不碰 IO 之外的东西
==============================================================================
它只做一件事：`email → User 行`（外加三重守卫）。判定本身（可见性是哪些账户）
仍然只有一处 —— `core/auth/accounts.py`。本模块**不复制**那条口径：
演示身份拿到真主角之后，`_matches_skill` 里 `user is None` 那档天然不再被走到，
而「演示账号成员可见什么」由**同一条**账户集合判定回答（就是那个账号自己的集合）。
"""

import logging
from typing import Optional

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import config
from core.identity.account_models import Account
from core.identity.models import User

logger = logging.getLogger(__name__)

#: 前端演示哨兵串的前缀（必须与 `frontend/src/config/demoMode.ts::DEMO_TOKEN` 一致）。
#:
#: ★ 第 182 轮把这个常量从 `dependencies.py` **下移**到本模块：它和
#:   「解析成谁」是同一件事的两半（「什么是演示凭据」+「这份凭据代表谁」），
#:   分开放会让将来改哨兵串的人只改到一半。
#:   `dependencies.py` 反过来 import 本常量 ⇒ 定义仍然只有一处。
DEMO_SENTINEL_PREFIX = "demo-"


def is_demo_credential(token: Optional[str]) -> bool:
    """这枚凭据是不是演示哨兵（**只看前缀，不做任何身份判断**）。

    ★ 刻意不校验 `config.demo_mode`：本函数回答的是「它长什么样」，
      而「承不承认它」是 `resolve_demo_user` 的第一道守卫。
      把两件事分开，是因为它们的失败语义不同 ——
      前者决定「走哪条分支」，后者决定「那条分支产出什么」。
    """
    return bool(token) and str(token).startswith(DEMO_SENTINEL_PREFIX)


def is_demo_request(request: Request) -> bool:
    """这次请求是不是**以演示身份**行事（唯一真源）。

    ★ 为什么单列一个函数（第 220 轮）：这条判定此前在 `dependencies.py` 里
      **手写了两份，而且两份不一样** ——
        · `require_auth_if_enabled`：`has_bearer and is_demo_credential(token)
          and config.demo_mode`
        · `get_acting_user`：`is_demo_credential(token) and config.demo_mode`
          （少了 `has_bearer` 那一半）
      本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。收口到一处之后，
      下一轮的配额豁免（`core/metering/usage_tracker.py`）也不必再抄第三份。

    ★ 它回答的是「凭据形态 + 演示开关」，**不解析身份** ——
      「演示账号是哪个人」仍然是 `resolve_demo_user` 的职责（带三重守卫）。
      两件事分开的理由见本模块 docstring：它们的失败语义不同。

    ★ `scheme == "bearer"` 那一半**必须保留**：`require_auth_if_enabled` 的
      ② 档（带了自称为 Bearer 的凭据 ⇒ 一律强制校验真身份）就是按这个 scheme
      分流的。少了它，`Authorization: Demo demo-token` 这类非 Bearer 头会被
      认成演示身份，于是出现「同一枚头，演示分支认、真身份分支不认」的缝。
    """
    auth_header = request.headers.get("Authorization") or ""
    scheme, _, raw_token = auth_header.partition(" ")
    token = raw_token.strip()
    if scheme.lower() != "bearer" or not token:
        return False
    return is_demo_credential(token) and bool(config.demo_mode)


async def resolve_demo_user(
    db: AsyncSession,
    *,
    allow_demo: bool = True,
) -> Optional[User]:
    """演示哨兵 ⇒ 演示账号主人（三重守卫，见模块 docstring）。

    Args:
        db: 会话（由调用方提供 —— 本模块**不自己开事务**：
            解析结果要与同一请求里的后续查询同处一个会话，
            另开一个连接会读到不同的快照）。
        allow_demo: 调用方是否允许承认演示身份。
            `dependencies.require_auth_if_enabled` 传 `True`；
            任何**身份与授权数据**的入口（`require_authenticated_user` 那类）
            传 `False` 或干脆不调本函数 —— 身份数据编不出一份可降级的
            「演示版团队成员」。

    Returns:
        演示账号的主人（真 `User` 行）；任一守卫不通过 ⇒ `None`。
    """
    if not allow_demo or not config.demo_mode:
        return None

    email = (config.demo_account_email or "").strip()
    if not email:
        # 显式留空 = 「演示身份退回匿名」的降级开关（见 config 字段描述）。
        # ★ 不 fallback 到默认 email：那会让"我把这一项清空以关闭演示身份"
        #   变成一句无声的谎话。
        return None

    user = (
        await db.execute(
            select(User)
            .join(Account, Account.owner_user_id == User.id)
            .where(User.email == email)
            .order_by(Account.created_at, Account.id)
            .limit(1)
        )
    ).scalars().first()

    if user is None:
        # 守卫 ②：查不到 ⇒ 无身份（**不是**"随便挑一个人"）。
        logger.debug("演示账号主人不存在（email=%s）⇒ 演示身份退回匿名", email)
        return None

    # 守卫 ③：超管 ⇒ 拒绝。
    # ★ import 放在函数内是刻意的：`core/auth/accounts.py` 反过来会 import
    #   本模块的兄弟（dependencies），顶层 import 会造出一个 import 环。
    #   本函数每次请求只调一次，函数内 import 的代价（dict 命中）可忽略。
    from core.auth.accounts import is_platform_admin

    if is_platform_admin(user):
        logger.error(
            "演示账号主人（%s）是平台超管 ⇒ 拒绝解析演示身份。"
            "超管在归属判定里走「全库可见」短路，一旦放行，演示模式会变成"
            "整个平台的只读镜像。请把 DEMO_ACCOUNT_EMAIL 指向一个普通账号。",
            email,
        )
        return None

    if not getattr(user, "is_active", True):
        # ④ 停用账号不构成有效身份（与 `get_current_user` 的 is_active 口径一致）。
        #    这条不是"额外的保险"：停用是**管理动作**，必须立刻生效，
        #    否则演示身份会绕过刚刚下达的封停。
        logger.warning("演示账号主人（%s）已被停用 ⇒ 演示身份退回匿名", email)
        return None

    return user


__all__ = [
    "DEMO_SENTINEL_PREFIX",
    "is_demo_credential",
    "is_demo_request",
    "resolve_demo_user",
]
