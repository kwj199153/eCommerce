"""
A 档：建店可指定账户 + 店铺转移归属（2026-09-17）

★ 背景
「新建账户」在改造前是个**没有闭环的空壳**：
  · `StoreCreate` 里没有 `account_id` ⇒ 建出来的店只能落回**个人账户**；
  · 没有任何转移入口 ⇒ 已有的店也搬不进团队账户。
用户建完团队发现用不上，只能看到一堆彼此无关的空账户。

★ 新增的两个入口，以及它们各自要守的门
  · `POST /stores` 带 `account_id`  → 建到指定账户（需目标账户 `store.write`）
  · `POST /stores/{id}/transfer`    → 改挂到指定账户（需**源**侧 + **目标**侧
    各一次 `store.write`）

★★★ 为什么是两道门而不是一道
  源侧保护的是「别把别人的店搬走」；目标侧保护的是「别往别人团队里塞店」。
  这两个越权**方向相反、受害者不同**，用一次判定表达不了。
  只查一道的表现是：测试全绿、代码看不出异常，但某一种越权安静地放行。

★ 反向注入验证
  把 `create_store` 里那个 `if data.account_id:` 分支的能力门去掉，
  `test_cannot_create_store_in_foreign_account` 必须转红；
  把 `transfer_store` 的①去掉，`test_cannot_transfer_foreign_store` 转红；
  把②去掉，`test_cannot_transfer_into_foreign_account` 转红。
"""


async def _mk_account(client, user, name):
    r = await client.post(
        "/api/v1/accounts", headers=user["headers"], json={"name": name}
    )
    assert r.status_code == 201, f"建账户失败: {r.status_code} {r.text[:300]}"
    return r.json()["account"]["id"]


