"""
多租户隔离回归自检（业务侧）

验证 `core/tenant/middleware.py` 公开入口的归属校验是否真正生效
（`get_current_shop_id` / `get_current_shop_id_optional`）：
  - 用户 A 的 token 拿用户 B 的店铺 ID 当 X-Shop-ID -> 403
  - 店铺所有者 B 自己访问                          -> 放行（返回该 shop_id）
  - 平台超管跨账户访问                             -> 放行（设计如此）
  - 无 token / 伪造 token                          -> 401
  - 无 X-Shop-ID 头：读方法 -> None（端点回空列表）；写方法 -> 400
  - 演示模式（AUTH_REQUIRED=false）                -> 演示身份**只**放行演示店铺：
                                                     演示店 -> 放行；真实店 -> 403
                                                     （第 177 轮收紧；**不是**「全部放行」）

★★★ P1-c 改造（2026-09-16）：本脚本原先打的是**账户侧**
    `get_tenant_from_header` / `require_shop_owner`（查 `shops` 表 / UUID）。
    那套符号已随账户侧实体整体删除。现在改打**业务侧**唯一解析者，
    并且用**真实的 account → store 层级**造数据（而不是手插一行 shops）：
    店铺必须挂在一个账户上、账户必须有 owner 成员行 —— 否则测的不是生产形态。
    判定实现见 `core/auth/accounts.py`。

★★★ 2026-09-18：本脚本改走**公开依赖入口**（`get_current_shop_id` /
    `get_current_shop_id_optional`），不再直接 import `_resolve_current_shop_id`。
    两条理由：
      ① 生产代码走的本来就是那两个公开依赖，直接打私有实现 = **少测一层**；
      ② 跨包 import 下划线私有符号等于对内部签名**静默上锁** —— `middleware.py`
         改名或加参数时这里会失联，而 `scripts/` 不在任何 CI 的 import 图上。
    该形态由 `tests/test_import_boundaries.py::test_no_cross_package_private_symbol_imports`
    钉住（本处是它挖出的**唯一**真实违规）。
    行为等价性有实测：改造前后本脚本均 `10/10 通过`、逐条 PASS 文案一致。

运行方式（两个分支都有真断言，**两种模式都要跑**）：
    cd backend
    python scripts/check_tenant_isolation.py                     # 演示模式分支
    AUTH_REQUIRED=true python scripts/check_tenant_isolation.py  # 生产模式分支

★★★ 第 353 轮：此前本脚本**不在任何自动入口**（`tests/` 里对它的 3 处提及
    全是注释 / docstring / assert 样例字符串，没有任何一处**执行**它；CI 也不跑）。
    ⇒ 它 1/2 通过这件事，没有任何流程会看见。本轮的配套动作：
      · 新增 `tests/test_tenant_isolation_gate.py`（pytest 包装 ⇒ 进 CI）；
      · 本文件的两个分支各有独立断言，包装里**各跑一次**。

退出码：0 = 全部通过；1 = 有用例失败
"""

import asyncio
import os
import sys
import uuid

BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402
from sqlalchemy import select  # noqa: E402

from core.auth.accounts import ensure_owner_member, ensure_default_account  # noqa: E402
from core.auth.demo_identity import DEMO_SENTINEL_PREFIX  # noqa: E402
from core.auth.jwt_handler import create_token_pair  # noqa: E402
from core.config import config  # noqa: E402
from core.database import get_async_session  # noqa: E402
from core.identity.models import User, UserRole  # noqa: E402
from core.identity.router import hash_password  # noqa: E402
from core.tenant.middleware import (  # noqa: E402
    TENANT_HEADER,
    get_current_shop_id,
    get_current_shop_id_optional,
)
from core.stores import StoreRecord  # noqa: E402
from modules.stores.demo import demo_account_id  # noqa: E402


