"""
演示数据可见性与隔离守护（第 175 轮建立、第 176 轮按新形态重写）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
老板实测：「演示模式下 UI 上看不到店铺、选品、素材、产品、业务话术、平台规则」。

根因**不是数据丢了**，而是唯一筛法
`core/auth/accounts.py::filter_accessible_stores` 的匿名分支写着：

    if user is None:
        return []        # ← 演示身份（无凭据 / demo-token）永远看不到店铺

这一行本身**是对的** —— 它来自安全修复 `4612abb`（改前是 `return list(stores)`，
也就是匿名请求能拿走**全库真实店铺**）。但演示档下用户**按设计就没有身份**
（前端那条 `demo-token` 不是 JWT，`isDemoToken()` 明确判定），于是：

    `/stores` 恒返回空 → `shopStore.shops = []`
    → `current_shop_id` 写不进 localStorage
    → 所有业务请求不带 `X-Shop-ID`
    → 后端 `get_current_shop_id` 拿不到租户
    → **每个面板都是空的**。

⇒ 修复**不是**把过滤放宽（那等于回退安全修复），而是给演示身份一个**专属数据集**。

==============================================================================
★★★ 第 176 轮为什么重写（老板的第二轮反馈）
==============================================================================
第 175 轮的形态是「新建**一家**无主演示店铺 `store_demo0001`，用 `SEED_*` 灌数据」。
老板实测后：

    「以前的图文是可以一一对应的，现在图片又变成了不对应了（是比一一对应更早的
      版本）；我需要的是演示模式下，有多个店铺（之前的亚马逊1，亚马逊2，虾皮1，
      虾皮2…）；你现在这个好好像是更早的版本图文，并且只设置了1个店铺」
    「应该是一个演示账号，这个账号读取数据库中的 mock 数据，然后店铺和产品都
      无所谓了啊 都在我的演示账号下」

两个问题都在"新建一家店"这个形态本身：
  · **只有 1 家店**，老板要 4 家；
  · 灌的是 `SEED_*`，图片是 `https://picsum.photos/...`（**随机图**，与商品无关），
    而库里早先那批演示数据用的是 `/mock/products/<ASIN>.png`（**图片文件名 = ASIN**，
    严格 1:1）—— 老板要的是后者。

⇒ 第 176 轮把锚点从"新建一家店"改为「**演示账号**」：
  `DEMO_ACCOUNT_EMAIL`（默认 `tenant-test-a@example.com`）名下 4 家店就是数据集。
  `ensure_demo_stores()` 把该账号名下的店铺打上 `is_demo = true`（并清掉不属于
  它的标记），`filter_accessible_stores` 的匿名分支**不变**。

==============================================================================
★★★ 反向注入（两条方向相反，缺一条门禁就是半盲）
==============================================================================
  1. 把演示分支改回 `return []`
     ⇒ `test_no_identity_gets_only_demo_stores` 必须转红。
  2. 把演示分支改成 `return list(stores)`（回退安全修复）
     ⇒ `test_no_identity_never_sees_real_stores` 必须转红。
  只钉一个方向，另一半会静默失守 —— 这正是第 175 轮之前的状态。

★★★ 第 177 轮补的两条（「列表紧、单店松」的统一）：
  3. 把 `core/tenant/middleware.py::_resolve_current_shop_id` 里的
     `if current_user is None: return shop_id` 恢复
     ⇒ `test_no_identity_foreign_shop_id_is_forbidden` 必须转红。
  4. 把 `core/auth/accounts.py::require_account_permission` 的
     `user is None ⇒ 403` 改回 `return None`
     ⇒ `test_no_identity_cannot_transfer_demo_store_into_real_account` 必须转红。
"""

import pytest
from sqlalchemy import text

from core.auth.accounts import filter_accessible_stores
from core.database import async_session_factory


#: 演示账号（演示数据都挂在它名下）
DEMO_ACCOUNT_EMAIL = "tenant-test-a@example.com"

#: 演示账号名下那 4 家店（= 演示模式应当看到的全部）
DEMO_SHOP_IDS = [
    "store_c3529ab1",   # 亚马逊1（数据最全，老板点名"就取它"）
    "store_a498a7d5",   # 亚马逊2
    "store_27a9e7ec",   # 虾皮1
    "store_16f776b2",   # 虾皮2
]

#: 数据最全的那家（老板原话：「其中 store_c3529ab1（亚马逊1）最全」）
SRC_STORE_ID = "store_c3529ab1"

