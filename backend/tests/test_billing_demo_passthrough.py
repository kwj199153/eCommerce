"""计费模块的「演示身份直通」门禁（2026-09-25 · 支付宝扫码支付接入后）

==============================================================================
★★★ 这条门禁守的是老板的一句硬要求
==============================================================================
需求原文：

    「P0+P1，支付宝（**同时保留演示用户无需扫码支付，保持目前功能**）」

拆成两句**互相制约**的话：

    ① 真实用户 —— 必须走支付宝当面付：下单拿二维码 ⇒ 扫码 ⇒ 回调 ⇒ 才激活；
    ② 演示用户 —— 必须**照旧直通**：点一下即开通，**没有二维码这回事**。

② 不是"顺便留一下"，它是①的**对照面**：只要有人为了做①而把整条链路改成
异步两段式，②就会跟着一起变成"演示用户也要扫码"—— 而演示环境没有商户号、
没有二维码可言，症状是**演示账号整个订阅页不能用**，且不会有任何报错。

==============================================================================
★★★ 本轮真正踩到的坑：一个「注释很全、一行不执行」的死代码
==============================================================================
`change_plan` 里早就写好了分流：

    demo = is_demo_request(request)
    if demo:
        gateway = get_gateway("mock")      # ← 演示直通
    else:
        gateway = get_gateway()            # ← 支付宝

而**同一个端点的依赖**是 `Depends(get_current_user)` —— 它**不认** `demo-`
哨兵（`get_current_user` 只会拿 token 去验 JWT 签名）。于是演示请求在
**鉴权层**就 401，函数体一行都没进 ⇒ 上面那段分流是一段**死代码**。

★ 为什么这类缺陷最难发现：
  · 代码读起来完全正确（分流逻辑对、注释齐全、条件表达式也没写错）；
  · 单元测试若只测函数体（直接调 `change_plan(...)`）会**全绿**；
  · 只有"从 HTTP 打进来"的用例才会红 —— 而当时**没有任何计费用例用演示身份**。

⇒ 本文件的用例一律**从 HTTP 打进来**（`client.post(...)` + 真请求头），
  不直接调用端点函数。判据：「端点行为」只能用端到端的方式测。

==============================================================================
★★ 修法：把鉴权档从 `get_current_user` 换成 `require_acting_user`
==============================================================================
`core/auth/dependencies.py::require_acting_user` = `get_acting_user` 的
fail-closed 形态：

    · 认 `demo-` 哨兵（解析成**演示账号主人**，真 `User` 行）；⟸ 演示直通靠这一格
    · 真匿名（无任何凭据）⇒ **401**（而不是返回 `None` 让下游 `current_user.id`
      炸成 500 —— 500 的归因方向是"服务端 bug"，真因只是没带 token）。

★ 与 `modules/skills/router.py` 第 182 轮同判据：那边把技能写口从
  `require_auth_if_enabled` 换成 `get_acting_user`，理由逐字相同。

==============================================================================
★ 三条反向断言（缺任何一条，"认演示"就会变成"谁都能白拿套餐"）
==============================================================================
    ① `demo_mode=False`（生产档）⇒ 哨兵与任意伪造串同等待遇 ⇒ 401
    ② `auth_required=True` ⇒ 取更严的一侧 ⇒ 401
    ③ 演示账号查不到 / 是超管 / 已停用 ⇒ 三重守卫降级 ⇒ 401
      （三条守卫的实现都在 `resolve_demo_user`，本文件只钉"它们真的拦到这里"）

==============================================================================
★ 反向注入清单（每一条都必须让本文件**至少一条**转红）
==============================================================================
 1. `modules/billing/router.py` 的 `Depends(require_acting_user)`
    改回 `Depends(get_current_user)`
    ⇒ `test_demo_token_subscribes_without_scanning` 转红（401）——
      这正是修复前的形态。
 2. `change_plan` 里删掉 `demo = is_demo_request(request)` 那一档
    （演示身份也走 `get_gateway()`）
    ⇒ `test_demo_token_subscribes_without_scanning` 转红
      （当前网关是 mock 时它仍会绿 ⇒ 用例必须**把网关设成 alipay** 才咬得住，
       见该用例里的 `config.payment_gateway` 前置）。
 3. `require_acting_user` 里 `if user is None: raise 401` 改成 `return None`
    ⇒ `test_anonymous_without_credentials_is_refused` 转红（500 而非 401）。
 4. `require_acting_user` 跳过 `get_acting_user`、直接 `get_current_user`
    ⇒ 用例 1 转红。
"""

