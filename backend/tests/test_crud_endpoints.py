"""
零覆盖端点的补测：SPU / SKU / 素材 / 三类分组的**写操作**。

为什么是这一批（不是"随手补几个"）
----------------------------------
按「前端在调用（`frontend/src` 里有该路径）× 有副作用（POST/PUT/DELETE/PATCH）
× 测试里零字面量引用」三个条件筛全量 197 个 `/api` 路由，落到同一批端点上：

    POST/PUT/DELETE  /api/v1/spus                 主产品
    POST/PUT/DELETE  /api/v1/skus                 变体
    PATCH            /api/v1/skus/{id}/listing    Listing 写回（版本历史）
    POST/PUT/DELETE  /api/v1/assets               素材
    POST/PUT/DELETE  /api/v1/asset-groups         素材分组
    POST/PUT/DELETE  /api/v1/product-groups       产品分组
    POST/PUT/DELETE  /api/v1/candidate-groups     候选分组
    POST             /api/v1/*-groups/{id}/move

全量结果：89 个路由在测试里零引用（45.2%），其中 21 个是「零覆盖 + 前端在用」。
本文件覆盖这 21 个里风险最高的部分 —— **删除类**（不可逆）与**跨店铺写入**。

为什么选「删除」和「跨租户」优先
--------------------------------
- 删除不可逆：错了就是数据没了（`spus` 删除会级联删掉其下 SKU）
- 跨租户写错：是 BOLA/越权类问题，且**不会报错**（写得进去、没人发现）
其余 CRUD 只做契约级断言（状态码 + 结构），不重复测框架。

不测什么（重要）
----------------
**不测分组的「排序」语义。** 三个 `move` 端点都是「把列表读出来、交换两项、
再写回 `updatedAt`」，而对应的 list 端点（`list_groups`）**没有 order_by**。
排序到底有没有真的持久化，取决于前端读的时候按什么排 —— 这是一个独立的
待查问题，本文件只钉住 `move` 的**边界行为**（不许崩、不许 500），
不假装覆盖排序语义。

夹具
----
统一用 `ensure_shop`（conftest）：它把自造 shop_id 在 stores_store 里建出
真实行并在用例结束后清干净。必须这样做的原因：迁移 d5e6f7a8b9c0 之后
`shop_id` 有指向 `stores_store` 的外键，凭空的 id 会让写入被数据库拒绝。
"""

import uuid

from sqlalchemy import select

from modules.assets.db_model import AssetRecord
from modules.candidates.db_model import CandidateGroupRecord
from modules.products.db_model import ProductGroupRecord, SkuRecord, SpuRecord


# ====== 造数助手 ======