#: 老板自己的账号（`263977396@qq.com`）名下的店 —— 演示模式**绝不能**看见
OTHER_ACCOUNT_EMAIL = "263977396@qq.com"

#: 一家无数据的测试孤店：用来验证"不属于演示账号的标记会被清掉"
STALE_SHOP_ID = "store_33d77cb3"

#: 演示店铺名下应当有数据的表（表名, 列名）
DEMO_SCOPED_TABLES = [
    ("spus", "shop_id"),
    ("assets", "shop_id"),
    ("candidates", "shop_id"),
    ("monitors", "shop_id"),
    ("platform_rules", "shop_id"),
    ("knowledge_bases", "shop_id"),
    ("knowledge_faqs", "shop_id"),
    ("amazon_competitor_snapshots", "store_id"),
]


class _ExplodingSession:
    """任何 IO 都抛 —— 用来证明某分支**零 DB 往返**。

    与 `test_account_store_hierarchy.py` 里的同款：若哪天有人把
    `get_visible_account_ids()` 提到短路之前，本类会用一条明确的 AssertionError
    报出"该分支不应查库"，而不是悄悄多出一次全表查询。
    """

    async def execute(self, *a, **kw):
        raise AssertionError("该分支不应查库（应在 get_visible_account_ids 之前短路）")


def _fake(sid: str, *, account_id=None, owner_id=None, is_demo=None):
    """构造一个轻量 store 对象。

    `is_demo=None` 表示**不带该属性**（模拟 pydantic 老版本 / 测试合成对象）。
    """
    from types import SimpleNamespace

    kw = {"id": sid, "account_id": account_id, "owner_id": owner_id}
    if is_demo is not None:
        kw["is_demo"] = is_demo
    return SimpleNamespace(**kw)


async def _demo_account_id():
    async with async_session_factory() as db:
        return (await db.execute(text("""
            SELECT a.id FROM accounts a JOIN users u ON u.id = a.owner_user_id
            WHERE u.email = :e ORDER BY a.created_at, a.id LIMIT 1
        """), {"e": DEMO_ACCOUNT_EMAIL})).scalar()


# ============================================================================
# 1. 归属内核：演示身份拿到什么
# ============================================================================

async def test_no_identity_gets_only_demo_stores():
    """
    ★★★ 核心判据：演示身份（`user is None`）→ **只有** `is_demo` 的店铺。

    反向注入：把 `filter_accessible_stores` 的演示分支改回 `return []`，
    本用例必须转红（`assert [s.id ...] == []` 会失败）。

    ★ 第 176 轮语义补全：这里的 `is_demo` 不再是"某一家孤零零的演示店铺"，
      而是"**演示账号名下**的店铺"（现在是 4 家）。判定分支一行没改。
    """
    d1 = _fake("s-demo-1", account_id="acct-demo", owner_id="u-demo", is_demo=True)
    d2 = _fake("s-demo-2", account_id="acct-demo", owner_id="u-demo", is_demo=True)
    real_owned = _fake("s-real-1", account_id="acct-1", owner_id="u-1", is_demo=False)
    real_ownerless = _fake("s-real-2", account_id=None, owner_id=None, is_demo=False)

    got = await filter_accessible_stores(
        _ExplodingSession(), None, [d1, d2, real_owned, real_ownerless]
    )

    assert [s.id for s in got] == ["s-demo-1", "s-demo-2"], (
        f"演示身份拿到的不是「全部演示店铺」：{[s.id for s in got]}。"
        f"改回 `return []` 会让演示模式整站空白（第 175 轮的原始缺陷）；"
        f"多给真实店铺则是越权。"
    )


async def test_no_identity_never_sees_real_stores():
    """
    ★★★ 反向守卫：真实店铺对**匿名**仍然不可见。

    这一条守的是安全修复 `4612abb` 的成果。**没有它**，任何"顺手把演示分支
    写成 `return list(stores)`"的改动都会全绿通过 —— 那就回到了"匿名能拿走
    全库真实店铺"的形态（老板当时看到的就是这个：登录后主页显示别人的店）。

    反向注入：把演示分支改成 `return list(stores)`，本用例必须转红。
    """
    real = [
        _fake("s-real-1", account_id="acct-1", owner_id="u-1"),
        _fake("s-real-2", account_id="acct-2", owner_id="u-2"),
    ]
    got = await filter_accessible_stores(_ExplodingSession(), None, real)

    assert got == [], (
        f"匿名拿到了真实店铺：{[s.id for s in got]} —— "
        f"「没有身份 ⇒ 没有真实数据」的守卫失效了（安全修复 4612abb 被回退）。"
        f"演示店铺是**唯一**允许的例外（见上一条用例），不是把口子重新打开。"
    )


