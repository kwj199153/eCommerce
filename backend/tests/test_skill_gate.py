"""技能归属 / 版本 / 端到端 —— 门禁（第 181 轮 · 批 B）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
老板本轮要的「全局 Skill 管理 + Agent 内勾选启用 + 演示账号有示例」，
落地后有四类东西**看起来都对、实际不生效**：

① **可见性判定被抄成第二份**。`visibility` / `is_demo` / `account_id` 三者
   必须走**同一个内核**（`_matches_skill` → `_matches`）。抄一份的后果是
   「列表入口收紧了、单条路径还是松的」—— 本仓第 177 轮 P1-5 就是这个形态。

② **`private` 被后台任务无声降级成「公开」**。`ensure_demo_skills()` 会把
   演示账号名下的**全部**技能标成 `is_demo=True`（含该账号成员自己设成
   `private` 的）。若 `private` 档对演示身份不设防，一行 private 技能就会
   落到 `_matches` 的 `is_demo` 窄口 ⇒ 对匿名演示可见。

③ **写端点的两道门被搓成一道**（★ 第 182 轮改写）。
   写口需要**两个独立的判定**，缺任一侧都会出问题：
     · **能力门**（`router._reject_no_identity`）：说不清你是谁就不能写；
     · **归属门**（`ensure_can_access_skill`）：只能写**你账号下**的。
   第 181 轮：演示身份恒为 `None` ⇒ 能力门把它挡在门外（整体只读）；
   第 182 轮：演示身份解析成**真 `User`** ⇒ 能力门对它放行（老板要的"全套功能"）。

   ⇒ 现在必须**同时**钉住两件事，否则任一侧失衡都是假绿：
     「演示身份**能**写自己的」`test_demo_identity_can_write_skills`
     「演示身份**不能**写别人的」`test_demo_identity_still_cannot_write_outside_its_account`
     只测前者：一个把归属门一并删掉的实现全绿；只测后者：功能其实没打开也全绿。

④ **版本号变成没有真源的可编辑字符串**。判据是「**正文**变了才产生新版本」；
   若按「调了 update 就 +1」，用户改个标题就跳一个版本，版本号迅速失去意义。
   回滚不能删历史 —— 否则「回滚过」这个动作本身没有可追溯性。

==============================================================================
★ 反向注入清单（每条必须真的能转红，见文件末尾注释）
==============================================================================
 1. `filter_accessible_skills` 演示分支改成 `return list(skills)`
    ⇒ `test_demo_filter_never_returns_real_skills` 转红。
 2. `filter_accessible_skills` 演示分支改成 `return []`
    ⇒ `test_demo_filter_keeps_only_demo_skills` / 端到端列表用例转红。
 3. `_matches_skill` 的 private 档改回「对 user is None 落到 `_matches`」
    ⇒ `test_private_skill_is_never_visible_to_demo_identity` 转红。
 4. `core/auth/demo_identity.py::resolve_demo_user` 改成 `return None`
    （= 回退到第 181 轮的"演示身份 = 匿名"形态）
    ⇒ `test_demo_identity_can_write_skills` 转红（201 变 403）。★ 已实测
 5. `router.update_skill` 里删掉 `await ensure_can_access_skill(...)`（归属门）
    ⇒ `test_demo_identity_still_cannot_write_outside_its_account` 转红。
    同族靶子：`accounts._matches_skill` 的 private 档、`get_visible_account_ids`。
 6. `update_skill` 里把「比对正文」改成「无条件 bump_version」
    ⇒ `test_only_body_change_bumps_version` 转红。
 7. `rollback_skill` 改成先删历史再写回
    ⇒ `test_rollback_keeps_history` 转红。
 8. `seed.DEMO_SKILLS` 里把 `review-pain-mining` 的 `agents` 改回
    `["review_analyst"]`（= 回退到第 189 轮修正前的形态）
    ⇒ `test_demo_skill_anchor_tool_is_reachable_from_its_agent` 转红。
    ★ 已实测（第 189 轮）
 9. `service.tool_usage` 里的 `filter_accessible_skills(db, user, rows)` 换成 `rows`
    ⇒ `test_tool_usage_reverse_index_over_http` 转红（匿名身份会看见真实账号的
    技能引用）。★ 已实测（第 208 轮）
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from core.database import async_session_factory


# ============================================================================
# 夹具与工具
# ============================================================================


class _ExplodingSession:
    """任何 IO 都抛 —— 用来证明某分支**零 DB 往返**。

    与 `test_demo_store.py` / `test_account_store_hierarchy.py` 里的同款：
    若哪天有人把 `get_visible_account_ids()` 提到短路之前，本类会用一条明确的
    AssertionError 报出「该分支不应查库」，而不是悄悄多出一次全表查询。
    """

    async def execute(self, *a, **kw):
        raise AssertionError("演示分支不应查库（应在 get_visible_account_ids 之前短路）")


# ★ `skill_owner` 夹具**已提升到 conftest**（第 188 轮）——
#   理由与 `demo_on`/`demo_off` 第 182 轮的提升相同：出现了第二个消费者
#   （`test_skill_icon.py`），而它的清理逻辑涉及 SET NULL 外键的坑，
#   复制一份出去就是"改一处漏一处"。此处不再保留本地定义。


async def _load_user(db, user_id):
    from core.identity.models import User

    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


def _user(uid: str = "u-real"):
    """轻量用户对象（`_matches_skill` 只读 `.id` 与角色）。"""
    return SimpleNamespace(id=uid, role="user")


def _skill_row(sid, *, account_id=None, owner_id=None, is_demo=None, visibility=None):
    """轻量技能对象；`None` = **不带该属性**（模拟老版本 / 合成对象）。"""
    kw = {"id": sid, "account_id": account_id, "owner_id": owner_id}
    if is_demo is not None:
        kw["is_demo"] = is_demo
    if visibility is not None:
        kw["visibility"] = visibility
    return SimpleNamespace(**kw)


def _decide(obj, user, visible):
    """按 `filter_accessible_skills` 的**同一口径**判定（含归属访问器）。

    ★ 刻意不直接调 `_matches_skill` 塞裸参：访问器那层（字段缺失 ⇒ fail-closed）
      也是判据的一部分，绕开它就等于少测一半。
    """
    from core.auth.accounts import (
        _matches_skill,
        skill_account_id,
        skill_is_demo,
        skill_owner_id,
        skill_visibility,
    )

    return _matches_skill(
        skill_account_id(obj),
        skill_owner_id(obj),
        visible,
        user,
        skill_is_demo(obj),
        skill_visibility(obj),
    )


DEMO_ACCOUNT_EMAIL = "tenant-test-a@example.com"

#: 前端演示哨兵串（必须与 `frontend/src/config/demoMode.ts::DEMO_TOKEN` 一致）。
#: ★ 只在这里写一次：它同时是"演示身份的凭据"和"后端要认的前缀"
#:   （`core/auth/demo_identity.py::DEMO_SENTINEL_PREFIX == "demo-"`）。
DEMO_TOKEN = "demo-token"

#: 演示身份发请求时带的头（第 182 轮起它**不再等于匿名**：后端会把它解析成
#: 演示账号主人，因此写口放行、归属落在演示账号下）。
_DEMO_HEADERS = {"Authorization": f"Bearer {DEMO_TOKEN}"}


# ============================================================================
# 1. 归属内核（纯函数，零 IO）—— 演示身份 / 账户 / private / 字段缺失
# ============================================================================


def test_demo_identity_sees_only_demo_skills():
    """★★★ 核心判据：演示身份（`user is None`）**只**看得见 `is_demo` 的技能。

    ★ 这条与店铺侧是同一句话在另一种资源上的实例（第 177 轮「统一」）。
    """
    demo = _skill_row("s-demo", account_id="acct-demo", owner_id="u-demo", is_demo=True)
    real = _skill_row("s-real", account_id="acct-1", owner_id="u-1", is_demo=False)

    assert _decide(demo, None, None) is True, "演示身份看不到演示技能 ⇒ 技能仓库页空白"
    assert _decide(real, None, None) is False, "演示身份看到了真实技能 ⇒ 跨租户泄漏"


def test_demo_identity_never_sees_skills_without_the_flag():
    """演示身份 + 一堆真实技能 ⇒ **一个都不给**（不是"给一部分"）。

    反向注入：把 `filter_accessible_skills` 的演示分支改成 `return list(skills)`
    ⇒ 本条必须转红（这正是安全修复 `4612abb` 被回退的形态）。
    """
    reals = [
        _skill_row("s-real-1", account_id="acct-1", owner_id="u-1"),
        _skill_row("s-real-2", account_id="acct-2", owner_id="u-2"),
    ]
    got = [s for s in reals if _decide(s, None, None)]
    assert got == [], (
        f"匿名拿到了真实技能：{[s.id for s in got]} —— "
        f"「没有身份 ⇒ 没有真实数据」的守卫失效了。"
    )


def test_missing_is_demo_field_is_fail_closed():
    """对象**没有** `is_demo` 属性 ⇒ 视为"不是演示技能"。

    ★ 为什么必须显式钉住：字段缺失是本函数的常态（它同时服务 ORM 行、
      pydantic 模型、测试用的轻量对象）。默认值若是 `True`，
      「字段缺失」就等于「全部放行」。
    """
    plain = _skill_row("s-plain", account_id=None, owner_id=None)   # 刻意不带 is_demo
    assert _decide(plain, None, None) is False, (
        "缺 `is_demo` 字段的对象被当成了演示技能放行 —— 默认值必须是 False"
    )


def test_missing_visibility_is_treated_as_account_scope():
    """`visibility` 字段缺失 ⇒ 按 `account` 处理，**不会**变成人人可见。

    ★ 关键：`account` 档仍要过账户集合判定，所以「缺失」只是没有额外收紧，
      不是放宽。若默认成了 `private` 又会把同账号同事的技能误藏。
    """
    plain = _skill_row("s-plain", account_id="acct-1", owner_id="u-1")   # 不带 visibility
    assert _decide(plain, _user("u-1"), frozenset({"acct-1"})) is True
    assert _decide(plain, _user("u-9"), frozenset({"acct-9"})) is False


def test_real_user_sees_only_their_accounts_skills():
    """有身份 ⇒ 按 `account_id ∈ 可见账户集合`，跨账号一律不可见。"""
    mine = _skill_row("s-mine", account_id="acct-1", owner_id="u-1")
    other = _skill_row("s-other", account_id="acct-2", owner_id="u-2")

    visible = frozenset({"acct-1"})
    assert _decide(mine, _user("u-1"), visible) is True
    assert _decide(other, _user("u-1"), visible) is False


def test_private_visibility_is_creator_only():
    """`private` = **仅创建者可见**：同账号的同事也看不到。

    ★ 钉住它的理由：`visibility` 是本仓明令「必须真参与判定」的字段
      （有字段但不判 = 死重量）。若 private 档被简化掉，
      UI 上那个「权限」单选框就成了纯装饰。
    """
    mine = _skill_row("s-priv", account_id="acct-1", owner_id="u-1", visibility="private")

    assert _decide(mine, _user("u-1"), frozenset({"acct-1"})) is True, (
        "创建者自己看不到自己的 private 技能"
    )
    assert _decide(mine, _user("u-2"), frozenset({"acct-1"})) is False, (
        "★ 同账号的同事看到了 private 技能 —— 「仅创建者可见」没有生效"
    )


def test_private_skill_is_never_visible_to_demo_identity():
    """★★★ `private` 技能**永远不对匿名演示可见**，哪怕它被标了 `is_demo=True`。

    ★ 这条守的是一条**真的会发生**的降级链：
      `ensure_demo_skills()` 把演示账号名下的**全部**技能都标成 `is_demo=True`
      （含该账号成员自己设成 `private` 的）⇒ 若 private 档对 `user is None`
      不设防，判定就会落到 `_matches` 的 `is_demo` 窄口 ⇒ **对匿名可见**。
      那等于一条后台收敛任务把「private」无声降级成「公开」。

    ★ 反向注入：把 `_matches_skill` 的 private 分支改回
      `if user is not None and ...`（即让演示身份落到 `_matches`）
      ⇒ 本条必须转红。
    """
    leaked = _skill_row(
        "s-priv-demo",
        account_id="acct-demo",
        owner_id=None,        # ← 无主：`_matches` 的过渡期兜底分支也够不着它
        is_demo=True,         # ← 被后台任务标记为演示
        visibility="private",
    )
    assert _decide(leaked, None, None) is False, (
        "★ 一份 `private` 技能对匿名演示可见 —— "
        "「仅创建者可见」被 `ensure_demo_skills()` 的 is_demo 标记无声降级成了「公开」。"
        "演示身份没有『创建者』可言，所以 private 档对它只能回答『不可见』。"
    )


def test_platform_admin_still_sees_private_skills():
    """平台超管在 private 档上同样短路放行（`visible is None`）。

    ★ 只看 "private 对演示不可见" 而不看这条是不够的 —— 一个「把 private 打死」
      的改动也能让上一条绿，却把超管的运维可见性一起毁掉。
    """
    priv = _skill_row("s-priv", account_id="acct-1", owner_id="u-1", visibility="private")
    assert _decide(priv, _user("admin-1"), None) is True


def test_ownership_kernel_delegates_to_the_store_kernel():
    """★★ 技能判定必须**真的调用** `_matches`，不是抄一遍它的分支。

    ★ 为什么这条值得单独钉：抄一遍会造出**第二份**「演示/账户」口径，
      两份必然有一份永远测不到（体检报告 P1-5）。判据用「源码里出现
      `return _matches(`」这个**调用形态**，而不是行为 —— 行为在分支穷尽时
      看不出差别，形态可以。
    """
    import inspect

    from core.auth.accounts import _matches_skill

    src = inspect.getsource(_matches_skill)
    assert "return _matches(" in src, (
        "`_matches_skill` 里没有 `return _matches(` —— 它把店铺侧的归属分支抄了一遍，"
        "那会造出第二份「演示/账户」口径（本仓明令禁止，第 177 轮 P1-5 收掉的就是它）。"
    )


# ============================================================================
# 2. 列表筛选：演示分支**零 DB 往返**
# ============================================================================


async def test_demo_filter_makes_no_db_round_trip():
    """★★ 演示分支必须在 `get_visible_account_ids()` **之前**短路。

    ★ 为什么钉：这只是性能吗？不是。短路位置同时表达了「演示身份的可见性
      **不来自数据库查询**」—— 一旦有人把查询提到前面，
      「查不到账户集合 ⇒ 空集 ⇒ 什么都看不到」会把演示模式整体打死，
      而那是**运行期依赖 DB 状态**的行为（本地库没起来、表还没建都会触发）。
    """
    from core.auth.accounts import filter_accessible_skills

    demo = _skill_row("s-demo", account_id="acct-demo", owner_id="u-demo", is_demo=True)
    real = _skill_row("s-real", account_id="acct-1", owner_id="u-1", is_demo=False)

    got = await filter_accessible_skills(_ExplodingSession(), None, [demo, real])
    assert [s.id for s in got] == ["s-demo"], f"{[s.id for s in got]}"


async def test_real_user_filter_still_uses_the_db_session():
    """对照实验：有身份时**确实**要查库（否则上一条可能只是"永远短路"的假绿）。"""
    from core.auth.accounts import filter_accessible_skills

    with pytest.raises(AssertionError):
        await filter_accessible_skills(
            _ExplodingSession(), _user("u-1"), [_skill_row("s-1", account_id="acct-1")]
        )


# ============================================================================
# 3. 版本语义（真库）—— 只有正文变化才产生新版本；回滚不删历史
# ============================================================================


async def test_only_body_change_bumps_version(skill_owner):
    """★★★ 只有**正文**变化才产生新版本与快照。

    ★ 反向注入：把 `update_skill` 里那段 `if new_content != (row.content or "")`
      改成无条件 bump ⇒ 本条必须转红。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ver"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await service.create_skill(
            db, user,
            {"name": name, "title": "标题", "description": "描述", "content": "正文v1"},
            account_id=account.id,
        )
        sid = created["id"]
        assert created["version"] == "1.0.0"

        # 建档即留一条快照（否则"最初那版长什么样"在改过之后无从查证）
        revs = await service.list_revisions(db, sid)
        assert len(revs) == 1 and revs[0]["action"] == "create", (
            f"建档时没有留下初始快照：{[(r['action'], r['version']) for r in revs]}"
        )

        # ① 只改元数据 / 权限 / 勾选 ⇒ 版本不动、历史不增
        #
        # ★ 工具名必须是**平台已注册**的：第 185 轮起写口会拒绝未注册的工具名
        #   （`service._validate_tools`）。这里原先是 `["search_faq"]` ——
        #   **那时它是未注册的**：客服模块的工具住在当时**悬空**的
        #   `customer_service_tools` 里（全仓没有任何 Agent 绑定它）。
        #   旧测试能过，正是因为**当时不校验存在性**，而那个形态恰好就是第 185 轮
        #   要修掉的：存得进去、跑不起来、且不报错。
        #   ★ 第 204 轮起 `search_faq` 已随接线登记入表 ⇒ 它现在是合法名字；
        #     本用例仍用 `set_theme`（店秘书的工具），因为它要钉的是
        #     「元数据更新里的 tools 落库」，与具体是哪个工具无关。
        row = await service.get_skill_row(db, sid)
        await service.update_skill(db, user, row, {
            "title": "新标题",
            "description": "新描述",
            "enabledAgents": ["secretary"],
            "visibility": "private",
            "tools": ["set_theme"],
        })
        after_meta = service.serialize(
            await service.get_skill_row(db, sid), include_content=True
        )
        assert after_meta["tools"] == ["set_theme"], (
            "元数据更新里的 tools 没有落库 —— 新的那一档校验把合法值也拦了？"
        )
        assert after_meta["version"] == "1.0.0", (
            f"只改了元数据却跳版本：1.0.0 -> {after_meta['version']}。"
            f"版本号一改描述就跳，会迅速失去意义。"
        )
        assert len(await service.list_revisions(db, sid)) == 1, (
            "只改元数据就落了新快照 ⇒ 版本历史变成「每次保存都有一条」的流水账"
        )

        # ①b ★★ 带 `content` 键但**内容逐字未变** ⇒ 同样不许跳版本。
        #
        #    ★ 为什么必须有这一档（反向注入实测）：前端保存时**总是整份提交**
        #      （含未改动的正文），所以「content 在、值没变」是**真实形态**。
        #      而 ① 那次更新压根不带 content 键 ⇒ 它进不到 `new_content != row.content`
        #      那个比对里 —— 实测把 `if new_content != (row.content or ""):`
        #      改成 `if True:` 时，只有 ① 的本用例**仍然绿**。
        await service.update_skill(db, user, await service.get_skill_row(db, sid), {
            "title": "又一次改标题",
            "content": "正文v1",          # ← 与当前正文逐字相同
        })
        unchanged = service.serialize(
            await service.get_skill_row(db, sid), include_content=True
        )
        assert unchanged["version"] == "1.0.0", (
            f"正文**没变**却跳了版本：1.0.0 -> {unchanged['version']} ⇒ "
            f"前端每点一次保存就落一个新版本，版本号迅速失去意义"
        )
        assert len(await service.list_revisions(db, sid)) == 1, (
            "正文没变却落了新快照 ⇒ 版本历史变成「每次保存都有一条」的流水账"
        )

        # ② 改正文 ⇒ 版本 +1、历史 +1
        await service.update_skill(db, user, await service.get_skill_row(db, sid), {
            "content": "正文v2",
        })
        after_body = service.serialize(
            await service.get_skill_row(db, sid), include_content=True
        )
        assert after_body["version"] == "1.0.1", f"正文变了但版本没跳：{after_body['version']}"
        revs2 = await service.list_revisions(db, sid)
        assert len(revs2) == 2
        assert {r["action"] for r in revs2} == {"create", "update"}
        assert revs2[0]["content"] == "正文v2", "最新一条快照不是刚写进去的正文"