import uuid

from sqlalchemy import select, text

from core.database import async_session_factory


#: 与 `frontend/src/config/demoMode.ts::DEMO_TOKEN` 逐字一致。
#: ★ 刻意在这里再写一遍而不是 import 前端文件：这条串是**跨语言的契约**，
#:   抄错一个字符的症状是"演示直通静默失效"（401 ⇒ 前端降级到 mock，
#:   界面看起来一切正常）。`test_demo_identity.py::test_demo_sentinel_prefix_matches_frontend`
#:   钉住的是**前缀**，这里钉住**整串**。
DEMO_TOKEN = "demo-token"

DEMO_HEADERS = {"Authorization": f"Bearer {DEMO_TOKEN}"}


# ============================================================================
# 前置：把「演示账号主人」造出来
# ============================================================================

async def _make_demo_owner(make_user, monkeypatch, *, label: str = "demopay") -> dict:
    """造一个**临时**用户当演示账号主人，并把 `config.demo_account_email` 指向它。

    ★ 为什么不直接用 `.env` 里那个真演示账号：
      那会在用例中途改动**全局**演示身份（并可能因并发/失败残留），
      连带影响其它演示相关用例 —— 症状是"另一条用例红了"（归因反向）。
      `test_demo_identity.py::test_inactive_demo_owner_is_refused` 已有同结论。

    ★★ 为什么必须显式 `ensure_default_account`（这条是实测踩出来的）：
      注册只建 `users` / `subscriptions` / `email_tokens`，**名下一个容器都没有**；
      而 `resolve_demo_user` 的查询里带着 `join(Account, ...)` ⇒ 容器缺失时
      演示身份解析结果是 `None`，本文件所有用例会红在**鉴权那一步**，
      看起来像"新依赖写错了"，实则只是前置没造齐。
      ⇒ 守卫 ② 的真实语义是「**查得到一个名下有容器的主人**」。

    ★ `ensure_default_account` 只 `flush()` 不 `commit()`（它服务于"同一事务内
      建店 + 建容器"这个用法）⇒ 这里必须自己 commit，否则退出 `with` 时整体回滚。
    """
    from core.auth.accounts import ensure_default_account
    from core.identity.models import User

    owner = await make_user(label)
    monkeypatch.setattr(
        "core.config.config.demo_account_email", owner["email"], raising=True
    )

    async with async_session_factory() as db:
        u = (
            await db.execute(select(User).where(User.id == owner["user_id"]))
        ).scalar_one()
        await ensure_default_account(db, u)
        await db.commit()

    return owner


async def _demo_invoices(user_id: str) -> list[tuple]:
    async with async_session_factory() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT amount, status, plan_id, billing_cycle, payment_channel "
                    "FROM invoices WHERE user_id = :u ORDER BY issued_at"
                ),
                {"u": user_id},
            )
        ).all()
    return list(rows)


# ============================================================================
# 1. 正向：演示身份**点一下就开通**，没有二维码
# ============================================================================