async def test_no_identity_gets_demo_stores_even_among_real_ones():
    """演示店铺与真实店铺**混在一起**时，也只挑出演示的那几家（窄口，不是放宽）。"""
    mixed = [
        _fake("s-real-1", account_id="acct-1", owner_id="u-1"),
        _fake("s-demo-1", is_demo=True),
        _fake("s-real-2", account_id="acct-2", owner_id="u-2"),
        _fake("s-demo-2", is_demo=True),
    ]
    got = await filter_accessible_stores(_ExplodingSession(), None, mixed)
    assert [s.id for s in got] == ["s-demo-1", "s-demo-2"], f"{[s.id for s in got]}"


async def test_missing_is_demo_field_is_fail_closed():
    """
    对象**没有** `is_demo` 属性 ⇒ 视为"不是演示店铺"。

    ★ 为什么必须显式钉住：判定写的是 `getattr(s, "is_demo", False)`。
      若哪天有人"顺手简化"成 `getattr(s, "is_demo", True)`（或把整个分支写成
      `return [s for s in stores if getattr(s, 'is_demo', None) is not False]`），
      所有字段缺失的对象都会**被当成演示店铺放行** —— 而字段缺失恰恰是本函数
      的常态（它同时服务 ORM 行、pydantic `Store`、测试用的轻量对象）。
      默认值必须是 **False**（fail-closed），不能是 True。
    """
    no_flag = _fake("s-plain", account_id=None, owner_id=None)   # 刻意不带 is_demo
    got = await filter_accessible_stores(_ExplodingSession(), None, [no_flag])
    assert got == [], (
        f"缺 is_demo 字段的对象被当成了演示店铺：{[s.id for s in got]}。"
        f"该分支的默认值必须是 False（fail-closed）—— 否则字段缺失 = 全部放行。"
    )


# ============================================================================
# 2. 有身份时：谁能看到演示店铺
# ============================================================================

async def test_other_account_user_cannot_see_demo_stores():
    """
    ★★★ 别的账号的用户看不到演示店铺（隔离的**真正**判据）。

    ★ 第 176 轮语义变化（必须在用例里说清）：第 175 轮的演示店铺刻意**无主**，
      所以"真实用户看不到它"是**无账户归属**兜底分支的推论。第 176 轮改为
      "演示店铺属于**演示账号**" ⇒ 演示账号自己的成员**看得见**（那是正常的，
      他就是这个账号的主人），隔离靠的是**账号边界**。

      ⇒ 所以本用例要断言的是：**其它账号**（老板的 `263977396@qq.com`）
        看不到演示账号名下的任何一家店。
    """
    async with async_session_factory() as db:
        demo_acct = await _demo_account_id()
        other_acct = (await db.execute(text("""
            SELECT a.id FROM accounts a JOIN users u ON u.id = a.owner_user_id
            WHERE u.email = :e ORDER BY a.created_at, a.id LIMIT 1
        """), {"e": OTHER_ACCOUNT_EMAIL})).scalar()
        other_user = (await db.execute(text(
            "SELECT id, role FROM users WHERE email = :e"
        ), {"e": OTHER_ACCOUNT_EMAIL})).first()

    assert demo_acct, f"前置缺失：演示账号（{DEMO_ACCOUNT_EMAIL}）不在库里"
    assert other_acct, f"前置缺失：{OTHER_ACCOUNT_EMAIL} 的账号不在库里"

    from types import SimpleNamespace

    user = SimpleNamespace(id=other_user[0], role=other_user[1])
    stores = [
        _fake("s-demo", account_id=demo_acct, owner_id="u-demo", is_demo=True),
        _fake("s-mine", account_id=other_acct, owner_id=user.id, is_demo=False),
    ]

    async with async_session_factory() as db:
        got = await filter_accessible_stores(db, user, stores)
    ids = [s.id for s in got]

    assert "s-demo" not in ids, (
        f"其它账号的用户看到了演示店铺：{ids} —— 账号边界失效，这是跨租户泄漏。"
    )
    assert "s-mine" in ids, (
        f"用户看不到自己的店了：{ids} —— `is_demo` 分支误伤了有身份的判定。"
    )


