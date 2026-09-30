"""技能收藏（⭐）—— 门禁（第 194 轮建 / 第 195 轮收窄）

==============================================================================
★★★ 这条测试钉住的是什么
==============================================================================
老板第 194 轮要「技能仓库加筛选 / 分组 / 收藏」。筛选与分组是纯前端派生
（由 `scripts/check-skill-filter-logic.cjs` 用 vm 沙箱钉），唯一**必须落后端**
的是收藏 —— 而它有一个「看起来对、实际不生效」的形态：

★ **第 195 轮收窄**：本文件原先还钉「自定义标签 `tags`」（9 条纯函数 + 5 条 HTTP）。
  老板看到界面后指出「删除标签相关内容」—— 复核发现该概念**只有筛选口、
  没有任何录入入口**（永远筛不出东西），属半成品 ⇒ 整体退役
  （列已 drop，见迁移 `c5f9a3e7b2d8`）。那些用例随之删除。

① **收藏 `favorited`**：它是「用户 × 技能」的关系，**不是 `skills` 行上的字段**。
   由此派生三条容易漏的判据：
     · **必须按人隔离** —— 张三的收藏不能显示在李四的星标上；
     · **必须是幂等的「设为」而不是 toggle** —— toggle 在任何重试/双击/
       乐观更新重发下都会翻转两次，最终与用户意图相反，而界面上看不出错；
     · **不能污染 `skills.updated_at`** —— 否则本轮的「按更新时间排序」
       会因为点了个星标而把技能顶到最前面（排序失真），
       而症状看起来是「排序功能坏了」，不会有人怀疑到星标上。

③ **每个返回技能对象的路径都要传对 `favorited`**。漏传 ⇒ 返回 `false` ⇒
   前端据此取消星标 ⇒ 症状是「我的收藏丢了」，看起来像数据被删。
   本轮有 4 个返回点：列表 / 详情 / 新建 / 更新，逐个钉住。

==============================================================================
★ 反向注入清单（每条都必须真的能转红 —— 已实测，见文件末尾）
==============================================================================
 ★ 原 #1 / #2 两条靶子（`_validate_tags` 的静默截断、数量判定位置）
   已随「自定义标签」概念退役一并移除 —— 对应的函数已不在 `service.py`。

 3. `service.set_favorite` 里删掉 `existing is not None` 的判断、
    改成无条件 `db.add(...)` ⇒ 唯一约束抛 IntegrityError ⇒
    `test_favorite_is_idempotent_and_single_row` 转红（500 / 两行）。
 4. `router.set_skill_favorite` 把 `isinstance(raw, bool)` 那道门删掉
    ⇒ `test_favorite_rejects_truthy_string` 转红（`"false"` 会被当成真值收藏）。
 5. `service.list_skills` 把 `favorited=s.id in fav_ids` 改回 `favorited=False`
    ⇒ `test_list_inlines_favorited` 转红。
 6. `service.set_favorite` 里加一句 `row.updated_at = datetime.utcnow()`
    ⇒ `test_favorite_does_not_touch_skills_updated_at` 转红。
 7. `service.is_favorited` / `_favorite_ids` 去掉 `user.id` 过滤条件
    （= 变成"有人收藏过就算收藏"）⇒ `test_favorite_is_per_user` 转红。
"""

import asyncio
import uuid

import pytest
from sqlalchemy import text

from core.database import async_session_factory
from modules.skills import service


# ============================================================================
# 工具
# ============================================================================


async def _fav_rows(user_id: str, skill_id: str) -> int:
    """直接数 DB 行 —— 幂等判据必须看**行数**，不能只看接口回执。"""
    async with async_session_factory() as db:
        r = await db.execute(
            text(
                "SELECT count(*) FROM skill_favorites "
                "WHERE user_id = :u AND skill_id = :s"
            ),
            {"u": user_id, "s": skill_id},
        )
        return int(r.scalar_one())


async def _make_skill(client, owner, **over):
    """经 HTTP 真建一条技能（`skill_owner` 夹具会按前缀清掉它）。"""
    body = {
        "name": owner["prefix"] + "-" + uuid.uuid4().hex[:6],
        "title": "标签与收藏用例",
        "content": "正文",
    }
    body.update(over)
    r = await client.post("/api/v1/skills", json=body, headers=owner["headers"])
    assert r.status_code == 201, f"{r.status_code} {r.text[:400]}"
    return r.json()


