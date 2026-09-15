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

★ 这些用例的价值不在于「跑通流程」，而在于**锁住方向**：
  上面 3、4 两条的 bug 方向都是「多收用户的钱 / 少收平台的钱」，
  一旦回归，对账时要花几天才能定位。
"""

import asyncio

import pytest
from sqlalchemy import select, text

from core.billing.pricing import (
    build_idempotency_key,
    is_duplicate_submission,
    normalize_cycle,
    plan_amount,
    subscription_state_fingerprint,
    yearly_price,
)
from core.config import KNOWN_UNIMPLEMENTED_GATEWAYS, config
from core.database import get_async_session
from modules.user_subscription.models import Subscription, SubscriptionPlan


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
      · `invoices.idempotency_key` 唯一约束：只兜「此前没有任何订阅行可锁」的
        首购竞态，那种情况下无法串行化。
    """
    rs = await asyncio.gather(
        *[_subscribe(client, auth_headers, "3", "yearly") for _ in range(4)],
        return_exceptions=True,
    )
    codes = [r.status_code if not isinstance(r, Exception) else repr(r) for r in rs]
    assert all(c == 200 for c in codes), f"并发请求出现非 200：{codes}"

    bodies = [r.json() for r in rs if not isinstance(r, Exception)]
    assert sum(1 for b in bodies if b["charged"]) == 1, (
        f"4 个并发请求只应有 1 次真正扣款，实际 {sum(1 for b in bodies if b['charged'])}"
    )

    rows = await _invoices_of(user["user_id"])
    assert len(rows) == 1, f"4 个并发请求只应建 1 张账单，实际 {len(rows)}: {rows}"


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

def _prod_settings(**over):
    """构造一个 production Settings 实例（validator 只在实例化时跑）"""
    from core.config import Settings

    base = dict(
        environment="production",
        auth_required=True,
        jwt_secret_key="a-very-strong-random-secret-9f2c8e1b7d4a6035",
        debug=False,
        payment_gateway="internal",   # 既非 mock 也非未接入清单，用于证明护栏不过宽
    )
    base.update(over)
    return Settings(**base)


def test_production_guard_accepts_compliant_config():
    """正向：合规配置必须放行（否则护栏变成「生产永远起不来」）。"""
    _prod_settings()   # 不抛异常即通过


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
    ],
)
def test_production_guard_rejects(over, keyword):
    """反向：7 种违规配置逐一必须拒绝启动，且错误文案要指出是哪个配置项。"""
    with pytest.raises(Exception) as ei:
        _prod_settings(**over)
    assert keyword in str(ei.value), f"错误信息里应出现 {keyword!r}：{ei.value}"


def test_production_guard_not_applied_outside_production():
    """非生产环境不校验：本地开发需要 mock 网关跑通整条链路。"""
    from core.config import Settings

    s = Settings(environment="development", payment_gateway="mock", auth_required=False)
    assert s.environment == "development"