# ============================================================================
# 3. 数据库事实：is_demo 标记 == 演示账号名下店铺（第 176 轮的核心不变量）
# ============================================================================

async def test_demo_marker_is_derived_from_demo_account():
    """
    ★★★ 本轮的核心不变量：全库 `is_demo = true` 的集合
    **恰好等于**演示账号名下的店铺集合 —— 一家不多、一家不少。

    ★ 为什么这条比第 175 轮的 `test_demo_store_row_is_ownerless_and_unique`
      更值得钉：那条钉的是"恰好一行且无主"（是**形态**），形态一改就得重写；
      这条钉的是"标记**从账号推导**出来"（是**关系**），换演示账号、增减店铺
      都不用改 —— 而一旦有人手工标了一家不属于演示账号的店（或漏标），
      演示模式立刻多/少一家店，这里就会红。
    """
    ns = await _demo_account_id()
    assert ns, f"前置缺失：演示账号（{DEMO_ACCOUNT_EMAIL}）不在库里"

    async with async_session_factory() as db:
        owned = set((await db.execute(text(
            "SELECT id FROM stores_store WHERE account_id = :a"
        ), {"a": ns})).scalars().all())
        marked = set((await db.execute(text(
            "SELECT id FROM stores_store WHERE is_demo IS TRUE"
        ))).scalars().all())

    assert owned, "演示账号名下没有任何店铺 —— 演示模式会整站空白"
    assert marked == owned, (
        f"is_demo 集合 ≠ 演示账号名下店铺。\n"
        f"  只有标记没有归属: {sorted(marked - owned)}（演示模式会显示别人的店）\n"
        f"  只有归属没有标记: {sorted(owned - marked)}（演示模式会少显示店）\n"
        f"两者都必须为空 —— 标记的唯一来源是 `ensure_demo_stores()`。"
    )


async def test_ensure_demo_stores_is_idempotent():
    """标记**幂等**：已是期望状态时返回 0（否则每次启动都写库）。"""
    from modules.stores.demo import ensure_demo_stores

    assert await ensure_demo_stores() == 0, "已是期望状态时不该再改"
    assert await ensure_demo_stores() == 0, "第二次调用也不该改"

    async with async_session_factory() as db:
        n = (await db.execute(text(
            "SELECT count(*) FROM stores_store WHERE is_demo IS TRUE"
        ))).scalar()
    assert n == len(DEMO_SHOP_IDS), f"is_demo 行数 = {n}，应为 {len(DEMO_SHOP_IDS)}"


async def test_ensure_demo_stores_clears_stale_marker():
    """
    ★★ 双向收敛：不属于演示账号的 `is_demo = true` 会被**清掉**。

    ★ 为什么必须有这条：第 175 轮留下的那家无主店 `store_demo0001` 就是这种
      形态（`is_demo=true` 且 `account_id=None`）。若 `ensure_demo_stores()` 只
      "标 True"而不降 False，它会对演示身份**永久可见** —— 演示模式莫名多出
      一家空店，而且没有任何用例会发现。

    做法：把一家**无数据的测试孤店**临时标成演示店铺 ⇒ 跑一次
    `ensure_demo_stores()` ⇒ 断言它被降回 False。失败时用 finally 还原。
    """
    from modules.stores.demo import ensure_demo_stores

    async with async_session_factory() as db:
        row = (await db.execute(text(
            "SELECT id, is_demo FROM stores_store WHERE id = :s"
        ), {"s": STALE_SHOP_ID})).first()
    assert row is not None, f"前置缺失：测试孤店 {STALE_SHOP_ID} 不在库里"

    async with async_session_factory() as db:
        await db.execute(text(
            "UPDATE stores_store SET is_demo = TRUE WHERE id = :s"
        ), {"s": STALE_SHOP_ID})
        await db.commit()

    try:
        changed = await ensure_demo_stores()
        assert changed >= 1, (
            f"残留标记没有被清（changed={changed}）—— 只标 True 不降 False，"
            f"演示模式会永久多出不属于演示账号的店。"
        )
        async with async_session_factory() as db:
            flag = (await db.execute(text(
                "SELECT is_demo FROM stores_store WHERE id = :s"
            ), {"s": STALE_SHOP_ID})).scalar()
        assert flag is False, (
            f"{STALE_SHOP_ID} 不属于演示账号，标记应被清成 False，实际 {flag}"
        )
    finally:
        async with async_session_factory() as db:
            await db.execute(text(
                "UPDATE stores_store SET is_demo = FALSE WHERE id = :s"
            ), {"s": STALE_SHOP_ID})
            await db.commit()


