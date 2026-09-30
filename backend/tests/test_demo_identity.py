"""演示身份解析 —— 门禁（第 182 轮）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
需求原文：「演示模式也当作一个真实的账号，只是无需账号密码。也有全套功能。」

实现方式是：把前端哨兵串 `demo-token` 解析成**演示账号主人**（真 `User` 行），
于是整条归属链一行不改就能工作。**收益越大，误配的代价也越大** ——
演示身份一旦解析错人，弹窗里出现的就不再是演示数据，而是某个真实账号的店铺与技能。
所以本文件只钉一件事：**解析结果的边界**。

==============================================================================
★ 四条守卫，任何一条失守都会静默放大可见范围
==============================================================================
  ① `demo_mode=False` ⇒ 无身份
     生产必须如此（`config._enforce_production_safety` 另有启动期硬拦）。
  ② 找不到演示账号主人 ⇒ 无身份
     **不能退回"随便挑一个用户"** —— 那会让演示身份命中一个与 .env 无关的人。
  ③ 演示账号主人是**平台超管** ⇒ 拒绝
     最致命的一条：`is_platform_admin` 在 `accounts._matches` 与
     `get_visible_account_ids` 里都走「全库短路」⇒ 演示模式会变成
     **整个平台的只读镜像**，而提示条上还写着"演示"。
  ④ 演示账号主人**已被停用** ⇒ 无身份
     停用是管理动作，必须立刻生效 —— 否则演示身份会绕过刚刚下达的封停。

==============================================================================
★ 还有一条"不多不少"的不变量
==============================================================================
`get_visible_account_ids(演示身份)` 必须**恰好等于**演示账号那一个
（不是"包含"，也不是"包含它之外的"）。

  · 少了 ⇒ 演示模式看不到自己的数据（空壳）；
  · 多了 ⇒ 弹窗里藏着别的账号的归属 —— 这正是老板那句
    「演示模式等于演示账号，不影响其他真实账号」要防的事。

==============================================================================
★ 反向注入清单
==============================================================================
 1. `resolve_demo_user` 的 `return user` 改成 `return None`
    ⇒ `test_demo_mode_on_resolves_the_demo_account_owner` 转红。
 2. 删掉守卫 ③（超管检查）
    ⇒ `test_platform_admin_owner_is_refused` 转红。
 3. 删掉守卫 ④（is_active 检查）
    ⇒ `test_inactive_demo_owner_is_refused` 转红。
 4. 守卫 ② 改成「查不到就取第一个用户」（`limit(1)` 去掉 where）
    ⇒ `test_unknown_email_yields_no_identity` 连带
      `test_visible_accounts_equal_exactly_the_demo_account` 一起转红。
"""

import uuid

from sqlalchemy import text

from core.database import async_session_factory


DEMO_ACCOUNT_EMAIL = "tenant-test-a@example.com"
DEMO_TOKEN = "demo-token"


def _patch_email(monkeypatch, email: str):
    monkeypatch.setattr("core.config.config.demo_account_email", email, raising=True)


# ============================================================================
# 1. 守卫 ①：开关
# ============================================================================


async def test_demo_mode_off_yields_no_identity(demo_off):
    """`demo_mode=False` ⇒ 演示哨兵**不是身份**（生产形态）。"""
    from core.auth.demo_identity import resolve_demo_user

    async with async_session_factory() as db:
        assert await resolve_demo_user(db, allow_demo=True) is None, (
            "★ demo_mode 关着还把哨兵解析成了身份 —— "
            "生产环境（DEMO_MODE=false）下任何知道 `demo-token` 这个字符串的人"
            "都会拿到演示账号的归属。config 的启动期护栏也拦不住这条（它只管住启动）。"
        )


async def test_allow_demo_false_yields_no_identity(demo_on):
    """即使 demo_mode 开着，调用方也能**显式拒绝**演示身份。

    ★ 这是给「身份与授权数据」类端点留的出口（`require_authenticated_user` 那档）：
      「我的团队成员」编不出一份可降级的"演示版"。
    """
    from core.auth.demo_identity import resolve_demo_user

    async with async_session_factory() as db:
        assert await resolve_demo_user(db, allow_demo=False) is None


