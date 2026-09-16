"""
支付链路回归测试（★ P1-4 / 2026-09-15）

覆盖四类**曾经真实出过问题**的场景，每条都对应一份实测证据
（.workbuddy/probes/project-audit-20260915/09-支付链路-实测证据.txt）：

  1. 账单落库          —— invoices 表曾有 0 行，需证明确实写得进去
  2. 展示价 == 收款价   —— 年付公式曾在两处独立硬编码 `* 10`（口径分叉）
  3. 零元不开票        —— 切免费套餐曾凭空开出一张 ¥0.00 的 paid 账单
  4. 重复提交不重复扣款 —— 连点两次升级曾产生 2 张账单（真实网关下 = 扣两次钱）
                          并发双击由 DB 唯一约束兜底

另外两条护栏测试：
  5. 未接入的真实网关必须 501，**不得**静默降级为「支付成功」
  6. 生产环境用 mock 网关必须拒绝启动（正向/反向各一次）
  7. 兜底闸：唯一约束命中时必须 409 而非 500；其他完整性错误不得被吞

★ 这些用例的价值不在于「跑通流程」，而在于**锁住方向**：
  上面 3、4 两条的 bug 方向都是「多收用户的钱 / 少收平台的钱」，
  一旦回归，对账时要花几天才能定位。
"""

import asyncio

import pytest
from sqlalchemy import select, text

from modules.billing.pricing import (
    build_idempotency_key,
    is_duplicate_submission,
    normalize_cycle,
    plan_amount,
    subscription_state_fingerprint,
    yearly_price,
)
from core.config import KNOWN_UNIMPLEMENTED_GATEWAYS, config
from core.database import get_async_session
from modules.billing.models import Subscription, SubscriptionPlan


# ====== 工具 ======

async def _invoices_of(user_id: str) -> list[tuple]:
    async with get_async_session() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT number, amount, status, description, idempotency_key "
                    "FROM invoices WHERE user_id = :u ORDER BY issued_at"
                ),
                {"u": user_id},
            )
        ).all()
    return list(rows)


async def _subscribe(client, headers, plan_id: str, cycle: str):
    return await client.post(
        "/api/v1/billing/subscribe",
        json={"plan_id": plan_id, "billing_cycle": cycle},
        headers=headers,
    )


# ====== 1. 账单落库 ======

async def test_change_plan_writes_invoice(client, auth_on, user, auth_headers):
    """升级到 pro 年付：必须真的写出一条 paid 账单，且金额等于套餐年价。"""
    plans = (await client.get("/api/v1/billing/plans", headers=auth_headers)).json()
    plan_list = plans.get("plans", plans) if isinstance(plans, dict) else plans
    pro = next(p for p in plan_list if p["name"] == "pro")

    r = await _subscribe(client, auth_headers, "2", "yearly")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["charged"] is True
    assert body["subscription"]["plan"]["name"] == "pro"
    assert body["subscription"]["billing_cycle"] == "yearly"

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 1, f"期望 1 条账单，实际 {rows}"
    number, amount, status, desc, idem = rows[0]
    assert status == "paid"
    assert amount == pytest.approx(pro["price_yearly"]), (
        f"实收 {amount} 与套餐年价 {pro['price_yearly']} 不一致"
    )
    assert "年付" in desc
    assert idem, "账单必须有幂等键（唯一约束兜底并发重复提交）"


# ====== 2. 展示价 == 收款价（口径分叉守卫） ======