async def test_demo_stores_hold_all_seed_kinds():
    """
    演示店铺（至少数据最全的那家）七类数据都非空 —— 这是**用户体验**的可执行面。

    ★ 判据是"非空"而不是"等于源店铺行数"：源店铺里混着**用户真实新建**的数据
      （10 个产品 / 8 个选品 / 2 个上传素材），那些**不参与**任何判定。
    ★ 老板本轮明确「（补数据）只保证亚马逊1」⇒ 这里只对 `SRC_STORE_ID` 断言。
    """
    async with async_session_factory() as db:
        empty = []
        for tn, col in DEMO_SCOPED_TABLES:
            n = (await db.execute(
                text(f'SELECT count(*) FROM "{tn}" WHERE {col} = :s'),
                {"s": SRC_STORE_ID},
            )).scalar()
            if not n:
                empty.append(tn)
    assert not empty, (
        f"{SRC_STORE_ID}（亚马逊1）在这些表里一行都没有：{empty} —— "
        f"对应的演示面板会是空白的。"
    )


async def test_demo_stores_images_are_one_to_one_with_asin():
    """
    ★★★ 图文一一对应门禁（老板本轮的核心诉求）。

    老板逐字：「以前的图文是可以一一对应的，现在图片又变成了不对应了
    （**是比一一对应更早的版本**）」—— 那句"更早的版本"指的就是
    `https://picsum.photos/seed/...` **随机图**（`SEED_*` 常量里那套）。

    ★ 判据的两条腿（缺一不可）：
      ① 演示店铺里**一条 picsum 都不能有**（它是"图与商品无关"的确凿特征）；
      ② 选品库的 `main_image` 文件名必须**含自己的 ASIN**（图集命名规矩：
         `/mock/products/<ASIN>.png`）。
    ★ 产品库只断言"无 picsum"：它有 2 条历史遗留行的图指向别的 ASIN，而
      对应图片在磁盘上不存在（`B0CAND0002/3.png` 没有），修不了也不该乱改。
    """
    async with async_session_factory() as db:
        n_picsum_c = (await db.execute(text(
            "SELECT count(*) FROM candidates WHERE shop_id = ANY(:s) "
            "AND main_image LIKE '%picsum%'"
        ), {"s": DEMO_SHOP_IDS})).scalar()
        n_picsum_p = (await db.execute(text(
            "SELECT count(*) FROM spus WHERE shop_id = ANY(:s) "
            "AND main_image LIKE '%picsum%'"
        ), {"s": DEMO_SHOP_IDS})).scalar()
        n_picsum_a = (await db.execute(text(
            "SELECT count(*) FROM assets WHERE shop_id = ANY(:s) "
            "AND url LIKE '%picsum%'"
        ), {"s": DEMO_SHOP_IDS})).scalar()

        rows = (await db.execute(text("""
            SELECT asin, main_image FROM candidates
            WHERE shop_id = :s AND main_image IS NOT NULL AND asin IS NOT NULL
        """), {"s": SRC_STORE_ID})).all()

    assert n_picsum_c + n_picsum_p + n_picsum_a == 0, (
        f"演示店铺里出现了 picsum 随机图（选品 {n_picsum_c} / 产品 {n_picsum_p} / "
        f"素材 {n_picsum_a}）—— 那就是老板说的「比一一对应更早的版本」。"
        f"种子常量 `SEED_*` 里用的就是这套图，别把它灌进演示店铺。"
    )
    assert rows, f"前置缺失：{SRC_STORE_ID} 没有带图的选品"
    bad = [a for a, img in rows
           if str(a) not in str(img).rsplit("/", 1)[-1]]
    assert not bad, (
        f"这些选品的图与自己的 ASIN 不对应：{bad}。"
        f"图集规矩是 `/mock/products/<ASIN>.png`（图片文件名 = ASIN）。"
    )


# ============================================================================
# 4. seed 补灌通道：只动点名店铺（能力保留，但启动流程已不再自动调用）
# ============================================================================

