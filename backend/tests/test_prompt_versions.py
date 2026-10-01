"""提示词覆写层（第 351 轮 · P0-7 B 档）门禁。

================================ 这道门禁守什么 ================================
B 档把「当前生效的提示词正文」从 `.py` 常量搬进 `prompt_versions` 表，于是
多出三类**静默失效** —— 它们都不会让任何一处报错：

  S1 **虚假陈述**：库里有一行 `enabled=True`、基线也对得上，却装不上
     （正文变量集不符）⇒ `service._status_of()` 判 `active`，
     界面显示「覆写生效中」，线上跑的却是源码版。
     ▶ 判据：写口**在落库之前**过闸门 —— `test_upsert_with_bad_body_writes_nothing`

  S2 **幽灵覆写**：库里那一行删了，内存里那份还在生效。
     ▶ 判据：`apply_all_overrides()` 是「先撤回、再按库应用」的**可重放等式**
       —— `test_apply_all_is_replayable_not_incremental`

  S3 **静默回滚**：源码改过之后，一条旧覆写盖掉了别人新改的正文
     （改动确实在 git 里，翻代码看不出问题）。
     ▶ 判据：`base_fingerprint` 对不上 ⇒ 拒绝 ——
       `test_stale_is_rejected_by_both_entry_points`

★ 另有一条与「同一判定两份实现」直接相关的判据：
  `test_gates_are_one_implementation` —— 两道闸门（stale / vars-mismatch）
  必须在 `validate_override()` 与 `apply_override()` 上给出**同一个 reason**。
  两份实现的下场是「写的时候拦住了、应用的时候没拦」（或反过来）。

★ 为什么本文件**刻意不加** `pytestmark = pytest.mark.tenant_identity`：
  那个 marker 会让 `client` 夹具默认带上 `tenant_headers`（见 conftest 的
  `client`）⇒ 下面「匿名 ⇒ 401」的用例实际会带身份，期望 401 却拿到 403
  （第 351 轮在 SP-API 那批用例上**实测踩过**这一次）。
  本模块要测的恰恰是「匿名 / 非超管 / 超管」三档，必须真匿名。
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select, text

from ai_infra.llm import (
    PROMPT_TEMPLATES,
    PromptOverrideRejected,
    applied_overrides,
    apply_override,
    registered_names,
    reset_override,
    source_fingerprint,
    validate_override,
)
from core.database import get_async_session
from core.identity.models import UserRole
from modules.prompt_versions.db_model import PromptVersion

BASE = "/api/v1/prompt-versions"


# ============================================================ 夹具 / 工具


@pytest.fixture(scope="module", autouse=True)
def _ensure_prompt_registry() -> None:
    """★ 注册表是 **import 副作用** 填的 —— 不 import 业务 `prompts.py` 它就是空的。

    实测：裸 `import ai_infra.llm` 后 `registered_names() == []`；
    `import main`（它经各 router 拉进 5 个 `prompts.py`）之后才是那 10 个。

    ★ 为什么必须**显式**做这一步，而不是「反正别的用例会先 import main」：
      那会让本文件单独跑时全绿、进全量时才红（或反过来），
      而且症状是「注册表为空 ⇒ 靶子不存在 ⇒ 用例 skip」—— **一条静默的假绿**。
      「注册＝import 副作用」这条判据在本仓记忆里已登记，这里按它写。

    ★ 必须是 **module 作用域**：`target` 也是 module 作用域，而 pytest 按作用域
      从大到小建夹具 ⇒ 若这里写成 function 作用域，`target` 会在它**之前**建好
      （那时注册表还是空的）⇒ 直接 skip。`target` 显式声明依赖它就是为这个。
    """
    import main  # noqa: F401  —— 只为触发各 prompts 模块的注册副作用


@pytest.fixture(scope="module")
def target(_ensure_prompt_registry) -> str:
    """挑一个**零变量**的已注册模板当靶子。

    ★ 为什么按变量集挑、不写死名字：写死会在某次提示词加变量后，
      让「vars-mismatch 前置拒绝」那条用例变成**假红**，而报错方向完全错位
      —— 看起来像覆写层坏了，其实是用例选错了靶子。
    """
    for n in registered_names():
        if not PROMPT_TEMPLATES[n].required_vars:
            return n
    pytest.skip("注册表里没有零变量模板，本文件需要它做靶子")


def _src_body(name: str) -> str:
    return PROMPT_TEMPLATES[name].content


def _src_version(name: str) -> str:
    return PROMPT_TEMPLATES[name].version


def _body_with_marker(name: str, marker: str) -> str:
    """造一份**能过规格校验**的覆写正文（追加一行，不改变量集）。

    ★ 不能只写 `"..."` 这种占位串：`PromptSpec` 会拒绝空正文，
      而一份连规格都不合法的正文让用例红在 `invalid` 上 ——
      看起来像在测 vars-mismatch，其实根本没走到那一步。
    """
    return _src_body(name) + f"\n\n[{marker}]\n"


async def _promote_to_admin(user_id: str) -> None:
    """把用户提成平台超管。

    ★ 原生 SQL 里的 enum 字面量是 **name**（`ADMIN`）而不是 `.value`（`admin`）：
      SQLAlchemy 的 `Enum(UserRole)` 按 name 落库。写小写会直接
      `InvalidTextRepresentationError`。这里从枚举取名字，不手抄字面量。
    """
    async with get_async_session() as db:
        await db.execute(
            text("UPDATE users SET role = :r WHERE id = :u"),
            {"r": UserRole.ADMIN.name, "u": user_id},
        )
        await db.commit()


async def _row(name: str) -> PromptVersion | None:
    async with get_async_session() as db:
        return (
            await db.execute(select(PromptVersion).where(PromptVersion.name == name))
        ).scalar_one_or_none()


async def _seed_override(
    name: str, *, content: str, version: str = "9", enabled: bool = True,
    base_fingerprint: str | None = None,
) -> None:
    """直接往表里插一行（模拟「不走写端点的改库」——迁移脚本 / 手工 SQL）。"""
    from ai_infra.llm import PromptSpec

    async with get_async_session() as db:
        db.add(
            PromptVersion(
                name=name,
                content=content,
                version=version,
                fingerprint=PromptSpec(name="__fp__", content=content).fingerprint,
                base_fingerprint=base_fingerprint or source_fingerprint(name) or "",
                enabled=enabled,
                note="pytest",
                created_by=None,
            )
        )
        await db.commit()


@pytest_asyncio.fixture(autouse=True)
async def _isolate_prompt_overrides():
    """用例前后把内存注册表与表都还原 —— 本文件**故意**要改全局单例。

    ★ 只删「本用例新增的行」（先取差集再删）：这张表是平台级配置，
      手上有数据时不能一把清空（`delete` 全表会把真实配置一起带走，
      而测试跑在**共享库**上 —— 见本仓「tests/ 直连共享生产库」那条登记）。
    """
    async with get_async_session() as db:
        before = set((await db.execute(select(PromptVersion.name))).scalars().all())
    yield
    for n in list(applied_overrides()):
        reset_override(n)
    async with get_async_session() as db:
        now = set((await db.execute(select(PromptVersion.name))).scalars().all())
        for n in sorted(now - before):
            await db.execute(delete(PromptVersion).where(PromptVersion.name == n))
        await db.commit()


# ============================================================ A 组 · 纯逻辑


def test_registry_is_not_empty() -> None:
    """防「靶子为空 ⇒ 下面全在空跑」：注册表必须有可覆写的模板。"""
    assert len(registered_names()) >= 5, f"注册表只有 {registered_names()}"


def test_stale_is_rejected_by_both_entry_points(target: str) -> None:
    """S3：基线对不上 ⇒ 两道入口都拒，且 reason 一致、**绝不落写**。"""
    bogus = "0" * 12
    assert bogus != source_fingerprint(target), "用例前提：bogus 必须不是真指纹"

    with pytest.raises(PromptOverrideRejected) as via_validate:
        validate_override(
            target, content=_src_body(target), version="2", base_fingerprint=bogus
        )
    with pytest.raises(PromptOverrideRejected) as via_apply:
        apply_override(
            target, content=_src_body(target), version="2", base_fingerprint=bogus
        )

    assert via_validate.value.reason == "stale"
    assert via_apply.value.reason == "stale"
    assert target not in applied_overrides(), "被拒的覆写竟然生效了"


def test_vars_mismatch_is_rejected_by_both_entry_points(target: str) -> None:
    """第二道闸门：变量集是**调用点契约** ⇒ 两道入口都拒，reason 一致。"""
    fp = source_fingerprint(target)
    # ★ 必须写**单个**花括号：`{{...}}` 是转义 —— `extract_required_vars()`
    #   只收标识符形态的真占位符，双括号渲染出来是字面量 `{...}`，不是变量。
    #   实测踩过：用双括号写这条用例 ⇒ 变量集没变 ⇒ 根本没走到 vars-mismatch，
    #   而用例报的是「DID NOT RAISE」（看着像闸门失效）。
    bad = _src_body(target) + "\n{pytest_new_var}\n"

    with pytest.raises(PromptOverrideRejected) as via_validate:
        validate_override(target, content=bad, version="2", base_fingerprint=fp)
    with pytest.raises(PromptOverrideRejected) as via_apply:
        apply_override(target, content=bad, version="2", base_fingerprint=fp)

    assert via_validate.value.reason == "vars-mismatch"
    assert via_apply.value.reason == "vars-mismatch"
    assert target not in applied_overrides()


def test_gates_are_one_implementation(target: str) -> None:
    """★ 闸门必须只有一份实现：三种非法输入在两道入口上给出**逐字相同**的 reason。

    ★ 反向注入（本用例的牙齿）：把 `_prepare()` 里的任一判定复制一份到
      `apply_override()` 并改掉其中一处，本用例立刻红。
    """
    fp = source_fingerprint(target)
    cases = [
        (_src_body(target), "0" * 12, "stale"),
        (_src_body(target) + "\n{pytest_new_var}\n", fp, "vars-mismatch"),
    ]
    for content, base, expect in cases:
        got = []
        for fn in (validate_override, apply_override):
            with pytest.raises(PromptOverrideRejected) as exc:
                fn(target, content=content, version="2", base_fingerprint=base)
            got.append(exc.value.reason)
        assert got == [expect, expect], f"两道入口的 reason 不一致：{got}"

    # 未注册的名字也要两处一致
    ghost = "not-a-registered-prompt-" + uuid.uuid4().hex[:6]
    got = []
    for fn in (validate_override, apply_override):
        with pytest.raises(PromptOverrideRejected) as exc:
            fn(ghost, content="hello", version="1", base_fingerprint="x")
        got.append(exc.value.reason)
    assert got == ["unknown-name", "unknown-name"]


def test_validate_override_has_no_side_effect(target: str) -> None:
    """`validate_override()` 只校验、**不应用** —— 写口要在落库之前用它。"""
    before_fp = PROMPT_TEMPLATES[target].fingerprint
    validate_override(
        target,
        content=_body_with_marker(target, "pytest-validate"),
        version="2",
        base_fingerprint=source_fingerprint(target),
    )
    assert target not in applied_overrides(), "只校验却改了内存注册表"
    assert PROMPT_TEMPLATES[target].fingerprint == before_fp, "注册表原文被改动"


# ============================================================ B 组 · 表 ↔ 内存


@pytest.mark.asyncio
async def test_apply_all_is_replayable_not_incremental(target: str) -> None:
    """S2：库删了行 ⇒ 内存里那份必须跟着撤掉（禁幽灵覆写）。

    ★ 「先撤回、再按库应用」是一个**可重放的等式**；增量维护会在
      「删了一行」「改了名字」时把库里已经没有的覆写继续留在线上。
    """
    from modules.prompt_versions import apply_all_overrides

    src_fp = source_fingerprint(target)
    await _seed_override(target, content=_body_with_marker(target, "pytest-replay"))

    r1 = await apply_all_overrides()
    assert target in r1["applied"], r1
    assert target in applied_overrides()
    assert PROMPT_TEMPLATES[target].version == "9", "覆写版本没盖上"

    # 库里删掉 ⇒ 再同步一次，内存必须回到源码版
    await _purge(target)
    r2 = await apply_all_overrides()
    assert target in r2["reset"], r2
    assert target not in applied_overrides(), "★ 幽灵覆写：库已删、内存还在用"
    assert PROMPT_TEMPLATES[target].fingerprint == src_fp, "源码版没恢复"
    assert PROMPT_TEMPLATES[target].version == _src_version(target)


@pytest.mark.asyncio
async def test_apply_all_reports_skipped_without_blocking_others(target: str) -> None:
    """单条 stale **不**该让其它条装不上；失败必须逐条报出来（禁静默）。"""
    from modules.prompt_versions import apply_all_overrides

    good = target
    await _seed_override(good, content=_body_with_marker(good, "pytest-good"))
    # 同一个名字只能有一行（unique）⇒ 换一个模板做「坏」的那条
    bad = [n for n in registered_names() if n != target][0]
    await _seed_override(
        bad,
        content=_body_with_marker(bad, "pytest-bad"),
        base_fingerprint="0" * 12,  # ⇒ stale
    )

    r = await apply_all_overrides()
    assert good in r["applied"], r
    assert bad not in r["applied"]
    assert [s["name"] for s in r["skipped"]] == [bad], r
    assert r["skipped"][0]["reason"] == "stale"
    assert bad not in applied_overrides(), "stale 的覆写竟然装上了"
    assert PROMPT_TEMPLATES[bad].fingerprint == source_fingerprint(bad)


async def _purge(name: str) -> None:
    async with get_async_session() as db:
        await db.execute(delete(PromptVersion).where(PromptVersion.name == name))
        await db.commit()


# ============================================================ C 组 · HTTP


@pytest.mark.asyncio
async def test_endpoints_reject_anonymous_and_non_admin(client, make_user) -> None:
    """401（匿名）与 403（登录了但不是超管）必须分得开。"""
    # ① 匿名 ⇒ 401（真匿名：本文件刻意不带 tenant_identity 标记）
    anon = [
        await client.get(BASE),
        await client.put(f"{BASE}/whatever", json={"content": "x"}),
        await client.post(f"{BASE}/apply"),
        await client.delete(f"{BASE}/whatever"),
    ]
    for r in anon:
        assert r.status_code == 401, f"匿名访问应 401，实际 {r.status_code}：{r.text}"

    # ② 登录但不是平台超管 ⇒ 403
    u = await make_user("pv_nonadmin")
    r = await client.get(BASE, headers=u["headers"])
    assert r.status_code == 403, f"非超管读覆写应 403，实际 {r.status_code}：{r.text}"
    r = await client.post(f"{BASE}/apply", headers=u["headers"])
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_upsert_then_list_then_delete(client, make_user, target) -> None:
    """超管全链路：写入 ⇒ 列表显示 active+applied ⇒ 删除 ⇒ 回到源码版。"""
    u = await make_user("pv_admin")
    await _promote_to_admin(u["user_id"])

    r = await client.put(
        f"{BASE}/{target}",
        json={"content": _body_with_marker(target, "pytest-http"), "version": "7",
              "note": "pytest"},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active", body
    assert body["applied"] is True, body
    assert body["version"] == "7", body
    assert body["fingerprint"], body

    # 列表里能查到，且分母/分子对得上
    r = await client.get(BASE, headers=u["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    hit = [i for i in data["items"] if i["name"] == target]
    assert hit and hit[0]["status"] == "active" and hit[0]["applied"] is True
    assert data["applied_total"] >= 1
    assert data["registered_total"] == len(registered_names())

    # 库里确实落了行（不是只改了内存）
    row = await _row(target)
    assert row is not None and row.version == "7" and row.enabled is True

    # 单条读
    r = await client.get(f"{BASE}/{target}", headers=u["headers"])
    assert r.status_code == 200 and r.json()["status"] == "active", r.text

    # 删除 ⇒ 源码版重新生效
    r = await client.delete(f"{BASE}/{target}", headers=u["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert r.json()["status"] == "not-overridden", r.json()
    assert target not in applied_overrides()
    assert PROMPT_TEMPLATES[target].version == _src_version(target)


@pytest.mark.asyncio
async def test_upsert_with_bad_body_writes_nothing(client, make_user, target) -> None:
    """★ S1：变量集不符的正文在**落库之前**被拒 ⇒ 库里不留永远装不上的行。

    ★ 这条是本轮修掉的真缺陷：写口原本先落库、后应用 ⇒ 库里会有一行
      `enabled=True` + 基线对得上，`_status_of()` 判 `active`，
      而应用时被 `vars-mismatch` 拒 —— 界面说「生效中」，线上跑源码版。
    """
    u = await make_user("pv_badbody")
    await _promote_to_admin(u["user_id"])

    r = await client.put(
        f"{BASE}/{target}",
        json={"content": _src_body(target) + "\n{pytest_new_var}\n", "version": "2"},
        headers=u["headers"],
    )
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert detail["reason"] == "vars-mismatch", detail

    assert await _row(target) is None, "★ 被拒的正文竟然落库了"
    assert target not in applied_overrides()


@pytest.mark.asyncio
async def test_upsert_unknown_name_is_400_and_writes_nothing(
    client, make_user, target
) -> None:
    """未注册的名字 ⇒ 400（去修注册），且不留行。"""
    u = await make_user("pv_unknown")
    await _promote_to_admin(u["user_id"])
    ghost = "not-registered-" + uuid.uuid4().hex[:8]

    r = await client.put(
        f"{BASE}/{ghost}", json={"content": "hello", "version": "1"},
        headers=u["headers"],
    )
    assert r.status_code == 400, r.text
    assert await _row(ghost) is None


@pytest.mark.asyncio
async def test_toggle_without_row_is_404(client, make_user, target) -> None:
    """注册了但没有覆写行 ⇒ 404（不是静默 no-op 的 200）。"""
    u = await make_user("pv_toggle")
    await _promote_to_admin(u["user_id"])

    r = await client.post(
        f"{BASE}/{target}/enabled", json={"enabled": False}, headers=u["headers"]
    )
    assert r.status_code == 404, r.text

    # 有行之后能开关
    r = await client.put(
        f"{BASE}/{target}",
        json={"content": _body_with_marker(target, "pytest-toggle"), "version": "2"},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text
    r = await client.post(
        f"{BASE}/{target}/enabled", json={"enabled": False}, headers=u["headers"]
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disabled", r.json()
    assert r.json()["applied"] is False, r.json()
    assert target not in applied_overrides(), "停用后覆写仍在生效"


@pytest.mark.asyncio
async def test_delete_is_idempotent(client, make_user, target) -> None:
    """删除幂等：第二次 `deleted=False`（200，不是 404）。"""
    u = await make_user("pv_del")
    await _promote_to_admin(u["user_id"])

    r = await client.delete(f"{BASE}/{target}", headers=u["headers"])
    assert r.status_code == 200 and r.json()["deleted"] is False, r.text
    r = await client.delete(f"{BASE}/{target}", headers=u["headers"])
    assert r.status_code == 200 and r.json()["deleted"] is False, r.text


@pytest.mark.asyncio
async def test_apply_endpoint_reports_skipped(client, make_user, target) -> None:
    """`POST /apply` 给出显式收敛点，并把逐条失败原因报出来。"""
    u = await make_user("pv_apply")
    await _promote_to_admin(u["user_id"])

    await _seed_override(target, content=_body_with_marker(target, "pytest-apply"))
    r = await client.post(f"{BASE}/apply", headers=u["headers"])
    assert r.status_code == 200, r.text
    assert target in r.json()["applied"], r.json()

    # 直接把基线改坏（模拟「源码改过、覆写没跟上」）⇒ 必须报 skipped 且不生效
    async with get_async_session() as db:
        row = (
            await db.execute(
                select(PromptVersion).where(PromptVersion.name == target)
            )
        ).scalar_one()
        row.base_fingerprint = "0" * 12
        await db.commit()

    r = await client.post(f"{BASE}/apply", headers=u["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert [s["reason"] for s in body["skipped"]] == ["stale"], body
    assert target not in applied_overrides(), "stale 的覆写装上了"


@pytest.mark.asyncio
async def test_read_endpoints_do_not_404_on_unknown_name(client, make_user) -> None:
    """改名后的孤儿行要能被看见（`unknown-name`），而不是被 404 藏掉。"""
    u = await make_user("pv_orphan")
    await _promote_to_admin(u["user_id"])
    ghost = "orphan-" + uuid.uuid4().hex[:8]

    async with get_async_session() as db:
        db.add(
            PromptVersion(
                name=ghost,
                content="legacy body",
                version="1",
                fingerprint="0123456789ab",
                base_fingerprint="0123456789ab",
                enabled=True,
            )
        )
        await db.commit()

    r = await client.get(f"{BASE}/{ghost}", headers=u["headers"])
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "unknown-name", r.json()

    r = await client.get(BASE, headers=u["headers"])
    assert r.status_code == 200, r.text
    names = {i["name"]: i["status"] for i in r.json()["items"]}
    assert names.get(ghost) == "unknown-name", names.get(ghost)


@pytest.mark.asyncio
async def test_apply_never_records_secrets_in_audit(client, make_user, target) -> None:
    """审计写了、且 detail 里**不含覆写正文**（正文可能含内部指令，不该外溢）。"""
    from core.audit.models import AuditLog

    u = await make_user("pv_audit")
    await _promote_to_admin(u["user_id"])
    marker = "pytest-audit-" + uuid.uuid4().hex[:8]

    r = await client.put(
        f"{BASE}/{target}",
        json={"content": _body_with_marker(target, marker), "version": "3"},
        headers=u["headers"],
    )
    assert r.status_code == 200, r.text

    async with get_async_session() as db:
        rows = (
            await db.execute(
                select(AuditLog)
                .where(AuditLog.target_type == "prompt")
                .where(AuditLog.target_id == target)
                .order_by(AuditLog.created_at.desc())
            )
        ).scalars().all()
    assert rows, "写覆写没有留下审计"
    assert rows[0].action == "prompt.override.write"
    assert rows[0].status == "success"
    blob = repr(rows[0].detail)
    assert marker not in blob, f"审计 detail 里出现了覆写正文标记：{blob}"
    assert len(blob) < 2000


# =============================================== D 组 · 配置态 / 运行态 / 启动钩子


@pytest.mark.asyncio
async def test_active_but_not_applied_is_distinguishable(
    client, make_user, target
) -> None:
    """★ 配置态 ≠ 运行态：直接改库（没跑同步）时 `status=active` 但 `applied=False`。

    ★ 反向注入（本用例的牙齿）：把 `_to_item()` 里的 `applied` 从
      `name in applied_overrides()` 改成 `status == STATUS_ACTIVE`
      ⇒ 本用例第 ① 段立刻红。没有这一条，那个字段就是**没有判据的装饰**。
    """
    u = await make_user("pv_nosync")
    await _promote_to_admin(u["user_id"])

    # 直接写库（模拟迁移脚本 / 手工 SQL）—— **不**经过写端点 ⇒ 内存没被同步
    await _seed_override(target, content=_body_with_marker(target, "pytest-nosync"))
    assert target not in applied_overrides(), "用例前提：内存里不该有它"

    r = await client.get(f"{BASE}/{target}", headers=u["headers"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "active", body      # ① 能装上
    assert body["applied"] is False, body        # ① 但还没装上

    # ② 列表的 `applied_total` 必须与**条目自己的 applied** 自洽。
    #    ★ 反向注入（本段的牙齿）：把 `list_status()` 的
    #      `applied = set(applied_overrides()) & {...}` 退回成
    #      `{i["name"] for i in items if i["status"] == STATUS_ACTIVE}`
    #      ⇒ 分母算成 1 而条目 `applied` 全是 False ⇒ 本段立刻红。
    r = await client.get(BASE, headers=u["headers"])
    assert r.status_code == 200, r.text
    data = r.json()
    live = [i for i in data["items"] if i["applied"]]
    assert data["applied_total"] == len(live), (
        f"applied_total({data['applied_total']}) 与条目自洽性破裂（实际生效 {len(live)} 条）"
    )
    assert target not in {i["name"] for i in live}, data

    # 跑一次同步 ⇒ 同一个 status，applied 翻成 True
    r = await client.post(f"{BASE}/apply", headers=u["headers"])
    assert r.status_code == 200, r.text
    r = await client.get(f"{BASE}/{target}", headers=u["headers"])
    assert r.json()["applied"] is True, r.json()
    r = await client.get(BASE, headers=u["headers"])
    data = r.json()
    live = [i for i in data["items"] if i["applied"]]
    assert data["applied_total"] == len(live) >= 1, data["applied_total"]


@pytest.mark.asyncio
async def test_override_version_is_not_reported_when_it_is_not_live(
    client, make_user, target
) -> None:
    """★ 非 active 的行不许把**覆写版本**报成当前版本（虚假陈述）。

    行存在、`enabled=True`、但基线已被改坏（stale）⇒ 线上跑的是**源码版**，
    所以接口必须报 `source_version`，不能报覆写的 `9`。

    ★ 反向注入（本用例的牙齿）：把 `_to_item()` 里那句条件
      `row is not None and status == STATUS_ACTIVE` 改成 `row is not None`
      ⇒ 本用例立刻红（界面会显示「v9 生效中」而实际跑 v{源码}）。
    """
    u = await make_user("pv_version")
    await _promote_to_admin(u["user_id"])
    src_ver = _src_version(target)

    await _seed_override(target, content=_body_with_marker(target, "pytest-ver"))
    async with get_async_session() as db:
        row = (
            await db.execute(select(PromptVersion).where(PromptVersion.name == target))
        ).scalar_one()
        row.base_fingerprint = "0" * 12  # ⇒ stale
        await db.commit()

    r = await client.get(f"{BASE}/{target}", headers=u["headers"])
    body = r.json()
    assert body["status"] == "stale", body
    assert body["version"] == src_ver, f"stale 时仍报覆写版本：{body}"
    assert body["fingerprint"] is None, f"stale 时仍报覆写指纹：{body}"

    # 对照：禁用态同样不许报覆写版本
    async with get_async_session() as db:
        row = (
            await db.execute(select(PromptVersion).where(PromptVersion.name == target))
        ).scalar_one()
        row.base_fingerprint = source_fingerprint(target)
        row.enabled = False
        await db.commit()
    r = await client.get(f"{BASE}/{target}", headers=u["headers"])
    body = r.json()
    assert body["status"] == "disabled", body
    assert body["version"] == src_ver, body


@pytest.mark.asyncio
async def test_startup_hook_is_fail_open(monkeypatch) -> None:
    """启动钩子的两条行为判据 —— 抽成 `main._sync_prompt_overrides()` 才测得到。

    ★ 反向注入（本用例的牙齿）：
      · 去掉 `_sync_prompt_overrides()` 里的 `try/except` ⇒ 第 ② 段红（异常冒出去）；
      · 把 `return report` 改成 `return None` ⇒ 第 ① 段红。
    """
    import main

    ok = {"applied": ["a"], "reset": ["b"], "skipped": [{"name": "c"}]}

    async def _ok():
        return dict(ok)

    monkeypatch.setattr("modules.prompt_versions.apply_all_overrides", _ok)
    got = await main._sync_prompt_overrides()
    assert got == ok, f"① 同步成功时没有把报告交出来：{got}"

    async def _boom():
        raise RuntimeError("表还没建（迁移未跑）")

    monkeypatch.setattr("modules.prompt_versions.apply_all_overrides", _boom)
    assert await main._sync_prompt_overrides() is None, (
        "② 启动钩子把异常抛了出去 —— 配置问题会让整站起不来"
    )