def make_request(shop_id: str = None, token: str = None, method: str = "GET") -> Request:
    """构造一个最小可用的 ASGI Request，用于直接调用依赖函数"""
    headers = []
    if shop_id is not None:
        headers.append((TENANT_HEADER.lower().encode(), str(shop_id).encode()))
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))

    scope = {
        "type": "http",
        "method": method,
        "path": "/test",
        "headers": headers,
        "query_string": b"",
        "scheme": "http",
        "server": ("127.0.0.1", 8001),
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


async def ensure_user(session, email: str, role: str = "user") -> User:
    """确保测试用户存在，返回该用户"""
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user:
        return user

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        hashed_password=hash_password("test123456"),
        name=email.split("@")[0],
        role=UserRole.ADMIN if role == "admin" else UserRole.USER,
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def ensure_store(session, owner: User, name: str) -> StoreRecord:
    """
    确保测试店铺存在（**按生产形态造**：个人账户 + owner 成员行 + 挂账户的店）。

    ★ 为什么不手插一行 `stores_store` 了事：那样 `account_id` 为空，
      归属判定会走**过渡期兜底分支**（按 owner_id 判），
      于是本脚本验证的是"过渡期行为"，而不是收拢后的真实口径
      —— 口径不同、结论可能完全相反，这种自检等于没做。
    """
    result = await session.execute(select(StoreRecord).where(StoreRecord.name == name))
    store = result.scalars().first()
    if store:
        return store

    account = await ensure_default_account(session, owner)
    await ensure_owner_member(session, account, owner)
    await session.flush()

    store = StoreRecord(
        id=f"store_{uuid.uuid4().hex[:8]}",
        name=name,
        platform="amazon_us",
        tenant_id="default_tenant",
        owner_id=owner.id,
        account_id=account.id,
    )
    session.add(store)
    await session.commit()
    await session.refresh(store)
    return store


async def ensure_demo_store(session) -> StoreRecord:
    """
    按**生产形态**造一家演示店：落在演示账号名下，并标 `is_demo=True`。

    ★ 为什么不"随便造一家店再硬贴 `is_demo=True`"：
      生产里 `is_demo` 不是手填的，是从**账户归属**推导出来的
      （`modules/stores/demo.py::ensure_demo_stores`：
      `is_demo = (store.account_id == 演示账号)`）。
      硬贴标记等于验证一个**生产里不存在的形态** —— 那种"通过"没有意义，
      而且一旦有人把推导规则改成别的依据，本脚本照样绿。

    ⇒ 两个条件都做：先落在演示账号（`config.demo_account_email`）名下，
      再按同一规则标 `is_demo`。二者缺一就报出来，不静默通过。
    """
    email = (config.demo_account_email or "").strip()
    if not email:
        print()
        print("★ DEMO_ACCOUNT_EMAIL 为空 ⇒ 演示身份已降级为匿名，演示分支不适用。")
        return None

    owner = await ensure_user(session, email)
    store = await ensure_store(session, owner, "TenantA-Demo-Store")

    # ★ 一致性自检：这家店的 `account_id` 必须**就是**演示账号。
    #   为什么这条值得写出来而不是"应该相等"：
    #     `ensure_store` 走 `ensure_default_account`（取「最早创建的容器」），
    #     `demo_account_id()` 取的是**同一条排序** —— 两处口径若哪天分了叉，
    #     演示店就会挂在 A 账号、而演示身份命中 B 账号，表现为「演示模式半死不活」。
    #     这种失效**不会报错**，只会让演示一片空白，所以必须在这里当场断言。
    demo_acct = await demo_account_id()
    if demo_acct is not None and getattr(store, "account_id", None) != demo_acct:
        print(
            f"  ✘ 演示店归属不一致：store.account_id={getattr(store, 'account_id', None)!r} "
            f"≠ demo_account_id()={demo_acct!r} —— 两处口径已分叉"
        )
        return None

    if not bool(getattr(store, "is_demo", False)):
        store.is_demo = True
        await session.commit()
        await session.refresh(store)

    print()
    print(f"演示店铺 [{store.name}] ({store.id}) 已标 is_demo={getattr(store, 'is_demo', None)}")
    return store


async def expect(coro_func, expected, label: str, results: list, *, expect_value=None):
    """
    执行一个依赖调用并断言结果。

    `expected` 为 int 时按 HTTP 状态码断言（200 表示放行）；
    为 None 时断言"无异常返回的原始值 == expect_value"（读方法缺头的情形）。
    """
    try:
        result = await coro_func()
        actual = 200
        detail = f"放行 -> {result!r}"
    except HTTPException as exc:
        actual = exc.status_code
        result = None
        detail = str(exc.detail)

    if expected is None:
        ok = actual == 200 and result == expect_value
        shown = f"期望返回 {expect_value!r}"
    else:
        ok = actual == expected
        shown = f"期望 {expected}"

    results.append(ok)
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}: {shown} / 实际 {actual}  ({detail})")
    return result


