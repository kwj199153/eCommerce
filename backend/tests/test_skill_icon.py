"""技能图标（emoji）—— 门禁（第 188 轮）

==============================================================================
★★★ 需求原文
==============================================================================
    「emoji + 保存时自动生成 + 允许手工改（留空则 AI 补）」

这句话拆开后，有**四类**「看起来做完了、实际不生效」的形态，本文件逐一钉住：

① **解析塌陷**：提示词写着"只回一个 emoji"，但模型经常回
   「这个技能的图标是：📉」。若直接把 `response.content.strip()` 存进库，
   `skills.icon` 里就会是一整句话 —— 界面一个 `<span>` 里塞一段中文，
   而列只有 16 字符还会被截断。⇒ `extract_emoji` 必须真的**摘**。

② **裸字符误判**（★ 这条最隐蔽）：`extract_emoji` 若不把 ASCII 数字
   当作"有条件的基字符"，`"每月1号复盘"` 会被摘出 `"1"` 并当成图标存进去。
   而这行描述**完全正常**，所以真实数据里迟早出现，
   且症状（图标变成一个数字）极难归因到解析函数。

③ **生成失败把保存一起带走**：图标是装饰性元数据，LLM 抖一下不该让用户
   刚写完的 900 字正文保存失败。⇒ 任何异常都必须吞掉并落空串。

   ★★ 但「不阻断」必须与「不伪装」成对：失败时**落空串**而不是塞一个
      `📦` 之类的默认图标 —— 后者会让"AI 从没成功过"在界面上**完全不可见**
      （本仓「降级路径禁用全 0 兜底」的同族形态）。

④ **三态被搓成两态**：`update` 里「没带这个字段」与「带了空值」是**两件事**：
     · 没带   ⇒ 不动（"这次请求没提交图标" ≠ "我要清空它"）；
     · 空值   ⇒ AI 补（这就是需求原文的「留空则 AI 补」）；
     · 非空   ⇒ 采纳（这就是「允许手工改」）。
   只实现两种（比如"空值 = 不动"）会让需求里的"留空则 AI 补"**永远走不到**，
   而表面上一切正常。

==============================================================================
★ 反向注入清单
==============================================================================
 1. `extract_emoji` 里删掉 `if conditional and not saw_keycap_mark: continue`
    ⇒ `test_extract_emoji_never_mistakes_bare_digits...` 转红。
 2. `generate_skill_icon` 里把 `except Exception` 去掉（让异常冒出去）
    ⇒ `test_icon_generation_failure_never_blocks_a_save` 转红。
 3. `create_skill` 里删掉 `if not icon:` 直接 `row.icon = icon`
    ⇒ `test_create_fills_the_icon_when_left_empty` 转红。
 4. `update_skill` 里把 `if "icon" in data:` 改成 `if data.get("icon"):`
    ⇒ `test_update_with_an_empty_icon_regenerates_it` 转红
    （"留空则 AI 补"在这条路径上失效）。
 5. `service.serialize` 里删掉 `"icon": ...`
    ⇒ `test_icon_travels_through_the_wire_contract` 转红。
"""

import pytest
from sqlalchemy import select, text

from core.database import async_session_factory

from modules.skills.icon import (
    ICON_MAX_CHARS,
    extract_emoji,
    generate_skill_icon,
    set_icon_generator,
)


async def _load_user(db, user_id):
    from core.identity.models import User

    return (await db.execute(select(User).where(User.id == user_id))).scalar_one()


# ============================================================================
# 1. 解析：从任意文本里摘出 emoji（纯函数，零 IO）
# ============================================================================


