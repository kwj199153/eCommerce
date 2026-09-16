"""
套餐价目口径真源（★ P1-4 收敛 2026-09-15）

背景（实测发现）：
    「年付价」这个数字在本项目里曾被**两处独立实现**：
      · modules/billing/router.py::_serialize_plan
            price_yearly = round(plan.price_monthly * 10, 2)     ← 给前端看
      · modules/billing/router.py::change_plan
            amount       = round(plan.price_monthly * 10, 2)     ← 真正扣的钱
    两处各自硬编码同一个魔法系数 10。今天两边值一样（pro: 2990），但只要
    有人改一处（例如把年付改成「9 折」），就会出现
        「页面上写 ¥2990、结算扣 ¥2691」
    这种用户一定会发现、但事后对账最难查的口径事故。

判据（沿用本项目既有的口径收敛结论）：
    同一个业务数字，若前端只是展示、后端才是权威，那么
    **谁掌握着别人推不出来的输入，谁才是源**。
    这里的输入是「月付价 + 计费周期」，两者都在 subscription_plans 表里，
    所以源只能有一个——本模块。前端与 `_serialize_plan` 都只能消费它，
    不允许自己算第二遍。

用法：
    from modules.billing.pricing import plan_amount, yearly_price, cycle_days

    amount = plan_amount(plan, "yearly")     # 展示与扣费共用同一个函数
    days   = cycle_days("yearly")            # 周期长度也同源
"""

from datetime import datetime, timedelta
from typing import Optional

__all__ = [
    "MONTHS_CHARGED_PER_YEAR",
    "CYCLE_DAYS",
    "VALID_CYCLES",
    "normalize_cycle",
    "yearly_price",
    "plan_amount",
    "cycle_days",
    "period_end",
    "is_period_active",
    "is_duplicate_submission",
    "subscription_state_fingerprint",
    "build_idempotency_key",
]

# 年付按「10 个月」计价（即买 12 个月送 2 个月 ≈ 省 16.7%）。
# ★ 这个常量是价格口径的一部分，改动会直接改变收款金额，请与运营确认后再动。
MONTHS_CHARGED_PER_YEAR: int = 10

# 周期天数。用 30/365 而非日历月，是因为订阅周期是「滚动窗口」——
# 若用日历月，1 月 31 日续费会落到 2 月 28 日，周期长度在一个月内不固定，
# 会给「本期应扣金额」的对账带来无意义的偏差。365 天跨闰年会少一天，
# 但金额口径是按月×10 计的，与天数无关，故不影响金额。
CYCLE_DAYS: dict[str, int] = {"monthly": 30, "yearly": 365}

# 允许的计费周期（非法值一律回落 monthly，避免静默按年扣款）
VALID_CYCLES: tuple[str, ...] = ("monthly", "yearly")


def normalize_cycle(cycle: Optional[str]) -> str:
    """把任意输入规整为合法周期；非法/空值一律回落 monthly。"""
    c = (cycle or "").strip().lower()
    return c if c in VALID_CYCLES else "monthly"


def yearly_price(monthly: float) -> float:
    """按年付口径折算年价（唯一实现）。"""
    return round(float(monthly or 0) * MONTHS_CHARGED_PER_YEAR, 2)


def plan_amount(plan, billing_cycle: str) -> float:
    """
    某个套餐在指定周期下的**应扣金额**（唯一实现）。

    Args:
        plan: SubscriptionPlan 实例（需有 price_monthly）
        billing_cycle: monthly / yearly（非法值按 monthly）

    Returns:
        金额（元），保留两位小数
    """
    cycle = normalize_cycle(billing_cycle)
    monthly = float(getattr(plan, "price_monthly", 0) or 0)
    if monthly <= 0:
        return 0.0
    return yearly_price(monthly) if cycle == "yearly" else round(monthly, 2)


def cycle_days(billing_cycle: str) -> int:
    """周期长度（天），与 plan_amount 同源。"""
    return CYCLE_DAYS[normalize_cycle(billing_cycle)]


def period_end(start: datetime, billing_cycle: str) -> datetime:
    """给定周期起点，算本期结束时间。"""
    return start + timedelta(days=cycle_days(billing_cycle))