async def main() -> int:
    print("=" * 70)
    print("多租户隔离回归自检（业务侧 · account → store 层级）")
    print("=" * 70)
    print(f"AUTH_REQUIRED = {config.auth_required}")
    print(f"判定实现      = core/auth/accounts.py::can_access_store")
    if not config.auth_required:
        print()
        print("提示：当前为演示模式 —— 归属校验**仍然生效**（第 177 轮起）：")
        print("      演示身份只放行 `is_demo` 店铺；真实店铺一律 403。")
        print("      要验证真实身份之间的越权拦截，请用 AUTH_REQUIRED=true 运行本脚本。")

    results = []
    created_store_ids = []

    async with get_async_session() as session:
        user_a = await ensure_user(session, "tenant-test-a@example.com")
        user_b = await ensure_user(session, "tenant-test-b@example.com")
        admin = await ensure_user(session, "tenant-test-admin@example.com", role="admin")
        store_b = await ensure_store(session, user_b, "TenantB-Store")
        created_store_ids.append(store_b.id)

        # 演示店（真实店 vs 演示店 = 第 177 轮收口后**唯一**有意义的对照）
        store_demo = await ensure_demo_store(session)
        if store_demo is not None:
            created_store_ids.append(store_demo.id)

        token_a = create_token_pair(user_a.id, user_a.email, user_a.role.value).access_token
        token_b = create_token_pair(user_b.id, user_b.email, user_b.role.value).access_token
        token_admin = create_token_pair(admin.id, admin.email, admin.role.value).access_token

        print()
        print(f"店铺 [{store_b.name}] ({store_b.id}) 归属于账户 {store_b.account_id}")
        print(f"  账户所有者 = {user_b.email}；测试破坏者 = {user_a.email}")
        print()

        if config.auth_required:
            print("用例：")
            # 1. A 带着自己的合法 token 用 B 的店铺 ID -> 403
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_a), session),
                403, "用户A token 冒充 用户B 的店铺", results,
            )
            # 2. 所有者 B 访问自己的店铺 -> 放行
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_b), session),
                200, "所有者B 访问自己的店铺", results,
            )
            # 3. 平台超管跨账户 -> 放行
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, token_admin), session),
                200, "平台超管 跨账户访问", results,
            )
            # 4. 无 token -> 401
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, None), session),
                401, "无 token 访问", results,
            )
            # 5. 伪造 token -> 401
            await expect(
                lambda: get_current_shop_id(
                    make_request(store_b.id, "fake.token.value"), session),
                401, "伪造 token 访问", results,
            )
            # 6. 不存在的店铺 ID -> 403（**不是 404**：不泄露存在性）
            await expect(
                lambda: get_current_shop_id(
                    make_request("store_ffffffff", token_b), session),
                403, "不存在的店铺 ID（应为 403 而非 404）", results,
            )
            # 7. 缺 X-Shop-ID + 写方法 -> 400（空值守卫）
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, token_b, method="POST"), session),
                400, "写方法缺 X-Shop-ID", results,
            )
            # 8. 缺 X-Shop-ID + 读方法 -> 返回 None（端点回空列表）
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, token_b, method="GET"), session),
                None, "读方法缺 X-Shop-ID（应返回 None）", results, expect_value=None,
            )
            # 9. 纯空白头 + 写方法 -> 400（不能被当成合法店铺 ID）
            await expect(
                lambda: get_current_shop_id(
                    make_request("   ", token_b, method="POST"), session),
                400, "写方法 + 纯空白 X-Shop-ID", results,
            )
            # 10. get_current_shop_id_optional（对话/导航入口）缺头 -> 返回 None，不 400
            await expect(
                lambda: get_current_shop_id_optional(
                    make_request(None, token_b, method="POST"), session),
                None, "对话入口缺头（不应 400）", results, expect_value=None,
            )
        else:
            print("用例：")
            # ★★★ 第 353 轮修正：本分支的期望值此前**停在修复之前**。
            #
            #   旧写法只有两条，第一条断言「演示身份 + 真实店 ⇒ 200」，与
            #   `core/tenant/middleware.py:256-262`（第 177 轮）直接矛盾 ——
            #   那一轮已删掉「user is None ⇒ 直接放行」，改为「演示身份也走
            #   can_access_store：演示店铺 200 / 真实店铺 403」。
            #   ⇒ 这不是"发现了回归"，而是**期望值过期**（负资产）：既误导
            #     （让人以为演示坏了），又不设防（真坏时也没人知道）。
            #   定性过程见 `docs/reviews/2026-10-01-第353轮-项目复审.md` §3。
            #
            #   ★ 修正后**两个方向都测** —— 只验"演示店放行"会漏掉真正的回归
            #     （有人把 `_matches` 改回 `return True` 时，只测演示店仍然绿）。
            if store_demo is None:
                # ★ 演示店造不出来 ⇒ 依赖它的用例**必须记红**，不能"少跑两条"。
                #   少跑会让 `结果: 3/3 通过` 看起来与 `5/5 通过` 一样漂亮 ——
                #   那正是本门禁原来的病（红着没人知道）换了张皮。
                results.append(False)
                print(
                    "  [FAIL] 演示店不可用（DEMO_ACCOUNT_EMAIL 未指向"
                    "「名下有容器的账号」）⇒ 演示身份的两条用例无法执行，按失败计"
                )
            else:
                await expect(
                    lambda: get_current_shop_id(
                        make_request(store_demo.id, None), session),
                    200, "演示身份 + 演示店铺（应放行：演示能力完好）", results,
                )
                await expect(
                    lambda: get_current_shop_id(
                        make_request(store_b.id, None), session),
                    403, "演示身份 + 真实店铺（应 403：第 177 轮收紧）", results,
                )
            await expect(
                lambda: get_current_shop_id(
                    make_request(None, None, method="POST"), session),
                400, "演示模式：写方法缺头仍 400（空值守卫与身份无关）", results,
            )

            # ★ 第 182 轮那条身份路径（前端哨兵 ⇒ 演示账号主人）此前**零覆盖**：
            #   本脚本只测了「完全不带凭据」这一种演示身份。哨兵身份走的是
            #   `resolve_demo_user`（三重守卫），与匿名不是同一条路。
            if config.demo_mode:
                sentinel = f"{DEMO_SENTINEL_PREFIX}sentinel"
                # 真实店这条**不依赖演示店** ⇒ 先跑，哪怕演示店造不出来也有读数
                await expect(
                    lambda: get_current_shop_id(
                        make_request(store_b.id, sentinel), session),
                    403, "演示哨兵 token + 真实店铺（不得因哨兵放大可见面）", results,
                )
                if store_demo is not None:
                    await expect(
                        lambda: get_current_shop_id(
                            make_request(store_demo.id, sentinel), session),
                        200, "演示哨兵 token + 演示店铺（第 182 轮路径）", results,
                    )

        # ---- 清理：只删本脚本造出来的店（保留用户，便于复跑）----
        for sid in created_store_ids:
            await session.execute(
                StoreRecord.__table__.delete().where(StoreRecord.id == sid)
            )
        await session.commit()

    print()
    passed = sum(1 for r in results if r)
    print(f"结果: {passed}/{len(results)} 通过")
    print("=" * 70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
