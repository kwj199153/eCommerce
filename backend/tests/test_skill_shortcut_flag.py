"""技能「快捷卡片开关」（`as_shortcut`）—— 门禁（第 248 轮）

==============================================================================
★★★ 需求原文（老板提问 → 拍板）
==============================================================================
    「我看了【复盘结论写法】是被周报月报**引用**的，那么这个【复盘结论写法】
      是否不应该出现在快捷卡片栏，是直接在 skill 仓库中取消【启用】该技能吗？
      还是需要增加额外按钮」
    →「走方案 B；字段名：as_shortcut」

⇒ 方案 B = **新增一把与「启用」并列的闸**，只决定「对话页要不要给它一张卡」。

==============================================================================
★ 本文件要守的**唯一不变量**（其余用例都是它的外围）
==============================================================================
        「关掉卡片」**绝不等于**「关掉启用」。

因为 `enabled` / `enabled_agents` 一组值被**三处**消费，共用同一套过滤：
    ① 目录注入（第一级披露）  `provider.build_catalog_for`
    ② 正文加载（第二级披露）  `service.read_skill_for_agent`
    ③ 对话页快捷卡片         前端 `useAgentShortcuts.skillCards`

取消【启用】能让 ③ 的卡片消失，但 ① 与 ② 会**一起**断 —— 而「复盘结论写法」
正被同类技能在正文里引用（周报 description + 正文：
「表达结构沿用「复盘结论写法」」），它们的 schema 里
`tools` 不含它、`description` 里也没有那段结构 ⇒ **结构定义整体丢失**，
且 `_load_skill` 会回一句「没有找到名为 … 的技能」，模型被明令禁止自行补全。
⇒ 没有"零改动的正确解法"，只能拆字段（这就是方案 B 的由来）。

`test_turning_the_card_off_never_touches_injection` 就是这条不变量的守门人：
若将来有人"顺手简化"，在 ①/② 的过滤条件里加上 `and s.as_shortcut`，
它当场转红。

==============================================================================
★ 反向注入清单（证明下面每条断言都不是空跑）
==============================================================================
 1. `service.serialize` 里删掉 `"isShortcut": ...`
    ⇒ `test_the_flag_travels_through_the_wire_contract` 转红。
 2. `getattr(skill, "as_shortcut", True)` 的默认值改成 `False`
    ⇒ `test_serialize_assumes_true_when_the_column_is_missing` 转红
    （方向错了会让任何"没跟上新列的假对象 / 旧响应"**静默丢光整排卡片**）。
 3. `read_skill_for_agent` 的过滤链里加上 `or not bool(row.as_shortcut)`
    ⇒ `test_turning_the_card_off_never_touches_injection` 转红（★ 最关键的一条）。
 4. `provider.build_catalog_for` 的 `usable` 推导里加上 `and bool(s.as_shortcut)`
    ⇒ 同上（该用例同时覆盖两条通道）。
 5. `update_skill` 里把 `if any(k in data for k in SHORTCUT_KEYS):` 改成
    `if data.get("isShortcut"):`
    ⇒ `test_update_without_the_field_does_not_touch_it` 转红
    （"没提交"与"提交了 False"会被混为一谈 ⇒ 任何一次"只改标题"的保存
      都会**静默把卡片关掉**）。
 6. `service.create_skill` 的 `as_shortcut=_read_shortcut(payload)` 改成
    `as_shortcut=False` ⇒ `test_create_defaults_to_a_visible_card` 转红。
 7. 迁移文件里删掉 `comment=...` ⇒ 不归本文件管，由 CI 的 `alembic check` 抓
    （本轮实测：漏写后 `alembic check` = FAILED，补上才归零）。
"""

import pytest
from sqlalchemy import text

from core.database import async_session_factory


async def _load_user(db, user_id):
    from sqlalchemy import select

    from core.identity.models import User

    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


async def _make(db, user, account_id, name, **extra):
    """建一条测试技能（默认带上「对本 Agent 生效」的两个必要字段）。"""
    from modules.skills import service

    payload = {
        "name": name,
        "title": "卡片开关用例",
        "description": "用于验证 as_shortcut 与 enabled 是两把闸",
        "content": "## 适用条件\n\n用例正文。\n",
        "enabledAgents": ["review_analyst"],
        "enabled": True,
    }
    payload.update(extra)
    return await service.create_skill(db, user, payload, account_id=account_id)