async def test_only_for_shop_ids_does_not_touch_other_shops():
    """
    `only_for_shop_ids` 通道**只**为点名店铺补灌，其它店铺行数不变。

    ★ 为什么单列一条：这条通道的风险面在**别的店铺** —— 若过滤写错
      （比如把 `targets` 写成 `shop_ids`），会给**所有**店铺再灌一份，
      症状是"某天发现每个店铺的监控池变成了 12 条"，且不报错。
    """
    from modules.monitors.seed import seed_monitors_if_empty

    async with async_session_factory() as db:
        before = dict((await db.execute(text(
            "SELECT shop_id, count(*) FROM monitors GROUP BY shop_id"
        ))).all())

    # 演示店铺已有数据 ⇒ 幂等分支应把它们全部滤掉 ⇒ 0
    n = await seed_monitors_if_empty(only_for_shop_ids=list(DEMO_SHOP_IDS))
    assert n == 0, (
        f"对已有数据的店铺补灌返回了 {n} 条 —— 幂等判空（`already`）没生效，"
        f"重复启动会把每个店铺的监控池翻倍。"
    )

    async with async_session_factory() as db:
        after = dict((await db.execute(text(
            "SELECT shop_id, count(*) FROM monitors GROUP BY shop_id"
        ))).all())

    assert after == before, (
        f"补灌通道改动了别的店铺：before={before} after={after}"
    )


async def test_only_for_shop_ids_restores_a_wiped_shop():
    """
    反向验证通道**真的会灌**（不只是"永远返回 0"）。

    ★ 第 176 轮改法：第 175 轮这条用例是**删掉演示店铺的 monitors 再补灌** ——
      当时演示店铺是新建的孤店，删得起。第 176 轮演示店铺就是老板的
      亚马逊1/2、虾皮1/2，**绝不能删它们的数据**。所以改成：临时插入一家
      测试店铺，补灌，然后把它和它名下的行删干净。
    """
    from modules.monitors.seed import seed_monitors_if_empty

    # ① 假 id（不在 stores 表）⇒ 必须 0，且不留下孤儿数据
    n_fake = await seed_monitors_if_empty(only_for_shop_ids=["store_not_exists_xyz"])
    assert n_fake == 0, f"为不存在的店铺灌了 {n_fake} 条 —— 会造出永久孤儿数据"

    # ② 真实通道：点名一家**真实存在、但 monitors 为空**的测试孤店
    #
    #    ★ 为什么不新建一家：`stores_store` 的 `discount_template_id` 是
    #      NOT NULL 且**无默认值**（实测），裸 INSERT 容易缺字段直接违约；
    #      而且建完还得连着清理业务行 —— 不如借一家本来就没有监控数据的孤店。
    #    ★ 为什么借 `store_33d77cb3`（隔离店铺-A）：它不在演示账号名下，
    #      动它的 monitors 不会影响演示模式看到的数据；用完立刻删干净。
    tmp_id = STALE_SHOP_ID
    async with async_session_factory() as db:
        await db.execute(text("DELETE FROM monitors WHERE shop_id = :s"), {"s": tmp_id})
        await db.commit()

    try:
        n = await seed_monitors_if_empty(only_for_shop_ids=[tmp_id])
        assert n > 0, (
            "点名一个**空**店铺，补灌返回 0 —— 通道是死的。"
            "若将来要「给新建的演示店铺补灌数据」，这条路已经不通了。"
        )
        async with async_session_factory() as db:
            back = (await db.execute(text(
                "SELECT count(*) FROM monitors WHERE shop_id = :s"
            ), {"s": tmp_id})).scalar()
        assert back == n, f"补灌后行数 = {back}，与返回值 {n} 不一致"
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM monitors WHERE shop_id = :s"), {"s": tmp_id})
            await db.commit()


# ============================================================================
# 5. 端到端：无凭据打真接口
# ============================================================================