@pytest.mark.parametrize(
    "raw,expected",
    [
        # 理想形态
        ("📉", "📉"),
        # ★ 实际最常见的形态：模型先说一句话再给图标
        ("图标：📉", "📉"),
        ("这个技能的图标是：💰 请使用它", "💰"),
        # 带引号（模型爱加）
        ("“📉”", "📉"),
        ('"📉"', "📉"),
        # 前后都有噪声
        ("好的，我建议用 📊 来表示复盘。", "📊"),
    ],
)
def test_extract_emoji_picks_it_out_of_a_sentence(raw, expected):
    """★★ 摘取必须真的发生 —— 存一整句话会让 `icon` 变成一个 UI 事故。

    ★ 反向注入：把 `extract_emoji` 改成 `return raw.strip()` ⇒ 本用例转红。
    """
    assert extract_emoji(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "每月1号复盘",
        "TOP10 关键词监控",
        "# 5 步法",
        "周一 8 点看数据",
        "3.5 倍增长",
        "SHEIN 竞品对比",
        "A/B 测试变体",
        "2026 年度规划",
        "利润率 12% 以上",
    ],
)
def test_extract_emoji_never_mistakes_bare_digits_or_letters_for_icons(raw):
    """★★★ 裸数字 / 字母 / 符号**绝不能**被当成图标。

    ★ 这条是真实缺陷的守门人，不是洁癖：
      `0-9` 在 Unicode 里可以构成键帽 emoji（`1️⃣` = `1` + VS16 + U+20E3），
      所以它们必须是"**有条件的**基字符"—— 只有后面真跟着键帽修饰符才算。
      若图省事把 `0-9` 无差别当基字符，上面这些**完全正常**的技能描述
      会被摘出一个裸数字存进 `icon`，界面上就显示一个数字。
      症状（图标变成数字）与原因（解析函数的条件判断）隔了很远，极难归因。

    ★ 反向注入：删掉 `if conditional and not saw_keycap_mark: continue`
      ⇒ 本用例整体转红（每条都会摘出首字符）。
    """
    assert extract_emoji(raw) is None, (
        f"{raw!r} 里没有 emoji，却摘出了图标 —— 会把一个数字/字母当图标存进库"
    )


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("☀️", "☀️"),          # 基字符 + VS16（缺 VS16 会渲染成文字色）
        ("👍🏽", "👍🏽"),        # 基字符 + 肤色修饰
        ("🇨🇳", "🇨🇳"),         # 区域指示符成对 = 国旗
        ("👨\u200d💻", "👨\u200d💻"),  # ZWJ 拼合序列
        ("1️⃣", "1️⃣"),          # 键帽（★ 有条件的基字符，这条证明条件**成立**时放行）
        ("第2️⃣季度", "2️⃣"),    # 键帽夹在文字中
    ],
)
def test_extract_emoji_keeps_whole_sequences(raw, expected):
    """多码点 emoji 序列必须**整段**保留，不能只取首个码点。

    ★ 只取首码点的症状：`☀️` 变成 `☀`（渲染成黑色文字符号）、
      `🇨🇳` 变成 `🇨`（一个孤立的区域指示符，多数环境渲染成方框）。
    """
    assert extract_emoji(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "没有任何图标的纯文字", "hello world"])
def test_extract_emoji_returns_none_without_any_icon(raw):
    """没有 emoji ⇒ `None`（**不是**空串、不是首个字符）。"""
    assert extract_emoji(raw) is None


def test_extract_emoji_truncates_a_runaway_sequence():
    """模型一次甩出一长串 emoji ⇒ 只取第一个，且长度受控。

    ★ 不设上限的症状：`icon` 列是 `String(16)`，超长值会被数据库**静默截断**
      （PostgreSQL 的 `character varying(n)` 超长会直接报错，但截断风险
      在别的库上真实存在）—— 更要紧的是会把一串 emoji 渲染成一排乱码图标。
    """
    got = extract_emoji("📉🎯💬📣🖼🎧🧭✅📊🔀")
    assert got is not None and len(got) <= ICON_MAX_CHARS
    assert extract_emoji(got) == got, "截断之后应当仍是一个合法 emoji 序列"


