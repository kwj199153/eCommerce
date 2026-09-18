"""
「optional auth」语义守护（2026-09-17）

★★★ 这条测试钉住的是什么
老板实测：用 `263977396@qq.com` **真实登录**后，主页面仍看到别人的 4 个店铺。

根因不是显示问题，而是**多租户隔离整体失效**。两处叠加：

  ① `core/auth/dependencies.py::require_auth_if_enabled`
        `if not config.auth_required: return None`   # ← 第一步，连 token 都不解析
     它不是「optional auth（有凭据就解析身份）」，而是「**auth 整体关闭**」。
     后果：真实登录用户拿到 `None` ⇒ 下游所有 `user is None → 放行` 分支被触发：
       · `accounts.filter_accessible_stores(db, None, stores)` → 返回**全库**店铺
         （★ 2026-09-17 已收紧为「无身份 ⇒ 空列表」，见本文件末的守卫用例）
       · `accounts.can_access_store` / `_matches` → 恒真 ⇒ 伪造 `X-Shop-ID`
         即可读写任意店铺业务数据（2026-09-15 修的 BOLA 在演示模式下原样回归）
  ② `main.py::BUSINESS_AUTH`
        = [Depends(require_auth_if_enabled)] if config.auth_required else []
    把**运行期**判断（这次请求带没带凭据）提成了**启动期常量** ⇒
    `AUTH_REQUIRED=false` 时 router 级根本没挂依赖。

⇒ 修复后 `require_auth_if_enabled` 是 optional auth 三档：
     有真 token → **强制解析**（失败 401）；demo 哨兵 → 匿名；无凭据 → 看开关。

★ 反向注入验证（必须做，否则不知道测试是不是空跑）
  把 `require_auth_if_enabled` 的 ② 分支去掉、改回
  `if not config.auth_required: return None`，
  则 `test_cross_user_store_isolation_with_real_token` 必须转红
  （B 会看到 A 的店）。实测已确认。
"""

import pytest


# ====== 夹具：演示哨兵开关 ======


@pytest.fixture
def demo_on():
    """显式打开演示哨兵（不依赖 .env，避免测试结论随外部配置漂移）"""
    from core.config import config

    prev = config.demo_mode
    config.demo_mode = True
    yield
    config.demo_mode = prev


@pytest.fixture
def demo_off():
    from core.config import config

    prev = config.demo_mode
    config.demo_mode = False
    yield
    config.demo_mode = prev


async def _create_store(client, user, name):
    """在 `user` 名下建一家店（走真实端点 ⇒ 自动挂到其个人账户）。"""
    r = await client.post(
        "/api/v1/stores",
        headers=user["headers"],
        json={"name": name, "platform": "amazon"},
    )
    assert r.status_code in (200, 201), f"建店失败: {r.status_code} {r.text}"
    return r.json()


def _names(resp):
    return {s["name"] for s in resp.json()["stores"]}


# ====== 核心门禁：真实 token 必须被解析 ======


async def test_cross_user_store_isolation_with_real_token(auth_off, client, make_user):
    """
    ★★★ 本文件最重要的一条 —— 老板那条现象的直接复现。

    演示模式（`AUTH_REQUIRED=false`，就是本地 `.env`）下：
      A 建一家店；**B 带自己的合法 token** 打 `/api/v1/stores`，不能看见 A 的店。

    反向注入：把 `require_auth_if_enabled` 改回「第一步 return None」，
    本条立刻转红（B 会看到 A 的店 == 老板界面上那 4 家店的成因）。
    """
    a = await make_user("iso-a")
    b = await make_user("iso-b")

    store = await _create_store(client, a, "隔离店铺-A")

    ra = await client.get("/api/v1/stores", headers=a["headers"])
    assert ra.status_code == 200, ra.text
    assert "隔离店铺-A" in _names(ra), "车主自己看不到自己的店 —— 修过头了"

    rb = await client.get("/api/v1/stores", headers=b["headers"])
    assert rb.status_code == 200, rb.text
    assert "隔离店铺-A" not in _names(rb), (
        "★★★ 越权可见：B 的合法 token 看到了 A 的店铺。"
        "说明带凭据时身份没被解析 ⇒ 归属过滤整体失效（多租户隔离失效）。"
    )