async def test_no_identity_store_list_over_http(client):
    """
    ★ 端到端：无凭据 `GET /api/v1/stores` 必须返回**演示账号名下的 4 家店**。

    这条覆盖的正是老板看到的那个界面症状 —— 前端 `fetchShops()` 拿到的
    `stores` 若非空，`shopStore` 会自动选中第一家并把 `current_shop_id` 写进
    localStorage，后续所有请求才带上 `X-Shop-ID`。

    ★ 判据从「恰好 1 家」改成「恰好 4 家且是那 4 家」：老板本轮明确要
      「有多个店铺（之前的亚马逊1，亚马逊2，虾皮1，虾皮2）」。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()

    r = await client.get("/api/v1/stores")
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    stores = r.json()["stores"]
    ids = [s["id"] for s in stores]

    assert sorted(ids) == sorted(DEMO_SHOP_IDS), (
        f"无凭据店铺列表 = {ids}，应为 {sorted(DEMO_SHOP_IDS)}。"
        f"空 ⇒ 演示模式整站空白（第 175 轮的缺陷）；"
        f"含别的账号的店 ⇒ 越权（安全修复 4612abb 被回退）。"
    )
    assert all(s["is_demo"] is True for s in stores), (
        "响应里没带 is_demo=true，前端无法区分演示店铺"
    )
    names = sorted(s["name"] for s in stores)
    assert names == sorted(["亚马逊1", "亚马逊2", "虾皮1", "虾皮2"]), (
        f"店名 = {names}，应为亚马逊1/2、虾皮1/2"
    )


@pytest.mark.parametrize("path", [
    "/api/v1/candidates",
    "/api/v1/assets",
    "/api/v1/spus",
    "/api/v1/platform-rules",
    "/api/v1/monitors",
    "/api/v1/knowledge-base",
])
async def test_demo_store_business_endpoints_are_not_empty(client, path):
    """
    带 `X-Shop-ID: <亚马逊1>` 打六个业务端点 ⇒ 全部 200 且**响应体非空**。

    这是"老板点名的六类数据在演示模式下都看得见"的端到端可执行面。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()

    r = await client.get(path, headers={"X-Shop-ID": SRC_STORE_ID})
    assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:300]}"
    assert len(r.text.strip()) > 2, f"{path} 返回了空响应体 ⇒ 对应面板会是空的"


# ============================================================================
# 6. 单店路径 / X-Shop-ID：与列表**同一处判定**（第 177 轮统一）
# ============================================================================

async def _real_store_id() -> str:
    """从库里真取一家**非演示**店铺（不硬编码：数据一变就假红/假绿）。"""
    async with async_session_factory() as db:
        return (await db.execute(text(
            "SELECT id FROM stores_store WHERE is_demo = false ORDER BY id LIMIT 1"
        ))).scalar()


async def test_no_identity_foreign_shop_id_is_forbidden(auth_off, client):
    """
    ★★★ 第 177 轮的核心靶子：**演示身份 + 伪造 `X-Shop-ID` 打真实店铺 ⇒ 403**。

    第 175/176 轮只收口了列表入口，`middleware.py::_resolve_current_shop_id` 里
    还留着 `if current_user is None: return shop_id` ⇒ 归属校验**整段被跳过** ——
    于是"列表只有演示店铺、单店详情对任何 id 仍可读"。同一件事两份实现，
    必然有一份永远测不到（体检报告 P1-5）。

    ★ 反向注入：把那两行恢复，本条必须转红（会 200）。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()
    real_id = await _real_store_id()
    assert real_id, "前置缺失：库里没有非演示店铺"
    assert real_id not in DEMO_SHOP_IDS, "取到的竟是演示店铺，前置假设不成立"

    for path in ("/api/v1/spus", "/api/v1/candidates", "/api/v1/monitors"):
        r = await client.get(path, headers={"X-Shop-ID": real_id})
        assert r.status_code == 403, (
            f"★★★ 演示身份用 `X-Shop-ID: {real_id}` 读到了**真实店铺**的业务数据"
            f"（{path} -> {r.status_code}）—— 单店路径比列表松（P1-5 未结清）。"
            f" {r.text[:200]}"
        )


async def test_no_identity_demo_shop_id_is_allowed(auth_off, client):
    """
    对照实验：同一入口、同一个 `X-Shop-ID` 头，指向**演示店铺** ⇒ 200。

    ★ 只看 403 不看 200 是不够的 —— 一个"把演示档整体打死"的改动也能让上面那条
      绿，却把老板要的「演示模式下有演示模式的店铺和相关数据」一起毁掉。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()

    r = await client.get("/api/v1/spus", headers={"X-Shop-ID": SRC_STORE_ID})
    assert r.status_code == 200, (
        f"演示店铺自己的数据被挡了（{r.status_code}）—— 收紧播及了演示数据。"
        f" {r.text[:200]}"
    )