async def test_demo_token_subscribes_without_scanning(
    client, demo_on, auth_off, make_user, monkeypatch
):
    """★★★ 本文件的核心用例：演示身份订阅必须**同步直通**，且不受网关配置影响。

    ==========================================================================
    ★ 为什么必须把 `config.payment_gateway` 设成 `alipay`（关键，别删）
    ==========================================================================
    如果把网关留在 `mock`，那么**无论演示分流那段代码在不在**，
    结果都是"同步开通" —— 用例恒绿，反向注入也证不伪（**假绿**）。

    真正的判据是：「**当前配置了支付宝**，但这次请求是演示身份」
    ⇒ 必须走 mock、必须同步。所以这里显式把网关切成 `alipay`：
      · 分流生效 ⇒ 走 mock ⇒ `charged=True`、订阅立刻 active（本用例绿）；
      · 分流被删 ⇒ 走 alipay ⇒ 要么 `GatewayConfigError` 503
        （本机没配商户凭证），要么返回 `requires_confirmation=True`（配了）
        ⇒ 本用例红。
    这是本用例唯一能咬住"分流那两行"的写法。
    """
    from core.config import config as _cfg

    prev_gw = _cfg.payment_gateway
    owner = await _make_demo_owner(make_user, monkeypatch)
    _cfg.payment_gateway = "alipay"
    try:
        r = await client.post(
            "/api/v1/billing/subscribe",
            json={"plan_id": "2", "billing_cycle": "yearly"},
            headers=DEMO_HEADERS,
        )
    finally:
        _cfg.payment_gateway = prev_gw

    assert r.status_code == 200, (
        f"★ 演示身份订阅被拒（{r.status_code}）：{r.text}\n"
        f"  · 401 ⇒ 端点用的还是 `get_current_user`（它不认 demo- 哨兵），"
        f"演示请求在鉴权层就被拦下，`change_plan` 里的分流是**死代码**；\n"
        f"  · 503 ⇒ 演示身份被当成了真实用户，去调支付宝下单了。"
    )

    body = r.json()
    assert body["charged"] is True, f"演示身份必须**同步**扣款成功：{body}"
    assert not body.get("requires_confirmation"), (
        "★ 演示身份竟然返回了 `requires_confirmation=True` —— "
        "这意味着前端会给演示用户弹一个二维码，而演示环境根本没有商户号。"
        f"老板的硬要求是「演示用户无需扫码支付」：{body}"
    )
    assert body.get("payment") in (None, {}), (
        f"演示身份不该有支付凭据返回（前端会据此渲染二维码）：{body.get('payment')}"
    )

    sub = body["subscription"]
    assert sub["plan"]["name"] == "pro"
    assert sub["billing_cycle"] == "yearly"
    assert sub["status"] == "active", (
        f"★ 演示身份是**同步**形态 ⇒ 订阅必须一步到位 active，实际 {sub['status']}"
    )

    # 账单落在**演示账号主人**名下（不是某个前端传上来的 id —— 前端只传了哨兵串）
    rows = await _demo_invoices(owner["user_id"])
    assert len(rows) == 1, f"演示身份订阅应恰好产生 1 张账单，实际 {rows}"
    amount, status, plan_id, cycle, channel = rows[0]
    assert status == "paid", f"同步形态下账单必须是 paid（钱与权限同时到位）：{rows[0]}"
    assert cycle == "yearly"
    assert channel, "账单必须记下支付渠道（对账要按它筛）"
    assert abs(amount - 2990.0) < 0.01, f"年付金额应等于价目表，实际 {amount}"


# ============================================================================
# 2. 正向（读口）：演示身份也能读自己的订阅 / 用量 / 账单
# ============================================================================