# ============================================================================
# 2. 生成失败：不抛错、不伪装
# ============================================================================


async def test_icon_generation_failure_never_raises():
    """★★★ 生成器炸了 ⇒ 返回 `None`，**绝不把异常抛给保存路径**。

    ★ 反向注入：去掉 `generate_skill_icon` 里的 `except Exception` ⇒ 本用例转红。
    """

    async def _boom(title, description):
        raise RuntimeError("模拟 LLM 挂了")

    set_icon_generator(_boom)
    try:
        assert await generate_skill_icon("标题", "描述") is None
    finally:
        set_icon_generator(None)


async def test_icon_generation_returns_none_when_reply_has_no_emoji():
    """生成器回了纯文本 ⇒ `None`。

    ★★ 关键：**不要**在这里换成一个"默认图标"。
      一个像模像样的默认图标会让"AI 从没成功过"这件事在界面上完全不可见 ——
      老板会以为图标是 AI 挑的，实际是写死的。
    """

    async def _plain(title, description):
        return None  # 真实实现里 `extract_emoji` 摘不到时就是返回 None

    set_icon_generator(_plain)
    try:
        assert await generate_skill_icon("标题", "描述") is None
    finally:
        set_icon_generator(None)


# ============================================================================
# 3. 保存路径：留空则补 / 给了就用
# ============================================================================


async def test_create_fills_the_icon_when_left_empty(skill_owner):
    """★★ 新建时**不给** `icon` ⇒ 由生成器补上一个。

    ★ 反向注入：`create_skill` 里删掉 `if not icon:` 那段 ⇒ 本用例转红。

    ★ 本用例走的是 conftest 的确定性桩（零网络）。桩换个生成器不等于没测 ——
      "生成内容对不对"由上面的 `extract_emoji` 用例覆盖，
      这里要钉的是**调用关系**：留空 ⇒ 生成器被调用 ⇒ 值落库。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic1"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "评论痛点挖掘",
                "description": "把评论按三分类归纳",
                "content": "正文",
                # ★ 刻意**不带** icon
            },
            account_id=account.id,
        )

        assert created["icon"], (
            "新建时没给图标，结果也没补上 —— 需求原文的「留空则 AI 补」在这条路径上没生效"
        )
        assert extract_emoji(created["icon"]) == created["icon"], (
            f"补上来的不是一个合法 emoji：{created['icon']!r}"
        )


async def test_create_keeps_a_hand_written_icon(skill_owner):
    """★★ 「允许手工改」：给了就用给的，**不被 AI 覆盖**。

    ★ 与上一条成对。只测上一条的话，一个"无条件覆盖成生成值"的实现全绿 ——
      而那正好把老板手工挑的图标每次保存都改掉。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic2"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "icon": "🚀",  # ← 手工值
            },
            account_id=account.id,
        )
        assert created["icon"] == "🚀", (
            f"手工指定的图标被改掉了：{created['icon']!r} —— 「允许手工改」没生效"
        )


async def test_update_without_the_icon_field_does_not_touch_it(skill_owner):
    """更新请求**没带** `icon` 字段 ⇒ 原值不动。

    ★ 三态的第一态。若把它与"带了空值"混为一谈，那么任何一次
      「只改标题」的保存都会顺手把图标重新生成一遍（多一次 LLM 调用，
      而且图标会漂移成另一个）。⇒ 必须用 `in` 判定，不能用真值判定。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic3"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "icon": "🚀",
            },
            account_id=account.id,
        )
        row = await service.get_skill_row(db, created["id"])
        updated = await service.update_skill(db, user, row, {"title": "新标题"})
        assert updated["icon"] == "🚀", (
            f"没提交 icon 字段，图标却被改了：{updated['icon']!r}"
        )


async def test_update_with_an_empty_icon_regenerates_it(skill_owner):
    """更新请求带了**空** `icon` ⇒ AI 补（这就是需求原文那句「留空则 AI 补」）。

    ★ 反向注入：把 `if "icon" in data:` 改成 `if data.get("icon"):`
      ⇒ 本用例转红 —— 空值会被当成"没提交"而**静默跳过**，
      于是需求里"留空则补"这条路**永远走不到**，而表面上一切正常。
      这是本条最主要的守门对象：**一个永远不执行的正常路径**。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic4"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "icon": "🚀",
            },
            account_id=account.id,
        )
        row = await service.get_skill_row(db, created["id"])
        updated = await service.update_skill(db, user, row, {"icon": ""})
        assert updated["icon"] and updated["icon"] != "🚀", (
            f"提交了空图标却没重新生成（当前 {updated['icon']!r}）—— "
            f"「留空则 AI 补」在更新路径上没生效"
        )
        assert extract_emoji(updated["icon"]) == updated["icon"]