async def _make_spu(client, headers, **overrides) -> dict:
    payload = {"title": f"pytest-spu-{uuid.uuid4().hex[:6]}", **overrides}
    r = await client.post("/api/v1/spus", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _make_sku(client, headers, spu_id: str, **overrides) -> dict:
    payload = {"spu_id": spu_id, "spec_value": "标准", "price": 19.99, **overrides}
    r = await client.post("/api/v1/skus", json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


async def _make_group(client, headers, path: str, **overrides) -> dict:
    payload = {"name": f"pytest-grp-{uuid.uuid4().hex[:6]}", **overrides}
    r = await client.post(path, json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


# ====== 一、SPU：删除必须级联（不可逆操作，风险最高） ======

async def test_spu_delete_cascades_to_its_skus(client, auth_off, ensure_shop):
    """
    删 SPU 后不能留下孤儿 SKU。

    ★ 实测（反向注入发现的，值得记下来）
    把 `delete_spu` 里那段显式的「级联删除其下 SKU」循环**整段删掉**，
    本用例依然通过。原因：`skus_spu_id_fkey` 是 **ON DELETE CASCADE**
    （实测 `pg_constraint.confdeltype = 'c'`），数据库自己就把子行删了。

    所以本条断言的是**结果**（不留孤儿），而不是某段应用代码在起作用。
    两层都在是对的（显式循环 + 外键 CASCADE = 双保险），但测试必须说清
    自己覆盖的是哪一层 —— 否则就会出现
    「测试绿 ⇒ 我以为的那段代码是对的」这种**假信心**。

    这正是反向注入的价值：它把「我以为生效的机制」和「实际生效的机制」
    分开了。注入 A 的结论 = 本用例不覆盖应用层循环，覆盖的是最终数据状态。
    """
    from core.database import async_session_factory

    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    spu = await _make_spu(client, headers)
    sku_a = await _make_sku(client, headers, spu["id"], spec_value="红")
    sku_b = await _make_sku(client, headers, spu["id"], spec_value="蓝")

    r = await client.delete(f"/api/v1/spus/{spu['id']}", headers=headers)
    assert r.status_code == 200, r.text

    async with async_session_factory() as session:
        left = (await session.execute(
            select(SkuRecord.id).where(SkuRecord.id.in_([sku_a["id"], sku_b["id"]]))
        )).scalars().all()
    assert left == [], f"SPU 已删除，但它的 SKU 还在库里（孤儿）: {left}"

    assert (await client.get(f"/api/v1/spus/{spu['id']}", headers=headers)).status_code == 404


async def test_spu_update_ignores_unknown_fields(client, auth_off, ensure_shop):
    """
    PUT 只更新白名单字段；不在白名单里的键不能被写进去。

    这条防的是「用 dict 直接 update 整行」的写法：一旦有人改成那样，
    客户端就能顺手改 `shop_id` / `id` —— 等于把租户隔离交给调用方决定。
    """
    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    other = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    spu = await _make_spu(client, headers, title="原始标题")
    r = await client.put(
        f"/api/v1/spus/{spu['id']}",
        json={"title": "改后标题", "shop_id": other, "id": "hacked-id"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["title"] == "改后标题"
    assert body["id"] == spu["id"], "id 被请求体改掉了"
    assert body.get("shop_id", sid) == sid, "shop_id 被请求体改掉了（租户隔离失守）"


# ====== 二、SKU：跨店铺写入必须被拦 ======

async def test_sku_create_rejects_spu_of_another_shop(client, auth_off, ensure_shop):
    """
    ★ 用别人店铺的 spu_id 建 SKU 必须 404。

    `create_sku` 里有显式校验（「校验 SPU 归属（防止跨店铺写入 SKU）」）。
    这类校验失效时**不会报错**：SKU 会挂到别人家的 SPU 上，
    两边列表都能看到异常数据，但没人会收到报警。
    """
    shop_a = await ensure_shop(f"store_crud_a_{uuid.uuid4().hex[:8]}")
    shop_b = await ensure_shop(f"store_crud_b_{uuid.uuid4().hex[:8]}")

    spu_a = await _make_spu(client, {"X-Shop-ID": shop_a})

    r = await client.post(
        "/api/v1/skus",
        json={"spu_id": spu_a["id"], "spec_value": "越权写入", "price": 1.0},
        headers={"X-Shop-ID": shop_b},
    )
    assert r.status_code == 404, (
        f"B 店用 A 店的 spu_id 建 SKU 应被拒（404），实际 {r.status_code}: {r.text[:200]}"
    )


async def test_sku_listing_patch_version_history(client, auth_off, ensure_shop):
    """
    Listing 写回端点的契约：版本号递增、历史保留旧标题、草稿转 ready。

    `PATCH /skus/{id}/listing` 是「Listing 优化 Agent」的写回口。
    版本历史是它唯一的回滚依据，写错就等于用户改不回上一版。

    实测顺序语义（源码如此）：
      第 1 次：标题原本为空 ⇒ 不产生历史条目，version 1 → 2
      第 2 次：标题已有值 ⇒ 旧标题进历史，version 2 → 3
    """
    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    spu = await _make_spu(client, headers)
    sku = await _make_sku(client, headers, spu["id"])
    assert sku["listing_version"] == 1
    assert sku["listing_status"] == "draft"

    r1 = await client.patch(
        f"/api/v1/skus/{sku['id']}/listing",
        json={"generated_title": "第一版标题", "generated_bullets": ["卖点 1"]},
        headers=headers,
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["generated_title"] == "第一版标题"
    assert b1["listing_version"] == 2
    assert b1["listing_history"] == [], "首版写入不该产生历史条目"
    assert b1["listing_status"] == "ready", "有标题后草稿应转 ready"

    r2 = await client.patch(
        f"/api/v1/skus/{sku['id']}/listing",
        json={"generated_title": "第二版标题"},
        headers=headers,
    )
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["listing_version"] == 3
    assert len(b2["listing_history"]) == 1, "第二版应把旧标题压进历史"
    assert b2["listing_history"][0]["title"] == "第一版标题"
    assert b2["generated_title"] == "第二版标题"


# ====== 三、素材 CRUD ======

async def test_asset_crud_roundtrip(client, auth_off, ensure_shop):
    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    r = await client.post(
        "/api/v1/assets",
        json={"name": "主图", "kind": "image", "url": "https://example.com/a.png"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    asset = r.json()
    assert asset["name"] == "主图"

    r = await client.put(
        f"/api/v1/assets/{asset['id']}",
        json={"name": "主图（改）", "notes": "备注"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "主图（改）"
    # 未提交的字段不被清空
    assert r.json()["url"] == "https://example.com/a.png"

    assert (await client.delete(f"/api/v1/assets/{asset['id']}", headers=headers)).status_code == 200
    assert (await client.get(f"/api/v1/assets/{asset['id']}", headers=headers)).status_code == 404


# ====== 四、三类分组：CRUD + 边界 ======

async def test_product_group_crud(client, auth_off, ensure_shop):
    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    g = await _make_group(client, headers, "/api/v1/product-groups", name="爆款")
    assert g["name"] == "爆款"

    ids = [x["id"] for x in (await client.get("/api/v1/product-groups", headers=headers)).json()["groups"]]
    assert g["id"] in ids

    r = await client.put(
        f"/api/v1/product-groups/{g['id']}", json={"name": "爆款（改）"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "爆款（改）"

    assert (await client.delete(f"/api/v1/product-groups/{g['id']}", headers=headers)).status_code == 200
    ids = [x["id"] for x in (await client.get("/api/v1/product-groups", headers=headers)).json()["groups"]]
    assert g["id"] not in ids
    # 删过的分组再操作 → 404（不能静默成功）
    assert (await client.put(
        f"/api/v1/product-groups/{g['id']}", json={"name": "x"}, headers=headers
    )).status_code == 404


async def test_product_group_delete_strips_id_from_spus(client, auth_off, ensure_shop):
    """
    删分组必须把它从 SPU 的 `groups` 里摘掉。

    否则 SPU 会残留一个指向已删分组的 id：前端按分组筛选时这些商品
    「哪个分组都不属于」，看起来像丢了。
    """
    from core.database import async_session_factory

    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    g = await _make_group(client, headers, "/api/v1/product-groups")
    spu = await _make_spu(client, headers, groups=[g["id"]])
    assert spu["groups"] == [g["id"]]

    assert (await client.delete(f"/api/v1/product-groups/{g['id']}", headers=headers)).status_code == 200

    async with async_session_factory() as session:
        left = (await session.execute(
            select(SpuRecord.groups).where(SpuRecord.id == spu["id"])
        )).scalar_one()
    assert not left or g["id"] not in left, f"SPU 里仍残留已删分组 id: {left}"

    # 数据库里那行确实没了
    async with async_session_factory() as session:
        gone = (await session.execute(
            select(ProductGroupRecord.id).where(ProductGroupRecord.id == g["id"])
        )).scalar_one_or_none()
    assert gone is None


async def test_asset_group_delete_strips_id_from_assets(client, auth_off, ensure_shop):
    """素材分组删除同上：必须从素材的 `groups` 里摘掉"""
    from core.database import async_session_factory

    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    g = await _make_group(client, headers, "/api/v1/asset-groups")
    r = await client.post(
        "/api/v1/assets",
        json={"name": "图", "kind": "image", "url": "https://example.com/b.png", "groups": [g["id"]]},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    asset_id = r.json()["id"]

    assert (await client.delete(f"/api/v1/asset-groups/{g['id']}", headers=headers)).status_code == 200

    async with async_session_factory() as session:
        left = (await session.execute(
            select(AssetRecord.groups).where(AssetRecord.id == asset_id)
        )).scalar_one()
    assert not left or g["id"] not in left, f"素材里仍残留已删分组 id: {left}"


async def test_candidate_group_crud(client, auth_off, ensure_shop):
    from core.database import async_session_factory

    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    g = await _make_group(client, headers, "/api/v1/candidate-groups", name="蓝海候选")
    assert g["name"] == "蓝海候选"

    r = await client.put(
        f"/api/v1/candidate-groups/{g['id']}", json={"name": "蓝海候选（改）"}, headers=headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "蓝海候选（改）"

    assert (await client.delete(f"/api/v1/candidate-groups/{g['id']}", headers=headers)).status_code == 200
    async with async_session_factory() as session:
        gone = (await session.execute(
            select(CandidateGroupRecord.id).where(CandidateGroupRecord.id == g["id"])
        )).scalar_one_or_none()
    assert gone is None


async def test_group_move_at_boundary_does_not_fail(client, auth_off, ensure_shop):
    """
    只有一个分组时上移/下移都必须安全返回，不能 IndexError → 500。

    三个 `move` 端点都是「交换列表相邻两项」，边界判断写错就是越界。
    这里只钉边界行为（不测排序是否真的持久化，见文件头说明）。
    """
    sid = await ensure_shop(f"store_crud_{uuid.uuid4().hex[:8]}")
    headers = {"X-Shop-ID": sid}

    for path in ("/api/v1/product-groups", "/api/v1/asset-groups"):
        g = await _make_group(client, headers, path)
        for direction in ("up", "down"):
            r = await client.post(
                f"{path}/{g['id']}/move", json={"direction": direction}, headers=headers
            )
            assert r.status_code == 200, f"{path} direction={direction} → {r.status_code} {r.text[:200]}"
            assert r.json()["message"] == "已在边界", r.json()

    # 不存在的分组必须 404，而不是「已在边界」这类成功语义
    missing = await client.post(
        "/api/v1/product-groups/grp-not-exist/move", json={"direction": "up"}, headers=headers
    )
    assert missing.status_code == 404, missing.text