async def test_display_price_equals_charge_amount(client, auth_on, user, auth_headers):
    """
    年付键：/plans 报的年价必须**逐套餐**等于真正会扣的金额。

    背景：`_serialize_plan` 与 `change_plan` 曾各自写一遍 `price_monthly * 10`。
    本用例把「展示」与「扣款」拉到同一个断言里——任一处再分叉都会红。
    """
    plans = (await client.get("/api/v1/billing/plans", headers=auth_headers)).json()
    plan_list = plans.get("plans", plans) if isinstance(plans, dict) else plans

    assert plan_list, "套餐目录为空，无法校验口径"

    async with get_async_session() as db:
        for p in plan_list:
            plan = (
                await db.execute(
                    select(SubscriptionPlan).where(SubscriptionPlan.name == p["name"])
                )
            ).scalar_one_or_none()
            if plan is None:
                continue
            assert p["price_monthly"] == pytest.approx(plan_amount(plan, "monthly"))
            assert p["price_yearly"] == pytest.approx(plan_amount(plan, "yearly")), (
                f"{p['name']}: 展示年价 {p['price_yearly']} != 应扣年价 "
                f"{plan_amount(plan, 'yearly')}"
            )
            assert p["price_yearly"] == pytest.approx(yearly_price(plan.price_monthly))


def test_pricing_helpers_are_consistent():
    """价目 helper 的单点自检：口径只有一处实现，边界值也不许分叉。"""
    assert yearly_price(299.0) == 2990.0
    # 非法周期一律回落 monthly（否则会静默按年扣款）
    assert normalize_cycle("YEARLY") == "yearly"
    assert normalize_cycle("weekly") == "monthly"
    assert normalize_cycle(None) == "monthly"
    assert normalize_cycle("") == "monthly"

    class _P:
        price_monthly = 299.0

    assert plan_amount(_P, "monthly") == 299.0
    assert plan_amount(_P, "yearly") == 2990.0
    assert plan_amount(_P, "weekly") == 299.0      # 非法周期按 monthly

    class _Free:
        price_monthly = 0

    assert plan_amount(_Free, "yearly") == 0.0


# ====== 3. 零元不开票 ======

async def test_free_plan_emits_no_invoice(client, auth_on, user, auth_headers):
    """
    切到免费套餐（¥0）不得产生任何账单。

    修复前实测：切 free 后 invoices 从 1 张涨到 2 张，多出一张
    `amount=0.0, status='paid', description='免费版月付'` 的脏数据，
    它会让「本月实收」统计与账单列表都失去意义。
    ★ 判据：没有资金流动就不该有资金凭证。
    """
    r = await _subscribe(client, auth_headers, "2", "yearly")
    assert r.status_code == 200 and r.json()["charged"] is True

    r2 = await _subscribe(client, auth_headers, "1", "monthly")   # free
    assert r2.status_code == 200, r2.text
    body2 = r2.json()
    assert body2["charged"] is False
    assert body2["subscription"]["plan"]["name"] == "free"
    assert "0" in body2.get("skipped_reason", ""), body2

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 1, f"切免费套餐不应新增账单，实际 {rows}"
    assert all(float(a) > 0 for _, a, *_ in rows), f"存在零元账单：{rows}"


# ====== 4. 重复提交不重复扣款 ======

async def test_sequential_duplicate_submission_is_not_charged(
    client, auth_on, user, auth_headers
):
    """
    连点两次「升级到 pro 月付」只允许扣一次钱。

    修复前实测：两次都 200 且各建一张账单（1 → 2）。
    接真实网关后这就是「点两下付两次」。第二次必须 charged=False。
    """
    r1 = await _subscribe(client, auth_headers, "2", "monthly")
    assert r1.status_code == 200 and r1.json()["charged"] is True

    r2 = await _subscribe(client, auth_headers, "2", "monthly")
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["charged"] is False, "同一周期内重复提交不得再次扣款"
    assert b2.get("already_subscribed") is True

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 1, f"重复提交后账单数应为 1，实际 {len(rows)}: {rows}"