def is_period_active(sub, now: Optional[datetime] = None) -> bool:
    """
    判断订阅当前是否在有效周期内（用于「重复提交不重复扣款」的守卫）。

    ★ 判据：周期结束时间缺失或已过期 ⇒ 视为不在有效期内 ⇒ 需要重新扣款
      （续费场景）。缺失时**不能**当作有效，否则漏收费。
    """
    if sub is None:
        return False
    if (getattr(sub, "status", "") or "") != "active":
        return False
    end = getattr(sub, "current_period_end", None)
    if end is None:
        return False
    return end > (now or datetime.utcnow())


def subscription_state_fingerprint(sub) -> str:
    """
    订阅**当前状态**的指纹，用作幂等键的基底。

    ★ 为什么不能用「时间桶」（我第一版就是这么写的，被测试打回了）：
      时间桶看似能兜住并发双击，实际会误伤**合法续费** ——
      测试里「把周期改到过期 → 再提交」发生在同一个 10 秒桶内，
      于是续费生成了与首次购买相同的键，被唯一约束当重复拦掉，
      表现是「续费收不到钱」。时间与业务事件无关，就不该拿时间当键。
      （时间粒度放粗到「天」也不行：同一天内 A 套餐 → B → A 回切，
       第二次 A 会撞上第一次 A 的账单键，同样漏收费。）

    ★ 正确做法：用「本次变更的**起点状态**」当键。
      它天然满足两个相反的要求：
        · 并发双击 —— 两个请求读到的是**同一个**旧状态 ⇒ 同一个键 ⇒ 唯一约束拦住重复；
        · 合法的后续动作（续费 / 改套餐 / 取消后重订）—— 前一次动作
          必然已经把状态改掉了 ⇒ 读到**不同**的旧状态 ⇒ 换键 ⇒ 正常扣款。
      换句话说：只要「前一次真的生效了」，键就一定会变；而「前一次没生效」
      时本来就没有账单，也就不会撞键。这是个闭环。

    指纹只取会被本次变更改动的字段（plan_id / status / billing_cycle /
    period_start），不取 updated_at（它每次写都会变，会让并发双击读到两个值）。
    """
    if sub is None:
        return "new"
    ps = getattr(sub, "current_period_start", None)
    stamp = ps.strftime("%Y%m%d%H%M%S") if ps is not None else "none"
    return (
        f"{getattr(sub, 'plan_id', '?')}"
        f"|{getattr(sub, 'status', '?')}"
        f"|{normalize_cycle(getattr(sub, 'billing_cycle', None))}"
        f"|{stamp}"
    )


def build_idempotency_key(
    user_id: str,
    plan_id: int,
    billing_cycle: str,
    from_state: str,
) -> str:
    """
    生成账单幂等键：同一用户 + 同一套餐 + 同一周期 + 同一**起点状态** → 同一张账单。

    用途分层：
      · 服务端（本函数）：落 Invoice.idempotency_key 唯一约束，兜住**并发**重复
        —— 业务守卫 `is_duplicate_submission()` 只能拦住**顺序**重复
        （它依赖「前一次已提交、后一次读得到新状态」），
        并发双击时两个请求都读到旧状态，唯有唯一约束拦得住。
      · 网关侧：作为请求头 / 参数发给真实网关（Stripe `Idempotency-Key`、
        支付宝 `out_trade_no`、微信 `out_trade_no`），让网关也做一次去重。
        起点状态键同样适合网关场景：同一次支付尝试重试时起点状态不变 ⇒ 同键。

    Args:
        from_state: `subscription_state_fingerprint(sub)`（变更前的订阅指纹）
    """
    return (
        f"sub:{user_id}:{plan_id}:"
        f"{normalize_cycle(billing_cycle)}:{from_state}"
    )


def is_duplicate_submission(sub, plan_id: int, billing_cycle: str) -> bool:
    """
    判断「这次提交是否属于同一套餐、同一周期内的重复提交」。

    命中时应直接返回当前订阅状态且**不扣款、不开票**——
    因为用户的意图（我要用专业版）已经满足了，再扣一次就是多收钱。

    ★ 注意与「续费」的区别：续费时 current_period_end 已过期，
      `is_period_active` 返回 False ⇒ 本函数返回 False ⇒ 正常走扣款。
    """
    if not is_period_active(sub):
        return False
    if int(getattr(sub, "plan_id", -1)) != int(plan_id):
        return False
    stored = normalize_cycle(getattr(sub, "billing_cycle", None))
    return stored == normalize_cycle(billing_cycle)