# ============================================================================
# 2. 守卫 ②：账号存在
# ============================================================================


async def test_unknown_email_yields_no_identity(demo_on, monkeypatch):
    """配了一个库里不存在的 email ⇒ 无身份（**不能**退回随便挑一个人）。

    反向注入：把 `resolve_demo_user` 的 `.where(User.email == email)`
    删掉（只剩 `limit(1)`）⇒ 本条转红，且演示身份会命中一个**随机的**真实用户。
    """
    from core.auth.demo_identity import resolve_demo_user

    _patch_email(monkeypatch, f"nobody-{uuid.uuid4().hex[:8]}@example.com")
    async with async_session_factory() as db:
        assert await resolve_demo_user(db, allow_demo=True) is None, (
            "★ 配了一个不存在的演示账号，却仍然解析出了一个人 —— "
            "说明实现里有一处「找不到就随便取一个」的兜底。"
        )


async def test_empty_email_yields_no_identity(demo_on, monkeypatch):
    """把配置项**显式留空** = 关闭演示身份的降级开关（不是"回落到默认 email"）。

    ★ 为什么这条值得单列：留空若被实现成"用默认值"，那么
      「我把这一项清空以关掉演示身份」就成了一句无声的谎话 ——
      运维以为自己关了，实际还开着，且没有任何提示。
    """
    from core.auth.demo_identity import resolve_demo_user

    _patch_email(monkeypatch, "")
    async with async_session_factory() as db:
        assert await resolve_demo_user(db, allow_demo=True) is None


# ============================================================================
# 3. 守卫 ③：平台超管
# ============================================================================


async def test_platform_admin_owner_is_refused(demo_on, monkeypatch):
    """★★★ 演示账号主人若是**平台超管** ⇒ 拒绝解析。

    ★ 为什么这条必须存在（不是"多一层保险"）：
      `accounts._matches_skill` / `get_visible_account_ids` 对超管都是
      `visible is None` **全库短路** ⇒ 一旦放行，演示模式就变成
      「整个平台的只读镜像」—— 而界面上还写着"演示"。
      这类"权限被静默放大"是本仓最警惕的形态。

    ★ 反向注入：删掉 `resolve_demo_user` 里的 `if is_platform_admin(user): return None`
      ⇒ 本条转红。
    """
    from core.auth import demo_identity

    monkeypatch.setattr(
        "core.auth.accounts.is_platform_admin", lambda user: True, raising=True
    )
    async with async_session_factory() as db:
        got = await demo_identity.resolve_demo_user(db, allow_demo=True)
    assert got is None, (
        "★ 演示账号主人是超管却仍被解析成演示身份 —— "
        "演示模式会因此看到**全库**数据（超管走「可见性不设限」短路）。"
    )


async def test_configured_demo_account_is_not_platform_admin(demo_on):
    """反向对照：**当前配置**里那个演示账号确实不是超管（守卫 ③ 在真实数据下不触发）。

    ★ 为什么要有这条：上一条把 `is_platform_admin` 打桩成 True，
      若只有它，那么"守卫 ③ 的实现对不对"和"当前配置合不合规"就混在一起了。
      这条把后者单独钉住：**老板把 .env 指向一个管理员账号**时，这里立刻红，
      而不是等到有人发现演示弹窗能看到全库。
    """
    from core.auth.accounts import is_platform_admin
    from core.auth.demo_identity import resolve_demo_user

    async with async_session_factory() as db:
        user = await resolve_demo_user(db, allow_demo=True)
    assert user is not None, f"前置缺失：{DEMO_ACCOUNT_EMAIL} 解析不出演示身份"
    assert not is_platform_admin(user), (
        f"★ 演示账号主人（{DEMO_ACCOUNT_EMAIL}）是平台超管。"
        f"这条路必须堵死：超管的可见性判定走「不设限」短路，"
        f"拿它当演示身份 = 演示模式看到整个平台的数据。"
        f"请把 DEMO_ACCOUNT_EMAIL 指向一个普通账号。"
    )