async def _personal_account(client, user):
    r = await client.get("/api/v1/accounts/me", headers=user["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    return r.json()["account"]["id"]


async def _store_account_id(client, user, store_id):
    r = await client.get(f"/api/v1/stores/{store_id}", headers=user["headers"])
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    return r.json().get("account_id")


async def _create_store(client, user, name, account_id=None):
    body = {"name": name, "platform": "amazon"}
    if account_id:
        body["account_id"] = account_id
    r = await client.post("/api/v1/stores", headers=user["headers"], json=body)
    assert r.status_code in (200, 201), f"建店失败: {r.status_code} {r.text[:300]}"
    return r.json()


# ====== 建店：默认 vs 指定 ======


async def test_create_store_defaults_to_personal_account(auth_off, client, make_user):
    """不传 `account_id` ⇒ 落个人账户（改造前的唯一行为，不能变）。"""
    a = await make_user("ct-personal")
    personal = await _personal_account(client, a)

    store = await _create_store(client, a, "默认落点店")

    assert await _store_account_id(client, a, store["id"]) == personal


async def test_create_store_in_specified_team_account(auth_off, client, make_user):
    """传了 `account_id` ⇒ 落到该团队账户（而不是个人账户）。"""
    a = await make_user("ct-team")
    personal = await _personal_account(client, a)
    team = await _mk_account(client, a, "跨境组")
    assert team != personal

    store = await _create_store(client, a, "团队店铺", account_id=team)

    assert await _store_account_id(client, a, store["id"]) == team


async def test_cannot_create_store_in_foreign_account(auth_off, client, make_user):
    """
    ★★ 把自己的店建到**别人**的账户下 ⇒ 403。

    反向注入：去掉 `create_store` 里 `data.account_id` 分支的能力门，
    本条转红（会变成 201 —— 往别人团队里塞了家店，且对方毫无察觉）。
    """
    a = await make_user("ct-fa-a")
    b = await make_user("ct-fa-b")
    b_team = await _mk_account(client, b, "B 的团队")

    r = await client.post(
        "/api/v1/stores",
        headers=a["headers"],
        json={"name": "越权塞店", "platform": "amazon", "account_id": b_team},
    )
    assert r.status_code == 403, (
        f"把自己的店建进了别人的账户（{r.status_code}）—— 写入型越权。"
        f" 响应={r.text[:300]}"
    )


async def test_create_store_in_nonexistent_account_404(auth_off, client, make_user):
    """目标账户不存在 ⇒ 404（不是静默挂到一个不存在的账户上）。"""
    a = await make_user("ct-404")
    r = await client.post(
        "/api/v1/stores",
        headers=a["headers"],
        json={"name": "幽灵账户店", "platform": "amazon", "account_id": "acc_nope"},
    )
    assert r.status_code == 404, f"{r.status_code} {r.text[:300]}"


# ====== 转移 ======


async def test_transfer_own_store_between_own_accounts(auth_off, client, make_user):
    """把自己的店从个人账户转到自己的团队账户 ⇒ 200，归属真的变了。"""
    a = await make_user("tf-ok")
    personal = await _personal_account(client, a)
    team = await _mk_account(client, a, "转出目标组")

    store = await _create_store(client, a, "待转移店")
    assert await _store_account_id(client, a, store["id"]) == personal

    r = await client.post(
        f"/api/v1/stores/{store['id']}/transfer",
        headers=a["headers"],
        json={"account_id": team},
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"
    assert await _store_account_id(client, a, store["id"]) == team


async def test_transfer_is_idempotent(auth_off, client, make_user):
    """目标账户 == 当前账户 ⇒ 200（重复点"转移"不该变成错误）。"""
    a = await make_user("tf-idem")
    personal = await _personal_account(client, a)
    store = await _create_store(client, a, "幂等店")

    r = await client.post(
        f"/api/v1/stores/{store['id']}/transfer",
        headers=a["headers"],
        json={"account_id": personal},
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:300]}"


async def test_cannot_transfer_foreign_store(auth_off, client, make_user):
    """
    ★★ 转移**别人**的店 ⇒ 403（源侧门）。

    反向注入：去掉 `transfer_store` 的 `_ensure_store_access(...)` 调用，
    本条转红（会 200 —— 等于任何人都能把别人的店搬进自己账户）。
    """
    a = await make_user("tf-fa-a")
    b = await make_user("tf-fa-b")
    a_store = await _create_store(client, a, "A 的店")
    b_team = await _mk_account(client, b, "B 的账户")

    r = await client.post(
        f"/api/v1/stores/{a_store['id']}/transfer",
        headers=b["headers"],
        json={"account_id": b_team},
    )
    assert r.status_code == 403, (
        f"别人能转移我的店铺（{r.status_code}）—— 等于店铺被接管。"
        f" 响应={r.text[:300]}"
    )


async def test_cannot_transfer_into_foreign_account(auth_off, client, make_user):
    """
    ★★ 把**自己的**店转进**别人**的账户 ⇒ 403（目标侧门）。

    反向注入：去掉 `transfer_store` 的 `require_account_permission(...)`，
    本条转红（会 200 —— 往别人团队里塞店，污染其数据视图）。

    ★ 这条与上一条保护的是**方向相反**的两个越权，缺任何一道门都不会报错。
    """
    a = await make_user("tf-ta-a")
    b = await make_user("tf-ta-b")
    a_store = await _create_store(client, a, "A 自己的店")
    b_team = await _mk_account(client, b, "B 的团队")

    r = await client.post(
        f"/api/v1/stores/{a_store['id']}/transfer",
        headers=a["headers"],
        json={"account_id": b_team},
    )
    assert r.status_code == 403, (
        f"能把自己的店塞进别人的账户（{r.status_code}）—— 污染他人数据视图。"
        f" 响应={r.text[:300]}"
    )


async def test_transfer_foreign_store_to_own_account_403(auth_off, client, make_user):
    """「把别人的店搬进自己账户」这条最危险的路径，必须 403（两道门都拦）。"""
    a = await make_user("tf-steal-a")
    b = await make_user("tf-steal-b")
    a_store = await _create_store(client, a, "被盗店")
    b_personal = await _personal_account(client, b)

    r = await client.post(
        f"/api/v1/stores/{a_store['id']}/transfer",
        headers=b["headers"],
        json={"account_id": b_personal},
    )
    assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"
    # 归属未变
    assert await _store_account_id(client, a, a_store["id"]) != b_personal