async def test_no_identity_real_store_detail_is_forbidden(auth_off, client):
    """`GET /stores/{id}`：演示身份取真实店铺详情 ⇒ 403（不是 404，不泄露存在性）。

    ★★ 钉住它的**不是**中间件（反向注入实测得出，别误记）：本端点根本不带
      `X-Shop-ID` —— 归属由 `_get_store` + `_ensure_store_access`
      → `can_access_store` 给出。所以「把 middleware 里
      `if current_user is None: return shop_id` 恢复回去」时本条**照旧绿**，
      只有 `_matches` 的演示分支被改坏才会红。
      两条路径各由不同机制守，不要把它们当成同一条门禁。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()
    real_id = await _real_store_id()

    r = await client.get(f"/api/v1/stores/{real_id}")
    assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"


async def test_no_identity_demo_store_detail_is_allowed(auth_off, client):
    """`GET /stores/{id}`：演示身份取演示店铺详情 ⇒ 200。"""
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()

    r = await client.get(f"/api/v1/stores/{SRC_STORE_ID}")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"


async def test_no_identity_cannot_transfer_demo_store_into_real_account(auth_off, client):
    """
    ★★★ 实施中发现的**第二个**越权口子（账户级能力门）。

    `transfer_store` 的第二道门
    `require_account_permission(db, current_user, target, "store.write")`
    在 `user is None` 时**返回 None（放行）** ⇒ 演示身份能把一家演示店**转进
    任意真实账户** —— 对方团队列表里凭空多出一家 `is_demo=True` 的店，
    正是本轮指令禁止的「影响其他真实账号」。

    ★ 反向注入：把 `require_account_permission` 的 `user is None ⇒ 403` 改回
      `return None`，本条必须转红（会 200）。

    ★★★ 为什么整个请求-断言段包在 `try/finally` 里（**实测事故换来的**）：
      transfer 是**真实写操作**。在反向注入场景下，本用例会在 `assert 403`
      处立即中止 —— 而那时写**已经提交**，"归属必须原样"的收尾断言根本不会
      执行 ⇒ 演示店铺被永久搬进真实账户。实测发生过：`store_c3529ab1`
      （亚马逊1）就这样掉出演示集，且**没有任何夹具兜底**
      （`make_user` 的清理只覆盖"测试用户自己创建的店"）。
      ⇒ 凡是"断言会因注入而失败、失败前又已经写库"的用例，都必须自带
        `finally` 还原。反向注入靶子的副作用必须由靶子自己兜住。
    """
    from modules.stores.router import load_stores_into_memory

    await load_stores_into_memory()

    async with async_session_factory() as db:
        real_account = (await db.execute(text("""
            SELECT a.id FROM accounts a JOIN users u ON u.id = a.owner_user_id
            WHERE u.email = :e ORDER BY a.created_at, a.id LIMIT 1
        """), {"e": OTHER_ACCOUNT_EMAIL})).scalar()
    assert real_account, f"前置缺失：{OTHER_ACCOUNT_EMAIL} 名下没有账户"

    demo_account = await _demo_account_id()
    async with async_session_factory() as db:
        row = (await db.execute(text(
            "SELECT account_id, is_demo FROM stores_store WHERE id = :i"
        ), {"i": SRC_STORE_ID})).first()
    assert row is not None, f"前置缺失：{SRC_STORE_ID} 不在库里"
    before, before_demo = row[0], row[1]
    assert before == demo_account, (
        f"前置不成立：{SRC_STORE_ID} 当前归属 {before}，应为演示账号 {demo_account}。"
        f"（若这里红，说明显式演示店曾被搬走 —— 先修数据再跑本用例。）"
    )
    assert before != real_account, "前置不成立：演示店已经在目标账户下了"

    try:
        r = await client.post(
            f"/api/v1/stores/{SRC_STORE_ID}/transfer",
            json={"account_id": real_account},
        )
        assert r.status_code == 403, (
            f"★★★ 演示身份把演示店转进了真实账户（{r.status_code}）—— "
            f"对方团队列表会凭空多出一家演示店，违反「不影响其他真实账号」。"
            f" {r.text[:200]}"
        )

        # 403 之后不许有副作用：归属必须原样
        async with async_session_factory() as db:
            after = (await db.execute(text(
                "SELECT account_id FROM stores_store WHERE id = :i"
            ), {"i": SRC_STORE_ID})).scalar()
        assert after == before, f"403 之后归属仍被改动：{before} -> {after}"
    finally:
        # 无论断言过没过，都把 (account_id, is_demo) 拨回快照值
        async with async_session_factory() as db:
            await db.execute(
                text("UPDATE stores_store SET account_id = :a, is_demo = :d "
                     "WHERE id = :i"),
                {"a": before, "d": before_demo, "i": SRC_STORE_ID},
            )
            await db.commit()
        await load_stores_into_memory()   # `GET /stores` 读的是内存缓存
