"""
容器「默认落点」的判据（★ 第 110 轮重写，前身是 `test_account_kind.py`）

==============================================================================
★ 这个文件为什么被重写
==============================================================================
第 106 轮我在这里钉了「`accounts.kind` = personal / team」这套语义，核心用例是
`test_team_account_created_first_does_not_become_personal`。

第 110 轮老板把它**证伪**了：

    「没有拉团队成员就是私有店铺 —— 私有不是一种容器类型，而是**成员数的一个
      取值**（成员数 = 1 时观感私有，> 1 就是共享）。一个人也可以是一人团。」

实测证据就在他自己的账号里：容器「跨境1」被回填成 `personal`，而里面
**坐着另一名成员李航** —— 标签与数据互相矛盾。

⇒ 容器只有**一种**。`AccountKind` 枚举、`accounts.kind` 列（迁移 `b7e3f1a9c2d4`）
  以及前端所有「个人 / 团队」标签全部删除。

==============================================================================
★ 那么本文件现在钉什么
==============================================================================
只剩**一个**仍然真实的问题：**不指定归属时，新店铺落到哪个容器？**

答案必须**确定性**（同一用户反复调用拿到同一个容器），这就是
`ensure_default_account()` 的全部职责。判据：**该用户名下最早创建的容器**。

★ 与旧用例的关系（这不是"删掉一条碍事的测试"）
  旧用例要求「先建的团队容器**不得**成为默认落点」；
  新语义下这个要求**不成立**了（先建的那个就是最早的 ⇒ 它就是默认落点）。
  这是**概念变更**，不是回归 —— 所以旧断言必须换掉，而不是放宽它。
  换成了什么：从"落点 ≠ 先建的容器"改成"落点 == **最早**的容器"，
  同时保留旧用例真正的价值内核：**落点唯一且稳定**。

==============================================================================
★ 反向注入验证（本文件的门禁不是空跑）
==============================================================================
  1. 把 `ensure_default_account()` 的 `select(...).where(owner_user_id == user.id)`
     改成 `where(Account.id == user.id)`（无关条件）⇒ 查不到 ⇒ 每次**新建**一个
     容器 ⇒ `test_default_landing_is_idempotent` / `..._reuses_existing_container` 转红。
  2. 去掉 `.order_by(Account.created_at, Account.id)` ⇒ 顺序不定
     ⇒ `test_default_landing_is_the_earliest_container` 有概率转红（顺序敏感）。
  3. 把接口出参里的 `"kind"` 加回来 ⇒ `test_account_contract_has_no_kind_field` 转红。
  4. 在 `Account` 上把 `kind` 列加回来 ⇒ `test_account_model_has_no_kind_column` 转红。

==============================================================================
★ 两条形态门禁为什么必须走 AST
==============================================================================
`AccountKind` 与 `kind` 这两个词**逐字写在**本文件的 docstring、
`core/auth/accounts.py` 的历史注释、以及两份迁移的说明里（记录"这里曾经有过"）。
用字符串扫描会被自己的注释绊倒（"代码改对了、测试反而红"），
所以只数**代码级引用**（`ast.Name` / `ast.Attribute` / 类级赋值）。
"""

import ast
import asyncio
import pathlib


BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]


# ====== helpers ======

async def _mk_account(client, user, name):
    r = await client.post(
        "/api/v1/accounts", headers=user["headers"], json={"name": name}
    )
    assert r.status_code == 201, f"建容器失败: {r.status_code} {r.text[:300]}"
    return r.json()["account"]["id"]