async def test_invalid_token_is_rejected_even_in_demo_mode(auth_off, client):
    """
    带了自称为 Bearer 的凭据 ⇒ 必须按真身份校验，无效就 401。

    修复前的行为是「演示模式一律放行」，于是**伪造凭据与匿名无法区分**，
    攻击者只要知道演示模式开着就能零成本访问。
    """
    r = await client.get(
        "/api/v1/stores", headers={"Authorization": "Bearer not-a-real-jwt"}
    )
    assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"


async def test_anonymous_is_still_allowed_when_auth_not_required(auth_off, client):
    """
    ③ 档不能丢：**完全不带凭据** + `auth_required=False` ⇒ 匿名放行。
    这是本地联调（curl / 文档站）的既有体验，修复不该把它一起收掉。

    ★ 2026-09-17 订正："放行"指的是**状态码**，不是"能拿到数据"：
      本函数只收口数据可见性 ⇒ 匿名仍得 200，但 `total == 0`
      （见下方 `test_anonymous_store_list_is_empty_not_full_library`）。
    """
    r = await client.get("/api/v1/stores")
    assert r.status_code == 200, f"匿名联调被误伤: {r.status_code} {r.text[:200]}"


async def test_anonymous_rejected_when_auth_required(auth_on, client):
    """`auth_required=True`（生产）下，无凭据必须 401。"""
    r = await client.get("/api/v1/stores")
    assert r.status_code == 401


# ====== 演示哨兵（demo-token）======