async def test_write_rejects_unregistered_tool_names(skill_owner):
    """★★★ 写口必须拒绝**未注册**的工具名（第 185 轮修掉的缺陷）。

    ★ 它拦的是一个「存得进去、跑不起来、不报错」的配置：

      在此之前 `tools` 走 `_normalize_tools`，只做「去空 / 去重 / 保序」，
      **完全不校验存在性**。而前端那个自由输入框的 placeholder 举例正是
      `export_report` —— 一个全仓不存在的工具名。用户可以把它存进技能，然后：
        · 模型不会调它（这个工具不在**任何** Agent 的 `bind_tools` 清单里）；
        · 界面照常显示这个 tag，看不出异常；
        · 保存时没有任何提示。
      ⇒ 一个**静默无效**的配置。本用例把「写口拒绝」这件事钉住。

    ★ 五条断言各有分工：
      ① 拒绝必须发生（否则用户照样存得进去）
      ② 拒绝必须**无副作用**（库里不留半成品 —— 否则"拒绝"只是报了个错，
         数据已经脏了）
      ③ 合法值必须**原样保序**通过（防「一刀切拦掉所有值」这种假实现）
      ④ 更新时拒绝必须**原子**（旧绑定不能被改坏，"改一半"比不改更糟）
      ⑤ 空列表合法（= 纯提示词技能，不能被误拦）

    ★ 反向注入：把 `_validate_tools` 里的 `is_known_tool` 检查删掉 ⇒ 本条转红。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-tg"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        # ① + ② 新建时给一个**不存在**的工具名 ⇒ 拒绝，且库里不留半成品
        with pytest.raises(ValueError):
            await service.create_skill(
                db, user,
                {
                    "name": name,
                    "title": "标题",
                    "description": "描述",
                    "content": "正文",
                    "tools": ["export_report"],   # ← 那个假 placeholder 的名字
                },
                account_id=account.id,
            )
        assert await service.get_skill_by_name(db, name) is None, (
            "拒绝了非法工具名，却在库里留下了半成品技能 —— "
            "「拒绝」必须发生在任何写入之前"
        )

        # ③ 真实的工具名 ⇒ 放行，并**原样保序**存下（故意与字母序相反）
        created = await service.create_skill(
            db, user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "tools": ["switch_shop", "set_theme"],
            },
            account_id=account.id,
        )
        assert created["tools"] == ["switch_shop", "set_theme"], (
            f"合法工具名被改动了：{created['tools']}（应原样保序）"
        )

        # ④ 更新时给假名 ⇒ 拒绝，且**已有的绑定保持不变**
        row = await service.get_skill_row(db, created["id"])
        with pytest.raises(ValueError):
            await service.update_skill(db, user, row, {"tools": ["export_report"]})
        fresh = service.serialize(await service.get_skill_row(db, created["id"]))
        assert fresh["tools"] == ["switch_shop", "set_theme"], (
            f"拒绝之后绑定被改坏了：{fresh['tools']} —— "
            f"硬拒绝必须是原子的（要么全改、要么一个字段都不动）"
        )

        # ⑤ 空列表是合法的（= 纯提示词技能），不能被误拦
        await service.update_skill(
            db, user, await service.get_skill_row(db, created["id"]), {"tools": []}
        )
        cleared = service.serialize(await service.get_skill_row(db, created["id"]))
        assert cleared["tools"] == [], "清空工具绑定被拦了 —— 纯提示词技能应当是合法的"


async def test_bound_tools_reach_the_model_through_load_skill(skill_owner):
    """★★★ 端到端：勾选的工具真的会随 `load_skill` 的返回文本到达模型。

    ★ 这是「工具技能」这个概念**唯一的落地证据**。第 185 轮之前
      `skills.tools` 的执行侧消费者为零（`build_skill_tools()` 恒返回
      1 个 `load_skill`，与有没有绑定无关）⇒ 界面上勾了等于没勾，
      而这条链路上**没有任何一处会报错**。

    ★ 为什么"附清单"是必要的而不是锦上添花：模型的 `bind_tools` 清单比
      技能声明的更宽（同一 Agent 上挂着 5–9 个工具），技能的作用正是把
      那一次执行**收窄**到该场景该用的那个。

    ★ 反向注入：把 `render_skill_body` 末尾的 `render_skill_tools(...)` 去掉
      ⇒ 本条转红（`set_theme` 不再出现在返回文本里）。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-bind"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        await service.create_skill(
            db, user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "按下面步骤执行。",
                "tools": ["set_theme"],
                "enabledAgents": ["secretary"],
            },
            account_id=account.id,
        )

        text = await service.read_skill_for_agent(db, user, "secretary", name)
        assert text, "该技能对 secretary 启用了，却读不到正文"
        assert "set_theme" in text, (
            f"绑定的工具没有进入 load_skill 的返回文本：{text!r}\n"
            f"⇒ 模型只看到「去设置主题」，却在自己的工具表里猜名字 —— "
            f"猜错就是一次无效调用。"
        )
        # 不得把**没绑**的工具也塞进去：那会把技能的"收窄"作用抵消掉
        assert "analyze_profit" not in text, (
            "正文里出现了未绑定的工具 —— 工具段必须只含该技能声明的那些"
        )

        # 三重过滤的第二重（对该 Agent 启用）仍然生效：换个 Agent 读不到
        assert await service.read_skill_for_agent(db, user, "ListingGenerator", name) is None