async def test_duplicate_guard_allows_renewal_after_period_end(
    client, auth_on, user, auth_headers
):
    """
    守卫不得过宽：周期已过期时，同套餐再提交属于**续费**，必须照常扣款。

    ★ 这是上一用例的反向验证。「不重复扣款」的校验很容易写成
      「只要套餐相同就跳过」，那样就永远收不到续费的钱——
      比多收一次更隐蔽（不会有人投诉）。
    """
    from datetime import datetime, timedelta

    r1 = await _subscribe(client, auth_headers, "2", "monthly")
    assert r1.status_code == 200 and r1.json()["charged"] is True

    # 人为把周期推到过去（模拟到期）
    async with get_async_session() as db:
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.user_id == user["user_id"])
            )
        ).scalar_one()
        sub.current_period_end = datetime.utcnow() - timedelta(days=1)
        await db.commit()

    r2 = await _subscribe(client, auth_headers, "2", "monthly")
    assert r2.status_code == 200, r2.text
    assert r2.json()["charged"] is True, "周期已过期，续费必须照常扣款"

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 2, f"续费应新增一张账单，实际 {len(rows)}: {rows}"


async def test_concurrent_duplicate_submission_creates_single_invoice(
    client, auth_on, user, auth_headers
):
    """
    并发双击（网络重试 / 连点）只允许建一张账单，且**不允许出现错误响应**。

    ★ 两道闸的分工（缺一不可）：
      · `SELECT ... FOR UPDATE` 行锁：把同一用户的订阅变更串行化，
        后来的请求阻塞到前一个提交完，再读到新状态 ⇒ 被业务守卫判为重复提交
        ⇒ 200 + charged=False（用户视角是一次正常点击，不该看到报错）。
        ★ 判据：业务守卫是「读-判断-写」模式，天生有竞态窗口；只靠应用层判断
          + 事后唯一约束，会在「无订阅可锁」时不成立。行锁把竞态窗口直接关掉，
          唯一约束退化为兜底。
      · `invoices.idempotency_key` 唯一约束：只兜「此前没有任何订阅行可锁」的
        首购竞态，那种情况下无法串行化。

    ★★ 只加行锁是不够的：`.execution_options(populate_existing=True)` 不能省
      （P1-5 收尾修复 2026-09-15；原注释在 change_plan 函数体内，已外迁至此）

      行锁只在**数据库**层面把并发请求串行化；但 SQLAlchemy 的 identity map 会把
      「本 session 里已经加载过的那份 Subscription」原样返回，**不使用锁后重读到
      的新值覆盖已加载属性**（除非显式 populate_existing）。
      而 `User.subscription` 是 `lazy="selectin"`（models.py:62）——
      即 `get_current_user` 查 User 时，已经把这条订阅行连同**旧值**装进了
      identity map。于是「串行化之后后到的请求会读到新状态」这条设计前提不成立。

      实测（4 并发双击同一套餐）：
        · 语句确实阻塞串行了（阶梯等待 71 / 266 / 468 / 671ms，见
          .workbuddy/probes/project-audit-20260915/script-lock_probe.py）
        · 但 4 个请求全部读到加锁前的旧状态 ⇒ 算出**同一个**幂等键
          ⇒ 3 个撞 `invoices.idempotency_key` 唯一约束
          ⇒ 走到 IntegrityError 分支（本该 200 + charged=False）

      ★ 判据：**门禁语句存在 ≠ 门禁在生效**。加锁查询必须同时要求 ORM 重新装载，
        否则锁保护的是数据库行，业务读到的仍是内存里的旧对象。

    ★ 为什么必须用 `asyncio.Barrier` 对齐，而不能只写 `asyncio.gather`（实测 2026-09-16）
      裸 gather 的 4 个请求**并不会重叠在这个临界区**。实测时间轴
      （.workbuddy/probes/project-audit-20260915/r78m-authtiming.txt）：
        · 4 个请求确实同时进入（鉴权入口跨度仅 15ms）
        · 但**鉴权本身耗时 94~187ms**（User 连带 selectin 装 shops / subscription），
          而先到的那个请求走完「选套餐 → 加锁 → 扣款 → 提交」只要 ~60ms
        · 于是后到请求是在**鉴权期间**错过窗口的：等它走到加锁查询时，
          上一个请求早已提交，它读到的本来就是新值
      ⇒ 裸 gather 版本实际只考了「顺序重复提交」，`populate_existing` 一次都没被触发
        （反向注入 V4 证实：去掉它，该用例仍绿）。
      这里用 Barrier 把 4 个请求对齐到「鉴权完成（旧值已进 identity map）之后、
      加锁查询之前」—— 这正是真实高并发下双击的形态，也是本用例要守的那个窗口。
      ★ 判据：一个「证明竞态存在」的用例，必须**先证明该用例自己制造的窗口真实存在**；
        窗口不成立时它会静默退化成顺序用例，反向注入也证不伪（假绿）。

    ★ 本用例就是上面两种病态的门禁：把 `.execution_options(populate_existing=True)`
      去掉即红（反向注入见 .workbuddy/probes/project-audit-20260915/r78h-reverse.txt）。

    ⚠️ 锁只覆盖**当前用户自己那一行**，且事务内还包含一次网关调用
      （mock 瞬时完成；接真实网关若是同步 HTTP，需评估持锁时长，
      必要时改为「先建 pending 账单 → 释放锁 → 收 webhook」的两段式，
      见 platforms/payment/gateway.py 顶部接入清单第 5 条）。
    """
    from fastapi import Depends, Request

    from core.auth.dependencies import get_current_user, oauth2_scheme
    from core.database import get_db
    from main import app

    n = 4
    gate = asyncio.Barrier(n)

    async def _synced_auth(
        request: Request,
        token: str = Depends(oauth2_scheme),
        db=Depends(get_db),
    ):
        """照常鉴权（订阅行连同旧值进 identity map），再对齐到临界区入口。"""
        # ★ P0-2：`request` 是 get_current_user 的**必填首参**，且必须是裸
        #   `Request` 注解（`Optional[Request]` 会被 FastAPI 当 Pydantic 字段，
        #   路由注册期就抛 FastAPIError —— 见该函数 docstring）。
        u = await get_current_user(request=request, token=token, db=db)
        await gate.wait()
        return u

    app.dependency_overrides[get_current_user] = _synced_auth
    try:
        rs = await asyncio.wait_for(
            asyncio.gather(
                *[_subscribe(client, auth_headers, "3", "yearly") for _ in range(n)],
                return_exceptions=True,
            ),
            timeout=60,
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    codes = [r.status_code if not isinstance(r, Exception) else repr(r) for r in rs]
    assert all(c == 200 for c in codes), (
        f"并发请求出现非 200：{codes} —— 若为 409，说明后到请求读到了旧的订阅状态"
        f"（即 populate_existing 没生效或窗口没对齐）"
    )

    bodies = [r.json() for r in rs if not isinstance(r, Exception)]
    charged = sum(1 for b in bodies if b["charged"])
    assert charged == 1, f"{n} 个并发请求只应有 1 次真正扣款，实际 {charged}"

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 1, f"{n} 个并发请求只应建 1 张账单，实际 {len(rows)}: {rows}"


def test_idempotency_key_follows_start_state_not_wall_clock():
    """
    幂等键必须跟随「变更起点状态」，而不是墙钟时间。

    ★ 这条用例是一次真实的返工教训：最初我用「10 秒时间桶」做键，
      结果是**合法续费被当成重复提交** —— 测试里「把周期改到过期再提交」
      与首次购买落在同一个桶内，键相同 ⇒ 唯一约束拦下 ⇒ 续费收不到钱。
      所以这里显式把两种语义钉死：
        · 同一起点状态（并发双击）      → 同键
        · 起点状态已变（续费/改套餐）    → 换键
    """

    class _Sub:
        def __init__(self, plan_id, cycle, period_start, status="active"):
            self.plan_id = plan_id
            self.billing_cycle = cycle
            self.current_period_start = period_start
            self.status = status

    from datetime import datetime

    t0 = datetime(2026, 9, 1, 10, 0, 0)
    t1 = datetime(2026, 9, 15, 10, 0, 0)

    # 并发双击：两个请求读到同一个旧状态 ⇒ 同一个键（唯一约束才拦得住）
    f_a = subscription_state_fingerprint(_Sub(1, "monthly", t0))
    f_b = subscription_state_fingerprint(_Sub(1, "monthly", t0))
    assert f_a == f_b
    assert build_idempotency_key("u1", 2, "yearly", f_a) == build_idempotency_key(
        "u1", 2, "yearly", f_b
    ), "同一起点状态必须产生同一个键"

    # 续费：起点状态已推进（period_start 变了）⇒ 必须换键（否则收不到钱）
    f_renew = subscription_state_fingerprint(_Sub(2, "yearly", t1))
    assert f_a != f_renew
    assert build_idempotency_key("u1", 2, "yearly", f_a) != build_idempotency_key(
        "u1", 2, "yearly", f_renew
    ), "起点状态已变必须换键"

    # 无订阅 → 'new'（并发首购也能撞同一个键）
    assert subscription_state_fingerprint(None) == "new"

    # 目标套餐 / 周期不同必须换键
    base = subscription_state_fingerprint(_Sub(1, "monthly", t0))
    assert build_idempotency_key("u1", 3, "yearly", base) != build_idempotency_key(
        "u1", 2, "yearly", base
    )
    assert build_idempotency_key("u1", 2, "monthly", base) != build_idempotency_key(
        "u1", 2, "yearly", base
    )
    assert build_idempotency_key("u1", 2, "YEARLY", base) == build_idempotency_key(
        "u1", 2, "yearly", base
    ), "周期大小写不应产生不同键"


def test_duplicate_detector_matrix():
    """
    is_duplicate_submission 真值表（用轻量替身，不打 DB）。

    ★ 逐格覆盖而不是「随便挑一个跑通」：这个函数每判错一次，
      方向不是多收钱就是漏收费，属于必须穷尽的分支。
    """

    class _Sub:
        def __init__(self, plan_id, cycle, status="active", end=None):
            self.plan_id = plan_id
            self.billing_cycle = cycle
            self.status = status
            self.current_period_end = end

    from datetime import datetime, timedelta

    future = datetime.utcnow() + timedelta(days=10)
    past = datetime.utcnow() - timedelta(days=1)

    assert is_duplicate_submission(None, 2, "monthly") is False                    # 无订阅
    assert is_duplicate_submission(_Sub(2, "monthly", end=future), 2, "monthly") is True
    assert is_duplicate_submission(_Sub(2, "monthly", end=future), 2, "yearly") is False
    assert is_duplicate_submission(_Sub(1, "monthly", end=future), 2, "monthly") is False
    assert is_duplicate_submission(_Sub(2, "monthly", end=past), 2, "monthly") is False   # 到期→续费
    assert is_duplicate_submission(_Sub(2, "monthly", end=None), 2, "monthly") is False   # 无到期→按需扣款
    assert is_duplicate_submission(
        _Sub(2, "monthly", status="cancelled", end=future), 2, "monthly"
    ) is False


# ====== 5. 未接入的真实网关必须显式失败 ======

async def test_unimplemented_gateway_returns_501(client, auth_on, user, auth_headers):
    """
    配置成未接入的真实网关时，必须 501 并说明整改路径。

    ★ 绝不能「静默降级成 mock 支付成功」——那会让「配了真实网关」
      和「没配」在行为上完全一样，而用户真的拿到了付费套餐。
      也**不能**是 500：500 会被当成服务端 bug 去翻栈，
      实际原因只是「这个网关还没写」。
    """
    prev = config.payment_gateway
    config.payment_gateway = "stripe"     # 在 KNOWN_UNIMPLEMENTED_GATEWAYS 里
    try:
        r = await _subscribe(client, auth_headers, "2", "yearly")
    finally:
        config.payment_gateway = prev

    assert r.status_code == 501, f"期望 501，实际 {r.status_code} {r.text}"
    assert "尚未接入实现" in r.json()["detail"]
    rows = await _invoices_of(user["user_id"])
    assert rows == [], f"未接入网关不得产生任何账单，实际 {rows}"


def test_known_unimplemented_list_is_non_empty_and_lowercase():
    """清单本身的自检：名字必须全小写，否则 get_gateway 的 .lower() 比对会漏。"""
    assert KNOWN_UNIMPLEMENTED_GATEWAYS, "未接入网关清单纯空时护栏会失效"
    for name in KNOWN_UNIMPLEMENTED_GATEWAYS:
        assert name == name.lower().strip(), f"{name!r} 必须是小写去空白的规范形式"


# ====== 6. 生产护栏（正向 + 反向） ======
#
# ★ 合规基线**不在本文件里**：`prod_settings_kwargs` 夹具（tests/conftest.py）
#   是唯一来源。原因见该夹具的注释 —— 同一件事（新护栏上线把各处独立基线
#   打红）已经发生过三次，最后收敛成一处。

def test_production_guard_accepts_compliant_config(prod_settings_kwargs):
    """正向：合规配置必须放行（否则护栏变成「生产永远起不来」）。"""
    from core.config import Settings

    Settings(**prod_settings_kwargs())   # 不抛异常即通过


@pytest.mark.parametrize(
    "over, keyword",
    [
        ({"auth_required": False}, "AUTH_REQUIRED"),
        ({"jwt_secret_key": "your-super-secret-key-change-in-production"}, "JWT_SECRET_KEY"),
        ({"debug": True}, "DEBUG"),
        ({"payment_gateway": "mock"}, "PAYMENT_GATEWAY"),
        ({"payment_gateway": "stripe"}, "尚未接入实现"),
        ({"payment_gateway": "alipay"}, "尚未接入实现"),
        ({"payment_gateway": "wechat"}, "尚未接入实现"),
        # ★ P1-d（2026-09-16）：/metrics 漏配令牌。
        #   修复前这里只有 main.py 一句 WARNING（"门禁存在 ≠ 在执行"），
        #   漏配的后果是 QPS/错误率/接口清单**安静地**对外开放。
        ({"metrics_token": ""}, "METRICS_TOKEN"),
        ({"metrics_token": "   "}, "METRICS_TOKEN"),   # 纯空白必须与空串同待遇
    ],
)
def test_production_guard_rejects(prod_settings_kwargs, over, keyword):
    """反向：每一种违规配置逐一必须拒绝启动，且错误文案要指出是哪个配置项。

    ★ 刻意不写「N 种」：样本表会增长，写死的数字必然过期
      （过期文档比没有文档更误导）。
    """
    from core.config import Settings

    with pytest.raises(Exception) as ei:
        Settings(**prod_settings_kwargs(**over))
    assert keyword in str(ei.value), f"错误信息里应出现 {keyword!r}：{ei.value}"


def test_production_guard_allows_disabling_metrics_entirely(prod_settings_kwargs):
    """
    正向：不需要指标端点时显式关掉即可 —— 证明护栏不过宽。

    ★ 这条是必需的「反向保护」：没有它，把 METRICS_TOKEN 写成无条件必填
      也能让上面两条反向用例变绿，但会把「不需要监控的部署」一起挡在门外。
    """
    from core.config import Settings

    s = Settings(**prod_settings_kwargs(metrics_enabled=False, metrics_token=""))
    assert s.metrics_enabled is False


def test_production_guard_not_applied_outside_production():
    """非生产环境不校验：本地开发需要 mock 网关跑通整条链路。"""
    from core.config import Settings

    s = Settings(environment="development", payment_gateway="mock", auth_required=False)
    assert s.environment == "development"


# ====== 7. 兜底闸：唯一约束命中 → 409（不是 500），且只吞幂等键冲突 ======
#
# 这一节接收 change_plan 里 `except IntegrityError` 分支外迁的踩坑知识。
# ★ 为什么要给它单独一节：该分支原先是「注释 16 行 + 代码 5 行」，
#   而它守的是**最容易写歪**的一条 —— 把 `except IntegrityError` 写成
#   「回滚 + 重建状态 + 返回 409」看起来更友好，在 async SQLAlchemy 上却是
#   必崩的组合；反过来写成「一律 409」则会把真 bug 伪装成重复提交。
#   两个方向都只有跑起来才知道，所以必须有对应用例。

async def test_first_purchase_race_returns_409_not_500(
    client, auth_on, user, auth_headers, monkeypatch
):
    """
    兜底闸命中时必须是 409，**不允许**退化成 500。

    ★ 1) 为什么需要兜底闸 —— 行锁并非万能
        行锁只能在「该用户已经有订阅行」时串行化；注册流程虽会建默认订阅，
        但「无行可锁」仍可能出现在删号重建 / 数据迁移 / 人工补数据之后。
        那时两个并发请求都判定「不是重复提交」⇒ 各建一张单
        ⇒ `invoices.idempotency_key` 唯一约束兜住其中一个。

    ★ 2) 回滚后**立刻结束请求**，不再对这个 session 做任何 DB 操作
        实测踩坑：rollback 后继续 `db.execute(...)` 会在连接池 checkout 的
        pre-ping 阶段抛 `MissingGreenlet: greenlet_spawn has not been called`
        —— 顶层 greenlet 上下文已随异常一起退出，而 pre-ping 走的是同步路径里的
        `await_only`。同一个 `except IntegrityError` 分支里既回滚又读库，
        在 async SQLAlchemy 上是走不通的组合。
        所以这里不重建状态，直接 409 让前端刷新（前一个请求已提交成功，
        刷新后看到的订阅状态是正确的）。

    ★ 3) 这里只能用**回滚前取好的标量**（_user_id / _plan_id），不能读 ORM 属性
        `rollback()` 已经把 session 内所有对象 expire，此时读 `current_user.id`
        会触发隐式懒加载 → 纯 async 上下文没有 greenlet ⇒ 同样抛
        `MissingGreenlet`，本该 409 的响应变成 500 + 一串 SQLAlchemy 堆栈。
        ★ 判据：凡是「rollback 之后还要用」的值，必须在 rollback 之前落成标量。
        ★ 同一行的日志占位必须是 loguru 的 `{}`：写成 `%s` 不报错，
          但会把字面量 `%s` 打进日志并**丢掉全部参数**（该行原先就是错的）。

    测试手法：注册流程本身会建默认订阅，无法自然地制造「无行可锁」，
    因此这里显式把业务守卫短路掉 + 预置一条同键账单，
    等价于「另一个并发请求已经先赢下这一单」。
    """
    import uuid

    from modules.billing.pricing import build_idempotency_key, subscription_state_fingerprint

    r0 = await _subscribe(client, auth_headers, "2", "yearly")
    assert r0.status_code == 200 and r0.json()["charged"] is True, r0.text

    # 预置冲突账单：幂等键 = 下一次请求将要算出的那个键
    async with get_async_session() as db:
        sub = (
            await db.execute(
                select(Subscription).where(Subscription.user_id == user["user_id"])
            )
        ).scalar_one()
        key = build_idempotency_key(
            sub.user_id,
            sub.plan_id,
            sub.billing_cycle,
            subscription_state_fingerprint(sub),
        )
        await db.execute(
            text(
                # ★ created_at / issued_at 必须显式给：模型上的 default=datetime.utcnow
                #   是 Python 侧默认值，只在走 ORM 时生效；原生 SQL 会直接撞 NOT NULL。
                "INSERT INTO invoices (id, user_id, number, amount, currency, status, "
                "description, issued_at, created_at, idempotency_key) VALUES "
                "(:id, :u, :n, 1.0, 'CNY', 'paid', '并发赢家占位', now(), now(), :k)"
            ),
            {
                "id": str(uuid.uuid4()),
                "u": user["user_id"],
                "n": f"INV-RACE-{uuid.uuid4().hex[:8].upper()}",
                "k": key,
            },
        )
        await db.commit()

    # 短路业务守卫：让请求走到 commit，交给唯一约束兜底
    from modules.billing import router as _br

    monkeypatch.setattr(_br, "is_duplicate_submission", lambda *a, **k: False)

    r = await _subscribe(client, auth_headers, "2", "yearly")

    assert r.status_code == 409, f"兜底闸命中应返回 409，实际 {r.status_code} {r.text}"
    assert "重复提交" in r.json()["detail"]

    rows = await _invoices_of(user["user_id"])
    placeholders = [r for r in rows if r[0].startswith("INV-RACE-")]
    assert len(placeholders) == 1, f"占位账单应恰好 1 张，实际 {placeholders}"
    assert len(rows) == 2, (
        f"冲突的那张不得落库（应只有首购 1 张 + 占位 1 张），实际 {rows}"
    )


async def test_other_integrity_errors_are_not_swallowed(
    client, auth_on, user, auth_headers, monkeypatch
):
    """
    `except IntegrityError` 只允许吞幂等键冲突，其他完整性错误必须原样抛出。

    ★ 反向验证的必要性：「兜底闸」极易退化成
      `except IntegrityError: rollback(); return 409` —— 那样外键违例
      （如套餐被删）、账单号撞车都会伪装成「检测到重复提交」，
      真实的完整性缺陷被静默吞掉，只能等对账时才暴露。
      判据：只吞自己明确知道含义的那一种错误，其余一律向上抛。

    测试手法：把网关换成「返回一条 number 已经被占用的账单」的桩，
    制造一次**非**幂等键的冲突，断言它穿透端点向上抛。

    ★ 顺带锁住一个容易写歪的细节：「是不是幂等键冲突」必须用驱动层错误
      `exc.orig` 判别。用 `str(exc)` 判别会失效 —— 它把整条 INSERT 语句都
      带上了，列名里天然含 `idempotency_key`，于是**所有**完整性错误都会被
      误判成幂等键冲突吞掉（详见用例内的行内注释）。
    """
    import uuid

    from sqlalchemy.exc import IntegrityError as _IE

    from platforms.payment.gateway import ChargeResult, InvoiceDraft

    taken_number = f"INV-{uuid.uuid4().hex[:12].upper()}"
    async with get_async_session() as db:
        await db.execute(
            text(
                "INSERT INTO invoices (id, user_id, number, amount, currency, status, "
                "description, issued_at, created_at) VALUES "
                "(:id, :u, :n, 1.0, 'CNY', 'paid', '占用了这个账单号', now(), now())"
            ),
            {"id": str(uuid.uuid4()), "u": user["user_id"], "n": taken_number},
        )
        await db.commit()

    class _NumberCollisionGateway:
        name = "number-collision-stub"

        async def charge(self, intent):
            from datetime import datetime as _dt

            now = _dt.utcnow()
            # ★ 网关返回的是纯数据草案（InvoiceDraft），不是 ORM 实体。
            #   落库由 modules/billing/router.py::_invoice_from_draft 负责。
            return ChargeResult(
                success=True,
                invoice=InvoiceDraft(
                    id=str(uuid.uuid4()),
                    user_id=intent.user_id,
                    number=taken_number,          # ← 故意撞号
                    amount=float(intent.amount),
                    currency="CNY",
                    status="paid",
                    description="撞号账单",
                    issued_at=now,
                    paid_at=now,
                    idempotency_key=intent.idempotency_key or None,
                ),
            )

    from modules.billing import router as _br

    monkeypatch.setattr(_br, "get_gateway", lambda: _NumberCollisionGateway())

    with pytest.raises(_IE) as ei:
        await _subscribe(client, auth_headers, "2", "yearly")

    orig = str(getattr(ei.value, "orig", ei.value))
    assert "invoices_number_key" in orig, f"抛出的应是账单号唯一约束冲突：{orig}"
    # ★ 陷阱（本用例顺带锁住）：判别「是不是幂等键冲突」只能用 `exc.orig`。
    #   SQLAlchemy 的 `str(exc)` 会把整条 INSERT 语句一起渲染出来，而列名里
    #   天然含 `idempotency_key` —— 若写成 `if "idempotency_key" not in str(exc): raise`，
    #   这类账单号冲突会被**误判**成幂等键冲突而静默吞掉，伪装成 409「重复提交」，
    #   真实缺陷只能等对账时才暴露。当前实现用的是 `exc.orig`，判别正确。
    #   两种字符串的实际差异见 .workbuddy/probes/project-audit-20260915/r78g-*.txt