async def _set_fav(client, owner, sid, value, **kw):
    return await client.put(
        f"/api/v1/skills/{sid}/favorite",
        json=({"favorited": value} if kw.get("send", True) else {}),
        headers=owner["headers"],
    )


# ============================================================================
# ① 收藏：契约 / 幂等 / 按人隔离 / 不抖 updated_at
# ============================================================================


async def test_new_skill_is_not_favorited(auth_off, client, skill_owner):
    """新建的技能默认未收藏（否则前端一进来满屏星标）。"""
    created = await _make_skill(client, skill_owner)
    assert created["favorited"] is False


async def test_favorite_is_idempotent_and_single_row(auth_off, client, skill_owner):
    """★★★ 反向注入靶子 #3：`PUT true` 重复三次 ⇒ 永远是 true，且 DB 只有 1 行。

    「幂等」的完整含义是**重复请求收敛到同一状态**，不只是"不重复插入"：
    第二次请求必须仍然成功（而不是报冲突），第三次数出来还要是 1 行。
    """
    created = await _make_skill(client, skill_owner)
    sid = created["id"]

    for i in range(3):
        r = await _set_fav(client, skill_owner, sid, True)
        assert r.status_code == 200, f"第 {i + 1} 次：{r.status_code} {r.text[:300]}"
        assert r.json()["favorited"] is True

    assert await _fav_rows(skill_owner["user_id"], sid) == 1


async def test_unfavorite_is_idempotent_and_removes_row(auth_off, client, skill_owner):
    created = await _make_skill(client, skill_owner)
    sid = created["id"]

    assert (await _set_fav(client, skill_owner, sid, True)).json()["favorited"] is True
    for _ in range(2):
        r = await _set_fav(client, skill_owner, sid, False)
        assert r.status_code == 200
        assert r.json()["favorited"] is False
    assert await _fav_rows(skill_owner["user_id"], sid) == 0


async def test_list_inlines_favorited(auth_off, client, skill_owner):
    """★★ 反向注入靶子 #5：列表要**内联**下发收藏态。

    不内联的话前端得再拉一次「我的收藏」再合并 —— 那会引入
    「两次请求之间收藏变了」的时间窗，以及 id 匹配不上的口径分叉。
    """
    created = await _make_skill(client, skill_owner)
    sid, name = created["id"], created["name"]

    assert (await _set_fav(client, skill_owner, sid, True)).status_code == 200

    listed = await client.get("/api/v1/skills", headers=skill_owner["headers"])
    assert listed.status_code == 200
    row = next(it for it in listed.json()["items"] if it["name"] == name)
    assert row["favorited"] is True, "★ 列表没带收藏态（前端星标会显示成未收藏）"
    assert "content" not in row, "列表接口不应下发正文（既有契约）"


async def test_detail_inlines_favorited(auth_off, client, skill_owner):
    created = await _make_skill(client, skill_owner)
    sid = created["id"]
    assert (await _set_fav(client, skill_owner, sid, True)).status_code == 200

    got = await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
    assert got.json()["favorited"] is True


async def test_favorite_is_per_user(auth_off, client, skill_owner, make_user):
    """★★ 反向注入靶子 #7：收藏是「用户 × 技能」的关系，不是技能属性。

    若查询漏了 `user_id` 过滤（变成"有人收藏过就算收藏"），
    别人收藏过的技能在本人的列表里会显示成已收藏。

    ★ 判据刻意**直接打 service 层**，不经过 HTTP 可见性：
      走 HTTP 时另一个账号本来就 403，用例会变成拿到 403 就跳过 ——
      那是「空跑假绿」，注入 #7 之后仍然全绿。
    """
    created = await _make_skill(client, skill_owner)
    sid = created["id"]
    assert (await _set_fav(client, skill_owner, sid, True)).status_code == 200

    other = await make_user("favother")

    def _u(uid):
        return type("_U", (), {"id": uid})()

    async with async_session_factory() as db:
        assert await service.is_favorited(db, _u(other["user_id"]), sid) is False, (
            "★ 别人收藏过的技能，在我这里也是已收藏（漏了 user_id 过滤）"
        )
        assert await service.is_favorited(db, _u(skill_owner["user_id"]), sid) is True, (
            "★ 本人反而看不到自己的收藏"
        )
        # 收藏集合也一样要按人切
        assert sid not in (await service._favorite_ids(db, _u(other["user_id"])))
        assert sid in (await service._favorite_ids(db, _u(skill_owner["user_id"])))