# ============================================================================
# 1. ★★★ 核心不变量：关卡片 ≠ 关注入
# ============================================================================


async def test_turning_the_card_off_never_touches_injection(skill_owner):
    """★★★ 一条 `as_shortcut=False` 的技能，**仍然**进目录、**仍然**能 load 到正文。

    ★ 这是本轮的**核心不变量**，也是方案 B 存在的全部理由：
      「复盘结论写法」必须保留「对本 Agent 生效」（否则引用它的三条技能断链），
      只是不该占一格卡片。

    ★ 反向注入（两条通道各自都要能被这条抓到）：
        · `service.read_skill_for_agent` 的过滤链加 `or not bool(row.as_shortcut)`
        · `provider.build_catalog_for` 的 `usable` 推导加 `and bool(s.as_shortcut)`
      ⇒ 任一处改动，本用例转红。

    ★ 为什么两条通道必须**一起**断言：只测其中一条的话，另一条被加上
      `as_shortcut` 过滤时无人发现 —— 而两条通道的失效症状完全不同
      （目录里没了 ⇒ 模型"看不见"；正文读不到 ⇒ 模型"看得见读不到"）。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service
    from modules.skills.provider import build_catalog_for

    name = skill_owner["prefix"] + "-sc1"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await _make(db, user, account.id, name, asShortcut=False)
        assert created["isShortcut"] is False, "前置不成立：卡片开关没落成 False"

        # ① 第二级披露：正文必须**照旧**读得到
        body = await service.read_skill_for_agent(db, user, "review_analyst", name)
        assert body and body.strip(), (
            "as_shortcut=False 的技能读不到正文 —— 卡片开关**不该**影响注入。"
            "这条一断，引用它的技能（周报）就失去了结构定义。"
        )

    # ② 第一级披露：目录里必须**照旧**有它（★ 该函数自建 session，故放在 with 外）
    catalog = await build_catalog_for("review_analyst", skill_owner["user_id"])
    assert name in catalog, (
        f"as_shortcut=False 的技能从目录里消失了（目录={catalog[:200]!r}）—— "
        f"关卡片被误实现成了关注入（本仓判据：一个字段两个判定 ⇒ 想动其中一个必误伤另一个）"
    )


# ============================================================================
# 2. 契约：字段必须真的传到前端
# ============================================================================


async def test_the_flag_travels_through_the_wire_contract(skill_owner):
    """出参必须带 `isShortcut`，且**列表与详情两档都在**。

    ★ 反向注入：`serialize` 里删掉 `"isShortcut": ...` ⇒ 本用例转红。

    ★ 为什么列表档也必须带：卡片区读的正是**列表接口**
      （`skillStore.loadAll()` → `GET /skills`）。只在详情档带 = 卡片区永远读到
      `undefined`（然后靠前端的 `!== false` 兜底成"显示"）——
      表面上一切正常，功能**完全不生效**且零报错。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-sc2"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        await _make(db, user, account.id, name, asShortcut=False)

        listed = [it for it in await service.list_skills(db, user) if it["name"] == name]
        assert listed, "刚建的技能不在列表里（前置不成立）"
        assert "isShortcut" in listed[0], "列表接口没带 isShortcut ⇒ 卡片区拿不到它"
        assert listed[0]["isShortcut"] is False, (
            f"列表档的 isShortcut 不是 False：{listed[0]['isShortcut']!r}"
        )

        detail = await service.get_skill_detail(db, user, listed[0]["id"])
        assert detail["isShortcut"] is False, "详情档的 isShortcut 不对"