async def test_demo_token_reads_its_own_billing_state(
    client, demo_on, auth_off, make_user, monkeypatch
):
    """读口与写口**同一档**：否则演示用户在订阅页看到的永远是"未订阅"。

    ★ 与 `modules/skills/router.py` 第 182 轮同判据 —— 那边明确写着
      「读口与写口同一档」：演示身份既然能订阅，就必须能看见自己订了什么。
      只放开写口（或只放开读口）都会让页面自相矛盾，且症状是"点了没反应"。
    """
    owner = await _make_demo_owner(make_user, monkeypatch, label="demoread")

    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "2", "billing_cycle": "monthly"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 200, r.text

    sub = await client.get("/api/v1/billing/subscription", headers=DEMO_HEADERS)
    assert sub.status_code == 200, sub.text
    got = sub.json()["subscription"]
    assert got is not None, "★ 刚订阅完却读不到订阅 —— 读口没认演示身份"
    assert got["plan"]["name"] == "pro"

    usage = await client.get("/api/v1/billing/usage", headers=DEMO_HEADERS)
    assert usage.status_code == 200, usage.text

    inv = await client.get("/api/v1/billing/invoices", headers=DEMO_HEADERS)
    assert inv.status_code == 200, inv.text
    body = inv.json()
    items = body.get("invoices", body) if isinstance(body, dict) else body
    assert len(items) == 1, (
        f"★ 演示身份应在 /invoices 里看到**自己那 1 张**账单，实际 {len(items)} 条 —— "
        f"读口若没认演示身份，这里会是 0 条（页面显示“暂无账单”）。"
    )

    # 归属确认：账单确实挂在演示账号主人名下
    rows = await _demo_invoices(owner["user_id"])
    assert len(rows) == 1


# ============================================================================
# 3. 反向①：demo_mode 关闭 ⇒ 哨兵不是身份（生产档）
# ============================================================================

async def test_demo_mode_off_refuses_demo_token(
    client, demo_off, auth_off, make_user, monkeypatch
):
    """`DEMO_MODE=false`（生产形态）下，`demo-token` 与任意伪造串同等待遇 ⇒ 401。

    ★ 这条是"认演示"的**安全下界**：哨兵串明文写在前端源码里，
      任何会读代码的人都能带上它。它只是"本地演示开关"，不是"身份"。
    """
    owner = await _make_demo_owner(make_user, monkeypatch, label="demooff")
    assert owner  # 账号**存在**，唯一变量是 demo_mode 关着

    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "2", "billing_cycle": "monthly"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 401, (
        f"★ demo_mode 关着却仍然承认了 demo- 哨兵（{r.status_code}）—— "
        f"生产环境里任何知道这枚字符串的人都能拿到演示账号的订阅与账单。"
    )
    assert await _demo_invoices(owner["user_id"]) == [], "被拒的请求不得产生账单"


# ============================================================================
# 4. 反向②：auth_required 打开 ⇒ 取更严的一侧
# ============================================================================

async def test_auth_required_refuses_demo_token(
    client, demo_on, auth_on, make_user, monkeypatch
):
    """`demo_mode` 与 `auth_required` 同时为真属**配置矛盾**（生产护栏另有硬拦）
    ⇒ 运行期按更严的一侧生效：不承认这个身份。

    ★ 为什么这条值得单列：它是"两个开关打架"时的**唯一**运行期防线。
      配置矛盾在生产起不来（`_enforce_production_safety`），
      但中间件/依赖层仍不能假设"外部已经拦住"。
    """
    owner = await _make_demo_owner(make_user, monkeypatch, label="demoauthon")
    assert owner

    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "2", "billing_cycle": "monthly"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 401, (
        f"★ auth_required=True 时仍放行了演示身份（{r.status_code}）—— "
        f"要求真实登录的环境里不该有一条免登录的旁路。"
    )
    assert await _demo_invoices(owner["user_id"]) == []


# ============================================================================
# 5. 反向③：演示账号查不到 ⇒ 三重守卫降级 ⇒ 401（**不能**随便挑一个人）
# ============================================================================