# ============================================================================
# 4. 守卫 ④：账号被停用
# ============================================================================


async def test_inactive_demo_owner_is_refused(demo_on, monkeypatch, make_user):
    """★★★ 演示账号主人被**停用** ⇒ 无身份（停用必须立刻生效）。

    ★ 造法：用一个**临时用户**当演示账号（`make_user` 自带 teardown 回收），
      而不是去改真实演示用户的 `is_active` —— 那会在用例中途把演示身份弄失效，
      一旦本用例崩在 finally 之前，**后续所有演示相关用例都会连带失败**
      （症状是"另一条用例红了"，归因方向完全错）。

    ★★ 一个**实测发现**（本用例第一版就是这么红的，记下来）：
      注册出来的用户**名下一个容器都没有**（注册只建 users / subscriptions /
      email_tokens），而 `resolve_demo_user` 的 join 要求「主人名下有容器」。
      ⇒ 这里必须显式 `ensure_default_account`，否则本用例会在**正向对照**那步
        就失败，看起来像"守卫 ④ 写错了"，实则只是前置没造齐。
      这条同时也说明守卫 ② 的真实语义是「**查得到一个有容器的主人**」。

    ★ 顺带证明了配置项**真的被读**：先把临时用户设成演示账号 ⇒ 解析成功
      （正向对照），再停用它 ⇒ 解析失败。少了正向对照，"哨兵形同虚设"
      这种 bug 也会让本条绿。
    """
    from sqlalchemy import select

    from core.auth.accounts import ensure_default_account
    from core.auth.demo_identity import resolve_demo_user
    from core.identity.models import User

    owner = await make_user("demoinactive")
    _patch_email(monkeypatch, owner["email"])

    # 前置：给他一个容器（否则 join 命中不了，正向对照必然失败）
    # ★ `ensure_default_account` 只 `flush()` **不 commit**（它服务于"同一事务内
    #   建店+建容器"），所以这里必须自己 commit —— 否则退出 with 时整体回滚，
    #   表现就是"容器没建成"，而断言失败会指向守卫 ④（归因错方向）。
    async with async_session_factory() as db:
        u = (
            await db.execute(select(User).where(User.id == owner["user_id"]))
        ).scalar_one()
        await ensure_default_account(db, u)
        await db.commit()

    # ---- 正向对照：把临时用户设成演示账号，此刻它应当是有效的演示身份 ----
    async with async_session_factory() as db:
        got = await resolve_demo_user(db, allow_demo=True)
    assert got is not None and got.id == owner["user_id"], (
        f"★ 把 config.demo_account_email 指向 {owner['email']!r} 之后解析不出它 —— "
        f"配置项没有真的被读（那样本用例的「停用」断言会恒真）。"
    )

    # ---- 停用它 ⇒ 必须不再构成身份 ----
    async with async_session_factory() as db:
        await db.execute(
            text("UPDATE users SET is_active = false WHERE id = :u"),
            {"u": owner["user_id"]},
        )
        await db.commit()
    try:
        async with async_session_factory() as db:
            got = await resolve_demo_user(db, allow_demo=True)
        assert got is None, (
            "★ 演示账号主人已被停用，却仍然构成有效演示身份 —— "
            "停用是管理动作，必须立刻生效；否则演示身份就是一条绕过封停的通道。"
        )
    finally:
        async with async_session_factory() as db:
            await db.execute(
                text("UPDATE users SET is_active = true WHERE id = :u"),
                {"u": owner["user_id"]},
            )
            await db.commit()


# ============================================================================
# 5. 正向：解析出来的**必须是**演示账号主人
# ============================================================================