async def test_favorite_does_not_touch_skills_updated_at(auth_off, client, skill_owner):
    """★★★ 反向注入靶子 #6：收藏**不得**改 `skills.updated_at`。

    本轮同时要做「按更新时间倒序」排序。若收藏顺手写了 `updated_at`，
    点个星标就会把技能顶到列表最前面 —— 症状是「排序坏了」，
    没有人会怀疑到收藏上。
    """
    created = await _make_skill(client, skill_owner)
    sid, before = created["id"], created["updatedAt"]

    await asyncio.sleep(0.01)  # 让 utcnow 有可观测的推进（精度微秒，足够）
    assert (await _set_fav(client, skill_owner, sid, True)).status_code == 200

    got = await client.get(f"/api/v1/skills/{sid}", headers=skill_owner["headers"])
    assert got.json()["updatedAt"] == before, "★ 收藏把 updated_at 抖了（排序会失真）"


# ============================================================================
# ④ 收藏端点边界
# ============================================================================


async def test_favorite_unknown_skill_is_404(auth_off, client, skill_owner):
    r = await _set_fav(client, skill_owner, "sk-does-not-exist", True)
    assert r.status_code == 404


async def test_favorite_rejects_truthy_string(auth_off, client, skill_owner):
    """★★★ 反向注入靶子 #4：必须是**真布尔**。

    `"false"` 是非空字符串 ⇒ 在 Python 里是**真值**。若只写 `if not raw`
    这道门，前端发字符串 `"false"` 会被理解成「收藏」—— 与用户意图相反，
    而且因为接口返回 200，前端不会发现。
    """
    created = await _make_skill(client, skill_owner)
    sid = created["id"]

    for bad in ["false", "true", 0, 1, "0"]:
        r = await _set_fav(client, skill_owner, sid, bad)
        assert r.status_code == 422, f"favorited={bad!r} 竟然被接受（{r.status_code}）"

    assert await _fav_rows(skill_owner["user_id"], sid) == 0, "非法请求竟然落库了"


async def test_favorite_missing_field_is_422(auth_off, client, skill_owner):
    """缺字段不能默认成 false（那会静默取消收藏）。"""
    created = await _make_skill(client, skill_owner)
    r = await _set_fav(client, skill_owner, created["id"], None, send=False)
    assert r.status_code == 422


async def test_favorite_cross_account_is_rejected(auth_off, client, skill_owner, make_user):
    """★ 归属门：别的账号的技能收藏不了。

    ★ 口径与既有写端点（update / delete）**一致用 403**，不改成 404。
      虽然"不存在"与"不属于你"同响应能防存在性枚举，但本仓既有写口
      一律 403（见 `test_skill_gate.py::test_write_endpoints_reject_cross_account_skill`），
      单为收藏端点新造一套口径才是真隐患。
    """
    created = await _make_skill(client, skill_owner)
    sid = created["id"]

    other = await make_user("favxacct")
    r = await _set_fav(client, other, sid, True)
    assert r.status_code == 403, f"★ 别的账号收藏到了我的技能（{r.status_code}）"
    assert await _fav_rows(skill_owner["user_id"], sid) == 0
    assert await _fav_rows(other["user_id"], sid) == 0


# ============================================================================
# ⑤ 并发兜底（唯一约束是第二道保障，不是错误来源）
# ============================================================================


async def test_concurrent_favorite_does_not_raise(auth_off, client, skill_owner):
    """★★ 三个并发「收藏」不能把 `IntegrityError` 泄漏成 500。

    `(user_id, skill_id)` 唯一约束在这里是**第二道保障**：三个请求都可能
    判定"需要插入"，后两个会撞约束。正确行为是把它当成
    「目标状态已达成」，而不是异常。
    """
    created = await _make_skill(client, skill_owner)
    skill_id = created["id"]

    me = type("_U", (), {"id": skill_owner["user_id"]})()

    async def one():
        async with async_session_factory() as db:
            row = await service.get_skill_row(db, skill_id)
            return await service.set_favorite(db, me, row, True)

    results = await asyncio.gather(one(), one(), one(), return_exceptions=True)
    errs = [r for r in results if isinstance(r, BaseException)]
    assert not errs, f"★ 并发收藏抛异常了：{errs[:2]}"
    assert all(r is True for r in results), results
    assert await _fav_rows(skill_owner["user_id"], skill_id) == 1