async def test_demo_token_without_demo_account_is_refused(
    client, demo_on, auth_off, make_user, monkeypatch
):
    """配了一个库里不存在的 email ⇒ 无身份 ⇒ 401。

    ★ 反向注入：把 `resolve_demo_user` 的 `.where(User.email == email)` 删掉
      ⇒ 本条转红，且演示身份会命中一个**随机的**真实用户
      （那个人的订阅与账单从此对任何知道 `demo-token` 的人可见）。
    """
    # 刻意**不**把 email 指向任何真人
    make_user("ghost")  # 库里确实有用户 —— 但不能被"随便挑中"
    monkeypatch.setattr(
        "core.config.config.demo_account_email",
        f"nobody-{uuid.uuid4().hex[:8]}@example.com",
        raising=True,
    )

    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "2", "billing_cycle": "monthly"},
        headers=DEMO_HEADERS,
    )
    assert r.status_code == 401, (
        f"★ 演示账号配成了一个不存在的 email，却仍然放行了（{r.status_code}）—— "
        f"说明实现里有一处「找不到就随便取一个」的兜底，"
        f"而那条兜底会把某个**无关真人**的订阅/账单暴露给任何知道哨兵串的人。"
    )


# ============================================================================
# 6. 反向④：真匿名仍然 fail-closed 401；**同时**公开定价不许被一起关掉
# ============================================================================

async def test_anonymous_without_credentials_is_refused_but_plans_stay_public(
    client, auth_off
):
    """无任何凭据 ⇒ 订阅端点 401（**不是** 500），而 `/plans` 仍然公开。

    ==========================================================================
    ★ 为什么"401 而不是 500"这条值得一个用例
    ==========================================================================
    `require_acting_user` 的**唯一**新增逻辑就是「`None` ⇒ 401」。
    去掉它（直接 `return None`）之后，端点会走到 `current_user.id`
    ⇒ `AttributeError` ⇒ **500**。两者对用户是**完全不同**的两句话：

        · 401「需要登录」⇒ 用户知道该去登录（前端也会跳登录页）；
        · 500「服务器错误」⇒ 用户报障、运维翻栈找 bug，而真因只是没带 token。

    判据：**错误码是产品的一部分**，不是实现细节。

    ==========================================================================
    ★ 为什么同一个用例里必须捎带断言 `/plans` 仍然 200
    ==========================================================================
    修演示直通最省事的做法是给整个 router 挂一条全局鉴权依赖 ——
    那会**顺手把公开定价页关掉**（未登录用户看不到套餐价格 ⇒ 无法比较、
    无法决定买哪个）。两条断言放在一起，是因为它们**互为对方的守门人**：
    只钉住 401 的实现里，那种"一刀切"改法会全绿。

    ★ 注意 `/plans` 用 `auth_off` 这一档：`auth_required=True` 时未登录
      打 `/plans` 应当如何，由该端点自己的注释定义（"公开信息"），
      不在本用例的断言范围内 —— 本用例只证明"演示档下它没被顺手关掉"。
    """
    r = await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": "2", "billing_cycle": "monthly"},
    )
    assert r.status_code == 401, (
        f"★ 真匿名访问订阅端点应得 401，实际 {r.status_code}。\n"
        f"  500 ⇒ `require_acting_user` 里那一步 `None ⇒ 401` 被删了："
        f"`current_user.id` 直接 AttributeError，归因方向完全反了。"
    )
    assert "Bearer" in r.text or "登录" in r.text or "凭据" in r.text, (
        f"401 的文案要能告诉用户“该怎么办”（去登录），实际：{r.text}"
    )

    plans = await client.get("/api/v1/billing/plans")
    assert plans.status_code == 200, (
        f"★ 公开定价被顺手关掉了（{plans.status_code}）—— "
        f"未登录用户看不到套餐价格就没法决定买哪个。"
        f"修鉴权档时把整个 router 挂全局依赖就会造成这个后果。"
    )
    body = plans.json()
    items = body.get("plans", body) if isinstance(body, dict) else body
    assert items, "公开定价返回了空列表"