def test_serialize_assumes_true_when_the_column_is_missing():
    """★★ 取不到这一列时**一律当 True**（方向必须是"照常显示卡片"）。

    ★ 为什么需要它：`serialize` 被测试用**简易对象 / dict 包装**喂过，
      而本列是最后加的（与 `icon` 同款处境）。写死属性访问会让那些既有用例炸；
      而"取不到就当 False"更糟 —— 任何一个没跟上新列的假对象 / 旧响应
      都会让**整排卡片静默消失**，零报错，极难归因。

    ★ 反向注入：把 `getattr(skill, "as_shortcut", True)` 的默认值改成 `False`
      ⇒ 本用例转红。
    """
    from modules.skills import service

    class _Fake:
        """没有 `as_shortcut` 属性的最小对象（模拟"没跟上新列的调用方"）。"""

        id = "skill_fake"
        name = "fake"
        title = "假技能"
        icon = ""
        description = ""
        content = ""
        tools = []
        version = "1.0.0"
        visibility = "account"
        enabled = True
        enabled_agents = []
        is_demo = False
        account_id = None
        created_at = None
        updated_at = None

    got = service.serialize(_Fake(), include_content=False)
    assert got["isShortcut"] is True, (
        "取不到 as_shortcut 时应当**照常显示卡片**（True）—— "
        "取 False 会让整排卡片静默消失，且没有任何一处会报错"
    )

    class _Null:
        """属性在但值为 None（老库 / 手工插入的行）。"""

        as_shortcut = None
        id = "skill_null"
        name = "null"
        title = ""
        icon = ""
        description = ""
        content = ""
        tools = []
        version = "1.0.0"
        visibility = "account"
        enabled = True
        enabled_agents = []
        is_demo = False
        account_id = None
        created_at = None
        updated_at = None

    assert service.serialize(_Null(), include_content=False)["isShortcut"] is True, (
        "as_shortcut 为 None 时也应当按 True 处理（列是 NOT NULL，None 只可能来自脏数据）"
    )


# ============================================================================
# 3. 写口：默认值 + 三态 + 别名
# ============================================================================


async def test_create_defaults_to_a_visible_card(skill_owner):
    """新建时**不提**卡片开关 ⇒ 默认 True（与 DB 列默认同向 = 保持现行为）。

    ★ 反向注入：`create_skill` 里把 `as_shortcut=_read_shortcut(payload)`
      改成 `as_shortcut=False` ⇒ 本用例转红。

    ★ 方向必须是 True：新建技能默认有卡片，是老板此刻看到的行为。
      取 False 会让"新建的技能一律没有卡片"—— 一个非常大的行为变更，
      而且用户会以为是"技能没建成功"。
    """
    from core.auth.accounts import ensure_default_account

    name = skill_owner["prefix"] + "-sc3"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await _make(db, user, account.id, name)
        assert created["isShortcut"] is True, (
            f"新建时没提卡片开关，默认却不是 True：{created['isShortcut']!r}"
        )


async def test_create_adopts_an_explicit_false(skill_owner):
    """新建时显式给 `asShortcut: False` ⇒ 采纳（否则前端那个开关在新建路径上无效）。"""
    from core.auth.accounts import ensure_default_account

    name = skill_owner["prefix"] + "-sc4"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await _make(db, user, account.id, name, asShortcut=False)
        assert created["isShortcut"] is False


async def test_update_without_the_field_does_not_touch_it(skill_owner):
    """★★ 三态第一态：更新请求**没带**任何别名 ⇒ 原值不动。

    ★ 反向注入：`update_skill` 里把 `if any(k in data for k in SHORTCUT_KEYS):`
      改成 `if data.get("isShortcut"):` ⇒ 本用例转红。

    ★ 为什么这条最重要：老板在演示里手工关掉某张卡片之后，只要**再编辑一次
      标题**（完全无关的操作），卡片就会静默长回来。而界面上没有任何线索
      指向"是那次保存把它打开的" —— 本仓「重启不覆盖演示改动」的同族形态。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-sc5"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await _make(db, user, account.id, name, asShortcut=False)

        row = await service.get_skill_row(db, created["id"])
        updated = await service.update_skill(db, user, row, {"title": "只改标题"})
        assert updated["isShortcut"] is False, (
            f"没提交卡片开关，它却被改成了 {updated['isShortcut']!r} —— "
            f"「没提交」与「提交了 False」被混为一谈"
        )


async def test_update_can_turn_the_card_off_and_back_on(skill_owner):
    """三态第二、三态：带 True / 带 False 都要**双向**生效。

    ★ 只测一个方向的话，"只会写 False"（或"只会写 True"）的实现全绿 ——
      而另一个方向就是用户点了开关却没有任何反应。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-sc6"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await _make(db, user, account.id, name)
        assert created["isShortcut"] is True

        row = await service.get_skill_row(db, created["id"])
        off = await service.update_skill(db, user, row, {"isShortcut": False})
        assert off["isShortcut"] is False, "拨到 False 没生效（关不掉卡片）"

        row = await service.get_skill_row(db, created["id"])
        on = await service.update_skill(db, user, row, {"isShortcut": True})
        assert on["isShortcut"] is True, "拨回 True 没生效（卡片再也回不来）"