async def test_demo_sentinel_allowed_only_when_demo_mode_on(auth_off, demo_on, client):
    """`demo_mode=True` 时哨兵按**匿名演示**处理 ⇒ 放行（不报 401）。"""
    r = await client.get(
        "/api/v1/stores", headers={"Authorization": "Bearer demo-token"}
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"


async def test_demo_sentinel_rejected_when_demo_mode_off(auth_off, demo_off, client):
    """
    ★ `demo_mode=False` 时它必须与任意伪造串同等待遇（401）。

    这条是安全底线：`demo-token` **明文写在前端源码里**
    （frontend/src/config/demoMode.ts），任何会读代码的人都能带上它。
    若这里放行，"演示模式"就等于"任何人可匿名读全部业务数据"。
    """
    r = await client.get(
        "/api/v1/stores", headers={"Authorization": "Bearer demo-token"}
    )
    assert r.status_code == 401, (
        "demo 哨兵在 demo_mode=False 时被接受了 —— 等于把业务数据对"
        "任何知道这个字符串的人敞开。"
    )


# ====== BOLA（归属校验必须真的执行）======


async def test_cross_store_business_data_access_forbidden(auth_off, client, make_user):
    """
    伪造 `X-Shop-ID` 访问别人的店铺业务数据 ⇒ 403。

    ★ 这是 2026-09-15 修过的 BOLA 洞，在演示模式下**原样回归**过：
      `middleware.py::_resolve_current_shop_id` 里 `current_user is None → return shop_id`
      使归属校验整段被跳过。修复后带真 token 必然解析出身份 ⇒ 走向 403 分支。
    """
    a = await make_user("bola-a")
    b = await make_user("bola-b")

    store = await _create_store(client, a, "BOLA店铺-A")

    # 车主本人：放行（不误伤）
    ok = await client.get(
        "/api/v1/products",
        headers={**a["headers"], "X-Shop-ID": store["id"]},
    )
    assert ok.status_code == 200, f"车主自己被误伤: {ok.status_code} {ok.text[:200]}"

    # 他人：403
    bad = await client.get(
        "/api/v1/products",
        headers={**b["headers"], "X-Shop-ID": store["id"]},
    )
    assert bad.status_code == 403, (
        f"越权读到了别人的店铺业务数据（{bad.status_code}）—— BOLA 回归。"
    )


# ====== 守卫：没有身份 ⇒ 没有数据（2026-09-17 收紧）======


async def test_anonymous_store_list_is_empty_not_full_library(auth_off, client, make_user):
    """
    ★★★ 演示档下匿名打 `/api/v1/stores`：**状态仍是 200，条数必须是 0**。

    改前是"不过滤 ⇒ 返回全库"：本地 / 演示档一旦连了真实数据，匿名就能拿走
    全部店铺。生产档靠 `BUSINESS_AUTH` 401 先拦（所以不是线上漏洞），
    但"生产不可达"不等于"本地安全"。

    为什么状态码仍是 200 而不是 401：上游 `require_auth_if_enabled` 在
    `auth_required=False` 时**有意放行**匿名（本地联调 / curl / 文档站的既有体验）。
    本函数只收口**数据可见性**，不反向改写上游的鉴权结论 ——
    "访问被允许，但你看不到任何店铺"。

    反向注入：把 `filter_accessible_stores` 的 `return []` 改回
    `return list(stores)`，本条必须转红（`total` 会变成 >= 1）。
    """
    a = await make_user("anon-should-not-see")
    await _create_store(client, a, "匿名不该看到的店")

    # 先确认不是"修过头把所有人都挡了"
    ra = await client.get("/api/v1/stores", headers=a["headers"])
    assert ra.status_code == 200, ra.text
    assert "匿名不该看到的店" in _names(ra), "车主自己都看不到了 —— 修过头了"

    # 匿名：放行，但没有任何店铺
    r = await client.get("/api/v1/stores")
    assert r.status_code == 200, f"匿名联调被误伤: {r.status_code} {r.text[:200]}"
    body = r.json()
    assert body["total"] == 0, (
        f"★★★ 匿名拿到了 {body['total']} 家店铺 —— 演示档 fail-open 回归。"
        "守卫应为「没有身份 ⇒ 没有数据」（返回空列表，而不是不过滤）。"
    )
    assert body["stores"] == [], f"stores 非空: {body['stores']}"


async def test_demo_sentinel_also_sees_no_stores(auth_off, demo_on, client, make_user):
    """
    ★ `demo-token` 是**匿名演示身份**，不是真身份 ⇒ 同样走「没有身份 ⇒ 没有数据」。

    这条最容易漏：哨兵能拿到 200（上游按匿名放行），于是很顺手就会以为
    "演示模式本来就该看到数据"。但 `demo-token` 明文写在前端源码里
    （frontend/src/config/demoMode.ts），任何读过代码的人都能带上它 ⇒
    若它能读到数据，等于把业务数据对全网敞开。

    ★ 与 `test_demo_sentinel_allowed_only_when_demo_mode_on` 的分工：
      那条只断言"放行（不报 401）"，本条断言"放行也拿不到数据"。
    """
    a = await make_user("sentinel-should-not-see")
    await _create_store(client, a, "哨兵不该看到的店")

    r = await client.get(
        "/api/v1/stores", headers={"Authorization": "Bearer demo-token"}
    )
    assert r.status_code == 200, f"{r.status_code} {r.text[:200]}"
    assert r.json()["total"] == 0, (
        "演示哨兵读到了真实店铺 —— 这个字符串是公开的，等于对任何人敞开。"
    )


# ====== 形态门禁 ======


def test_business_auth_is_not_conditionally_mounted():
    """
    ★ 形态门禁：`BUSINESS_AUTH` **不得**再按 `config.auth_required` 条件化。

    为什么用**源码**断言而不是行为断言：`BUSINESS_AUTH` 是 `main.py` 的
    **启动期快照**，行为断言只在「import main 时 auth_required 恰好为 False」
    才红 —— 测试进程换个配置就一路绿。源码断言在任何环境下都立刻报警。

    ★ 先剥行注释再匹配：本文件与 main.py 的注释里**故意**引用了旧写法
      （用来讲清它错在哪），直接 `in` 会被自己的说明文字骗过。
    """
    import inspect

    import main

    src = inspect.getsource(main)
    code = "\n".join(
        ln for ln in src.splitlines() if not ln.strip().startswith("#")
    )

    assert (
        "BUSINESS_AUTH = [Depends(require_auth_if_enabled)] if config.auth_required else []"
        not in code
    ), "BUSINESS_AUTH 又退回条件挂载 —— AUTH_REQUIRED=false 时 router 级没有依赖。"
    assert "BUSINESS_AUTH = [Depends(require_auth_if_enabled)]" in code, (
        "BUSINESS_AUTH 的挂载形态变了，请确认仍是**无条件**挂载。"
    )


def test_demo_mode_is_rejected_in_production(prod_settings_kwargs):
    """生产护栏：`DEMO_MODE=true` 必须拒绝启动（与 payment_gateway=mock 同构）。"""
    from core.config import Settings

    with pytest.raises(ValueError) as ei:
        Settings(**prod_settings_kwargs(demo_mode=True))

    assert "DEMO_MODE" in str(ei.value), (
        "生产环境没有拦住 DEMO_MODE=true —— 演示哨兵等于匿名读全部业务数据。"
    )