async def test_demo_mode_on_resolves_the_demo_account_owner(demo_on, monkeypatch):
    """正向：`demo_mode=True` + 配置齐全 ⇒ 解析出**就是这个 email 的主人**。

    ★ 断言用 `email` 而不是 id：id 是 uuid、换库就变，而
      「解析出来的人就是配置里那个 email」才是这条不变量本身。
    """
    from core.auth.demo_identity import resolve_demo_user

    _patch_email(monkeypatch, DEMO_ACCOUNT_EMAIL)
    async with async_session_factory() as db:
        user = await resolve_demo_user(db, allow_demo=True)

    assert user is not None, (
        f"★ demo_mode 开着、{DEMO_ACCOUNT_EMAIL} 也在库里，却解析不出演示身份 —— "
        f"演示模式会退化成匿名（看不到自己的店铺与技能）。"
    )
    assert user.email == DEMO_ACCOUNT_EMAIL, (
        f"解析出的人是 {user.email!r}，应为 {DEMO_ACCOUNT_EMAIL!r} —— "
        f"演示身份解析到了**别人**身上，这是最严重的一类越权。"
    )


async def test_visible_accounts_equal_exactly_the_demo_account(demo_on):
    """★★★ 「不多不少」：演示身份的可见账户集合**恰好等于**演示账号那一个。

    ★ 这条是老板那句「演示模式等于演示账号，不影响其他真实账号」
      在**可见范围**上的可执行面。两个方向都要堵：
        · 少了 ⇒ 演示模式看不到自己的数据（空壳，功能看着"没做"）；
        · 多了 ⇒ 弹窗里藏着别的账号的归属。

    ★ 反向注入：把 `get_visible_account_ids` 的超管短路改成
      `return None`（不判角色）⇒ 本条转红（`None` 表示"全库不设限"）。
    """
    from core.auth.accounts import get_visible_account_ids
    from core.auth.demo_identity import resolve_demo_user
    from modules.stores.demo import demo_account_id

    expected = await demo_account_id()
    assert expected is not None, f"前置缺失：演示账号（{DEMO_ACCOUNT_EMAIL}）不在库里"

    async with async_session_factory() as db:
        user = await resolve_demo_user(db, allow_demo=True)
        visible = await get_visible_account_ids(db, user)

    assert visible is not None, (
        "★ 演示身份拿到了 `None`（= 可见性不设限 = 全库）—— "
        "它被当成了平台超管。演示模式会看到整个平台的数据。"
    )
    assert set(visible) == {expected}, (
        f"★ 演示身份的可见账户集合 = {sorted(visible)}，"
        f"应为恰好 {{'…{expected[-8:]}'}}。\n"
        f"  多了 ⇒ 演示弹窗里会出现在别的账号的归属下（越权）；\n"
        f"  少了 ⇒ 演示模式连自己的店铺/技能都看不到（空壳）。"
    )


# ============================================================================
# 6. 唯一真源：演示账号 email 只能有一处定义
# ============================================================================


async def test_demo_account_email_has_a_single_truth_source(monkeypatch):
    """★★★ 演示账号 email 的**唯一真源**是 `config.demo_account_email`。

    ★ 为什么必须钉住：第 181 轮之前，店铺侧读的是 `modules/stores/demo.py` 里
      自己的 `os.getenv`，技能侧读门面转发出来的同一个常量 —— 看起来一致，
      但只要有人给其中一处换成别的来源，就会出现
      「演示店铺挂在 A 账号、演示技能挂在 B 账号」而**演示身份只能命中其中之一**
      （表现为"店铺列表有、技能仓库空"这种半死不活的状态）。
      本仓判据：同一判定两份实现 ⇒ 至少一份永远测不到。

    ★ 造法：改**一次** config，然后看两个消费方是否同时跟着变。
      只测其中一方的话，`os.getenv` 那种旧写法照样绿（因为 .env 里恰好配对了）。
    """
    from modules.skills import seed as skill_seed
    from modules.stores import demo_account_email

    probe = f"probe-{uuid.uuid4().hex[:8]}@example.com"
    _patch_email(monkeypatch, probe)

    assert demo_account_email() == probe, (
        "★ 店铺侧的演示账号 email 没跟着 config 走 —— "
        "它有自己的第二份来源（旧形态是 `os.getenv`）。"
    )
    # 技能侧走的是**同一个门面函数**；这里断言它查到的是「按新 email 查不到账号」，
    # 而不是旧 email 名下的那一行 —— 后者才说明两侧不是同一个真源。
    account = await skill_seed.demo_account_row()
    assert account is None, (
        f"★ 技能侧仍然按别的 email 查到了账号（{account!r}）—— "
        f"说明它与店铺侧不是同一个真源（症状：演示店铺在 A 账号、演示技能在 B 账号）。"
    )
    # 门面转发本身也要成立（否则「同一真源」只是巧合）
    assert skill_seed.demo_account_email() == probe, (
        "★ `modules.skills.seed` 用的不是 `modules.stores` 门面里那个函数。"
    )