async def _accounts(client, user):
    r = await client.get("/api/v1/accounts", headers=user["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    return {a["id"]: a for a in r.json()["accounts"]}


async def _create_store(client, user, name, account_id=None):
    body = {"name": name, "platform": "amazon"}
    if account_id:
        body["account_id"] = account_id
    r = await client.post("/api/v1/stores", headers=user["headers"], json=body)
    assert r.status_code in (200, 201), f"建店失败: {r.status_code} {r.text[:300]}"
    return r.json()


async def _store_account_id(client, user, store_id):
    r = await client.get(f"/api/v1/stores/{store_id}", headers=user["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    return r.json().get("account_id")


# ====== ① 契约：账户对象里不得再有 kind ======


async def test_account_contract_has_no_kind_field(auth_off, client, make_user):
    """`GET /accounts/me` 与 `POST /accounts` 的响应体里都不得有 `kind`。

    ★ 为什么单独钉契约：前端的「个人 / 团队」标签是**照着这个字段长出来的**。
      字段只要还在，标签就会被重新加上去（哪怕后端已经不再读它）。
    """
    a = await make_user("dac-contract")

    r = await client.get("/api/v1/accounts/me", headers=a["headers"])
    assert r.status_code == 200, r.text[:300]
    me = r.json()["account"]
    assert "kind" not in me, (
        f"`/accounts/me` 仍返回 kind 字段：{me} —— 该概念已被证伪"
        f"（容器只有一种，「私有」是成员数的取值），残留会让前端重新长出标签"
    )

    r2 = await client.post(
        "/api/v1/accounts", headers=a["headers"], json={"name": "契约容器"}
    )
    assert r2.status_code == 201, r2.text[:300]
    created = r2.json()["account"]
    assert "kind" not in created, f"`POST /accounts` 仍返回 kind 字段：{created}"


# ====== ② 默认落点：最早创建的容器 ======


async def test_default_landing_is_the_earliest_container(auth_off, client, make_user):
    """
    ★★★ 本文件最重要的一条。

    用户先建容器 A、再建容器 B，随后**不带** `account_id` 建店：
    店铺必须落进 **A（最早创建的）**。

    ★ 为什么要有 `asyncio.sleep(0.01)`：判据是**基于创建时间**的，
      夹具必须真的提供一个可分辨的时间顺序。两个 POST 挨着发时
      `created_at` 可能落在同一微秒，此时 tie-breaker 退化成随机 uuid
      （`id`），测试会变成偶发假红 —— 与其在边界上赌，不如让顺序确定。
    """
    a = await make_user("dac-earliest")
    first = await _mk_account(client, a, "先建的容器")
    await asyncio.sleep(0.01)
    second = await _mk_account(client, a, "后建的容器")
    assert first != second

    store = await _create_store(client, a, "默认落点店")
    landed = await _store_account_id(client, a, store["id"])

    assert landed == first, (
        f"默认落点不是最早创建的容器：落到了 {landed}，应为 {first}"
        f"（{first=} {second=}）—— 判据是「该用户名下最早创建的容器」"
    )


async def test_default_landing_is_stable(auth_off, client, make_user):
    """「默认落点」必须**确定**：两次默认建店落进同一个容器。"""
    a = await make_user("dac-stable")

    s1 = await _create_store(client, a, "店一")
    s2 = await _create_store(client, a, "店二")

    assert await _store_account_id(client, a, s1["id"]) == await _store_account_id(
        client, a, s2["id"]
    ), "两次默认建店落到了不同容器 —— 默认落点有歧义"


# ====== ③ 自动创建：一个容器都没有时才新建 ======


async def test_default_landing_reuses_existing_container(auth_off, client, make_user):
    """已有容器 ⇒ **复用**它，不得新建第二个（重复容器不报错，只会静默堆积）。"""
    a = await make_user("dac-reuse")
    existing = await _mk_account(client, a, "唯一容器")

    store = await _create_store(client, a, "落点店")
    assert await _store_account_id(client, a, store["id"]) == existing

    accounts = await _accounts(client, a)
    assert len(accounts) == 1, (
        f"已有容器的情况下又建了一个：{[x['name'] for x in accounts.values()]}"
    )


async def test_default_landing_creates_container_when_none_exists(
    auth_off, client, make_user
):
    """一个容器都没有 ⇒ 自动新建，名字是「{用户名} 的团队」。"""
    a = await make_user("dac-autocreate")

    store = await _create_store(client, a, "首店")
    landed = await _store_account_id(client, a, store["id"])
    assert landed, "默认建店没有落进任何容器（account_id 为空）"

    accounts = await _accounts(client, a)
    assert landed in accounts, f"落点 {landed} 不在可见容器列表里"
    name = accounts[landed]["name"]
    assert name.endswith("的团队"), (
        f"自动创建的容器名是 {name!r}，应以「的团队」结尾"
        f"（★ 第 110 轮把「{'{名}'} 的账户」改成了「{'{名}'} 的团队」）"
    )


async def test_default_container_is_idempotent(auth_off, client, make_user):
    """
    反复调用（`/accounts/me` × 3 + 两次默认建店）只会有**一个**自动容器。

    ★ 非幂等会造出第二个容器，而重复容器**不会报错** ——
      用户会看到两个一模一样的团队、店铺散落其中，日志里毫无提示。
    """
    a = await make_user("dac-idempotent")

    for _ in range(3):
        r = await client.get("/api/v1/accounts/me", headers=a["headers"])
        assert r.status_code == 200, r.text[:300]

    await _create_store(client, a, "落点一")
    await _create_store(client, a, "落点二")

    accounts = await _accounts(client, a)
    assert len(accounts) == 1, (
        f"自动创建了 {len(accounts)} 个容器，应恰好 1 个："
        f"{[(x['name'], x['created_at']) for x in accounts.values()]}"
    )


async def test_created_container_coexists_with_default(auth_off, client, make_user):
    """`POST /accounts` 建的容器与自动创建的那个**并存**，互不顶替、互不改写。"""
    a = await make_user("dac-coexist")
    await client.get("/api/v1/accounts/me", headers=a["headers"])  # 先有自动容器

    extra = await _mk_account(client, a, "并存的容器")

    accounts = await _accounts(client, a)
    assert extra in accounts, accounts
    assert len(accounts) == 2, (
        f"应恰好 2 个容器（自动创建的 + 手动创建的），实际："
        f"{[(x['id'], x['name']) for x in accounts.values()]}"
    )


# ====== ④ 形态门禁（AST，不是 grep）======


def _backend_py_files():
    """backend 下所有 .py，排除迁移目录（迁移是历史记录，允许逐字保留旧概念）。"""
    for p in sorted(BACKEND_ROOT.rglob("*.py")):
        parts = p.relative_to(BACKEND_ROOT).parts
        if parts and parts[0] in {"alembic", "__pycache__", ".venv"}:
            continue
        if "__pycache__" in parts:
            continue
        yield p


def test_no_account_kind_symbol_anywhere_in_backend():
    """
    ★ 形态门禁：`AccountKind` 不得再被**代码**引用。

    ★ 为什么走 AST：这个词逐字写在多份 docstring / 注释里（记录"这里曾经有过"）。
      字符串扫描会被自己的注释骗到 —— 只数 `ast.Name` / `ast.Attribute`。
    """
    offenders = []
    for p in _backend_py_files():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "AccountKind":
                offenders.append(f"{p.relative_to(BACKEND_ROOT)}:{node.lineno}")
            elif isinstance(node, ast.Attribute) and node.attr == "AccountKind":
                offenders.append(f"{p.relative_to(BACKEND_ROOT)}:{node.lineno}")

    assert not offenders, (
        f"`AccountKind` 又被引用了：{offenders} —— "
        f"「个人账户 / 团队账户」这个二分已被实测证伪（容器只有一种），"
        f"见迁移 b7e3f1a9c2d4"
    )


def test_account_model_has_no_kind_column():
    """
    ★ 形态门禁：`Account` 模型不得再有 `kind` 列。

    ★ 为什么要钉这个：本项目已把「字段只写不读」记为缺陷 ——
      一个不再被任何代码读的列，偏差可以无限期躺着而无人发现。
      要么它有真实用途，要么它不存在。删列不能只靠"这次删了"。
    """
    path = BACKEND_ROOT / "core/identity/account_models.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    cls = next(
        (n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "Account"),
        None,
    )
    assert cls is not None, "未能定位 account_models.py 里的 Account 类"

    declared = set()
    for stmt in cls.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            declared.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    declared.add(t.id)

    assert "kind" not in declared, (
        "`Account` 模型又有了 `kind` 列 —— 「个人 / 团队」容器类型的概念已被证伪"
        "（容器只有一种，「私有」是成员数的取值），见迁移 b7e3f1a9c2d4"
    )