@pytest.mark.parametrize("key", ["isShortcut", "asShortcut", "as_shortcut"])
async def test_write_accepts_every_documented_alias(skill_owner, key):
    """★★ 三个别名（前端 camelCase / 老板拍板的 DB 列名两个写法）都认。

    ★ 为什么必须允许别名：DB 列叫 `as_shortcut`（老板拍板），前端契约沿用
      camelCase（`isShortcut`）。只认一个名字的后果是**另一个名字静默落到默认值**
      —— 调用方以为关掉了卡片，实际什么都没发生，而且不报错。
      这正是本仓最怕的「写口缺值不报错」。

    ★ 反向注入：把 `SHORTCUT_KEYS` 收窄成 `("isShortcut",)`
      ⇒ 本参数化的后两条转红。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-sc7-" + key.lower()
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        created = await _make(db, user, account.id, name)

        row = await service.get_skill_row(db, created["id"])
        updated = await service.update_skill(db, user, row, {key: False})
        assert updated["isShortcut"] is False, (
            f"用 {key!r} 提交没生效 —— 这个别名会**静默落到默认值**"
        )


# ============================================================================
# 4. schema：列必须真的在库里
# ============================================================================


async def test_the_column_exists_in_the_database_with_the_right_shape():
    """`skills.as_shortcut` 必须在**库里**，`NOT NULL`，且**不带**数据库侧默认值。

    ★ 这条抓的是三件"本地开发完全正常"的事：
      ① 只改 ORM 忘了迁移 —— 全新库靠 `create_all` 建得出来，**老库**不炸在建表
         而是炸在第一次读写；
      ② 列可空 —— 老行取到 `NULL`，`bool(None)` 是 `False` ⇒ **卡片全没了**；
      ③ 留了 `server_default` —— 本仓口径是「默认值的唯一真源在 ORM」，
         数据库侧再留一个就是第二份真源，将来改口径必漏一处。
         （迁移里的 `server_default=sa.true()` 是**一次性回填手段**，用完即撤。）
    """
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT data_type, is_nullable, column_default, "
                    "       col_description(a.attrelid, a.attnum) "
                    "FROM information_schema.columns c "
                    "JOIN pg_class cl ON cl.relname = c.table_name "
                    "JOIN pg_attribute a ON a.attrelid = cl.oid "
                    "                   AND a.attname = c.column_name "
                    "WHERE c.table_name = 'skills' AND c.column_name = 'as_shortcut'"
                )
            )
        ).all()

    assert rows, (
        "skills 表里没有 as_shortcut 列 —— ORM 声明了但迁移没做"
        "（全新库靠 create_all 建得出来，老库不会）"
    )
    data_type, is_nullable, default, comment = rows[0]
    assert data_type == "boolean", f"列类型意外：{data_type}"
    assert is_nullable == "NO", (
        "as_shortcut 可空 ⇒ 老行的值为 NULL ⇒ bool(None)=False ⇒ 卡片全部消失"
    )
    assert default is None, (
        f"列上留了数据库侧默认值 {default!r} —— 本仓口径：默认值只写在 ORM "
        f"（迁移里的 server_default 只用于一次性回填，用完必须撤掉）"
    )
    assert comment, "列注释丢了 —— alembic check 会报 modify_comment（本轮踩过）"


# ============================================================================
# 5. 演示数据契约：被引用的那条「规矩型」技能
# ============================================================================


async def test_the_demo_narrative_skill_has_no_card_but_stays_enabled():
    """★★★ 演示库里「复盘结论写法」= `as_shortcut=False` + `enabled=True`。

    ★ 这是老板那条需求的**端到端落点声明**，四件事一起断言：
        · `enabled` 仍为 True      ⇒ 引用它的周报**不会断链**；
        · `enabled_agents` 仍含 review_analyst ⇒ 仍在目录里、仍可 load；
        · `as_shortcut` 为 False   ⇒ 对话页不再给它卡片；
        · 它被同类技能在正文里**显式引用**（可计算信号，防止将来有人"顺手"
          把它标回 True —— 那时引用就变成了一份无人遵守的口头约定）。

    ★ 引用信号用 `seed.DEMO_SKILLS` 的正文扫描取，而不是在这里抄一份名单：
      名单会与正文分叉，扫描不会。
    """
    from modules.skills import service
    from modules.skills.seed import DEMO_SKILLS

    narrative_name = "weekly-review-narrative"
    narrative_title = "复盘结论写法"

    # ---- ① 源码规格表：被引用的信号（可计算）----
    referencing = []
    for spec in DEMO_SKILLS:
        if spec["name"] == narrative_name:
            continue
        blob = (spec.get("description") or "") + "\n" + (spec.get("content") or "")
        if narrative_title in blob:
            referencing.append(spec["name"])
    assert referencing, (
        "没有任何技能在正文/描述里引用「复盘结论写法」—— 那它就**不满足**"
        "「规矩型」的第 ③ 条判据（被同类技能显式声明为结构来源），"
        "`as_shortcut=False` 的前提不成立了，需要重新判定"
    )

    # ---- ② 源码规格表：本条被标为规矩型 ----
    spec = next((s for s in DEMO_SKILLS if s["name"] == narrative_name), None)
    assert spec is not None, f"规格表里没有 {narrative_name}"
    assert spec.get("as_shortcut") is False, (
        f"规格表里 {narrative_name} 没有标 as_shortcut=False"
    )

    # ---- ③ 库行：与规格表一致，且**仍然启用** ----
    async with async_session_factory() as db:
        row = await service.get_skill_by_name(db, narrative_name)
        if row is None:
            pytest.skip(f"演示技能 {narrative_name} 不在本库（演示数据未灌）")
        assert bool(row.enabled) is True, (
            "「复盘结论写法」被停用了 —— 引用它的技能会断链（这正是老板最初"
            "想直接取消启用时我否掉的那条路）"
        )
        assert "review_analyst" in list(row.enabled_agents or []), (
            "「复盘结论写法」不再对 review_analyst 生效 ⇒ 它与周报"
            "落在不同 Agent 上，注入与引用必然错位"
        )
        assert bool(row.as_shortcut) is False, (
            "库行的 as_shortcut 仍是 True ⇒ 对话页还会给它一张卡片。"
            "（★ 常见成因：改了规格表但没跑 --resync —— 本仓「门禁守源码、"
            "缺陷住库行」的老形态）"
        )


async def test_the_demo_triage_skill_has_no_card_but_stays_reachable():
    """★★★ 演示库里「差评应对」= `as_shortcut=False` + `enabled=True`（第 295 轮 A 档）。

    ★★★ **与上一条理由不同，别把两者混为一谈**（这是本用例存在的一半理由）：
        · 「复盘结论写法」是「**规矩型**」—— 点下去拿不到成品，它只管"怎么写"，
          "写什么"得由别的技能先产出；
        · 「差评应对」是「**入口重复型**」—— 能力一点没少，只是**卡片那条通道冗余**：
          差评的取证 / 判定 / 补偿 / 处置在【差评处理】工作台里已是完整流程，
          卡片点下去只会把面板已有的东西（归因 / 重复计数 / 健康分）再算一遍。
      ⇒ 两条技能共用**同一个字段**，撤卡片的**理由却是两类**。将来第三条要撤卡片
        时，必须先答"它是哪一类"，而不是照着其中一条抄 —— 抄错的后果是把一条
        真有独立入口价值的技能从对话页藏起来。

    ★ 为什么**不能**改成「停用」（老板拍板 A 档时，B 档就是这个坑）：
      停用是**三条通道一起关**（目录注入 / `load_skill` / 卡片）⇒ 对话里的多轮追问
      （让它解释「凭什么算重复」、跟买家拉锯、跨 SKU 横向比）这条路一起没了 ——
      而那正是老板要保住的东西。

    ★ 老板原话（第 295 轮拍板）：
      「原则上我需要 agent 有相关领域技能，我可以对话实现，功能栏和看板只是辅助
       （因为是要做 ai native saas）」
      ⇒ 卡片是**渲染形态之一**，不是能力本身；撤它只能撤"入口"，不能撤"能力"。

    ★ 反向注入（本用例上挂两条，各自打在不同层）：
        · 规格表里删掉这条的 `"as_shortcut": False` ⇒ 断言 ① 转红；
        · 把库行的 `as_shortcut` 改回 True（= 改规格表但没跑 `--resync`）⇒ 断言 ③ 转红；
        · `provider.build_catalog_for` 的过滤链里加 `and bool(s.as_shortcut)`
          ⇒ 断言 ④ 转红（★ 这条同时防"将来有人顺手把 as_shortcut 也加进目录过滤"）。
    """
    from modules.skills import service
    from modules.skills.provider import build_catalog_for
    from modules.skills.seed import DEMO_SKILLS, demo_account_row

    triage_name = "cs-negative-review-triage"
    triage_agent = "智能客服"

    # ---- ① 源码规格表：撤卡片 ----
    spec = next((s for s in DEMO_SKILLS if s["name"] == triage_name), None)
    assert spec is not None, f"规格表里没有 {triage_name}"
    assert spec.get("as_shortcut") is False, (
        f"规格表里 {triage_name} 没有标 as_shortcut=False ⇒ 对话页又会给它一张卡片，"
        f"「入口统一到面板」这个产品决策被静默回退"
    )

    # ---- ② 源码规格表：取证链完整（撤卡片**不该**动工具绑定）----
    #   ★ 这条不是凑数：撤卡片时最容易顺手做的事就是"既然卡片没了，把它那串
    #     专属工具也摘了吧" —— 而面板的补偿依据正是走这几个工具落库的。
    tools = list(spec.get("tools") or [])
    assert len(tools) == 5, (
        f"{triage_name} 的取证链是 5 个工具（差评上下文 → 订单物流 → SKU 健康分 → "
        f"补偿建议 → 同类差评），实测 {len(tools)} 个 —— 撤卡片不该动这一列"
    )
    assert "get_customer_review_context" in tools and "plan_compensation" in tools

    # ---- ③ 库行：与规格表一致，且**仍然启用** ----
    acct = await demo_account_row()
    if acct is None:
        pytest.skip("演示账号不在本库（演示数据未灌）")
    async with async_session_factory() as db:
        row = await service.get_skill_by_name(db, triage_name)
        if row is None:
            pytest.skip(f"演示技能 {triage_name} 不在本库（演示数据未灌）")
        assert bool(row.enabled) is True, (
            "「差评应对」被停用了 —— 老板要的「对话里追问」这条路会一起断。"
            "（撤卡片只该关卡片这一条通道，不该动 enabled）"
        )
        assert triage_agent in list(row.enabled_agents or []), (
            f"「差评应对」不再对 {triage_agent} 生效 ⇒ 它连目录都进不去了"
        )
        assert bool(row.as_shortcut) is False, (
            "库行的 as_shortcut 仍是 True ⇒ 对话页还会给它一张卡片。"
            "（★ 常见成因：改了规格表但没跑 --resync —— 本仓「门禁守源码、"
            "缺陷住库行」的老形态）"
        )

    # ---- ④ 端到端：撤卡片之后，它**仍在**智能客服的技能目录里 ----
    #   ★ 问的是 `build_catalog_for` 函数本身，不是 grep 源码、也不是数前端卡片 ——
    #     「能力是否保留」的唯一权威是那条真正决定注入的函数。
    catalog = await build_catalog_for(triage_agent, acct.owner_user_id)
    assert triage_name in catalog, (
        f"撤卡片后「差评应对」从智能客服的目录里消失了 —— "
        f"这意味着 `as_shortcut` 被误接进了目录过滤链，能力真的丢了。"
        f"（目录={catalog[:200]!r}）"
    )