# ============================================================================
# 7. 跨语言契约：哨兵串必须与前端逐字一致
# ============================================================================


def test_demo_sentinel_prefix_matches_frontend():
    """★ 后端认的前缀与前端发的串必须**逐字一致**。

    ★ 为什么值得一条门禁：这两个常量分处两种语言、两个目录（`core/auth/demo_identity.py`
      与 `frontend/src/config/demoMode.ts`），**改一处不会有任何报错** ——
      症状是"演示模式点了没反应"（后端把哨兵当伪造串 → 401），
      而两端各自看起来都正常。
    """
    from pathlib import Path

    from core.auth.demo_identity import DEMO_SENTINEL_PREFIX

    assert DEMO_SENTINEL_PREFIX == "demo-", (
        f"后端哨兵前缀改成了 {DEMO_SENTINEL_PREFIX!r} —— 前端也要一起改"
    )
    assert DEMO_TOKEN.startswith(DEMO_SENTINEL_PREFIX), (
        f"本文件用的 {DEMO_TOKEN!r} 不满足后端前缀 {DEMO_SENTINEL_PREFIX!r}"
    )

    fe = Path(__file__).resolve().parents[2] / "frontend" / "src" / "config" / "demoMode.ts"
    assert fe.exists(), f"前端 demoMode.ts 不在预期位置：{fe}"
    src = fe.read_text(encoding="utf-8")
    assert "export const DEMO_TOKEN = 'demo-token'" in src, (
        "★ 前端的 DEMO_TOKEN 不再是 'demo-token' —— "
        "后端的哨兵前缀还停在 'demo-'，两端失配（演示模式会静默变成 401）。"
    )


# ============================================================================
# 8. 生产护栏：demo_mode 与 auth_required 不能同时为真
# ============================================================================


def test_production_refuses_demo_mode(prod_settings_kwargs):
    """★ 生产环境打开演示模式 ⇒ **拒绝构造 Settings**（启动期硬拦）。

    ★ 为什么这条在本轮依然重要：第 182 轮把演示身份从"匿名"升级为
      "**一个真用户**" —— 风险等级提高了（匿名只能读 `is_demo` 行，
      真用户能读能写它账号下的全部数据）。所以"生产必须关"这条不但不能松，
      还得确认它真的会**拒绝启动**，而不是打条日志继续跑。
    """
    import pytest
    from pydantic import ValidationError

    from core.config import Settings

    with pytest.raises(ValidationError) as exc:
        Settings(**prod_settings_kwargs(demo_mode=True))
    assert "DEMO_MODE" in str(exc.value), (
        f"生产 + demo_mode=True 没有报出 DEMO_MODE 相关错误：{exc.value}"
    )


def test_production_allows_demo_off(prod_settings_kwargs):
    """反向对照：`demo_mode=False` 的生产配置**必须能构造成功**。

    ★ 少了这条，"护栏写反了"（例如恒抛）也会让上一条绿。
    """
    from core.config import Settings

    s = Settings(**prod_settings_kwargs(demo_mode=False))
    assert s.demo_mode is False
    assert s.demo_account_email, (
        "演示账号 email 的默认值不该为空 —— 本地不配 .env 时演示模式要能直接跑"
    )