async def test_rollback_keeps_history(skill_owner):
    """★★★ 回滚 = 把历史正文写回 + **落一条新的** revision，**不删历史**。

    ★ 反向注入：把 `rollback_skill` 改成"先删历史再写回" ⇒ 本条必须转红。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-rb"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await service.create_skill(
            db, user, {"name": name, "content": "第一版"}, account_id=account.id
        )
        sid = created["id"]

        await service.update_skill(db, user, await service.get_skill_row(db, sid), {
            "content": "第二版",
        })
        revs = await service.list_revisions(db, sid)
        assert len(revs) == 2
        create_rev = [r for r in revs if r["action"] == "create"][0]

        result = await service.rollback_skill(
            db, user, await service.get_skill_row(db, sid), create_rev["id"]
        )
        assert result is not None, "回滚返回 None（该版本查不到）"
        assert result["content"] == "第一版", f"正文没被写回：{result['content']!r}"

        revs2 = await service.list_revisions(db, sid)
        assert len(revs2) == 3, (
            f"回滚后历史条数 = {len(revs2)}，应为 3（create + update + rollback）。"
            f"回滚若删历史，「回滚过」这个动作本身就没有可追溯性。"
        )
        assert {r["action"] for r in revs2} == {"create", "update", "rollback"}, (
            f"回滚没有留下 `action='rollback'` 的快照：{[r['action'] for r in revs2]}"
        )
        assert [r for r in revs2 if r["action"] == "create"][0]["content"] == "第一版", (
            "最初的快照被回滚删掉了 —— 历史必须只增不改"
        )
        assert result["version"] == "1.0.2", (
            f"回滚本身就是一次新版本，版本号应继续 +1，实际 {result['version']}"
        )


# ============================================================================
# 4. 演示示例落库不变量
# ============================================================================


async def test_demo_skill_is_seeded_and_idempotent():
    """演示账号里**确实**有一个示例技能，且 `ensure_demo_skills()` 是幂等的。"""
    from modules.skills import service
    from modules.skills.seed import DEMO_SKILL_AGENTS, DEMO_SKILL_NAME, ensure_demo_skills

    assert await ensure_demo_skills() == 0, "已是稳态时不该再改（否则每次启动都写库）"
    assert await ensure_demo_skills() == 0, "第二次调用也不该改"

    async with async_session_factory() as db:
        row = await service.get_skill_by_name(db, DEMO_SKILL_NAME)

    assert row is not None, f"演示示例技能 {DEMO_SKILL_NAME!r} 不在库里 ⇒ 演示页空白"
    assert row.is_demo is True, "示例技能没被标成演示 ⇒ 演示身份看不到它"
    assert row.enabled is True, "示例技能被关了 ⇒ 不进任何 Agent 的技能目录"
    assert sorted(row.enabled_agents or []) == sorted(DEMO_SKILL_AGENTS), (
        f"示例技能勾选的 Agent = {row.enabled_agents}，应为 {DEMO_SKILL_AGENTS} —— "
        f"「Agent 内勾选启用」的演示面"
    )
    assert row.content.strip(), "示例技能没有正文 ⇒ 第二级披露取到空（模型会以为工具坏了）"
    assert row.account_id, "示例技能没有账户归属 ⇒ 它落在演示账号之外"


async def test_demo_marker_matches_demo_account_skills():
    """★★★ 全库 `is_demo = true` 的技能集合 **恰好等于** 演示账号名下的技能集合。

    ★ 与店铺侧的 `test_demo_marker_is_derived_from_demo_account` 同判据：
      钉的是**关系**（标记从账号推导出来），不是形态 ——
      换演示账号、增减技能都不用改这条；而一旦有人手工标了一份不属于演示账号的
      技能（或漏标），演示模式立刻多/少一条，这里就会红。
    """
    from modules.skills.seed import demo_account_row, ensure_demo_skills

    await ensure_demo_skills()
    account = await demo_account_row()
    assert account is not None, f"前置缺失：演示账号（{DEMO_ACCOUNT_EMAIL}）不在库里"

    async with async_session_factory() as db:
        owned = set((await db.execute(
            text("SELECT id FROM skills WHERE account_id = :a"), {"a": account.id}
        )).scalars().all())
        marked = set((await db.execute(
            text("SELECT id FROM skills WHERE is_demo IS TRUE")
        )).scalars().all())

    assert owned, "演示账号名下没有任何技能 —— 演示模式会空白"
    assert marked == owned, (
        f"is_demo 集合 ≠ 演示账号名下技能。\n"
        f"  只有标记没有归属: {sorted(marked - owned)}（演示身份会看到不属于演示账号的技能）\n"
        f"  只有归属没有标记: {sorted(owned - marked)}（演示模式会少显示技能）\n"
        f"两者都必须为空 —— 标记的唯一来源是 `ensure_demo_skills()`。"
    )


async def test_demo_specs_are_self_consistent():
    """★★★ 演示技能**规格表自身**的两条「静默失效」入口。

    规格表是**手写数据**：写错不会抛异常，只会静默少一条 —— 这正是本仓
    反复吃过的那类缺陷（配置看起来生效、运行时无事可做）。两个具体入口：

      ① `name` 重复 ⇒ `ensure_demo_skills()` 按 `name` 查库，第二条命中的是
         第一条 ⇒ **永远建不出来**，而日志里一个字都不会说。
      ② `agents` 写了不存在的 `agent_name` ⇒ 该技能不进任何 Agent 的目录，
         卡片区恒空、system prompt 也永远不注入，同样零报错。

    ★ 判据只钉这两条**关系**，**不钉条数**：将来增删技能不用改本用例，
      而一旦写错，这里当场红。（绝对计数断言会随每次加技能腐烂。）
    ★ 与 `test_agents_catalog_over_http` 分工：那条钉 `/agents` 端点**如实下发**
      目录表；本条钉规格表里的**引用键**指向真实存在的 Agent。两条不重叠。
    """
    from modules.skills.agents import all_agent_names
    from modules.skills.seed import DEMO_SKILLS

    known = set(all_agent_names())

    names = [s["name"] for s in DEMO_SKILLS]
    dup = sorted({n for n in names if names.count(n) > 1})
    assert not dup, (
        f"演示技能规格表里 name 重复：{dup}。\n"
        f"  `ensure_demo_skills()` 按 name 查库 ⇒ 重名的第二条永远建不出来，"
        f"且**不报错**（静默少一条技能）。"
    )

    unknown = sorted(
        {
            (s["name"], a)
            for s in DEMO_SKILLS
            for a in (s.get("agents") or [])
            if a not in known
        }
    )
    assert not unknown, (
        f"演示技能挂了不存在的 agent_name：{unknown}。\n"
        f"  合法值只有 {sorted(known)}（真源 `modules/skills/agents.py::AGENT_CATALOG`）。\n"
        f"  挂错的表现是「这条技能不进任何 Agent 的目录」，且**不报错**。"
    )

    empty = [s["name"] for s in DEMO_SKILLS if not (s.get("agents") or [])]
    assert not empty, (
        f"演示技能没挂任何 Agent：{empty} —— 它永远不会出现在任何卡片区，"
        f"等于白建（不出现在仓库里反而更诚实）。"
    )


async def test_demo_skills_do_not_target_orchestrator_agent():
    """★★★ 演示技能不得归属**编排层** Agent（第 195 轮）。

    ★ 起因（老板原话）：「【店秘书转交与澄清规则】应该是 saas 内部的规则，
      为什么你会写出来给用户改（核查是否还有其他 skill 有类似情况）」。
      扫全表后发现 23 条里**只有 1 条**命中，但**当时的门禁查不出来** ——
      `test_demo_specs_are_self_consistent` 只校验「agent 名字**存在**」，
      而 `secretary` 是**合法存在**的 Agent。这条补的正是那个盲区。

    ★ 判据：`secretary` 是**全局调度器**，它的行为是**平台编排**
      （「怎么分流、什么时候澄清」写在 `SECRETARY_SYSTEM_PROMPT`
      与 `ai_infra/tools/clarification.py` 里，属于 SaaS 实现的一部分）。
      而技能仓库是**租户可编辑**的 ⇒ 任何归属编排层 Agent 的技能，
      都会变成「用户能改、但改了不知道生不生效」的**第二份编排规则**。
      本仓判据：**同一判定两份实现 ⇒ 至少一份永远测不到。**

    ★ 为什么钉「演示技能的规格表」而不是「全部技能」：真实租户可以建自己的技能，
      本用例管不到（也不该管）；而**演示数据是我们自己写的**，
      它对用户是第一印象，必须干净。
      （写口侧 `_validate_agents` 只校验「名字存在」——
       若将来要禁止租户给 secretary 挂技能，那是产品决策，需另立用例。）

    ★ 反向注入验证：把 `secretary-handoff-rules` 加回 `DEMO_SKILLS`
      （agents=["secretary"]）⇒ 本用例转红。
    """
    from modules.skills.agents import AGENT_CATALOG
    from modules.skills.seed import DEMO_SKILLS

    # 编排层 Agent = 「把需求分派给谁」的那一个（不是业务实现者）。
    ORCHESTRATOR = "secretary"
    assert ORCHESTRATOR in {a["name"] for a in AGENT_CATALOG}, (
        f"编排层 Agent 的名字变了（{ORCHESTRATOR} 不在 AGENT_CATALOG）？"
        f"请同步更新本用例与 `seed.RETIRED_DEMO_SKILLS` 的口径。"
    )

    bad = sorted(s["name"] for s in DEMO_SKILLS if ORCHESTRATOR in (s.get("agents") or []))
    assert not bad, (
        f"演示技能挂到了编排层 Agent `{ORCHESTRATOR}`：{bad}。\n"
        f"  `{ORCHESTRATOR}` 是全局调度器，它的行为是**平台编排**"
        f"（写在 `SECRETARY_SYSTEM_PROMPT` 与 `ai_infra/tools/clarification.py` 里），\n"
        f"  不是租户可配置的业务方法学。把它做成技能 ⇒ 用户能改、改了不知道生不生效。\n"
        f"  若确实要展示「主入口怎么分流」，写进产品文档，不要建技能。"
    )


async def test_retired_demo_skills_are_not_resurrected():
    """★ 退役清单里的 name 不得重新出现在规格表里（第 195 轮）。

    ★ 为什么需要这条：`RETIRED_DEMO_SKILLS` 的作用是让 `ensure_demo_skills()`
      把**已有库里**的那条删掉。但如果有人只删了退役清单、却把技能又加回
      `DEMO_SKILLS`（或反过来），就会出现两种静默状态：
        · 加回规格表 + 仍在退役清单 ⇒ 每次启动「建了又删」（抖动，且日志噪音）；
        · 删掉退役清单 + 库里那条还在 ⇒ **永远删不掉**（本仓判据：
          「从规格表删掉」≠「它消失了」）。
      本用例把这两种状态都堵住。
    """
    from modules.skills.seed import DEMO_SKILLS, RETIRED_DEMO_SKILLS

    live = {s["name"] for s in DEMO_SKILLS}
    both = sorted(live & set(RETIRED_DEMO_SKILLS))
    assert not both, (
        f"这些技能同时在「规格表」与「退役清单」里：{both}。\n"
        f"  ⇒ 每次启动都会「先删后建」，白抖一次并刷两条日志。\n"
        f"  二选一：确实要它 ⇒ 从 RETIRED_DEMO_SKILLS 移除；不要它 ⇒ 从 DEMO_SKILLS 移除。"
    )
    assert RETIRED_DEMO_SKILLS, (
        "退役清单为空 —— 若确实没有任何退役项，请连同本用例一起删掉，"
        "不要留一个恒真的空断言（本仓判据：没有反例的断言 = 没有断言）。"
    )


# ============================================================================
# 5. 两条披露通道真的能取到东西（渐进披露的价值所在）
# ============================================================================


async def test_catalog_is_scoped_to_the_agent():
    """★★★ 第一级披露：目录**按 Agent 过滤**（「Agent 内勾选启用」的实际生效点）。

    ★ 只测「目录里有东西」是不够的：不按 Agent 过滤的目录看起来完全正常，
      但勾选界面就成了装饰 —— 取消勾选后技能照样出现在所有 Agent 的目录里。
    """
    from modules.skills.provider import build_catalog_for
    from modules.skills.seed import DEMO_SKILL_AGENTS, DEMO_SKILL_NAME

    assert DEMO_SKILL_AGENTS, "演示技能没有勾选任何 Agent，本用例失去意义"
    for agent in DEMO_SKILL_AGENTS:
        got = await build_catalog_for(agent, None)
        assert DEMO_SKILL_NAME in got, (
            f"已勾选 {agent}，但它的技能目录里没有 {DEMO_SKILL_NAME}：{got[:200]!r}"
        )

    excluded = "secretary"
    assert excluded not in DEMO_SKILL_AGENTS, "前置假设不成立：secretary 也在勾选表里"
    other = await build_catalog_for(excluded, None)
    assert DEMO_SKILL_NAME not in other, (
        f"★ 没勾选 {excluded} 的技能照样出现在它的目录里 ⇒ "
        f"「Agent 内勾选启用」没有生效（勾选界面成了装饰）"
    )


async def test_load_skill_requires_ownership_enabled_and_agent(skill_owner):
    """★★★ 第二级披露：`read_skill_for_agent` 的三重过滤缺一不可。

    ① 归属（越权技能不能因为知道名字就读到）
    ② `enabled` 全局开关
    ③ `enabled_agents` 含本 Agent

    ★ 为什么三重都要测：只测①，则「知道名字就能读到未勾选的技能」；
      只测③，则跨租户按名字读取成立。而且判定返回 `None`（不是 403）——
      「不存在」与「没给你启用」在工具层**不该可分**（可分就是给模型的探测口）。
    """
    from modules.skills import service
    from modules.skills.seed import DEMO_SKILL_AGENTS, DEMO_SKILL_NAME

    agent = DEMO_SKILL_AGENTS[0]
    async with async_session_factory() as db:
        # ①+③ 演示身份 + 已勾选 Agent ⇒ 拿到**渲染好的正文**
        body = await service.read_skill_for_agent(db, None, agent, DEMO_SKILL_NAME)
        assert body, f"演示身份读不到示例技能正文（agent={agent}）"
        assert "闪促" in body, (
            f"拿到的不是技能正文（{body[:120]!r}）—— 第二级披露的内容不对"
        )

        # ③ 换成没勾选的 Agent ⇒ None
        assert await service.read_skill_for_agent(
            db, None, "secretary", DEMO_SKILL_NAME
        ) is None, "没勾选本 Agent 也能读到正文 ⇒ 勾选没有参与判定"

        # ② 关掉全局开关 ⇒ 谁都读不到
        row = await service.get_skill_by_name(db, DEMO_SKILL_NAME)
        backup = row.enabled
        row.enabled = False
        await db.commit()
        try:
            assert await service.read_skill_for_agent(
                db, None, agent, DEMO_SKILL_NAME
            ) is None, "`enabled=False` 的技能仍然被读到 ⇒ 全局开关没有参与判定"
        finally:
            row.enabled = backup
            await db.commit()

        # 名字不存在 ⇒ None
        assert await service.read_skill_for_agent(
            db, None, agent, "no-such-skill-181"
        ) is None

        # ④ 归属：有身份但不是演示账号 ⇒ None（**不能因为知道名字就读到**）
        user = await _load_user(db, skill_owner["user_id"])
        assert await service.read_skill_for_agent(
            db, user, agent, DEMO_SKILL_NAME
        ) is None, (
            "★ 真实用户用名字读到了演示账号的技能 —— 归属过滤在第二级披露上缺失"
        )


# ============================================================================
# 6. HTTP 端到端
# ============================================================================


async def _demo_account_id() -> str:
    """演示账号（容器）id —— 第 182 轮归属断言的**期望值**。

    ★ 从 seed 的同一处取（`demo_account_row`），不在测试里自己写一条 SQL：
      自己写会与产品代码的口径（join users + 按 created_at 取最早）分叉，
      而分叉的症状是「测试说归属错了」但产品其实是对的（错误方向）。
    """
    from modules.skills.seed import demo_account_row

    account = await demo_account_row()
    assert account is not None, f"前置缺失：演示账号（{DEMO_ACCOUNT_EMAIL}）不在库里"
    return account.id


async def _demo_skill_id(client) -> str:
    from modules.skills.seed import DEMO_SKILL_NAME

    r = await client.get("/api/v1/skills")
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    items = r.json()["items"]
    hit = [it for it in items if it["name"] == DEMO_SKILL_NAME]
    assert hit, f"列表里没有示例技能：{[it['name'] for it in items]}"
    return hit[0]["id"]


async def test_demo_identity_skill_list_over_http(auth_off, client, skill_owner):
    """★★★ 端到端：无凭据 `GET /api/v1/skills` ⇒ **只有**演示技能，且**不含正文**。

    ★ 「不含正文」是契约的一部分：技能正文动辄数千字符，列表页一次要展示几十条，
      全带上等于把列表接口变成一次全量导出（同 `platform_rules` 的判据）。

    ★★★ 为什么必须**先造一条真实技能**（这是反向注入实测换来的，别删）：
      本机库里原本只有一条演示技能 ⇒ `return list(skills)` 与「只给演示技能」
      **结果完全相同** ⇒ `all(isDemo is True)` 恒真，这条断言是**空跑**的。
      实测：把 `filter_accessible_skills` 的演示分支改回 `return list(skills)`
      （= 回退安全修复 `4612abb`）时，本用例**仍然绿**。
      造出反例之后它才会转红 —— 「没有反例的断言等于没有断言」。
    """
    from modules.skills.seed import DEMO_SKILL_NAME

    real_name = skill_owner["prefix"] + "-real"
    made = await client.post(
        "/api/v1/skills",
        json={"name": real_name, "title": "真实技能", "content": "真实技能正文"},
        headers=skill_owner["headers"],
    )
    assert made.status_code == 201, f"{made.status_code} {made.text[:300]}"

    r = await client.get("/api/v1/skills")
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    items = r.json()["items"]
    names = [it["name"] for it in items]

    assert items, "演示身份一条技能都拿不到 ⇒ 技能仓库页空白"
    assert real_name not in names, (
        f"★★ 演示身份的列表里出现了真实账号的技能 {real_name!r}：{names} —— "
        f"跨租户泄漏（安全修复 4612abb 被回退的形态）"
    )
    assert all(it["isDemo"] is True for it in items), (
        f"演示身份的列表里混进了非演示技能："
        f"{[(it['name'], it['isDemo']) for it in items]} ⇒ 跨租户泄漏"
    )
    assert DEMO_SKILL_NAME in names, f"示例技能不在演示列表里：{names}"
    assert all("content" not in it for it in items), (
        "列表接口带上了正文 ⇒ 列表变成全量导出（正文只在详情里按需拉）"
    )


async def test_demo_identity_can_read_detail_and_revisions(auth_off, client):
    """演示身份能读**详情（含正文）**与版本历史 —— 只读面完整。"""
    sid = await _demo_skill_id(client)

    detail = await client.get(f"/api/v1/skills/{sid}")
    assert detail.status_code == 200, f"{detail.status_code} {detail.text[:200]}"
    assert "闪促" in detail.json().get("content", ""), (
        "详情里没有正文 ⇒ 演示者点开看不到技能内容"
    )

    revs = await client.get(f"/api/v1/skills/{sid}/revisions")
    assert revs.status_code == 200, f"{revs.status_code} {revs.text[:200]}"
    assert revs.json()["total"] >= 1, "演示技能一条版本历史都没有"


async def test_demo_identity_can_write_skills(demo_on, auth_off, client):
    """★★★ 第 182 轮：演示身份对写端点**全部放行**，且归属恰好落在演示账号。

    ★★★ 本条**推翻了第 181 轮的同名用例**（`test_demo_identity_cannot_write_skills`
      断言五个写端点一律 403）。这是**需求变更**，不是缺陷修复 —— 老板原文：

        「演示模式也当作一个真实的账号，只是无需账号密码。也有全套功能，
          目前无法编辑 skill。」

      ⇒ 第 181 轮"演示身份恒为 None ⇒ 写口硬拒"的前提被推翻：
        演示哨兵现在被解析成**演示账号主人**（真 `User`），于是写口自然放行。
        ★ 但「为什么当初要禁」那条理由**今天依然成立**（演示技能是全局共享数据，
        被删了所有人演示页空白）—— 老板要的正是"可自由折腾、重启由 seed 拉回"，
        所以 seed 的「已有则不覆盖」也从谨慎升级成了体验依据。

    ★ 两个方向都必须断言，缺一即假绿：
      ① **能力面**：新建 / 改标题 / 改勾选 / 改正文（版本）/ 回滚 / 删除 全部成功
         —— 只要有一个还返回 403，老板看到的就还是"按钮点了没反应"；
      ② **归属面**：新建出来的技能 `accountId` **恰好等于演示账号**
         —— 演示身份写出去的东西必须落在自己账号下。
            少了这条，一个"写进别人容器"的越权会被"201 成功"掩盖。

    ★ 反向注入（本条必须能转红，已实测）：
      把 `core/auth/demo_identity.py::resolve_demo_user` 的 `return user`
      改成 `return None`（= 回退到第 181 轮的"演示身份 = 匿名"形态）
      ⇒ `get_acting_user` 落到 `require_auth_if_enabled`（同一个函数，也返回 None）
      ⇒ `_reject_no_identity` 抛 403 ⇒ 第 ① 条断言当场转红。
    """
    from modules.skills.seed import DEMO_SKILL_NAME

    expected_account = await _demo_account_id()
    seeded_id = await _demo_skill_id(client)
    name = "p182-demo-write-" + uuid.uuid4().hex[:8]

    # ★ 整段包在 `try/finally` 里（**实测事故换来的范式**）：
    #   反向注入或中途断言失败时，本用例会**已经真的写进去**一些东西。
    #   若断言在第一处就中止，收尾那几行根本不会执行 —— 残留会污染后续用例。
    #   ⇒ 会产生副作用的用例，收尾必须由自己兜住。
    try:
        # ---- ① 新建：能力 + 归属 ----
        created = await client.post(
            "/api/v1/skills",
            json={"name": name, "title": "演示身份新建", "content": "v1"},
            headers=_DEMO_HEADERS,
        )
        assert created.status_code == 201, (
            f"★ 演示身份新建技能被拒（{created.status_code}）：{created.text[:300]}\n"
            f"  第 182 轮需求：「演示模式也当作一个真实的账号 …… 也有全套功能」。"
        )
        body = created.json()
        new_id = body["id"]
        assert body["accountId"] == expected_account, (
            f"★ 演示身份新建的技能归属 = {body['accountId']!r}，"
            f"应为演示账号 {expected_account!r} —— "
            f"写出的归属必须落在自己账号下（否则是往别人的容器里塞数据）。"
        )
        assert body["isDemo"] is False, (
            "接口不该把技能标成演示 —— `is_demo` 的唯一来源是 seed 的收敛"
        )

        # ---- ② 改标题 ----
        upd = await client.put(
            f"/api/v1/skills/{new_id}",
            json={"title": "改过的标题"},
            headers=_DEMO_HEADERS,
        )
        assert upd.status_code == 200, f"★ 演示身份改标题失败（{upd.status_code}）"
        assert upd.json()["title"] == "改过的标题"

        # ---- ③ 改 Agent 勾选（「Agent 内勾选启用」的写口）----
        wired = await client.put(
            f"/api/v1/skills/{new_id}/agents",
            json={"agentNames": ["secretary"]},
            headers=_DEMO_HEADERS,
        )
        assert wired.status_code == 200, f"★ 演示身份改勾选失败（{wired.status_code}）"
        assert wired.json()["enabledAgents"] == ["secretary"], (
            f"勾选没落库：{wired.json().get('enabledAgents')}"
        )

        # ---- ④ 改正文 ⇒ 必须自动落一条版本快照 ----
        v2 = await client.put(
            f"/api/v1/skills/{new_id}", json={"content": "v2"}, headers=_DEMO_HEADERS
        )
        assert v2.status_code == 200, f"★ 演示身份改正文失败（{v2.status_code}）"
        revs = await client.get(
            f"/api/v1/skills/{new_id}/revisions", headers=_DEMO_HEADERS
        )
        assert revs.status_code == 200, f"演示身份读不到自己的版本历史（{revs.status_code}）"
        items = revs.json()["items"]
        assert len(items) >= 2, f"正文变了却没落新版本：{len(items)} 条"

        # ---- ⑤ 回滚到最早那版 ----
        oldest = items[-1]["id"]
        rolled = await client.post(
            f"/api/v1/skills/{new_id}/rollback",
            json={"revisionId": oldest},
            headers=_DEMO_HEADERS,
        )
        assert rolled.status_code == 200, (
            f"★ 演示身份回滚失败（{rolled.status_code}）：{rolled.text[:200]}"
        )

        # ---- ⑥ 删除自己刚建的（**不删预置那条**：它是全局共享的演示数据）----
        deleted = await client.delete(f"/api/v1/skills/{new_id}", headers=_DEMO_HEADERS)
        assert deleted.status_code == 200, f"★ 演示身份删除失败（{deleted.status_code}）"
        gone = await client.get(f"/api/v1/skills/{new_id}", headers=_DEMO_HEADERS)
        assert gone.status_code in (403, 404), f"删掉了却还读得到：{gone.status_code}"

        # ---- ⑦ 零副作用探针：对**预置的演示技能**的归属门也放行了吗？----
        # ★ 为什么这样问：直接对它 PUT / DELETE 会毁掉全局共享的演示数据
        #   （`test_demo_skill_is_seeded_and_idempotent` 依赖它）。
        #   而 `rollback` 一个**不存在的**版本，恰好能区分两种拒绝：
        #       403 ⇒ 卡在归属门        （本次要证伪的形态）
        #       404 ⇒ 已过归属门，只是版本不存在（期望）
        #   ⇒ 用一个必然 404 的请求探测授权，零写入、零副作用。
        probe = await client.post(
            f"/api/v1/skills/{seeded_id}/rollback",
            json={"revisionId": "rev_definitely_not_exists"},
            headers=_DEMO_HEADERS,
        )
        assert probe.status_code == 404, (
            f"★ 对预置演示技能的回滚探测返回 {probe.status_code}，期望 404。\n"
            f"  403 ⇒ 演示身份对**自己账号**的技能仍被归属门挡住（写口没真正打开）；\n"
            f"  200 ⇒ 竟然回滚成功了（本探针必须零副作用，revisionId 是编的）"
        )
        still = await client.get(f"/api/v1/skills/{seeded_id}", headers=_DEMO_HEADERS)
        assert still.status_code == 200 and "闪促" in still.json()["content"], (
            "探针改动了预置演示技能 —— 它必须是零副作用的"
        )
        listed = await client.get("/api/v1/skills", headers=_DEMO_HEADERS)
        names = [it["name"] for it in listed.json()["items"]]
        assert DEMO_SKILL_NAME in names, "预置演示技能从列表里消失了"
    finally:
        # 无论断言过没过，都把"注入下真的写进去的东西"收干净。
        async with async_session_factory() as db:
            await db.execute(
                text("DELETE FROM skills WHERE name = :n"), {"n": name}
            )
            await db.commit()


async def test_demo_identity_still_cannot_write_outside_its_account(
    demo_on, auth_off, client, skill_owner
):
    """★★★ 写口打开 = **只对自己账号**打开；跨账号写必须仍然 403。

    ★ 为什么这条必须和第 182 轮那条**配对存在**：
      「演示模式也能写」这个改动很容易被做成"写口没门了" ——
      而两件事只差一行：`_reject_no_identity` 放宽了（能力门），
      `ensure_can_access_skill` **没有也不能**放宽（归属门）。

      ⇒ 只测"能写"，一个"把归属门也一起删了"的实现会全绿。
        必须同时测"越界写仍然被拒"。

    ★ 反向注入：把 `router.update_skill` 里的
      `await ensure_can_access_skill(...)` 删掉 ⇒ 本条转红。
    """
    real_name = skill_owner["prefix"] + "-demo-cannot-touch"
    made = await client.post(
        "/api/v1/skills",
        json={"name": real_name, "title": "真实账号的技能", "content": "正文"},
        headers=skill_owner["headers"],
    )
    assert made.status_code == 201, f"{made.status_code} {made.text[:300]}"
    sid = made.json()["id"]

    try:
        # 演示身份去改 / 删**真实账号**的技能 ⇒ 403（统一响应，不泄露存在性）
        r = await client.put(
            f"/api/v1/skills/{sid}", json={"title": "演示改的"}, headers=_DEMO_HEADERS
        )
        assert r.status_code == 403, (
            f"★★ 演示身份改到了真实账号的技能（{r.status_code}）—— "
            f"写口打开时把**归属门**一起放宽了。"
        )
        d = await client.delete(f"/api/v1/skills/{sid}", headers=_DEMO_HEADERS)
        assert d.status_code == 403, f"★★ 演示身份删掉了真实账号的技能（{d.status_code}）"

        # 且真的没被改动
        after = await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
        assert after.status_code == 200
        assert after.json()["title"] == "真实账号的技能", "403 之后真实技能被改动了"
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM skills WHERE name = :n"), {"n": real_name})
            await db.commit()


async def test_agents_catalog_over_http(auth_off, client):
    """`GET /api/v1/agents` 返回 8 个平台 Agent，且**不需要身份**。

    ★ 演示身份要能渲染勾选界面；这个端点是静态平台元数据，不含租户数据。
    """
    from modules.skills.agents import AGENT_CATALOG

    r = await client.get("/api/v1/agents")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["total"] == len(AGENT_CATALOG) == 8, f"total={body['total']}"
    assert {it["name"] for it in body["items"]} == {it["name"] for it in AGENT_CATALOG}


async def test_tools_catalog_over_http(auth_off, client):
    """★ `GET /api/v1/tools` 返回 55 个**真接线**工具，且**不需要身份**。

    ★ 与 `/agents` 同档（静态平台元数据、不含租户数据）——
      演示身份要能渲染工具勾选界面；加鉴权只会让它渲染不出来。

    ★ 本用例钉两件事（它们是这个端点存在的全部意义）：

      ① **目录如实下发 + 分组口径住后端**：`grouped` 必须与平铺 `items` 一致，
         且每组的 `agentTitle` 与 `AGENT_CATALOG` 一致。
         前端自己按 `agent` 字段再分一遍 = 第二份实现，改一处静默失配；
         分组标题写错 ⇒ 用户看到的组名与 Agent 名对不上，且**没有人会报错**。

      ② **只下发真接线的**：那些「注册了但没有任何 Agent 绑定」的工具
         一个都不能出现 —— 让租户勾一个调不起来的工具，比不给他勾更糟
         （他会以为配好了）。
         ★ 第 204 轮之前这条要在本文件里**现取悬空集合**来判；接线后悬空集合
           已为空（见 `test_agent_tool_wiring.py`），于是它被**上移**到
           `tests/test_tool_catalog.py::test_catalog_names_match_real_assembly`
           —— 那里用「目录表 == 装配点运行时真值」的**集合相等**判，双向、
           且不依赖「悬空集合非空」这个已消失的前提。本文件不再重复实现它。

      ★ 分工：本用例只管**端点有没有如实下发那张表**；表本身对不对由
        `tests/test_tool_catalog.py` 负责。两条不重叠。
    """
    from modules.skills.tools_catalog import TOOL_CATALOG

    r = await client.get("/api/v1/tools")
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    body = r.json()
    # ★ 第 243 轮：分母 59 → 60（店秘书新增只读 `list_shops`）。
    #   ★ 第 251 轮：分母 60 → 61（运营复盘师新增只读 `list_reviews`，复盘库读口）。
    #   ★ 第 287 轮：分母 66 → 67（trade 新增 `propose_review_disposition`，
    #     给 `review_dispositions` 补出口；它有副作用 ⇒ 同时进 HITL 审批集合）。
    #   ★ 第 313 轮：分母 67 → 66（运营复盘师退役只读 `ad_review`，
    #     随老板「运营复盘删除广告数据」；只读 ⇒ HITL 集合不变）。
    #   ★ 第 316 轮：分母 66 → 64（广告分析师退役 `optimize_budget` /
    #     `detect_ad_anomalies`，老板「广告分析师删除异常检测、广告预算
    #     再平衡」；两者原本都是只读 ⇒ HITL 集合仍不变）。
    #   ★ 这里是**名单式分母的第四处** —— 改目录表条数时请全仓 grep，
    #     漏一处就是一条静默漂移的断言（本轮实测：先漏了它，全量回归才抓到；
    #     第 287 轮又漏了一次 —— 同批同步的是 `test_tool_catalog.py` 那两处）。
    assert body["total"] == len(TOOL_CATALOG) == 65, f"total={body['total']}"

    flat = {it["name"] for it in body["items"]}
    assert flat == {it["name"] for it in TOOL_CATALOG}, "端点下发的不是那张目录表"

    grouped = {t["name"] for g in body["grouped"] for t in g["tools"]}
    assert flat == grouped, (
        f"平铺与分组对不上。只在平铺: {sorted(flat - grouped)}；"
        f"只在分组: {sorted(grouped - flat)}"
    )

    # ① 分组标题必须与 `AGENT_CATALOG` 一致（「分组口径住后端」的另一半）。
    #
    #    ★ 这里**换掉**了原来的「悬空工具不得泄漏进可勾选清单」断言。
    #      旧版取 `customer_service_tools` / `ad_analysis_tools` 两个**模块里**的
    #      工具名，断言它们**不得**出现在可勾选清单里 —— 成立的前提是这两个容器
    #      「没有任何 Agent 绑定」。第 204 轮把它们接给了各自的 Agent 并登记入表，
    #      前提消失：旧断言要么恒红，要么被改成一句「恒真的谎话」。
    #    ★ 它原来的职责（可勾选 ⇔ 真装配）**已被完全覆盖，且覆盖得更强**：
    #      · `tests/test_tool_catalog.py::test_catalog_names_match_real_assembly`
    #        —— 目录表 == 装配点运行时真值（**集合相等**，双向都能咬住）；
    #      · `tests/test_agent_tool_wiring.py::test_every_tool_registry_is_wired_to_an_agent`
    #        —— 全仓 `*_tools` 容器不得悬空。
    #      ⇒ 删除它是**去重复**，不是丢覆盖（本仓判据：同一判定不许两份实现）。
    from modules.skills.agents import AGENT_CATALOG

    titles = {a["name"]: a["title"] for a in AGENT_CATALOG}
    bad_titles = sorted(
        (g["agent"], g.get("agentTitle"), titles.get(g["agent"]))
        for g in body["grouped"]
        if g.get("agentTitle") != titles.get(g["agent"])
    )
    assert not bad_titles, (
        f"分组标题与 `AGENT_CATALOG` 对不上（agent, 下发值, 期望值）：{bad_titles}\n"
        f"⇒ 界面上的分组标题**由后端给**（前端不查名字表），写错就没人会报错。"
    )


# ==============================================================================
# 工具仓库读口（第 208 轮）—— 反向引用：工具 ← 技能
# ==============================================================================


async def test_tool_usage_reverse_index_over_http(auth_off, demo_off, client, skill_owner):
    """★★★ `GET /api/v1/tools/usage`：反向引用**按调用者归属过滤**，且与目录表同源。

    ★ 反向注入靶子（第 9 条，已实测）：
      把 `service.tool_usage` 里的
          `visible = await filter_accessible_skills(db, user, rows)`
      换成
          `visible = rows`
      ⇒ 本用例转红。这是本读口**唯一的越权面**：它把「技能表」投影成
      「工具视角」，一旦忘了过滤，泄漏的不是少数字段，而是
      **别人账号里有哪些技能**这件事本身。

    ★ 为什么必须复用**同一条** `filter_accessible_skills`：
      它就是 `/skills` 列表端点的唯一筛法。这里重写一份可见性判断
      = 第 177 轮 P1-5 的形态（两个入口两份实现 ⇒ 至少一份永远测不到）。

    ★ 另钉「三张表同源」（`usage` / `unknownTools` / `unusedTools`）：
      它们是同一次遍历的三个投影，互相对不上就是**静默错位** ——
      界面上只会表现为"某个工具的引用数不对"，没有任何一处会报错。
    """
    from modules.skills.tools_catalog import all_tool_names

    tool = "optimize_listing_title"
    name = skill_owner["prefix"] + "-usage"

    created = await client.post(
        "/api/v1/skills",
        json={
            "name": name,
            "title": "反向引用用例",
            "description": "引用一个已注册工具",
            "content": "正文",
            "tools": [tool],
            "enabledAgents": ["ListingGenerator"],
        },
        headers=skill_owner["headers"],
    )
    assert created.status_code == 201, f"{created.status_code} {created.text[:300]}"

    try:
        # ---- ① 创建者自己看得到这条引用，且事实字段齐全 ----
        r = await client.get("/api/v1/tools/usage", headers=skill_owner["headers"])
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        body = r.json()

        refs = body["usage"].get(tool) or []
        mine = [x for x in refs if x["name"] == name]
        assert mine, (
            f"创建者看不到自己技能的引用。{tool} 的引用：{[x['name'] for x in refs]}"
        )
        # ★ 界面判「这条引用生效不到」全靠这两个字段（组合约束）：
        #   技能引用了工具，却没对**该工具所属的 Agent** 启用 ⇒ 运行期调不到。
        #   这两个事实必须**随引用一起下发**，否则前端只能再拉一次技能列表去对账
        #   （两次请求之间会变），或自己推算一份口径（第二份实现）。
        assert mine[0]["enabled"] is True
        assert mine[0]["enabledAgents"] == ["ListingGenerator"], mine[0]
        assert tool not in body["unknownTools"], (
            f"已注册的工具被报成未知：{body['unknownTools']}"
        )

        # ---- ② 三张表同源（双向 partition 断言）----
        cat = set(all_tool_names())
        used = set(body["usage"].keys())
        unused = set(body["unusedTools"])
        unknown = set(body["unknownTools"])
        assert unused == cat - used, (
            f"unusedTools 与 usage 对不上。目录里有却没算进 unused："
            f"{sorted((cat - used) - unused)}；算进了 unused 但其实有引用："
            f"{sorted(unused & used)}"
        )
        assert unknown == used - cat, (
            f"unknownTools 与 usage 对不上。引用了不存在的工具却没上报："
            f"{sorted((used - cat) - unknown)}"
        )
        assert body["referencedTools"] == len(used), body["referencedTools"]

        # ---- ③ ★ 归属过滤：换一个身份，这条引用必须在**任何工具名下**都消失 ----
        anon = await client.get("/api/v1/tools/usage")
        assert anon.status_code == 200, f"{anon.status_code} {anon.text[:300]}"
        anon_body = anon.json()
        leaked = sorted(
            x["name"] for lst in anon_body["usage"].values() for x in lst
            if x["name"] == name
        )
        assert not leaked, (
            f"★ 匿名身份看到了真实账号的技能引用（{leaked}）—— "
            f"`filter_accessible_skills` 没有作用在反向索引上。"
            f" 泄漏的不只是几个字段，而是「别人账号里有哪些技能」这件事本身。"
        )
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM skills WHERE name = :n"), {"n": name})
            await db.commit()


async def test_real_user_does_not_see_demo_skill(auth_off, client, skill_owner):
    """★★ 真实账号的用户**看不到**演示技能（演示档不污染真实账号）。

    ★ 这条是老板本轮那句「演示账号不影响其他真实账号」在技能上的可执行面。
    """
    from modules.skills.seed import DEMO_SKILL_NAME

    r = await client.get("/api/v1/skills", headers=skill_owner["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    items = r.json()["items"]
    assert DEMO_SKILL_NAME not in [it["name"] for it in items], (
        f"真实账号看到了演示技能：{[it['name'] for it in items]}"
    )
    assert all(it["isDemo"] is False for it in items), (
        f"真实账号的列表里出现了演示标记：{[(it['name'], it['isDemo']) for it in items]}"
    )


async def test_real_user_cannot_read_demo_skill(auth_off, client, skill_owner):
    """真实账号的用户按 id **读不到**演示技能详情 ⇒ 403（不是 404，不泄露存在性）。"""
    sid = await _demo_skill_id(client)

    r = await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
    assert r.status_code == 403, (
        f"★ 真实账号读到了演示技能详情（{r.status_code}）—— 跨租户泄漏。"
        f" 用 403 而不是 404：404 会泄露「该 id 是否存在」，帮对方枚举。"
    )


async def test_real_user_owns_a_private_skill_end_to_end(auth_off, client, skill_owner):
    """★★ 真身份建 `private` 技能 ⇒ 自己看得到、演示身份看不到、别的账号看不到。

    ★ 这条把「权限」四要素（新建 / 编辑 / 版本 / 权限）里的**权限**走了一遍真实链路：
      建（POST）→ 读详情（GET）→ 演示身份列表（GET，必须没有它）。
    """
    name = skill_owner["prefix"] + "-priv"
    created = await client.post(
        "/api/v1/skills",
        json={
            "name": name,
            "title": "私密技能",
            "description": "只有我能看见",
            "content": "正文",
            "visibility": "private",
        },
        headers=skill_owner["headers"],
    )
    assert created.status_code == 201, f"{created.status_code} {created.text[:300]}"
    sid = created.json()["id"]
    assert created.json()["visibility"] == "private"
    assert created.json()["isDemo"] is False, "接口能把技能标成演示（`is_demo` 只由 seed 收敛）"

    mine = await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
    assert mine.status_code == 200, f"创建者读不到自己的技能：{mine.status_code}"

    # 演示身份：列表里没有它，按 id 读也读不到
    listed = await client.get("/api/v1/skills")
    assert name not in [it["name"] for it in listed.json()["items"]], (
        "★ 真实用户的 private 技能出现在演示身份的列表里"
    )
    anon = await client.get(f"/api/v1/skills/{sid}")
    assert anon.status_code == 403, (
        f"★ 匿名演示身份读到了真实用户的 private 技能（{anon.status_code}）"
    )


async def test_write_endpoints_reject_cross_account_skill(auth_off, client, make_user):
    """★★ 另一个真实账号的用户改不到别人的技能 ⇒ 403（归属判定在写口生效）。"""
    owner = await make_user("skillowner2")
    other = await make_user("other2")

    created = await client.post(
        "/api/v1/skills",
        json={"name": f"p181-xacct-{uuid.uuid4().hex[:6]}", "content": "正文"},
        headers=owner["headers"],
    )
    assert created.status_code == 201, f"{created.status_code} {created.text[:300]}"
    sid = created.json()["id"]
    name = created.json()["name"]

    try:
        r = await client.put(
            f"/api/v1/skills/{sid}", json={"title": "被别人改了"}, headers=other["headers"]
        )
        assert r.status_code == 403, (
            f"★ 别的账号改到了我的技能（{r.status_code}）—— 归属判定在写口缺失"
        )
        assert (
            await client.delete(f"/api/v1/skills/{sid}", headers=other["headers"])
        ).status_code == 403
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM skills WHERE name = :n"), {"n": name})
            await db.commit()


# ==============================================================================
# 演示技能的「归属 ⇄ 锚工具」一致性（第 189 轮 · 老板核查卡片归属时发现）
# ==============================================================================


#: Agent `agent_name` → `(模块路径, 工具集变量名)`。
#:
#: ★ `secretary` **不在表内** —— 它的工具分散在 4 个模块（navigation /
#:   subscription / product / shop），而它名下的技能是**路由规范型**
#:   （锚工具为 `None`）⇒ 取不到工具集也不会漏判。
#:   把它写进来只会多一处"要跟着改名走"的抄本。
_AGENT_TOOL_MODULES: dict = {
    "competitor_intel": ("modules.competitor_intel.tools", "competitor_intel_tools"),
    "ProductResearcher": ("modules.product_research.tools", "product_research_tools"),
    "ListingGenerator": ("modules.listing_generator.tools", "listing_tools"),
    "AIGC 媒体生成器": ("modules.aigc_media.tools", "aigc_tools"),
    "ad_analysis": ("modules.ad_analysis.tools", "ad_analysis_tools"),
    "智能客服": ("modules.customer_service.tools", "customer_service_tools"),
    "review_analyst": ("modules.review_analyst.tools", "review_analyst_tools"),
}


def _real_tool_names() -> dict:
    """从模块**现取**每个 Agent 的工具名 —— 不手抄清单（手抄的那份必然漂移）。"""
    import importlib

    out = {}
    for agent, (modname, ref) in _AGENT_TOOL_MODULES.items():
        mod = importlib.import_module(modname)
        out[agent] = {t.name for t in getattr(mod, ref)}
    return out


def test_demo_skill_anchor_tool_is_reachable_from_its_agent():
    """★★ 演示技能声明的「锚工具」必须真的在它挂载的 Agent 手里。

    ==========================================================================
    ★ 这条判据的来历（第 189 轮 · 老板贴卡片截图核查归属时发现）
    ==========================================================================
    老板问：**为什么「运营复盘师」的卡片区里会有「评论痛点挖掘」？**

    查下来是真错位：该技能（`review-pain-mining`）正文要求「手上有一批**评论**
    （文本 + 评分）…样本少于 30 条不要出结论」，但它挂在 `review_analyst` 下，
    而该 Agent 的 6 个工具（`weekly_report` / `monthly_review` / `ad_review` /
    `product_performance` / `inventory_health` / `profit_audit`）**没有一个产出
    评论数据**，822 字的 system prompt 里也**不含「评论」二字**
    ⇒ 用户点了这张卡，Agent 手里根本没有原料，只能凭想象编。

    ⇒ 把「归属必须有工具支撑」变成可执行判据：`seed.DEMO_SKILL_ANCHOR_TOOLS`
      声明每条技能靠哪个工具产出原料；本条校验那个工具在不在它挂载的 Agent 手里。

    ==========================================================================
    ★ 反向注入（验证本条真的会红）
    ==========================================================================
    把 `seed.DEMO_SKILLS` 里 `review-pain-mining` 的 `agents` 改回
    `["review_analyst"]` ⇒ 本条红，且红在 `problems` 那一行。
    ★ 已实测（第 189 轮）

    ==========================================================================
    ★ 为什么锚工具要**人工声明**，而不是从正文里推断
    ==========================================================================
    试过关键词推断（"正文命中的原料域 ⊆ 该 Agent 的能力域"）：
    正文里的**举例 / 红线 / 输出对象**会命中同一个词 ——
    「不要用单条极端评论代表整体」也被判成"需要评论数据"，
    23 条里误报 **20 条**。这是典型的字符串包含假阳性（本仓铁律已登记）。

    ⇒ 「原料是什么」只有人能判；这里把人的判断**显式化**，
      让机器只做它擅长的那一步：「这个工具在这个 Agent 手里吗」。

    ★ 也**不**写成"每条技能都必须有锚工具" —— 那会把 6 条正当的
      清单 / 规范 / 推理 / 取证型技能判成缺陷，是另一种假阳性。
    """
    from modules.skills.seed import DEMO_SKILLS, DEMO_SKILL_ANCHOR_TOOLS

    real = _real_tool_names()

    # ① 防「两边都是空集也算相等」（同 `test_tool_catalog.py` 的自检 2）
    empty = [a for a, names in real.items() if not names]
    assert not empty, (
        f"这些 Agent 的工具集解析为空：{empty}\n"
        f"⇒ 本判据会**假绿**。通常是模块路径或工具集变量名改了，"
        f"请同步 `_AGENT_TOOL_MODULES`。"
    )

    by_name = {s["name"]: s for s in DEMO_SKILLS}

    # ② 锚工具表不得脱离规格表（多一条 / 少一条都是漂移）
    extra = sorted(set(DEMO_SKILL_ANCHOR_TOOLS) - set(by_name))
    lack = sorted(set(by_name) - set(DEMO_SKILL_ANCHOR_TOOLS))
    assert not extra and not lack, (
        f"锚工具表与 `DEMO_SKILLS` 对不上。\n"
        f"  只在锚表: {extra}\n"
        f"  只在规格表: {lack}\n"
        f"⇒ 新增 / 删除技能时必须同步这张表，否则新技能**没有任何归属门禁**。"
    )

    problems = []
    for name, tool in sorted(DEMO_SKILL_ANCHOR_TOOLS.items()):
        if tool is None:
            continue  # 清单 / 规范 / 推理 / 取证型：全仓无对口工具，正当
        spec = by_name[name]
        for agent in spec["agents"]:
            names = real.get(agent)
            if names is None:
                problems.append(
                    f"{name}「{spec['title']}」挂 `{agent}`，"
                    f"但该 Agent 不在 `_AGENT_TOOL_MODULES` 里 ⇒ 归属无法校验（请补登记）"
                )
            elif tool not in names:
                problems.append(
                    f"{name}「{spec['title']}」挂 `{agent}`，"
                    f"锚工具 `{tool}` 不在它的工具集里；该 Agent 有 {sorted(names)}"
                )

    assert not problems, (
        "以下技能的**归属没有工具支撑** —— 用户点了这张卡，Agent 手里也没有原料：\n  "
        + "\n  ".join(problems)
        + "\n⇒ 三选一：改 `agents`（换到有该工具的 Agent）、"
        "改锚工具（技能实际靠别的工具）、或把锚工具设为 None 并在 seed 里写明它为何无需工具。"
    )


def test_demo_skill_tools_are_registered_and_cover_their_anchor():
    """★★★ 演示技能声明的 `tools` 必须**真能调起来**，且覆盖它的锚工具（第 200 轮）。

    ==========================================================================
    ★ 这条补的是上面 `...anchor_tool_is_reachable_from_its_agent` 的**两个盲区**
    ==========================================================================
    那条校验的是「锚工具在**该 Agent 的模块**里有」（`_AGENT_TOOL_MODULES`
    从模块取工具集）—— 它管不到这两件事：

      ① 该工具**有没有被真装配**（`BaseAgent(tools=...)` 的实参）。
         广告分析 / AIGC / 智能客服三个 Agent 的工具集**曾是悬空注册表**
         （模块里有、装配点为零 ⇒ 那条门禁对它们**恒绿**）。
         ★ 第 204 轮已接线并登记入表 ⇒ 本条对它们**不再恒绿**：
           锚工具若落在那 19 个里，现在会真被校验（含下面的 B 分支）。
      ② 该技能的 `tools` 列**有没有真写上**那个工具。三条判据各自成立，
         但 `tools` 为空 ⇒ `render_skill_tools()` 不渲染「配套工具」段
         ⇒ 模型拿到的收窄指引为零（这正是第 185 轮接线至今的真实状态）。

    ==========================================================================
    ★ 判据（两条，都走 `TOOL_CATALOG` 这个**唯一真源**）
    ==========================================================================
      A. `tools` 里每个名字都必须是**已注册**的 —— 与写口
         `service._validate_tools` 用的是同一个 `is_known_tool`；
      B. 锚工具非 `None` 且**已注册** ⇒ 该技能的 `tools` 必须**包含**它。

    ★ 为什么 A 用 `TOOL_CATALOG` 而不是 `_AGENT_TOOL_MODULES`：
      `TOOL_CATALOG` 的收录判据就是「源码里 `BaseAgent(tools=...)` 实参命名的
      容器」⇒ 它表达的是**真装配**；`_AGENT_TOOL_MODULES` 只表达「模块里有」。

    ★ 反向注入（两条都必须能转红，已实测）：
      · 把某条技能的 `tools` 改成 `["export_report"]`（那个假 placeholder 名）
        ⇒ A 转红；
      · 把 `blueocean-hard-filter` 的 `tools` 清空（`spec["tools"] = []`
        放在 `_backfill_anchor_tools()` **之后**）⇒ B 转红。
    """
    from modules.skills.seed import DEMO_SKILLS, DEMO_SKILL_ANCHOR_TOOLS
    from modules.skills.tools_catalog import all_tool_names, is_known_tool

    known = set(all_tool_names())
    assert known, "TOOL_CATALOG 解析为空 ⇒ 本判据会假绿，请检查 tools_catalog"

    by_name = {s["name"]: s for s in DEMO_SKILLS}

    # ---- A. 声明的工具必须都已注册 ----
    unregistered = sorted(
        (s["name"], t)
        for s in DEMO_SKILLS
        for t in (s.get("tools") or [])
        if not is_known_tool(t)
    )
    assert not unregistered, (
        f"这些技能声明了**未注册**的工具：{unregistered}\n"
        f"⇒ 模型会照着去调一个不在任何 Agent 手上的工具（一次无效调用），"
        f"而界面上看不出异常。合法名字见 `modules/skills/tools_catalog.py::TOOL_CATALOG`。"
    )

    # ---- B. 有锚工具的技能必须真的把它写进 tools ----
    missing = []
    for name, anchor in sorted(DEMO_SKILL_ANCHOR_TOOLS.items()):
        if not anchor or not is_known_tool(anchor):
            # 无对口工具（锚为 None）/ 工具未注册：正当跳过 —— 见 `_backfill_anchor_tools`
            continue
        tools = list(by_name[name].get("tools") or [])
        if anchor not in tools:
            missing.append((name, anchor, tools))
    assert not missing, (
        f"这些技能有锚工具却没写进 `tools`：{missing}\n"
        f"⇒ `render_skill_tools()` 不渲染「本技能配套工具」段，"
        f"模型只能在自己的 5–9 个工具里**猜**该用哪个。\n"
        f"（`_backfill_anchor_tools()` 应在 import 时自动补上；这里红说明它被删了或被绕过。）"
    )


# ==============================================================================
# 悬空工具引用的**库内**清理（第 209 轮）
# —— 补第 207 轮门禁守不住的那一半
# ==============================================================================


async def test_prune_unknown_skill_tools_repairs_dangling_refs_and_is_idempotent(
    auth_off, demo_off, client, skill_owner
):
    """★★★ 「引用了目录里不存在工具」的**库行**必须能被幂等地修掉。

    ★ 这条门禁补的是第 207 轮**门禁守不住的那一半**：
      `test_demo_skill_tools_are_registered_and_cover_their_anchor` 扫的是
      `DEMO_SKILLS`（**源码规格表**），不是库里的行 ——
      「**门禁守源码，缺陷住库行**」。工具退役时规格表改了、库里的行没人动，
      而 `ensure_demo_skills()` 是「缺失才建」、**永不覆盖已有行的 `tools`**
      （那是「重启不覆盖演示改动」这条体验的代价），
      显式对账入口 `--resync` 又不在启动路径上
      ⇒ 悬空引用在库里活了下来，且**界面上完全没有展示面**。
      实测（第 208 轮 `/tools/usage` 才照出来）：4 个退役名 / 7 条引用 / 4 张演示卡。

    ★ 反向注入靶子（第 10 条，已实测）：
      把 `prune_unknown_skill_tools` 里的
          `bad = [t for t in cur if not is_known_tool(t)]`
      换成 `bad = []` ⇒ 本用例转红，红在「注入的坏名没被修掉」。
      （等价地，删掉 `row.tools = want` 也会红。）

    ★ 为什么本用例**不走 HTTP 写口**注入坏名：
      `service._validate_tools` 对未注册工具名是 **fail-closed**（写 422），
      所以「带坏名的行」**只能由『工具退役』这一历史事件产生**，API 产生不了。
      本用例直接改库，正是复现那个历史事件 —— 用写口注入是**做不到**的，
      硬要的话只能把校验关掉，那连门禁一起废了。
    """
    from modules.skills.db_model import SkillRecord
    from modules.skills.seed import prune_unknown_skill_tools
    from modules.skills.tools_catalog import all_tool_names

    good = "optimize_listing_title"
    assert good in all_tool_names(), f"用例锚点失效：{good} 已不在目录里"
    bogus = "__retired_tool_" + uuid.uuid4().hex[:8] + "__"
    name = skill_owner["prefix"] + "-prune"

    created = await client.post(
        "/api/v1/skills",
        json={
            "name": name,
            "title": "悬空引用清理用例",
            "description": "先合法创建，再改库注入退役名",
            "content": "正文",
            "tools": [good],
            "enabledAgents": ["ListingGenerator"],
        },
        headers=skill_owner["headers"],
    )
    assert created.status_code == 201, f"{created.status_code} {created.text[:300]}"

    try:
        # ---- ① 复现历史事件：把库里的行改成「含一个已退役的工具名」----
        async with async_session_factory() as db:
            row = (
                await db.execute(select(SkillRecord).where(SkillRecord.name == name))
            ).scalars().first()
            assert row is not None, "创建成功但库里查不到 —— 用例前提失效"
            row.tools = [good, bogus]
            await db.commit()

        # 先确认**缺陷真的存在**（否则下面的修复断言会变成恒真）
        r = await client.get("/api/v1/tools/usage", headers=skill_owner["headers"])
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert bogus in r.json()["unknownTools"], (
            f"注入的坏名没被读口照出来，用例前提失效：{r.json()['unknownTools']}"
        )

        # ---- ② 干跑：报告要改，但**不许写库** ----
        dry = await prune_unknown_skill_tools(dry_run=True)
        hit = [c for c in dry if c["skill"] == name]
        assert hit, f"干跑没报告这一行：{[c['skill'] for c in dry]}"
        assert hit[0]["after"] == [good], hit[0]
        assert hit[0]["dropped"] == [bogus], hit[0]
        assert hit[0]["source"] == "prune", (
            "这条技能不在 DEMO_SKILLS 里，应走「只摘坏名、保序保留合法名」分支；"
            f"实际 source={hit[0]['source']!r}"
        )
        async with async_session_factory() as db:
            row = (
                await db.execute(select(SkillRecord).where(SkillRecord.name == name))
            ).scalars().first()
            assert row.tools == [good, bogus], f"dry_run 竟然写了库：{row.tools}"

        # ---- ③ 真跑：坏名摘掉、合法名保序保留 ----
        real = await prune_unknown_skill_tools()
        hit = [c for c in real if c["skill"] == name]
        assert hit, f"真跑没报告这一行：{[c['skill'] for c in real]}"
        async with async_session_factory() as db:
            row = (
                await db.execute(select(SkillRecord).where(SkillRecord.name == name))
            ).scalars().first()
            assert row.tools == [good], f"坏名没被摘干净：{row.tools}"

        # ---- ④ 读口不再报未知（修的是「库行」，不是把读口调哑）----
        r2 = await client.get("/api/v1/tools/usage", headers=skill_owner["headers"])
        assert bogus not in r2.json()["unknownTools"], r2.json()["unknownTools"]

        # ---- ⑤ 幂等：稳态第二次跑不再报这一行 ----
        again = await prune_unknown_skill_tools()
        offenders = [c for c in again if c["skill"] == name]
        assert not offenders, f"复跑又改了同一行 —— 不是幂等：{offenders}"
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM skills WHERE name = :n"), {"n": name})


# ==============================================================================
# skill 配装写口（第 209 轮）—— `PUT /skills/{id}/tools`
# ==============================================================================


def _rev_count(body) -> int:
    """版本历史响应条数（端点是 `{items: [...]}` 还是裸数组都兼容）。"""
    if isinstance(body, dict):
        return len(body.get("items") or [])
    return len(body or [])


async def test_set_skill_tools_is_narrow_and_fail_closed(
    auth_off, demo_off, client, skill_owner, make_user
):
    """★★★ `PUT /skills/{id}/tools`（「skill 配装」的唯一写口）：**窄**且 **fail-closed**。

    三件事一起钉：

      ① **不知道就不写** —— 未知工具名 422 **整单拒绝**（不是静默丢弃）。
         静默丢弃会让用户看到「我勾了 3 个、保存后只剩 1 个」却不知道为什么；
         更糟的是工具退役后旧名字会从"生效"变成"永久空转"，而界面上看不出差别
         —— 第 207 轮那 4 个退役名就是这么在库里活下来的（第 209 轮才清掉）。

      ② **窄口不越界** —— 它只许改 `tools`。正文 / 版本号 / 修订史**一个都不许动**。
         否则「改个勾选」会刷爆版本号，真正的正文演进反而看不出来
         （口径同 `resync_demo_skills`：`tools` 是**配置列**，不落快照）。

      ③ **匿名不能改 / 跨账号不能改** —— 而且这条**不能只靠**
         `ensure_can_access_skill`：那是**读**判据，对无身份**刻意放行**
         `is_demo` 行（演示模式要看得到技能）。拿它当写口 =
         「谁看得见谁能改」⇒ 任何匿名访客都能改演示技能。
         本仓判据「认证 ≠ 授权」，所以写口必须自己再判一次身份
         （`_reject_no_identity`）。

    ★ 反向注入靶子（第 11 条，已实测）：
      · 删掉路由里的 `_reject_no_identity(current_user)` ⇒ **④-b** 段转红。
        ★★ 第一版靶子打在**非演示**技能上，注入后**照样绿** —— 因为那一条
           由读判据 `ensure_can_access_skill` 兜住，根本不区分两层判定
           （**判据空跑**：注入没打在要害上）。真靶子只有**演示行**。
      · 把 `if not is_known_tool(key):` 改成 `if False:` ⇒ ③ 段转红，
        但红在 `ValueError: tools 含未注册的工具`（**500**）而不是 422 ——
        说明内层 `service._validate_tools` 是"最后一道"、不是"用户看到的那一道"：
        外层（本路由）负责把非法输入变成 **422 可自查**，内层负责
        **绝不落库**。两层都必须在（去掉任一层都有独立证据）。
    """
    from modules.skills.db_model import SkillRecord

    good = "optimize_listing_title"
    good2 = "analyze_profit"
    name = skill_owner["prefix"] + "-settools"

    created = await client.post(
        "/api/v1/skills",
        json={
            "name": name,
            "title": "配装写口用例",
            "description": "只改 tools，不动正文",
            "content": "正文甲",
            "tools": [good],
            "enabledAgents": ["ListingGenerator"],
        },
        headers=skill_owner["headers"],
    )
    assert created.status_code == 201, f"{created.status_code} {created.text[:300]}"
    sid = created.json()["id"]

    # ★★ 演示行必须在 `try` **之外**取好快照：④-b 会**故意向它发起一次写请求**，
    #    而"写成功了"正是本用例要抓的那个缺陷 —— 那一刻断言抛，
    #    所以恢复动作只能挂在 `finally` 上，不能写成"断言之后的那几行"。
    #    不这么写的话：**用例转红的同时会把共享演示数据改坏**，
    #    接着一串无关用例跟着红 —— 症状伪装成"测试套件坏了"，
    #    而真因是"门禁红了还把夹具搞脏了"（同族：`pytest-fixture-hygiene`）。
    async with async_session_factory() as db:
        demo_row = (
            await db.execute(select(SkillRecord).where(SkillRecord.is_demo.is_(True)))
        ).scalars().first()
    assert demo_row is not None, (
        "测试库里没有演示技能 ⇒ ④-b 会**静默空跑**（第 209 轮踩过）。"
        "演示技能由 `modules.skills.seed` 的规格表提供，缺了要补种子。"
    )
    demo_id = demo_row.id
    demo_tools_before = list(demo_row.tools or [])

    try:
        before = (
            await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
        ).json()
        rev_before = _rev_count(
            (
                await client.get(
                    f"/api/v1/skills/{sid}/revisions", headers=skill_owner["headers"]
                )
            ).json()
        )

        # ---- ① 成功：tools 换成新集合 ----
        r = await client.put(
            f"/api/v1/skills/{sid}/tools",
            json={"toolNames": [good2]},
            headers=skill_owner["headers"],
        )
        assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
        assert r.json()["tools"] == [good2], r.json().get("tools")

        # ---- ② 窄口不越界：正文 / 版本 / 修订史一行都没动 ----
        after = (
            await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
        ).json()
        rev_after = _rev_count(
            (
                await client.get(
                    f"/api/v1/skills/{sid}/revisions", headers=skill_owner["headers"]
                )
            ).json()
        )
        assert after["content"] == before["content"] == "正文甲"
        assert after["version"] == before["version"], (
            f"改勾选竟然 bump 了版本：{before['version']} -> {after['version']}"
        )
        assert rev_after == rev_before, (
            f"改勾选竟然落了修订快照：{rev_before} -> {rev_after}"
        )

        # ---- ③ fail-closed：未知工具名 422，且**整单拒绝**（不能一半写进去）----
        bad = await client.put(
            f"/api/v1/skills/{sid}/tools",
            json={"toolNames": [good2, "__retired_nope__"]},
            headers=skill_owner["headers"],
        )
        assert bad.status_code == 422, f"{bad.status_code} {bad.text[:300]}"
        still = (
            await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
        ).json()
        assert still["tools"] == [good2], (
            f"422 之后配置却被改了 —— 拒必须是整单拒绝：{still['tools']}"
        )

        # 参数形态：缺字段 / 非数组 / 显式 null 一律 422（不静默当空数组）
        for payload in ({}, {"toolNames": good}, {"toolNames": None}):
            rr = await client.put(
                f"/api/v1/skills/{sid}/tools",
                json=payload,
                headers=skill_owner["headers"],
            )
            assert rr.status_code == 422, (
                f"{payload!r} -> {rr.status_code} {rr.text[:200]}"
            )

        # ---- ④-a 真匿名改**非演示**技能：403 ----
        #   ★ 但这条**不区分**「有没有写口身份判定」：非演示技能由**读**判据
        #     `ensure_can_access_skill` 兜住（`user is None` 本身就拒）。
        #     留着它是为了钉住"匿名写不进去"这个结果本身，
        #     但它**不能**充当 `_reject_no_identity` 的靶子（第 209 轮实测踩过）。
        anon = await client.put(
            f"/api/v1/skills/{sid}/tools", json={"toolNames": [good]}
        )
        assert anon.status_code == 403, (
            f"真匿名竟然能改配装：{anon.status_code} {anon.text[:200]}"
        )

        # ---- ④-b ★ 真匿名改**演示**技能：403（**唯一**能分辨两层判定的靶子）----
        #   为什么必须是演示行：读判据 `ensure_can_access_skill` 对无身份
        #   **刻意放行** `is_demo` 行（演示模式要看得到技能）。
        #   ⇒ 写口若只剩读判据，就是「谁看得见谁能改」——
        #      任何匿名访客都能改 / 删演示技能。这条路**只有**
        #      `_reject_no_identity` 守着，所以它才是这条靶子的落点。
        #   （快照已在 `try` 之外取好 —— 理由见那里的注释。）
        anon_demo = await client.put(
            f"/api/v1/skills/{demo_id}/tools", json={"toolNames": [good]}
        )
        assert anon_demo.status_code == 403, (
            f"★ 真匿名竟然能改**演示技能**（{anon_demo.status_code}）—— "
            f"`_reject_no_identity` 不在写口上，剩下的读判据对演示行是放行的。"
            f" {anon_demo.text[:200]}"
        )
        async with async_session_factory() as db:
            row = (
                await db.execute(
                    select(SkillRecord).where(SkillRecord.id == demo_id)
                )
            ).scalars().first()
            assert list(row.tools or []) == demo_tools_before, (
                f"匿名请求**改到了**演示技能：{row.tools}"
            )

        # ---- ⑤ 跨账号 403，且**数据没被动** ----
        other = await make_user("toolsintruder")
        cross = await client.put(
            f"/api/v1/skills/{sid}/tools",
            json={"toolNames": [good]},
            headers=other["headers"],
        )
        assert cross.status_code == 403, f"{cross.status_code} {cross.text[:200]}"
        final = (
            await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
        ).json()
        assert final["tools"] == [good2], f"越权请求竟然改到了数据：{final['tools']}"
    finally:
        async with async_session_factory() as db:
            await db.execute(text("DELETE FROM skills WHERE name = :n"), {"n": name})
            # ★ 演示行**无论绿红都还原**：红恰好就是"真写进去了"，
            #   那正是最需要还原的一刻。
            row = (
                await db.execute(select(SkillRecord).where(SkillRecord.id == demo_id))
            ).scalars().first()
            if row is not None and list(row.tools or []) != demo_tools_before:
                row.tools = list(demo_tools_before)
            await db.commit()