async def test_update_with_a_new_icon_adopts_it(skill_owner):
    """更新请求带了非空 `icon` ⇒ 采纳（手工改图标的主路径）。"""
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic5"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)

        created = await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "icon": "🚀",
            },
            account_id=account.id,
        )
        row = await service.get_skill_row(db, created["id"])
        updated = await service.update_skill(db, user, row, {"icon": "🧭"})
        assert updated["icon"] == "🧭", (
            f"手工换的图标没被采纳：{updated['icon']!r}"
        )


# ============================================================================
# 4. 契约与 schema
# ============================================================================


async def test_icon_travels_through_the_wire_contract(skill_owner):
    """出参必须带 `icon`（前端要拿它渲染卡片），且分列表/详情两档都在。

    ★ 反向注入：`serialize` 里删掉 `"icon": ...` ⇒ 本用例转红。

    ★ 两个都不带就完了吗？不 —— 列表接口（`include_content=False`）也带
      `icon` 才有意义：卡片列表正是从**列表接口**来的。
    """
    from core.auth.accounts import ensure_default_account
    from modules.skills import service

    name = skill_owner["prefix"] + "-ic6"
    async with async_session_factory() as db:
        user = await _load_user(db, skill_owner["user_id"])
        account = await ensure_default_account(db, user)
        await service.create_skill(
            db,
            user,
            {
                "name": name,
                "title": "标题",
                "description": "描述",
                "content": "正文",
                "icon": "🚀",
            },
            account_id=account.id,
        )

        listed = [it for it in await service.list_skills(db, user) if it["name"] == name]
        assert listed, "刚建的技能不在列表里（前置不成立）"
        assert listed[0]["icon"] == "🚀", "列表接口没带 icon ⇒ 卡片渲染不出图标"

        detail = await service.get_skill_detail(db, user, listed[0]["id"])
        assert detail["icon"] == "🚀", "详情接口没带 icon"


async def test_icon_column_exists_in_the_database():
    """`skills.icon` 必须在**库里**，不只是 ORM 声明。

    ★ 这条抓的是"加了字段忘了迁移"：ORM 声明了、代码到处能跑（写读都经 ORM），
      但迁移没做 ⇒ 只有**老库**会炸，而且是运行期才炸。
      而 `create_all()` 在全新库上会把列建出来 ⇒ 本地开发环境**完全正常**，
      事故只在已经存在的库上出现。
    """
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT data_type, character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_name = 'skills' AND column_name = 'icon'"
                )
            )
        ).all()

    assert rows, (
        "skills 表里没有 icon 列 —— ORM 声明了但迁移没做（全新库靠 create_all 建得出来，"
        "老库不会）"
    )
    data_type, max_len = rows[0]
    assert "character" in data_type, f"icon 列类型意外：{data_type}"
    assert max_len == ICON_MAX_CHARS, (
        f"icon 列长度 {max_len} 与代码里的 ICON_MAX_CHARS={ICON_MAX_CHARS} 不一致 —— "
        f"两处口径必须同源"
    )
